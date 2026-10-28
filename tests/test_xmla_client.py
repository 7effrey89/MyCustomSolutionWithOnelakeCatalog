"""Offline protocol/guardrail tests; compiled bridge tests never open a connection.

Run: .venv\\Scripts\\python.exe -m unittest discover -s tests -p test_xmla_client.py -v
Build the bridge first to enable its subprocess guardrail tests.
"""

import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from xmla_client import (
    TOKEN_SCOPE, XmlaClient, XmlaEndpoint, XmlaError, XmlaResult,
    _decode, _validate_dax,
)

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "xmla_bridge" / "bin" / "Release" / "net8.0" / "XmlaBridge.dll"
DOTNET = Path(r"C:\Program Files\dotnet\dotnet.exe")
WORKSPACE_GUID = "a1234567-1234-1234-1234-123456789abc"
MODEL_GUID = "b1234567-1234-1234-1234-123456789abc"
SERVER = f"powerbi://api.powerbi.com/v1.0/myorg/{WORKSPACE_GUID}"
SECRET = "offline-secret-never-log-this"
XML_DDL = [
    '<Execute xmlns="urn:schemas-microsoft-com:xml-analysis"><Command><Statement>'
    'EVALUATE ROW("x",1)</Statement></Command></Execute>',
    "<Batch><Delete><Object><DatabaseID>model</DatabaseID></Object></Delete></Batch>",
    '{"createOrReplace":{"object":{"database":"model"}}}',
    "CREATE TABLE T (C INTEGER)",
    "ALTER DATABASE [model]",
    "DELETE FROM T",
    "REFRESH DATABASE [model]",
    "SELECT * FROM $SYSTEM.TMSCHEMA_TABLES",
    'EVALUATE ROW("x",1); ALTER DATABASE [model]',
    'EVALUATE ROW("x",1) /* trailing */ CREATE TABLE T',
    'DEFINE MEASURE \'T\'[x] = 1 EVALUATE ROW("x",[x]) EXECUTE bad',
]


def success(rows=None, truncated=False):
    return {
        "version": 1, "ok": True,
        "columns": [{"name": "[Connected]", "type": "Int64"}],
        "rows": [[1]] if rows is None else rows, "truncated": truncated,
    }


def completed(payload, code=0):
    return subprocess.CompletedProcess(["dotnet", "bridge"], code, json.dumps(payload), "")


class EndpointTests(unittest.TestCase):
    def test_workspace_and_model_guids_accepted_verbatim(self):
        endpoint = XmlaEndpoint(SERVER, MODEL_GUID, "asset")
        self.assertEqual(endpoint.catalog, MODEL_GUID)
        self.assertEqual(endpoint.server, SERVER)

    def test_encoded_workspace_and_named_catalog(self):
        endpoint = XmlaEndpoint(
            "powerbi://api.powerbi.com/v1.0/myorg/Finance%20%26%20Sales",
            'Model;Roles=admin;"quoted"', "asset",
        )
        self.assertIn("%20", endpoint.server)
        # Catalogs are values, not connection strings; .NET uses a builder.
        self.assertIn("Roles", endpoint.catalog)

    def test_invalid_servers(self):
        for server in [
            "https://api.powerbi.com/v1.0/myorg/workspace",
            "powerbi://evil.example/v1.0/myorg/workspace",
            "powerbi://api.powerbi.com.evil/v1.0/myorg/workspace",
            "powerbi://user@api.powerbi.com/v1.0/myorg/workspace",
            "powerbi://api.powerbi.com:443/v1.0/myorg/workspace",
            "powerbi://api.powerbi.com/v1.0/myorg/",
            "powerbi://api.powerbi.com/v1.0/myorg/Raw Name",
            "powerbi://api.powerbi.com/v1.0/myorg/a/b",
            "powerbi://api.powerbi.com/v1.0/myorg/a?x=1",
            "powerbi://api.powerbi.com/v1.0/myorg/a#fragment",
            "powerbi://api.powerbi.com/v1.0/myorg/a;Password=x",
            "powerbi://api.powerbi.com/v1.0/myorg/bad%zz",
            "powerbi://api.powerbi.com/v1.0/myorg/%00",
            "powerbi://api.powerbi.com/v1.0/myorg/..",
            None,
        ]:
            with self.subTest(server=server), self.assertRaises(ValueError):
                XmlaEndpoint(server, MODEL_GUID, "asset")

    def test_catalog_and_asset_required(self):
        for catalog, asset in [("", "a"), (" \t", "a"), ("x\n", "a"), ("x", ""), ("x" * 1025, "a")]:
            with self.subTest(catalog=catalog), self.assertRaises(ValueError):
                XmlaEndpoint(SERVER, catalog, asset)


class DaxGuardTests(unittest.TestCase):
    def test_xmla_command_xml_and_ddl_cannot_be_sent(self):
        for dax in XML_DDL:
            with self.subTest(dax=dax), self.assertRaises(ValueError):
                _validate_dax(dax)

    def test_query_scoped_definitions_and_quoted_keywords_allowed(self):
        for dax in [
            'EVALUATE ROW("Connected",1)',
            '/* harmless */ DEFINE MEASURE \'Sales\'[Demo] = 1\nEVALUATE ROW("v",[Demo])',
            '// hi\n-- comment\nEVALUATE ROW("DROP; <Delete/>", 1)',
            'EVALUATE FILTER(\'CREATE TABLE\', [UPDATE] < 2 && [x] > 0) ORDER BY [x]',
            'EVALUATE ROW("say ""EVALUATE""", \'A\'\'B\'[a]]b])',
            'DEFINE VAR _table = { 1, 2 } EVALUATE _table',
        ]:
            with self.subTest(dax=dax):
                _validate_dax(dax)

    def test_empty_malformed_and_multiple_resultsets_rejected(self):
        for dax in ["", " ", None, "EVALUATE ROW(\"x,1)", "/* missing", "DEFINE VAR x = 1",
                    'EVALUATE {1} EVALUATE {2}', "EVALUATE {1};", "EVALUATE {\0}", "x" * 100001]:
            with self.subTest(dax=str(dax)[:60]), self.assertRaises(ValueError):
                _validate_dax(dax)


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Path(self.temp.name) / "XmlaBridge.dll"
        self.bridge.touch()
        self.credential = Mock()
        self.credential.get_token.return_value = SimpleNamespace(
            token=SECRET, expires_on=int(time.time()) + 3600,
        )
        self.client = XmlaClient(self.credential, bridge_path=self.bridge, dotnet_path=DOTNET)
        self.endpoint = XmlaEndpoint(SERVER, MODEL_GUID, "catalog-item")
        self.run_patch = patch("xmla_client.subprocess.run", return_value=completed(success()))
        self.run = self.run_patch.start()
        self.addCleanup(self.run_patch.stop)

    def test_connect_real_probe_and_stdin_only_token_protocol(self):
        result = self.client.connect(self.endpoint)
        self.assertIsInstance(result, XmlaResult)
        self.assertEqual(int(result.frame.iloc[0, 0]), 1)
        self.credential.get_token.assert_called_once_with(TOKEN_SCOPE)
        args, kwargs = self.run.call_args
        self.assertEqual(args[0], [str(DOTNET), str(self.bridge)])
        self.assertNotIn(SECRET, repr(args))
        self.assertNotIn("env", kwargs)
        request = json.loads(kwargs["input"])
        self.assertEqual(request["dax"], 'EVALUATE ROW("Connected",1)')
        self.assertEqual(request["server"], SERVER)
        self.assertEqual(request["catalog"], MODEL_GUID)
        self.assertEqual(request["token"], SECRET)
        self.assertEqual(request["max_rows"], 1)
        self.assertEqual(request["timeout_seconds"], 60)
        self.assertLessEqual(kwargs["timeout"], 60)
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertFalse(result.truncated)

    def test_no_xmla_or_ddl_payload_reaches_bridge_or_credential(self):
        for dax in XML_DDL:
            with self.subTest(dax=dax), self.assertRaises(ValueError):
                self.client.query(self.endpoint, dax, 10)
        self.run.assert_not_called()
        self.credential.get_token.assert_not_called()

    def test_row_limits_and_timeout_guardrails(self):
        for limit in [0, -1, 10001, True, 1.5, "20"]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.client.query(self.endpoint, "EVALUATE {1}", limit)
        for seconds in [0, -1, 61, True, 1.5]:
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                XmlaClient(self.credential, timeout_seconds=seconds)
        self.client.query(self.endpoint, "EVALUATE {1}", 10000)
        self.assertEqual(json.loads(self.run.call_args.kwargs["input"])["max_rows"], 10000)

    def test_missing_bridge_actionable(self):
        self.bridge.unlink()
        with self.assertRaisesRegex(XmlaError, "dotnet build"):
            self.client.connect(self.endpoint)
        self.credential.get_token.assert_not_called()

    def test_auth_failures_and_expired_tokens_redacted(self):
        self.credential.get_token.side_effect = RuntimeError(SECRET)
        with self.assertRaisesRegex(XmlaError, "az login") as ctx:
            self.client.connect(self.endpoint)
        self.assertNotIn(SECRET, str(ctx.exception))
        self.credential.get_token.side_effect = None
        self.credential.get_token.return_value = SimpleNamespace(token=SECRET, expires_on=1)
        with self.assertRaises(XmlaError):
            self.client.connect(self.endpoint)
        self.run.assert_not_called()

    def test_timeout_redacted(self):
        self.run.side_effect = subprocess.TimeoutExpired([SECRET], 60, output=SECRET, stderr=SECRET)
        with self.assertRaisesRegex(XmlaError, "timed out") as ctx:
            self.client.connect(self.endpoint)
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertEqual(self.run.call_count, 1)

    def test_launch_error(self):
        self.run.side_effect = FileNotFoundError(SECRET)
        with self.assertRaisesRegex(XmlaError, "runtime"):
            self.client.connect(self.endpoint)

    def test_bad_protocol_never_echoes_raw_output(self):
        for output in [SECRET, json.dumps([]), "{}", '{"version":1,"ok":1}',
                       '{"version":2,"ok":true}']:
            self.run.return_value = subprocess.CompletedProcess([], 1, output, SECRET)
            with self.subTest(output=output), self.assertRaises(XmlaError) as ctx:
                self.client.connect(self.endpoint)
            self.assertNotIn(SECRET, str(ctx.exception))

    def test_error_categories_no_silent_fallback_or_raw_errors(self):
        for code, expected in [("auth", "Read/Build"), ("query", "DAX syntax"),
                               ("validation", "rejected"), ("internal", "Rebuild"),
                               (SECRET, "unknown")]:
            self.run.reset_mock()
            self.run.return_value = completed(
                {"version": 1, "ok": False, "error": code, "message": SECRET}, 1,
            )
            with self.subTest(code=code), self.assertRaisesRegex(XmlaError, expected) as ctx:
                self.client.connect(self.endpoint)
            self.assertNotIn(SECRET, str(ctx.exception))
            self.assertEqual(self.run.call_count, 1)

    def test_transient_exponential_retry_and_deadline(self):
        self.run.side_effect = [
            completed({"version": 1, "ok": False, "error": "transient"}, 1),
            completed({"version": 1, "ok": False, "error": "transient"}, 1),
            completed(success()),
        ]
        with patch("xmla_client.time.sleep") as sleep:
            self.client.connect(self.endpoint)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.25, 0.5])
        self.assertEqual(self.run.call_count, 3)
        self.credential.get_token.assert_called_once()

    def test_truncation_from_bridge_and_protocol_row_cap_enforced(self):
        self.run.return_value = completed(success([[1]], True))
        self.assertTrue(self.client.connect(self.endpoint).truncated)
        self.run.return_value = completed(success([[1], [2]]))
        with self.assertRaisesRegex(XmlaError, "schema"):
            self.client.connect(self.endpoint)

    def test_nonzero_exit_cannot_be_success(self):
        self.run.return_value = completed(success(), 1)
        with self.assertRaises(XmlaError):
            self.client.connect(self.endpoint)

    def test_sanitized_diagnostics_preserve_root_cause_not_secrets(self):
        self.run.return_value = completed({
            "version": 1, "ok": False, "error": "auth",
            "diagnostics": [{
                "type": "AdomdConnectionException", "hresult": "0x80131500",
                "message": f"Authentication failed for all authenticators; {SECRET}; RootActivityId: support-id",
            }],
        }, 1)
        with self.assertRaises(XmlaError) as ctx:
            self.client.connect(self.endpoint)
        self.assertEqual(ctx.exception.code, "auth")
        self.assertIn("Authentication failed for all authenticators", ctx.exception.diagnostics)
        self.assertIn("RootActivityId", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))


class DecodeTests(unittest.TestCase):
    def test_nullable_types_decimal_dates_binary_and_duplicate_labels(self):
        columns = [
            ("x", "Int64"), ("x", "Boolean"), ("x_2", "String"), ("x", "Decimal"),
            ("when", "DateTime"), ("blob", "Byte[]"), ("huge", "UInt64"),
            ("floating", "Double"),
        ]
        payload = {
            "columns": [{"name": n, "type": t} for n, t in columns],
            "rows": [
                [9223372036854775807, True, "hello", "123456789.123456789",
                 "2026-10-28T10:00:00.1234567", "AAEC", 18446744073709551615, 1.5],
                [None] * len(columns),
            ], "truncated": False,
        }
        frame = _decode(payload, 2).frame
        self.assertEqual(list(frame.columns), ["x", "x_2", "x_2_2", "x_3", "when", "blob", "huge", "floating"])
        self.assertEqual(frame["x"].iloc[0], 9223372036854775807)
        self.assertEqual(frame["huge"].iloc[0], 18446744073709551615)
        self.assertTrue(pd.isna(frame["x"].iloc[1]))
        self.assertEqual(str(frame["x"].dtype), "Int64")
        self.assertEqual(str(frame["x_2"].dtype), "boolean")
        self.assertEqual(frame["x_3"].iloc[0], Decimal("123456789.123456789"))
        self.assertIsInstance(frame["when"].iloc[0], datetime)
        self.assertEqual(frame["blob"].iloc[0], b"\0\1\2")

    def test_empty_rowset_keeps_schema(self):
        frame = _decode(success([], False), 10).frame
        self.assertTrue(frame.empty)
        self.assertEqual(list(frame.columns), ["[Connected]"])
        self.assertEqual(str(frame.dtypes.iloc[0]), "Int64")

    def test_malformed_schema_rejected(self):
        for payload in [
            {}, {"columns": [], "rows": [[]], "truncated": "false"},
            {"columns": [{"name": "x"}], "rows": [], "truncated": False},
            {"columns": [{"name": "x", "type": "Int64"}], "rows": [[1, 2]], "truncated": False},
            {"columns": [{"name": "x", "type": "Decimal"}], "rows": [["oops"]], "truncated": False},
        ]:
            with self.subTest(payload=payload), self.assertRaises(XmlaError):
                _decode(payload, 10)


@unittest.skipUnless(BRIDGE.is_file() and DOTNET.is_file(), "Build bridge to run offline bridge guardrails.")
class CompiledBridgeTests(unittest.TestCase):
    def request(self, **overrides):
        request = {
            "version": 1, "server": SERVER, "catalog": MODEL_GUID,
            "dax": 'EVALUATE ROW("Connected",1)', "token": SECRET,
            "expires_on": int(time.time()) + 3600, "max_rows": 1, "timeout_seconds": 1,
        }
        request.update(overrides)
        return request

    def assert_rejected(self, request):
        process = subprocess.run(
            [str(DOTNET), str(BRIDGE)], input=json.dumps(request),
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        self.assertEqual(process.returncode, 1, process.stdout)
        payload = json.loads(process.stdout)
        self.assertEqual({k: payload[k] for k in ("version", "ok", "error")},
                         {"version": 1, "ok": False, "error": "validation"})
        self.assertTrue(payload["diagnostics"])
        self.assertNotIn(SECRET, process.stdout + process.stderr)

    def test_compiled_bridge_independently_rejects_xmla_xml_ddl(self):
        for dax in XML_DDL:
            with self.subTest(dax=dax):
                self.assert_rejected(self.request(dax=dax))

    def test_compiled_bridge_enforces_endpoint_limits_and_protocol(self):
        for change in [
            {"server": "https://evil.example"},
            {"server": SERVER + ";Password=bad"},
            {"server": SERVER + "/other"},
            {"server": SERVER + "?x=1"},
            {"catalog": ""}, {"catalog": "x\n"}, {"max_rows": 10001},
            {"max_rows": 0}, {"timeout_seconds": 61}, {"timeout_seconds": 0},
            {"token": ""}, {"expires_on": 1}, {"version": 2},
            {"dax": 'EVALUATE {1} EVALUATE {2}'}, {"dax": "/* unterminated"},
        ]:
            with self.subTest(change=change):
                self.assert_rejected(self.request(**change))

    def test_malformed_protocol_cannot_echo_token_payload(self):
        process = subprocess.run(
            [str(DOTNET), str(BRIDGE)], input='{"token":"' + SECRET + '","version":bad}',
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["error"], "validation")
        self.assertNotIn(SECRET, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
