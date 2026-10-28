from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
from contextlib import closing
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import pandas as pd
import pyodbc
import requests
import sqlglot
from azure.identity import AzureCliCredential
from sqlglot import exp
from sqlglot.errors import SqlglotError


FABRIC_API = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
POWERBI_API = "https://api.powerbi.com/v1.0/myorg"
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
SQL_SCOPE = "https://database.windows.net/.default"
ONELAKE_SCOPE = "https://storage.azure.com/.default"
TABLE_API = "https://onelake.table.fabric.microsoft.com/delta"
CATALOG_URL = "https://app.fabric.microsoft.com/onelake"
CONNECTABLE_TYPES = ("Warehouse", "Lakehouse")
CATALOG_TYPES = (*CONNECTABLE_TYPES, "SemanticModel", "Report", "Notebook", "DataPipeline", "Eventhouse")
SQL_ACCESS_TOKEN = 1256
QUERY_TIMEOUT = 60


class AppError(Exception):
    """An actionable error that can be displayed to the local user."""


@dataclass(frozen=True)
class SignedInAccount:
    username: str
    tenant_id: str
    account_type: str
    expires_at: int


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    type: str
    workspace_id: str
    workspace_name: str
    description: str

    @property
    def key(self) -> str:
        return f"{self.workspace_id}:{self.id}"

    @property
    def label(self) -> str:
        return f"{self.name} | {self.type} | {self.workspace_name} | {self.id[:8]}"

    @property
    def url(self) -> str:
        return (
            "https://app.fabric.microsoft.com/groups/"
            f"{self.workspace_id}/items/{self.id}"
        )


@dataclass(frozen=True)
class CatalogPage:
    assets: list[Asset]
    continuation_token: str | None


@dataclass(frozen=True)
class SqlEndpoint:
    asset_key: str
    server: str
    database: str


@dataclass(frozen=True)
class QueryResult:
    frame: pd.DataFrame
    truncated: bool


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise AppError(f"Fabric returned missing or invalid '{key}' metadata.")
    return value


def _guid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise AppError("Fabric returned an invalid item or workspace ID.") from exc


def validate_query(sql: str) -> str:
    """Accept one SELECT query, including CTEs and set operations."""
    try:
        statements = [node for node in sqlglot.parse(sql, read="tsql") if node]
    except SqlglotError as exc:
        raise AppError(f"Cannot parse this T-SQL query: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise AppError("Enter one read-only SELECT query (CTEs and UNION are supported).")
    tree = statements[0]
    if not any(tree.find_all(exp.Select)):
        raise AppError("The query must contain a SELECT.")
    if any(
        isinstance(node, (exp.DDL, exp.DML, exp.Into, exp.Command, exp.Lock))
        for node in tree.walk()
    ):
        raise AppError("SQL writes, SELECT INTO, commands, and locking clauses are disabled.")
    return sql.strip()


def odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


class FabricClient:
    def __init__(self) -> None:
        self.credential = AzureCliCredential(process_timeout=30)

    def signed_in_account(self) -> SignedInAccount:
        executable = shutil.which("az")
        if executable is None:
            raise AppError("Azure CLI is not installed or is not on PATH. Install it, then run az login.")
        try:
            result = subprocess.run(
                [executable, "account", "show", "--output", "json", "--only-show-errors"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppError("Unable to read the Azure CLI account. Check Azure CLI and retry.") from exc
        if result.returncode != 0:
            raise AppError("No Azure CLI account is available. Run az login for your Fabric tenant.")
        try:
            account = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AppError("Azure CLI returned invalid account metadata. Run az login again.") from exc
        if not isinstance(account, dict) or not isinstance(account.get("user"), dict):
            raise AppError("Azure CLI returned incomplete account metadata. Run az login again.")
        user = account["user"]
        username = _text(user, "name")
        tenant_id = _text(account, "tenantId")
        account_type = _text(user, "type")
        token = self.credential.get_token(FABRIC_SCOPE)
        return SignedInAccount(username, tenant_id, account_type, token.expires_on)

    def _table_request(
        self, asset: Asset, path: str, params: dict[str, str]
    ) -> dict[str, Any]:
        if asset.type not in CONNECTABLE_TYPES or not asset.workspace_id:
            raise AppError("Table API connections support Warehouse and Lakehouse items only.")
        workspace, item = _guid(asset.workspace_id), _guid(asset.id)
        token = self.credential.get_token(ONELAKE_SCOPE).token
        response = requests.request(
            "GET",
            f"{TABLE_API}/{workspace}/{item}/api/2.1/unity-catalog/{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(10, 60),
            allow_redirects=False,
        )
        if response.status_code != 200:
            hints = {
                400: (
                    "This request may not be supported for the item type, or its parameters "
                    "may be invalid. Check the API's supported capabilities."
                ),
                401: "Run az login again for your Fabric tenant.",
                403: "Your identity needs OneLake table read permissions.",
                404: (
                    "The resource is unavailable, unsupported, or not authorized. "
                    "A not-found response does not prove that the table does not exist."
                ),
                429: f"Retry after {response.headers.get('Retry-After', '60')} seconds.",
            }
            hint = hints.get(response.status_code, "Check OneLake service availability and retry.")
            raise AppError(f"OneLake Table API returned HTTP {response.status_code}. {hint}")
        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise AppError("OneLake Table API returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise AppError("OneLake Table API returned an unexpected response shape.")
        return data

    def _table_list(
        self, asset: Asset, collection: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen_tokens: set[str] = set()
        while True:
            data = self._table_request(asset, collection, params)
            page = data.get(collection)
            if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                raise AppError(f"OneLake Table API returned invalid {collection} metadata.")
            for entry in page:
                _text(entry, "name")
            entries.extend(page)
            next_token = data.get("next_page_token")
            if next_token is None or next_token == "":
                return entries
            if not isinstance(next_token, str) or next_token in seen_tokens:
                raise AppError("OneLake Table API returned an invalid or repeated page token.")
            seen_tokens.add(next_token)
            params = {**params, "page_token": next_token}

    def list_table_schemas(self, asset: Asset) -> list[dict[str, Any]]:
        return self._table_list(asset, "schemas", {"catalog_name": _guid(asset.id)})

    def list_schema_tables(self, asset: Asset, schema: str) -> list[dict[str, Any]]:
        if not schema:
            raise AppError("Choose a schema before listing tables.")
        return self._table_list(
            asset, "tables", {"catalog_name": _guid(asset.id), "schema_name": schema}
        )

    def get_table_metadata(self, asset: Asset, schema: str, table: str) -> dict[str, Any]:
        if not schema or not table:
            raise AppError("Choose a schema and table to inspect.")
        catalog = _guid(asset.id)
        full_name = quote(f"{catalog}.{schema}.{table}", safe="")
        data = self._table_request(
            asset,
            f"tables/{full_name}",
            {"catalog_name": catalog, "schema_name": schema},
        )
        _text(data, "name")
        return data

    def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None, service: str = "fabric",
        expected_status: int = 200, skill: str | None = None,
    ) -> dict[str, Any]:
        if service not in ("fabric", "powerbi") or not path.startswith("/") or path.startswith("//"):
            raise AppError("Invalid service request.")
        token = self.credential.get_token(FABRIC_SCOPE if service == "fabric" else POWERBI_SCOPE).token
        skill = skill or ("search-consumption-cli" if path == "/catalog/search" else "sqldw-cli")
        response = requests.request(
            method,
            (FABRIC_API if service == "fabric" else POWERBI_API) + path,
            json=body,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "x-ms-fabric-skill": skill,
            },
            timeout=(10, 60),
            allow_redirects=False,
        )
        if response.status_code != expected_status:
            hints = {
                401: "Run az login again for your Fabric tenant.",
                403: (
                    "Your identity lacks permission or the tenant blocks this API. "
                    "Catalog search requires Catalog.Read.All. Admin features require "
                    "a tenant-admin role and Tenant.Read.All; other features require "
                    "the corresponding item/workspace scopes. No access bypass is attempted."
                ),
                404: "The asset is unavailable or you no longer have access.",
                429: f"Rate limited. Retry after {response.headers.get('Retry-After', '60')} seconds.",
            }
            hint = hints.get(response.status_code, "Check Fabric service availability and retry.")
            name = "Fabric API" if service == "fabric" else "Power BI API"
            raise AppError(f"{name} returned HTTP {response.status_code}. {hint}")
        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise AppError("Fabric returned an invalid JSON response.") from exc
        if not isinstance(data, dict):
            raise AppError("Fabric returned an unexpected response shape.")
        return data

    def search(
        self, search: str = "", item_type: str = "All", continuation_token: str | None = None
    ) -> CatalogPage:
        if continuation_token:
            # The current API forbids search/filter alongside a continuation token.
            body: dict[str, Any] = {"continuationToken": continuation_token}
        else:
            body = {"search": search, "pageSize": 100}
            if item_type != "All":
                if item_type not in CATALOG_TYPES:
                    raise AppError("Unsupported catalog type filter.")
                body["filter"] = f"Type eq '{item_type}'"
        data = self._request("POST", "/catalog/search", body=body)
        entries = data.get("value")
        if not isinstance(entries, list):
            raise AppError("Fabric catalog response is missing its asset list.")
        assets = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise AppError("Fabric returned invalid catalog entry metadata.")
            hierarchy = entry.get("hierarchy", {})
            workspace = hierarchy.get("workspace", {}) if isinstance(hierarchy, dict) else {}
            if not isinstance(workspace, dict):
                raise AppError("Fabric returned invalid workspace metadata.")
            # Some catalog entries are not workspace items (for example workspaces).
            workspace_id = workspace.get("id")
            assets.append(
                Asset(
                    id=_guid(_text(entry, "id")),
                    name=_text(entry, "displayName"),
                    type=_text(entry, "type"),
                    workspace_id=_guid(workspace_id) if workspace_id else "",
                    workspace_name=workspace.get("displayName") or "(not a workspace item)",
                    description=entry.get("description") or "",
                )
            )
        continuation = data.get("continuationToken")
        if continuation is not None and not isinstance(continuation, str):
            raise AppError("Fabric returned an invalid continuation token.")
        return CatalogPage(assets, continuation or None)

    def resolve_endpoint(self, asset: Asset) -> SqlEndpoint:
        if asset.type not in CONNECTABLE_TYPES or not asset.workspace_id:
            raise AppError("SQL connections currently support Warehouse and Lakehouse items only.")
        collection = "warehouses" if asset.type == "Warehouse" else "lakehouses"
        workspace_id, item_id = _guid(asset.workspace_id), _guid(asset.id)
        data = self._request("GET", f"/workspaces/{workspace_id}/{collection}/{item_id}")
        properties = data.get("properties")
        if not isinstance(properties, dict):
            raise AppError("Fabric returned no SQL endpoint properties.")
        if asset.type == "Lakehouse":
            properties = properties.get("sqlEndpointProperties")
            if not isinstance(properties, dict) or properties.get("provisioningStatus") != "Success":
                raise AppError("This Lakehouse SQL analytics endpoint is not ready. Retry later.")
        server = _text(properties, "connectionString")
        if not re.fullmatch(r"[a-zA-Z0-9-]+\.datawarehouse\.fabric\.microsoft\.com", server):
            raise AppError("Fabric returned an unexpected SQL hostname; connection was blocked.")
        return SqlEndpoint(asset.key, server, _text(data, "displayName"))

    def _connect(self, endpoint: SqlEndpoint) -> pyodbc.Connection:
        drivers = pyodbc.drivers()
        driver = next(
            (name for name in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
             if name in drivers),
            None,
        )
        if not driver:
            raise AppError("Install Microsoft ODBC Driver 18 for SQL Server, then restart the app.")
        token_bytes = self.credential.get_token(SQL_SCOPE).token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
        connection_string = (
            f"DRIVER={odbc_value(driver)};"
            f"SERVER={odbc_value('tcp:' + endpoint.server + ',1433')};"
            f"DATABASE={odbc_value(endpoint.database)};"
            "Encrypt=yes;TrustServerCertificate=no;APP=OneLakeStreamlit;"
        )
        connection = pyodbc.connect(
            connection_string,
            attrs_before={SQL_ACCESS_TOKEN: token_struct},
            timeout=15,
            autocommit=False,
        )
        connection.timeout = QUERY_TIMEOUT
        return connection

    def test_connection(self, endpoint: SqlEndpoint) -> str:
        with closing(self._connect(endpoint)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("SELECT DB_NAME() AS database_name")
                row = cursor.fetchone()
                if row is None:
                    raise AppError("SQL connection test returned no database name.")
                return str(row[0])

    def query(self, endpoint: SqlEndpoint, sql: str, max_rows: int = 1000) -> QueryResult:
        sql = validate_query(sql)
        if not 1 <= max_rows <= 10000:
            raise AppError("The result limit must be between 1 and 10,000 rows.")
        with closing(self._connect(endpoint)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute(sql)
                if cursor.description is None:
                    raise AppError("The query did not return a tabular result.")
                columns: list[str] = []
                used: set[str] = set()
                for column in cursor.description:
                    name = column[0] or "(unnamed)"
                    candidate = name
                    suffix = 2
                    while candidate in used:
                        candidate = f"{name}_{suffix}"
                        suffix += 1
                    used.add(candidate)
                    columns.append(candidate)
                rows = cursor.fetchmany(max_rows + 1)
                frame = pd.DataFrame.from_records(
                    [tuple(row) for row in rows[:max_rows]], columns=columns
                )
                return QueryResult(frame, len(rows) > max_rows)
