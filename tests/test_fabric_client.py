import json
import struct
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pyodbc

from fabric_client import (
    FABRIC_SCOPE,
    ONELAKE_SCOPE,
    SQL_ACCESS_TOKEN,
    SQL_SCOPE,
    AppError,
    Asset,
    FabricClient,
    SqlEndpoint,
    TABLE_API,
    odbc_value,
    validate_query,
)


WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
ITEM_ID = "22222222-2222-2222-2222-222222222222"
SERVER = "example-test.datawarehouse.fabric.microsoft.com"
WAREHOUSE = Asset(ITEM_ID, "Sales", "Warehouse", WORKSPACE_ID, "Analytics", "")
LAKEHOUSE = Asset(ITEM_ID, "Sales", "Lakehouse", WORKSPACE_ID, "Analytics", "")
ENDPOINT = SqlEndpoint(WAREHOUSE.key, SERVER, "Sales")


class QueryValidationTests(unittest.TestCase):
    def test_select_queries_are_accepted(self):
        queries = [
            "SELECT TOP (10) * FROM dbo.Sales;",
            "-- comment\nSELECT 'DELETE FROM dbo.Sales' AS text;",
            "WITH x AS (SELECT 1 AS n) SELECT n FROM x;",
            "SELECT 1 AS n UNION ALL SELECT 2;",
            "SELECT [update], [drop] FROM dbo.[table];",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                self.assertEqual(validate_query(sql), sql.strip())

    def test_writes_commands_and_multiple_statements_are_rejected(self):
        queries = [
            "",
            "-- comment only",
            "DELETE FROM dbo.Sales;",
            "UPDATE dbo.Sales SET x = 1;",
            "CREATE TABLE dbo.NewTable (n int);",
            "SELECT * INTO dbo.Copy FROM dbo.Sales;",
            "SELECT 1; DROP TABLE dbo.Sales;",
            "SELECT 1; SELECT 2;",
            "EXEC dbo.RunSomething;",
            "WITH x AS (SELECT 1 AS n) DELETE FROM dbo.Sales;",
            "SELECT (",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                with self.assertRaises(AppError):
                    validate_query(sql)


class FabricClientTests(unittest.TestCase):
    def setUp(self):
        credential_patch = patch("fabric_client.AzureCliCredential")
        self.addCleanup(credential_patch.stop)
        self.credential = credential_patch.start().return_value
        self.credential.get_token.return_value = SimpleNamespace(token="fake-token", expires_on=2000000000)
        self.client = FabricClient()

    @patch("fabric_client.shutil.which", return_value="az.cmd")
    @patch("fabric_client.subprocess.run")
    def test_signed_in_account_verifies_token_without_exposing_it(self, run, which):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "user": {"name": "reader@example.com", "type": "user"},
                "tenantId": WORKSPACE_ID,
            }),
        )
        account = self.client.signed_in_account()
        self.assertEqual(account.username, "reader@example.com")
        self.assertEqual(account.tenant_id, WORKSPACE_ID)
        self.assertEqual(account.account_type, "user")
        self.assertEqual(account.expires_at, 2000000000)
        self.assertNotIn("fake-token", repr(account))
        self.credential.get_token.assert_called_once_with(FABRIC_SCOPE)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.args[0], [
            "az.cmd", "account", "show", "--output", "json", "--only-show-errors"
        ])

    @patch("fabric_client.shutil.which", return_value=None)
    def test_identity_missing_cli_is_actionable(self, which):
        with self.assertRaisesRegex(AppError, "Install"):
            self.client.signed_in_account()

    @patch("fabric_client.shutil.which", return_value="az.cmd")
    @patch("fabric_client.subprocess.run")
    def test_identity_cli_failures_are_explicit(self, run, which):
        run.return_value = SimpleNamespace(returncode=1, stdout="")
        with self.assertRaisesRegex(AppError, "az login"):
            self.client.signed_in_account()
        for error in (OSError("cannot start"), subprocess.TimeoutExpired("az", 30)):
            run.side_effect = error
            with self.assertRaisesRegex(AppError, "Unable to read"):
                self.client.signed_in_account()

    @patch("fabric_client.shutil.which", return_value="az.cmd")
    @patch("fabric_client.subprocess.run")
    def test_invalid_identity_metadata_is_not_success(self, run, which):
        for data in ("not json", "[]", "{}", '{"user":{}}'):
            run.return_value = SimpleNamespace(returncode=0, stdout=data)
            with self.subTest(data=data), self.assertRaises(AppError):
                self.client.signed_in_account()
        self.credential.get_token.assert_not_called()

    @patch("fabric_client.shutil.which", return_value="az.cmd")
    @patch("fabric_client.subprocess.run")
    def test_account_metadata_alone_does_not_prove_valid_sign_in(self, run, which):
        from azure.core.exceptions import ClientAuthenticationError

        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "user": {"name": "reader@example.com", "type": "user"},
                "tenantId": WORKSPACE_ID,
            }),
        )
        self.credential.get_token.side_effect = ClientAuthenticationError("Sign in again")
        with self.assertRaises(ClientAuthenticationError):
            self.client.signed_in_account()

    def response(self, data, status=200, headers=None):
        response = Mock(status_code=status, headers=headers or {})
        response.json.return_value = data
        return response

    def entry(self):
        return {
            "id": ITEM_ID,
            "displayName": "Sales",
            "type": "Warehouse",
            "hierarchy": {"workspace": {"id": WORKSPACE_ID, "displayName": "Analytics"}},
        }

    @patch("fabric_client.requests.request")
    def test_table_api_uses_storage_token_and_item_guids(self, request):
        request.return_value = self.response({"schemas": [{"name": "dbo"}], "next_page_token": None})
        self.assertEqual(self.client.list_table_schemas(LAKEHOUSE), [{"name": "dbo"}])
        self.credential.get_token.assert_called_once_with(ONELAKE_SCOPE)
        self.assertEqual(
            request.call_args.args,
            ("GET", f"{TABLE_API}/{WORKSPACE_ID}/{ITEM_ID}/api/2.1/unity-catalog/schemas"),
        )
        self.assertEqual(request.call_args.kwargs["params"], {"catalog_name": ITEM_ID})
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer fake-token")
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    @patch("fabric_client.requests.request")
    def test_table_api_schema_and_table_pagination(self, request):
        for collection in ("schemas", "tables"):
            request.side_effect = [
                self.response({collection: [{"name": "first"}], "next_page_token": "page2"}),
                self.response({collection: [{"name": "second"}]}),
            ]
            with self.subTest(collection=collection):
                result = (
                    self.client.list_table_schemas(LAKEHOUSE) if collection == "schemas"
                    else self.client.list_schema_tables(LAKEHOUSE, "schema.with spaces")
                )
                self.assertEqual([item["name"] for item in result], ["first", "second"])
                self.assertEqual(request.call_args.kwargs["params"]["page_token"], "page2")
                if collection == "tables":
                    self.assertEqual(request.call_args.kwargs["params"]["schema_name"], "schema.with spaces")

    @patch("fabric_client.requests.request")
    def test_table_api_get_metadata_encodes_names_and_disambiguates_schema(self, request):
        request.return_value = self.response({"name": "sales/table", "columns": []})
        data = self.client.get_table_metadata(LAKEHOUSE, "schema.with spaces", "sales/table")
        self.assertEqual(data["name"], "sales/table")
        self.assertIn(f"/tables/{ITEM_ID}.schema.with%20spaces.sales%2Ftable", request.call_args.args[1])
        self.assertEqual(
            request.call_args.kwargs["params"],
            {"catalog_name": ITEM_ID, "schema_name": "schema.with spaces"},
        )

    @patch("fabric_client.requests.request")
    def test_table_api_http_errors_are_not_empty_success(self, request):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                request.return_value = self.response({}, status, {"Retry-After": "9"})
                with self.assertRaisesRegex(AppError, str(status)):
                    self.client.list_table_schemas(LAKEHOUSE)

    @patch("fabric_client.requests.request")
    def test_table_api_invalid_metadata_and_repeated_pages_fail(self, request):
        for data in ({}, {"schemas": "bad"}, {"schemas": [{}]}, {"schemas": [1]},
                     {"schemas": [], "next_page_token": 123}):
            with self.subTest(data=data):
                request.return_value = self.response(data)
                with self.assertRaises(AppError):
                    self.client.list_table_schemas(LAKEHOUSE)
        request.return_value = self.response({"schemas": [], "next_page_token": "repeated"})
        with self.assertRaisesRegex(AppError, "repeated"):
            self.client.list_table_schemas(LAKEHOUSE)

    @patch("fabric_client.requests.request")
    def test_table_api_empty_schemas_and_unsupported_assets(self, request):
        request.return_value = self.response({"schemas": []})
        self.assertEqual(self.client.list_table_schemas(LAKEHOUSE), [])
        report = Asset(ITEM_ID, "Report", "Report", WORKSPACE_ID, "Analytics", "")
        with self.assertRaisesRegex(AppError, "only"):
            self.client.list_table_schemas(report)

    @patch("fabric_client.requests.request")
    def test_catalog_page_and_current_pagination_contract(self, request):
        request.return_value = self.response(
            {"value": [self.entry()], "continuationToken": "next-page"}
        )
        page = self.client.search("Sales", "Warehouse")
        self.assertEqual(page.assets[0], WAREHOUSE)
        self.assertEqual(page.continuation_token, "next-page")
        self.assertEqual(
            request.call_args.kwargs["json"],
            {"search": "Sales", "pageSize": 100, "filter": "Type eq 'Warehouse'"},
        )
        self.assertEqual(
            request.call_args.kwargs["headers"]["x-ms-fabric-skill"], "search-consumption-cli"
        )
        self.assertFalse(request.call_args.kwargs["allow_redirects"])
        self.credential.get_token.assert_called_with(FABRIC_SCOPE)
        self.client.search(continuation_token=page.continuation_token)
        self.assertEqual(request.call_args.kwargs["json"], {"continuationToken": "next-page"})

    @patch("fabric_client.requests.request")
    def test_catalog_empty_and_non_workspace_entries(self, request):
        entry = self.entry()
        entry.pop("hierarchy")
        request.return_value = self.response({"value": [entry]})
        page = self.client.search()
        self.assertEqual(page.assets[0].workspace_id, "")
        self.assertIsNone(page.continuation_token)
        request.return_value = self.response({"value": []})
        self.assertEqual(self.client.search().assets, [])

    @patch("fabric_client.requests.request")
    def test_api_errors_are_explicit(self, request):
        for status, expected in [(401, "az login"), (403, "permission"), (404, "unavailable"),
                                 (429, "17"), (503, "availability")]:
            with self.subTest(status=status):
                request.return_value = self.response({}, status, {"Retry-After": "17"})
                with self.assertRaisesRegex(AppError, expected):
                    self.client.search()

    @patch("fabric_client.requests.request")
    def test_malformed_catalog_is_not_reported_as_empty_success(self, request):
        for data in ({}, {"value": ["bad"]}, {"value": [dict(self.entry(), id="bad")]}):
            with self.subTest(data=data):
                request.return_value = self.response(data)
                with self.assertRaises(AppError):
                    self.client.search()

    @patch("fabric_client.requests.request")
    def test_warehouse_endpoint_resolution(self, request):
        request.return_value = self.response(
            {"displayName": "Sales", "properties": {"connectionString": SERVER}}
        )
        self.assertEqual(self.client.resolve_endpoint(WAREHOUSE), ENDPOINT)
        self.assertIn(f"/warehouses/{ITEM_ID}", request.call_args.args[1])
        self.assertEqual(
            request.call_args.kwargs["headers"]["x-ms-fabric-skill"], "sqldw-cli"
        )

    @patch("fabric_client.requests.request")
    def test_lakehouse_endpoint_resolution_and_provisioning(self, request):
        properties = {"connectionString": SERVER, "id": "endpoint-id", "provisioningStatus": "Success"}
        request.return_value = self.response(
            {"displayName": "Sales", "properties": {"sqlEndpointProperties": properties}}
        )
        self.assertEqual(self.client.resolve_endpoint(LAKEHOUSE), ENDPOINT)
        self.assertIn(f"/lakehouses/{ITEM_ID}", request.call_args.args[1])
        properties["provisioningStatus"] = "InProgress"
        with self.assertRaisesRegex(AppError, "not ready"):
            self.client.resolve_endpoint(LAKEHOUSE)

    @patch("fabric_client.requests.request")
    def test_untrusted_hostname_and_unsupported_assets_are_rejected(self, request):
        request.return_value = self.response(
            {"displayName": "Sales", "properties": {"connectionString": "evil.example;UID=x"}}
        )
        with self.assertRaisesRegex(AppError, "hostname"):
            self.client.resolve_endpoint(WAREHOUSE)
        report = Asset(ITEM_ID, "Report", "Report", WORKSPACE_ID, "Analytics", "")
        with self.assertRaisesRegex(AppError, "only"):
            self.client.resolve_endpoint(report)

    @patch("fabric_client.pyodbc.connect")
    @patch("fabric_client.pyodbc.drivers")
    def test_encrypted_sql_connection_and_token_encoding(self, drivers, connect):
        drivers.return_value = ["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"]
        connection = self.client._connect(ENDPOINT)
        args = connect.call_args
        self.assertIn("DRIVER={ODBC Driver 18 for SQL Server}", args.args[0])
        self.assertIn("Encrypt=yes;TrustServerCertificate=no", args.args[0])
        self.assertNotIn("fake-token", args.args[0])
        self.assertFalse(args.kwargs["autocommit"])
        self.assertEqual(args.kwargs["timeout"], 15)
        token = args.kwargs["attrs_before"][SQL_ACCESS_TOKEN]
        length = struct.unpack("<I", token[:4])[0]
        self.assertEqual(length, len(token[4:]))
        self.assertEqual(token[4:].decode("utf-16-le"), "fake-token")
        self.credential.get_token.assert_called_with(SQL_SCOPE)
        self.assertEqual(connection.timeout, 60)

    @patch("fabric_client.pyodbc.drivers", return_value=[])
    def test_missing_driver_is_actionable(self, drivers):
        with self.assertRaisesRegex(AppError, "Install Microsoft ODBC"):
            self.client._connect(ENDPOINT)

    def test_odbc_database_value_is_escaped(self):
        self.assertEqual(odbc_value("Sales};UID=other"), "{Sales}};UID=other}")

    @patch.object(FabricClient, "_connect")
    def test_connection_test_closes_resources(self, connect):
        cursor = connect.return_value.cursor.return_value
        cursor.fetchone.return_value = ("Sales",)
        self.assertEqual(self.client.test_connection(ENDPOINT), "Sales")
        connect.return_value.close.assert_called_once()
        cursor.close.assert_called_once()
        connect.return_value.commit.assert_not_called()

    @patch.object(FabricClient, "_connect")
    def test_query_result_limit_and_cleanup(self, connect):
        cursor = connect.return_value.cursor.return_value
        cursor.description = [("n",)]
        cursor.fetchmany.return_value = [(1,), (2,), (3,)]
        result = self.client.query(ENDPOINT, "SELECT 1 AS n", max_rows=2)
        self.assertEqual(result.frame["n"].tolist(), [1, 2])
        self.assertTrue(result.truncated)
        cursor.fetchmany.assert_called_once_with(3)
        connect.return_value.close.assert_called_once()
        cursor.close.assert_called_once()
        connect.return_value.commit.assert_not_called()

    @patch.object(FabricClient, "_connect")
    def test_empty_results_keep_columns(self, connect):
        cursor = connect.return_value.cursor.return_value
        cursor.description = [("n",)]
        cursor.fetchmany.return_value = []
        result = self.client.query(ENDPOINT, "SELECT 1 AS n WHERE 1=0")
        self.assertEqual(list(result.frame.columns), ["n"])
        self.assertTrue(result.frame.empty)
        self.assertFalse(result.truncated)

    @patch.object(FabricClient, "_connect")
    def test_duplicate_and_unnamed_columns_are_displayable(self, connect):
        cursor = connect.return_value.cursor.return_value
        cursor.description = [("n",), ("n",), ("n_2",), ("",)]
        cursor.fetchmany.return_value = [(1, 2, 3, 4)]
        result = self.client.query(ENDPOINT, "SELECT 1, 2, 3, 4")
        self.assertEqual(list(result.frame.columns), ["n", "n_2", "n_2_2", "(unnamed)"])
        self.assertEqual(result.frame.iloc[0].tolist(), [1, 2, 3, 4])

    @patch.object(FabricClient, "_connect")
    def test_maximum_row_limit_is_exact_and_checks_one_extra_row(self, connect):
        cursor = connect.return_value.cursor.return_value
        cursor.description = [("n",)]
        cursor.fetchmany.return_value = [(n,) for n in range(10001)]
        result = self.client.query(ENDPOINT, "SELECT n FROM dbo.Numbers", max_rows=10000)
        self.assertEqual(len(result.frame), 10000)
        self.assertTrue(result.truncated)
        cursor.fetchmany.assert_called_once_with(10001)
        cursor.fetchmany.return_value = [(n,) for n in range(10000)]
        result = self.client.query(ENDPOINT, "SELECT n FROM dbo.Numbers", max_rows=10000)
        self.assertFalse(result.truncated)

    @patch.object(FabricClient, "_connect")
    def test_sql_failure_closes_resources_and_propagates(self, connect):
        cursor = connect.return_value.cursor.return_value
        cursor.execute.side_effect = pyodbc.Error("Permission denied")
        with self.assertRaises(pyodbc.Error):
            self.client.query(ENDPOINT, "SELECT 1")
        cursor.close.assert_called_once()
        connect.return_value.close.assert_called_once()

    @patch.object(FabricClient, "_connect")
    def test_validation_precedes_network_access(self, connect):
        for sql, limit in [("DROP TABLE dbo.x", 1), ("SELECT 1", 0), ("SELECT 1", 10001)]:
            with self.subTest(sql=sql, limit=limit):
                with self.assertRaises(AppError):
                    self.client.query(ENDPOINT, sql, limit)
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
