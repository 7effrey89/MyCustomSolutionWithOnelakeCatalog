"""Read-only XMLA/DAX adapter (no REST fallback, model authoring, or impersonation).

Build once, from this directory (requires .NET 8+ SDK):
    dotnet restore xmla_bridge/XmlaBridge.csproj --source https://www.nuget.org/api/v2/
    dotnet build xmla_bridge/XmlaBridge.csproj -c Release --no-restore

Usage with the existing CLI login:
    client = XmlaClient(AzureCliCredential())
    endpoint = XmlaEndpoint("powerbi://api.powerbi.com/v1.0/myorg/<workspace>",
                            "<model name or GUID>", "<catalog asset key>")
    client.connect(endpoint)  # EVALUATE ROW("Connected",1), not just an open socket
    result = client.query(endpoint, 'EVALUATE ROW("Example",1)', max_rows=100)

Server workspace segments must be RFC3986 encoded (GUIDs are accepted). Catalogs
are passed verbatim as Initial Catalog, including GUIDs, not mapped via REST.
Microsoft documents friendly names and name-GUID disambiguation; GUID-only target
resolution should be verified against the intended tenant using connect():
https://learn.microsoft.com/fabric/enterprise/powerbi/service-premium-connect-tools
https://learn.microsoft.com/analysis-services/instances/connection-string-properties-analysis-services

The row limit bounds rows transferred, not engine work. Command timeout and a
process deadline bound each query, including retries, to at most 60 seconds after
credential acquisition. Disposing/killing the client is best-effort cancellation
on the server. Nothing here changes the signed-in identity's server permissions.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Protocol
from urllib.parse import unquote

import pandas as pd

TOKEN_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_SERVER = re.compile(r"powerbi://api\.powerbi\.com/v1\.0/myorg/([A-Za-z0-9._~%-]+)\Z")
_FORBIDDEN = {
    "ALTER", "CREATE", "DELETE", "DROP", "INSERT", "UPDATE", "MERGE",
    "REFRESH", "PROCESS", "EXECUTE", "CALL", "CLEAR", "ATTACH", "DETACH",
    "BACKUP", "RESTORE", "SELECT", "DRILLTHROUGH",
}
_BRIDGE = Path(__file__).resolve().parent / "xmla_bridge"


class TokenCredential(Protocol):
    """Compatible with AzureCliCredential and DefaultAzureCredential."""

    def get_token(self, *scopes: str) -> Any: ...


class XmlaError(RuntimeError):
    """Actionable XMLA/bridge failure; never includes token or raw process output."""

    def __init__(self, message: str, *, code: str | None = None, diagnostics: str = "") -> None:
        super().__init__(message + (f" Details: {diagnostics}" if diagnostics else ""))
        self.code = code
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class XmlaEndpoint:
    server: str
    catalog: str
    asset_key: str

    def __post_init__(self) -> None:
        match = _SERVER.fullmatch(self.server) if isinstance(self.server, str) else None
        if not match or re.search(r"%(?![0-9a-fA-F]{2})", match[1]):
            raise ValueError("Use powerbi://api.powerbi.com/v1.0/myorg/<encoded-workspace-or-GUID>.")
        decoded = unquote(match[1], errors="strict")
        if not decoded.strip() or decoded in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
            raise ValueError("Invalid workspace segment.")
        if not isinstance(self.catalog, str) or not self.catalog.strip() or len(self.catalog) > 1024:
            raise ValueError("Initial Catalog must be a nonempty model name or GUID (max 1024 characters).")
        if any(ord(c) < 32 or ord(c) == 127 for c in self.catalog):
            raise ValueError("Initial Catalog cannot contain control characters.")
        if not isinstance(self.asset_key, str) or not self.asset_key.strip():
            raise ValueError("asset_key must identify the selected catalog item.")


@dataclass(frozen=True)
class XmlaResult:
    frame: pd.DataFrame
    truncated: bool


def _validate_dax(dax: str) -> None:
    """Lex a restricted single-result DAX query, ignoring quoted names/comments.

    Not a full DAX parser: ADOMD/the server checks grammar. Only EVALUATE or
    DEFINE...EVALUATE can reach ExecuteReader. No XMLA/MDX/TMSL interface exists.
    """
    if not isinstance(dax, str) or not dax.strip() or len(dax) > 100_000 or "\0" in dax:
        raise ValueError("Provide a nonempty DAX query of at most 100000 characters.")
    tokens: list[str] = []
    i = 0
    while i < len(dax):
        if dax.startswith(("//", "--"), i):
            end = dax.find("\n", i + 2)
            i = len(dax) if end < 0 else end + 1
        elif dax.startswith("/*", i):
            end = dax.find("*/", i + 2)
            if end < 0:
                raise ValueError("Unterminated DAX comment.")
            i = end + 2
        elif dax[i] in "\"'[":
            closing = "]" if dax[i] == "[" else dax[i]
            i += 1
            while True:
                end = dax.find(closing, i)
                if end < 0:
                    raise ValueError("Unterminated quoted DAX name or string.")
                i = end + 1
                if i < len(dax) and dax[i] == closing:
                    i += 1
                else:
                    break
            tokens.append("QUOTED")
        elif dax[i].isalpha() or dax[i] == "_":
            end = i + 1
            while end < len(dax) and (dax[end].isalnum() or dax[end] in "_."):
                end += 1
            tokens.append(dax[i:end].upper())
            i = end
        elif dax[i].isspace():
            i += 1
        else:
            if dax[i] == ";":
                raise ValueError("Semicolon batches are not supported; send one DAX query.")
            tokens.append(dax[i])
            i += 1
    if not tokens or tokens[0] not in {"DEFINE", "EVALUATE"}:
        raise ValueError("Read-only DAX only: start with EVALUATE or DEFINE, never XMLA/DDL/MDX.")
    if tokens.count("EVALUATE") != 1 or tokens.count("DEFINE") > 1 or _FORBIDDEN.intersection(tokens):
        raise ValueError("Only one read-only DAX EVALUATE is allowed; XMLA/DDL commands are forbidden.")


def _unique_labels(names: list[str]) -> list[str]:
    used: set[str] = set()
    result = []
    for name in names:
        label = name
        suffix = 2
        while label in used:
            label = f"{name}_{suffix}"
            suffix += 1
        used.add(label)
        result.append(label)
    return result


def _decode(payload: dict[str, Any], max_rows: int) -> XmlaResult:
    """Decode schema-tagged cells without float-coercing nullable 64-bit integers."""
    try:
        columns, rows, truncated = payload["columns"], payload["rows"], payload["truncated"]
        if not isinstance(columns, list) or not isinstance(rows, list) or type(truncated) is not bool:
            raise ValueError
        if len(rows) > max_rows or any(not isinstance(r, list) or len(r) != len(columns) for r in rows):
            raise ValueError
        if any(not isinstance(c, dict) or not isinstance(c.get("name"), str)
               or not isinstance(c.get("type"), str) for c in columns):
            raise ValueError
        names = _unique_labels([c["name"] for c in columns])
        series: dict[str, pd.Series] = {}
        integers = {"Int16", "Int32", "Int64", "Byte", "SByte", "UInt16", "UInt32", "UInt64"}
        for index, (name, column) in enumerate(zip(names, columns)):
            kind = column["type"]
            values = [r[index] for r in rows]
            if kind in integers:
                dtype = "UInt64" if kind == "UInt64" else "Int64"
            elif kind == "Boolean":
                dtype = "boolean"
            elif kind in {"Double", "Single"}:
                values = [float(v) if v is not None else None for v in values]
                dtype = "Float64"
            else:
                dtype = "object"
                if kind == "Decimal":
                    values = [Decimal(v) if v is not None else None for v in values]
                elif kind in {"DateTime", "DateTimeOffset"}:
                    values = [datetime.fromisoformat(v) if v is not None else None for v in values]
                elif kind == "Byte[]":
                    values = [base64.b64decode(v, validate=True) if v is not None else None for v in values]
            series[name] = pd.Series(values, dtype=dtype)
        frame = pd.DataFrame(series, index=range(len(rows)))
        return XmlaResult(frame, truncated)
    except (KeyError, TypeError, ValueError, OverflowError, ArithmeticError):
        raise XmlaError("Invalid XMLA bridge result schema or cell encoding; rebuild the bridge.") from None


class XmlaClient:
    """One short-lived ADOMD process/connection per call, safe for Streamlit reruns.

    No credentials are stored outside the injected credential object. Build is
    explicit, not performed during queries. timeout_seconds must be 1..60.
    Only explicitly classified transient failures retry (0.25, 0.5 second
    exponential backoff), under the same overall deadline.
    """

    def __init__(
        self, credential: TokenCredential, *, timeout_seconds: int = 60,
        dotnet_path: str | Path | None = None, bridge_path: str | Path | None = None,
    ) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be an integer from 1 to 60.")
        self.credential = credential
        self.timeout_seconds = timeout_seconds
        self.dotnet_path = str(dotnet_path) if dotnet_path else (
            shutil.which("dotnet") or r"C:\Program Files\dotnet\dotnet.exe"
        )
        self.bridge_path = Path(bridge_path) if bridge_path else (
            _BRIDGE / "bin" / "Release" / "net8.0" / "XmlaBridge.dll"
        )

    def connect(self, endpoint: XmlaEndpoint) -> XmlaResult:
        """Verify access by executing a constant-only DAX probe; return its frame."""
        return self.query(endpoint, 'EVALUATE ROW("Connected",1)', max_rows=1)

    def query(self, endpoint: XmlaEndpoint, dax: str, max_rows: int = 1000) -> XmlaResult:
        """Execute one read-only DAX rowset, returning at most max_rows (1..10000)."""
        if not isinstance(endpoint, XmlaEndpoint):
            raise TypeError("endpoint must be an XmlaEndpoint.")
        _validate_dax(dax)
        if type(max_rows) is not int or not 1 <= max_rows <= 10_000:
            raise ValueError("max_rows must be an integer from 1 to 10000.")
        if not self.bridge_path.is_file():
            raise XmlaError(
                "XMLA bridge is not built. Run: dotnet restore xmla_bridge/XmlaBridge.csproj "
                "--source https://www.nuget.org/api/v2/ ; then "
                "dotnet build xmla_bridge/XmlaBridge.csproj -c Release --no-restore"
            )
        try:
            token = self.credential.get_token(TOKEN_SCOPE)
            secret, expires = token.token, int(token.expires_on)
            if not isinstance(secret, str) or not secret or expires <= time.time():
                raise ValueError
        except Exception:
            raise XmlaError(
                "Could not obtain a Power BI token. Run az login for the correct tenant "
                "and provide AzureCliCredential (or a configured DefaultAzureCredential)."
            ) from None
        deadline = time.monotonic() + self.timeout_seconds
        messages = {
            "validation": "Bridge rejected the request: use one read-only DAX EVALUATE query.",
            "auth": "XMLA authentication/access failed. Check az login tenant, Read/Build permission, "
                    "XMLA-enabled capacity, tenant settings and workspace/catalog addressing.",
            "timeout": "XMLA query timed out. Narrow the DAX query or reduce its engine workload.",
            "transient": "XMLA service/network temporarily unavailable. Check connectivity and retry.",
            "query": "XMLA query/connection failed. Check DAX syntax, model names, Read/Build access "
                     "and XMLA-enabled capacity. GUID-only catalogs may require the model's XMLA name.",
            "internal": "XMLA bridge failed internally. Rebuild the bridge and verify its .NET runtime.",
        }
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise XmlaError(messages["timeout"])
            request = {
                "version": 1, "server": endpoint.server, "catalog": endpoint.catalog,
                "dax": dax, "max_rows": max_rows, "timeout_seconds": max(1, math.ceil(remaining)),
                "token": secret, "expires_on": expires,
            }
            try:
                process = subprocess.run(
                    [self.dotnet_path, str(self.bridge_path)],
                    input=json.dumps(request), capture_output=True, text=True,
                    encoding="utf-8", timeout=remaining, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired:
                # subprocess.run kills and waits for the child; never echo its captured input.
                raise XmlaError(messages["timeout"]) from None
            except OSError:
                raise XmlaError("Cannot launch XMLA bridge. Install .NET 8+ runtime or set dotnet_path.") from None
            try:
                payload = json.loads(process.stdout)
                if not isinstance(payload, dict) or payload.get("version") != 1 or type(payload.get("ok")) is not bool:
                    raise ValueError
            except (ValueError, TypeError):
                raise XmlaError("Invalid XMLA bridge protocol. Rebuild it; verify .NET 8+ runtime is installed.") from None
            if payload["ok"] and process.returncode == 0:
                return _decode(payload, max_rows)
            code = payload.get("error")
            if not isinstance(code, str) or code not in messages:
                raise XmlaError("XMLA bridge returned an unknown failure. Rebuild the bridge.")
            delay = 0.25 * (2 ** attempt)
            if code == "transient" and attempt < 2 and deadline - time.monotonic() > delay:
                time.sleep(delay)
                continue
            details = []
            raw_details = payload.get("diagnostics", [])
            if isinstance(raw_details, list):
                for detail in raw_details[:4]:
                    if isinstance(detail, dict):
                        parts = [detail.get(key) for key in ("type", "hresult", "message")]
                        safe = " ".join(p for p in parts if isinstance(p, str))
                        safe = safe.replace(secret, "[REDACTED]").replace(dax, "[DAX]")
                        safe = re.sub(r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+", "[JWT]", safe)
                        safe = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", safe)
                        safe = re.sub(
                            r"""(?i)\b(password|pwd|token|authorization|client_secret|access_token)\s*["']?\s*[:=]\s*[^;\r\n]+""",
                            r"\1=[REDACTED]", safe,
                        )
                        details.append(safe[:1400])
            raise XmlaError(messages[code], code=code, diagnostics=" | ".join(details))
        raise AssertionError("unreachable")
