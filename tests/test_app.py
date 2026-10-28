import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from fabric_client import AppError, Asset, CatalogPage, QueryResult, SignedInAccount, SqlEndpoint
from xmla_client import XmlaError, XmlaResult


WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
WAREHOUSE = Asset(
    "22222222-2222-2222-2222-222222222222", "Sales", "Warehouse", WORKSPACE_ID, "Analytics", ""
)
LAKEHOUSE = Asset(
    "33333333-3333-3333-3333-333333333333", "Lake", "Lakehouse", WORKSPACE_ID, "Analytics", ""
)
REPORT = Asset(
    "44444444-4444-4444-4444-444444444444", "Report", "Report", WORKSPACE_ID, "Analytics", ""
)
MODEL = Asset(
    "66666666-6666-6666-6666-666666666666", "Revenue", "SemanticModel",
    WORKSPACE_ID, "Analytics", "",
)
APP = str(Path(__file__).resolve().parents[1] / "app.py")


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()


def open_tab(app, label):
    app.session_state["explorer_tab"] = label
    app.run()


def connect_sql(app, asset=WAREHOUSE):
    app.button(key=f"select_asset_{asset.key}").click().run()
    click(app, "Connect via SQL endpoint")


class AppTests(unittest.TestCase):
    def setUp(self):
        client_patch = patch("fabric_client.FabricClient")
        self.addCleanup(client_patch.stop)
        self.client = client_patch.start().return_value
        self.client.signed_in_account.return_value = SignedInAccount(
            "reader@example.com", WORKSPACE_ID, "user", int(time.time()) + 3600
        )
        self.client.search.return_value = CatalogPage([WAREHOUSE, LAKEHOUSE, REPORT], None)
        self.client.resolve_endpoint.side_effect = lambda asset: SqlEndpoint(
            asset.key, "example.datawarehouse.fabric.microsoft.com", asset.name
        )
        self.client.test_connection.return_value = "Sales"
        self.client.query.return_value = QueryResult(pd.DataFrame({"n": [1, 2]}), False)
        self.client.list_table_schemas.return_value = [{"name": "dbo"}]
        self.client.list_schema_tables.return_value = [{"name": "SalesTable", "data_source_format": "DELTA"}]
        self.client.get_table_metadata.return_value = {"name": "SalesTable", "columns": [{"name": "n"}]}
        details_patch = patch("explorer.CatalogDetails")
        self.addCleanup(details_patch.stop)
        self.details = details_patch.start().return_value
        self.details.metadata.return_value = {"id": WAREHOUSE.id, "description": "Live metadata"}
        self.details.workspace.return_value = {"id": WORKSPACE_ID, "displayName": "Analytics"}
        self.details.endpoint_metadata.return_value = {"displayName": "Sales"}
        self.details.connections.return_value = []
        self.details.workspace_roles.return_value = [{"role": "Viewer", "principal": {"displayName": "Reader"}}]
        self.details.item_access.return_value = [{"principal": {"displayName": "Admin-only access record"}}]
        self.details.domains.return_value = [{"id": WAREHOUSE.id, "displayName": "Finance"}]
        self.details.domain_workspaces.return_value = []
        self.details.monitoring.return_value = []
        xmla_patch = patch("xmla_client.XmlaClient")
        self.addCleanup(xmla_patch.stop)
        self.xmla = xmla_patch.start().return_value
        self.xmla.query.return_value = XmlaResult(pd.DataFrame({"Amount": [123]}), False)
        self.app = AppTest.from_file(APP, default_timeout=20).run()
        click(self.app, "Sales")

    def test_initial_page_is_wide_catalog_without_selection_or_metadata_calls(self):
        self.details.reset_mock()
        app = AppTest.from_file(APP, default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertNotIn("selected_asset", app.session_state)
        self.assertFalse(app.session_state.asset_details_open)
        self.assertTrue(any(block.proto.id.endswith("-catalog_wide") for block in app.get("flex_container")))
        self.assertFalse(any(block.proto.id.endswith("-asset_detail") for block in app.get("flex_container")))
        self.assertEqual(
            [app.text_input(key=key).label for key in ("filter_name", "filter_workspace", "filter_description")],
            ["Name", "Workspace", "Description"],
        )
        self.assertEqual(app.multiselect(key="filter_types").label, "Type")
        self.details.metadata.assert_not_called()
        self.details.workspace.assert_not_called()
        self.details.endpoint_metadata.assert_not_called()
        self.assertFalse(any(button.key == "close_asset_details" for button in app.button))

    def test_close_restores_wide_catalog_and_reopening_keeps_sql_results_and_filters(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        self.app.text_input(key="filter_name").set_value("Sales").run()
        endpoint = self.app.session_state.endpoint
        self.app.button(key="close_asset_details").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.session_state.asset_details_open)
        self.assertFalse(any(block.proto.id.endswith("-asset_detail") for block in self.app.get("flex_container")))
        self.assertEqual(self.app.text_input(key="filter_name").value, "Sales")
        self.assertEqual(self.app.session_state.endpoint, endpoint)
        self.assertIn("result", self.app.session_state)
        self.assertFalse(any(button.label == "Run query" for button in self.app.button))
        click(self.app, "Sales")
        self.assertTrue(self.app.session_state.asset_details_open)
        self.assertEqual(self.app.session_state.endpoint, endpoint)
        self.assertEqual(self.app.dataframe[-1].value["n"].tolist(), [1, 2])
        self.client.resolve_endpoint.assert_called_once()
        self.client.query.assert_called_once()
        self.details.metadata.assert_called_once()

    def test_closed_catalog_stays_wide_through_style_changes_and_reopens_another_asset(self):
        self.app.button(key="close_asset_details").click().run()
        for fabric_style in (False, True):
            self.app.toggle(key="fabric_style").set_value(fabric_style).run()
            self.assertFalse(self.app.exception)
            self.assertFalse(self.app.session_state.asset_details_open)
            self.assertTrue(any(block.proto.id.endswith("-catalog_wide") for block in self.app.get("flex_container")))
        click(self.app, "Lake")
        self.assertTrue(self.app.session_state.asset_details_open)
        self.assertEqual(self.app.session_state.selected_asset, LAKEHOUSE.key)
        self.details.metadata.assert_called_with(LAKEHOUSE)

    def test_close_keeps_selected_tab_and_does_not_reload_cached_metadata(self):
        open_tab(self.app, "Permissions")
        self.app.button(key="close_asset_details").click().run()
        self.app.run()
        click(self.app, "Sales")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.explorer_tab, "Permissions")
        self.details.workspace_roles.assert_called_once_with(WAREHOUSE)

    def test_close_keeps_table_api_schema_selection_and_metadata(self):
        self.client.list_table_schemas.return_value = [{"name": "dbo"}, {"name": "sales"}]
        click(self.app, "Lake")
        click(self.app, "Connect via Table API")
        self.app.selectbox(key="api_schema").select("sales").run()
        click(self.app, "List tables")
        click(self.app, "Inspect table")
        metadata = self.app.session_state.table_metadata
        self.app.button(key="close_asset_details").click().run()
        self.app.run()
        click(self.app, "Lake")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.selectbox(key="api_schema").value, "sales")
        self.assertEqual(self.app.session_state.table_metadata, metadata)
        self.client.list_table_schemas.assert_called_once_with(LAKEHOUSE)
        self.client.get_table_metadata.assert_called_once_with(LAKEHOUSE, "sales", "SalesTable")

    def test_fabric_style_defaults_on_and_original_can_be_restored(self):
        self.assertTrue(self.app.toggle(key="fabric_style").value)
        self.assertTrue(any("Fabric-inspired (light)" in item.value for item in self.app.caption))
        self.app.toggle(key="fabric_style").set_value(False).run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Original Streamlit" in item.value for item in self.app.caption))
        self.client.search.assert_called_once_with("", "All")

    def test_connect_uses_native_primary_variant_in_both_styles(self):
        for fabric_style in (True, False):
            self.app.toggle(key="fabric_style").set_value(fabric_style).run()
            popover = next(node for node in self.app.get("popover") if node.proto.popover.label == "Connect")
            self.assertEqual(popover.proto.popover.type, "primary")

    def test_non_table_item_types_do_not_show_tables_tab_or_call_table_api(self):
        for index, item_type in enumerate(
            ("Report", "SemanticModel", "Notebook", "DataPipeline", "Ontology", "Plan", "DataAgent", "Eventhouse")
        ):
            with self.subTest(item_type=item_type):
                asset = Asset(
                    f"77777777-7777-7777-7777-{index:012d}", f"Item {index}",
                    item_type, WORKSPACE_ID, "Analytics", "",
                )
                self.client.search.return_value = CatalogPage([asset], None)
                click(self.app, "Search catalog")
                click(self.app, asset.name)
                self.assertFalse(self.app.exception)
                self.assertNotIn("Tables & columns", [tab.label for tab in self.app.tabs])
        self.client.list_table_schemas.assert_not_called()
        self.client.list_schema_tables.assert_not_called()
        self.client.get_table_metadata.assert_not_called()

    def test_warehouse_and_lakehouse_keep_table_browser_tab(self):
        for asset in (WAREHOUSE, LAKEHOUSE):
            click(self.app, asset.name)
            self.assertIn("Tables & columns", [tab.label for tab in self.app.tabs])
        self.client.list_table_schemas.assert_not_called()
        open_tab(self.app, "Tables & columns")
        self.client.list_table_schemas.assert_called_once_with(LAKEHOUSE)

    def test_stale_table_tab_selection_is_normalized_for_non_table_item(self):
        click(self.app, "Report")
        self.app.session_state["explorer_tab"] = "Tables & columns"
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.explorer_tab, "Overview")
        self.assertNotIn("Tables & columns", [tab.label for tab in self.app.tabs])
        self.client.list_table_schemas.assert_not_called()

    def test_style_toggle_preserves_sql_results_filters_and_admin_scope(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        self.app.text_input(key="filter_name").set_value("Sales").run()
        self.app.toggle(key="admin_view").set_value(True).run()
        calls = self.client.search.call_count
        endpoint = self.app.session_state.endpoint
        for fabric_style in (False, True):
            self.app.toggle(key="fabric_style").set_value(fabric_style).run()
            self.assertFalse(self.app.exception)
            self.assertEqual(self.app.text_input(key="filter_name").value, "Sales")
            self.assertTrue(self.app.toggle(key="admin_view").value)
            self.assertEqual(self.app.session_state.endpoint, endpoint)
            self.assertEqual(self.app.session_state.connection_mode, "SQL endpoint")
            self.assertEqual(self.app.dataframe[-1].value["n"].tolist(), [1, 2])
            self.assertTrue(any("Read-only demo" in item.value for item in self.app.warning))
        self.assertEqual(self.client.search.call_count, calls)

    def test_style_toggle_preserves_submitted_search_fields(self):
        self.app.text_input(key="catalog_search_text").set_value("revenue")
        self.app.selectbox(key="catalog_search_type").select("SemanticModel")
        click(self.app, "Search catalog")
        calls = self.client.search.call_count
        self.app.toggle(key="fabric_style").set_value(False).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.text_input(key="catalog_search_text").value, "revenue")
        self.assertEqual(self.app.selectbox(key="catalog_search_type").value, "SemanticModel")
        self.assertEqual(self.client.search.call_count, calls)
        self.client.search.assert_called_with("revenue", "SemanticModel")

    def test_style_toggle_preserves_table_api_connection(self):
        click(self.app, "Lake")
        click(self.app, "Connect via Table API")
        click(self.app, "List tables")
        self.app.toggle(key="fabric_style").set_value(False).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.connection_mode, "Table API")
        self.assertIn("schema_tables", self.app.session_state)
        self.client.list_table_schemas.assert_called_once_with(LAKEHOUSE)
        self.assertTrue(any(button.label == "Inspect table" for button in self.app.button))

    def test_style_toggle_preserves_xmla_connection_and_results(self):
        self.connect_xmla()
        click(self.app, "Run DAX query")
        endpoint = self.app.session_state.xmla_endpoint
        self.app.toggle(key="fabric_style").set_value(False).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.xmla_endpoint, endpoint)
        self.assertEqual(self.app.session_state.connection_mode, "XMLA / DAX")
        self.assertEqual(self.app.dataframe[-1].value["Amount"].tolist(), [123])
        self.xmla.connect.assert_called_once()

    def connect_xmla(self):
        self.client.search.return_value = CatalogPage([WAREHOUSE, MODEL], None)
        click(self.app, "Search catalog")
        click(self.app, MODEL.name)
        click(self.app, "Connect via XMLA / DAX")

    def test_semantic_model_uses_actual_xmla_adapter_and_dax_results(self):
        self.connect_xmla()
        self.assertFalse(self.app.exception)
        endpoint = self.xmla.connect.call_args.args[0]
        self.assertEqual(endpoint.catalog, MODEL.name)
        self.assertEqual(endpoint.asset_key, MODEL.key)
        self.assertIn("powerbi://", endpoint.server)
        self.assertIn(MODEL.workspace_id, endpoint.server)
        self.client.resolve_endpoint.assert_not_called()
        self.assertFalse(any(button.label == "Run query" for button in self.app.button))
        click(self.app, "Run DAX query")
        self.assertFalse(self.app.exception)
        self.xmla.query.assert_called_once_with(endpoint, 'EVALUATE ROW("Connected", 1)', 1000)
        self.assertEqual(self.app.dataframe[-1].value["Amount"].tolist(), [123])

    def test_failed_xmla_connection_is_visible_not_successful(self):
        self.xmla.connect.side_effect = XmlaError("XMLA capacity unavailable")
        self.connect_xmla()
        self.assertFalse(self.app.exception)
        self.assertNotIn("connection_mode", self.app.session_state)
        self.assertTrue(any("capacity unavailable" in item.value for item in self.app.error))

    def test_failed_dax_clears_previous_result(self):
        self.connect_xmla()
        click(self.app, "Run DAX query")
        self.xmla.query.side_effect = XmlaError("Read-only DAX required")
        click(self.app, "Run DAX query")
        self.assertFalse(self.app.exception)
        self.assertNotIn("dax_result", self.app.session_state)
        self.assertTrue(any("DAX query failed" in item.value for item in self.app.error))

    def test_xmla_results_are_cleared_on_asset_change(self):
        self.connect_xmla()
        click(self.app, "Run DAX query")
        connect_sql(self.app)
        self.assertNotIn("dax_result", self.app.session_state)
        self.assertNotIn("xmla_endpoint", self.app.session_state)
        self.assertFalse(any(button.label == "Run DAX query" for button in self.app.button))

    def test_developer_default_is_read_only_and_does_not_fetch_optional_sections(self):
        self.assertFalse(self.app.toggle(key="admin_view").value)
        self.assertTrue(any("Read-only demo" in item.value for item in self.app.warning))
        self.assertTrue(any("No create, update, delete" in item.value for item in self.app.warning))
        self.details.metadata.assert_called_once_with(WAREHOUSE)
        self.details.workspace.assert_called_once_with(WAREHOUSE)
        self.details.endpoint_metadata.assert_called_once_with(WAREHOUSE)
        self.client.list_table_schemas.assert_not_called()
        self.details.connections.assert_not_called()
        self.details.workspace_roles.assert_not_called()
        self.details.monitoring.assert_not_called()
        self.details.domains.assert_not_called()
        self.details.item_access.assert_not_called()
        self.details.start_lineage_scan.assert_not_called()
        self.assertFalse(any(button.label == "Load item access (admin)" for button in self.app.button))
        self.assertTrue(any("does not impersonate" in item.value for item in self.app.caption))

    def test_admin_toggle_exposes_only_on_demand_admin_features(self):
        self.app.toggle(key="admin_view").set_value(True).run()
        self.assertFalse(self.app.exception)
        self.details.item_access.assert_not_called()
        self.details.start_lineage_scan.assert_not_called()
        open_tab(self.app, "Permissions")
        self.details.item_access.assert_called_once_with(WAREHOUSE)
        self.assertTrue(any("Admin-only access record" in str(item.value) for item in self.app.dataframe))
        self.app.toggle(key="admin_view").set_value(False).run()
        self.assertFalse(any("Admin-only access record" in str(item.value) for item in self.app.dataframe))
        self.assertFalse(any(button.label == "Start workspace lineage scan" for button in self.app.button))

    def test_metadata_load_is_automatic_cached_and_clears_stale_payload_on_error(self):
        self.details.metadata.assert_called_once_with(WAREHOUSE)
        self.app.run()
        self.details.metadata.assert_called_once()
        self.assertTrue(any("Live metadata" in str(item.value) for item in self.app.json))
        self.details.metadata.side_effect = AppError("HTTP 403")
        click(self.app, "Refresh tab")
        self.assertFalse(self.app.exception)
        self.assertTrue(any("403" in error.value for error in self.app.error))
        self.assertFalse(any("Live metadata" in str(item.value) for item in self.app.json))
        self.app.run()
        self.assertEqual(self.details.metadata.call_count, 2)
        self.details.metadata.side_effect = None
        click(self.app, "Refresh tab")
        self.assertEqual(self.details.metadata.call_count, 3)
        self.assertTrue(any("Live metadata" in str(item.value) for item in self.app.json))

    def test_developer_and_admin_domain_results_do_not_share_cache(self):
        self.details.domains.side_effect = lambda admin: [
            {"id": WAREHOUSE.id, "displayName": "Admin finance" if admin else "Developer finance"}
        ]
        open_tab(self.app, "Domains")
        self.details.domains.assert_called_with(False)
        self.app.toggle(key="admin_view").set_value(True).run()
        self.details.domains.assert_called_with(True)
        self.details.domain_workspaces.assert_called_once_with(WAREHOUSE.id)
        self.assertTrue(any("Admin finance" in str(item.value) for item in self.app.dataframe))
        self.app.toggle(key="admin_view").set_value(False).run()
        self.assertFalse(any("Admin finance" in str(item.value) for item in self.app.dataframe))
        self.assertTrue(any("Developer finance" in str(item.value) for item in self.app.dataframe))
        self.assertEqual(self.details.domains.call_count, 2)

    def test_workspace_roles_do_not_trigger_item_access_or_admin_scan(self):
        open_tab(self.app, "Permissions")
        self.details.workspace_roles.assert_called_once_with(WAREHOUSE)
        self.details.item_access.assert_not_called()
        self.details.start_lineage_scan.assert_not_called()
        self.assertTrue(any("not a calculation" in item.value for item in self.app.info))

    def test_independent_table_metadata_browsing_does_not_connect_sql(self):
        open_tab(self.app, "Tables & columns")
        self.assertFalse(self.app.exception)
        self.client.list_table_schemas.assert_called_once_with(WAREHOUSE)
        self.client.get_table_metadata.assert_called_once_with(WAREHOUSE, "dbo", "SalesTable")
        self.client.resolve_endpoint.assert_not_called()
        self.assertNotIn("connection_mode", self.app.session_state)

    def test_tab_revisits_are_cached_and_refresh_is_scoped_to_active_tab(self):
        open_tab(self.app, "Permissions")
        open_tab(self.app, "Monitor")
        open_tab(self.app, "Permissions")
        self.details.workspace_roles.assert_called_once_with(WAREHOUSE)
        self.details.monitoring.assert_called_once_with(WAREHOUSE)
        click(self.app, "Refresh tab")
        self.assertEqual(self.details.workspace_roles.call_count, 2)
        self.details.monitoring.assert_called_once()
        self.details.metadata.assert_called_once()
        self.assertEqual(
            [button.label for button in self.app.button if button.label == "Refresh tab"],
            ["Refresh tab"],
        )
        self.assertFalse(any(button.label.startswith("Load ") for button in self.app.button
                             if button.label != "Load more assets"))

    def test_table_selection_loads_columns_and_survives_tab_navigation(self):
        self.client.list_table_schemas.return_value = [{"name": "dbo"}, {"name": "sales"}]
        self.client.list_schema_tables.return_value = [{"name": "Orders"}, {"name": "Customers"}]
        open_tab(self.app, "Tables & columns")
        self.app.selectbox(key=WAREHOUSE.key + ":schema").select("sales").run()
        self.client.list_schema_tables.assert_called_with(WAREHOUSE, "sales")
        self.app.selectbox(key=WAREHOUSE.key + ":table:sales").select("Customers").run()
        self.client.get_table_metadata.assert_called_with(WAREHOUSE, "sales", "Customers")
        calls = self.client.get_table_metadata.call_count
        open_tab(self.app, "Overview")
        open_tab(self.app, "Tables & columns")
        self.assertEqual(self.app.selectbox(key=WAREHOUSE.key + ":schema").value, "sales")
        self.assertEqual(self.app.selectbox(key=WAREHOUSE.key + ":table:sales").value, "Customers")
        self.assertEqual(self.client.get_table_metadata.call_count, calls)

    def test_automatic_metadata_cache_is_isolated_by_asset(self):
        self.app.button(key=f"select_asset_{LAKEHOUSE.key}").click().run()
        self.details.metadata.assert_called_with(LAKEHOUSE)
        self.assertEqual(self.details.metadata.call_count, 2)
        self.app.button(key=f"select_asset_{WAREHOUSE.key}").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.details.metadata.call_count, 2)

    def test_monitoring_empty_result_is_explained(self):
        open_tab(self.app, "Monitor")
        self.details.monitoring.assert_called_once_with(WAREHOUSE)
        self.assertTrue(any("No runs were returned" in item.value for item in self.app.info))

    def test_admin_lineage_is_workspace_scoped_and_polled_automatically(self):
        scan_id = "55555555-5555-5555-5555-555555555555"
        self.details.start_lineage_scan.return_value = scan_id
        self.details.scan_status.side_effect = [{"status": "Running"}, {"status": "Succeeded"}]
        self.details.scan_result.return_value = {"workspaces": [{"id": WORKSPACE_ID}]}
        self.app.toggle(key="admin_view").set_value(True).run()
        with patch("explorer.sleep") as sleep:
            open_tab(self.app, "Lineage")
        sleep.assert_called_once_with(1)
        self.details.start_lineage_scan.assert_called_once_with(WAREHOUSE)
        self.assertEqual(self.details.scan_status.call_count, 2)
        self.assertFalse(self.app.exception)
        self.details.scan_result.assert_called_once_with(scan_id)
        self.assertTrue(any("does not prove" in item.value for item in self.app.info))

    def test_pending_lineage_is_bounded_and_not_retried_on_rerun(self):
        scan_id = "55555555-5555-5555-5555-555555555555"
        self.details.start_lineage_scan.return_value = scan_id
        self.details.scan_status.return_value = {"status": "Running"}
        self.app.toggle(key="admin_view").set_value(True).run()
        with patch("explorer.sleep"):
            open_tab(self.app, "Lineage")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.details.scan_status.call_count, 10)
        self.details.scan_result.assert_not_called()
        self.assertTrue(any("still running" in item.value for item in self.app.error))
        self.app.run()
        self.details.start_lineage_scan.assert_called_once()
        self.assertEqual(self.details.scan_status.call_count, 10)
        self.details.scan_status.return_value = {"status": "Succeeded"}
        self.details.scan_result.return_value = {"workspaces": [{"id": WORKSPACE_ID}]}
        click(self.app, "Refresh tab")
        self.details.start_lineage_scan.assert_called_once()
        self.details.scan_result.assert_called_once_with(scan_id)
        self.assertFalse(self.app.error)

    def test_lineage_polling_also_stops_at_time_budget(self):
        self.details.scan_status.return_value = {"status": "Running"}
        self.app.toggle(key="admin_view").set_value(True).run()
        with patch("explorer.monotonic", side_effect=[0, 21]), patch("explorer.sleep") as sleep:
            open_tab(self.app, "Lineage")
        self.assertFalse(self.app.exception)
        self.details.scan_status.assert_called_once()
        sleep.assert_not_called()
        self.assertTrue(any("still running" in item.value for item in self.app.error))

    def test_failed_lineage_is_explicit_and_refresh_retries(self):
        self.details.scan_status.return_value = {"status": "Failed", "error": "Scanning denied"}
        self.app.toggle(key="admin_view").set_value(True).run()
        open_tab(self.app, "Lineage")
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Scanning denied" in item.value for item in self.app.error))
        self.details.scan_result.assert_not_called()
        self.details.scan_status.return_value = {"status": "Succeeded"}
        self.details.scan_result.return_value = {"workspaces": [{"id": WORKSPACE_ID}]}
        click(self.app, "Refresh tab")
        self.assertEqual(self.details.start_lineage_scan.call_count, 2)
        self.details.scan_result.assert_called_once()
        self.assertFalse(self.app.error)

    def test_returned_lineage_edges_render_as_graph_and_table(self):
        scan_id = "55555555-5555-5555-5555-555555555555"
        self.details.start_lineage_scan.return_value = scan_id
        self.details.scan_status.return_value = {"status": "Succeeded"}
        self.details.scan_result.return_value = {
            "workspaces": [{"id": WORKSPACE_ID, "reports": [{"id": REPORT.id, "datasetId": WAREHOUSE.id}]}]
        }
        self.app.toggle(key="admin_view").set_value(True).run()
        open_tab(self.app, "Lineage")
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.get("component_instance"))
        self.assertEqual(self.app.dataframe[-1].value["To"].tolist(), [REPORT.id])
        self.app.toggle(key="admin_view").set_value(False).run()
        self.assertFalse(self.app.get("component_instance"))
        self.assertFalse(self.app.json)

    def prepare_fabric_lineage(self):
        self.details.start_lineage_scan.return_value = "55555555-5555-5555-5555-555555555555"
        self.details.scan_status.return_value = {"status": "Succeeded"}
        self.details.scan_result.return_value = {"workspaces": [{
            "id": WORKSPACE_ID, "name": "Analytics",
            "Warehouse": [{
                "id": WAREHOUSE.id, "name": "Sales",
                "relations": [{"dependentOnArtifactId": LAKEHOUSE.id, "relationType": "Datasource"}],
            }],
            "Lakehouse": [{"id": LAKEHOUSE.id, "name": "Lake"}],
            "Notebook": [{
                "id": "notebook", "name": "Prepare Sales",
                "relations": [{"dependentOnArtifactId": WAREHOUSE.id, "relationType": "Datasource"}],
            }],
            "DataPipeline": [{
                "id": "pipeline", "name": "Daily pipeline",
                "relations": [{"dependentOnArtifactId": "notebook", "relationType": "Association"}],
            }],
            "Ontology": [{"id": "unrelated", "name": "Unrelated ontology"}],
            "datasets": [{
                "id": MODEL.id, "name": "Revenue",
                "relations": [{"dependentOnArtifactId": WAREHOUSE.id, "relationType": "Association"}],
            }],
            "reports": [{"id": REPORT.id, "name": "Sales report", "datasetId": MODEL.id}],
        }]}
        self.app.toggle(key="admin_view").set_value(True).run()
        open_tab(self.app, "Lineage")

    def lineage_table(self):
        return next(frame.value for frame in self.app.dataframe if "Relation" in frame.value.columns)

    def test_named_fabric_lineage_graph_and_table_toggle_use_same_cached_scan(self):
        self.prepare_fabric_lineage()
        self.assertFalse(self.app.exception)
        args = json.loads(self.app.get("component_instance")[0].proto.json_args)
        graph = args["dot"]
        self.assertIn("Prepare Sales", graph)
        self.assertIn("Daily pipeline", graph)
        self.assertNotIn("Unrelated ontology", graph)
        self.assertIn("penwidth=3", graph)
        self.assertIn('IMG SRC="data_warehouse.svg"', graph)
        self.assertIn('IMG SRC="notebook.svg"', graph)
        self.assertIn("data:image/svg+xml;base64,", args["icons"]["notebook.svg"])
        self.app.get("button_group")[0].set_value("Table").run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.get("component_instance"))
        frame = self.lineage_table()
        self.assertEqual(set(frame["Name"]), {"Sales", "Lake", "Prepare Sales", "Daily pipeline", "Revenue", "Sales report"})
        self.assertEqual(frame.loc[frame["Name"] == "Lake", "Relation"].item(), "Upstream")
        self.assertEqual(frame.loc[frame["Name"] == "Daily pipeline", "Relation"].item(), "Downstream")
        self.assertIn("Not returned", frame["Modified"].tolist())
        self.details.start_lineage_scan.assert_called_once()
        self.details.scan_result.assert_called_once()

    def test_lineage_scope_and_filters_do_not_trigger_more_scans(self):
        self.prepare_fabric_lineage()
        self.app.get("button_group")[0].set_value("Table").run()
        scope = WAREHOUSE.key + ":lineage:scope"
        self.app.selectbox(key=scope).select("Upstream").run()
        self.assertEqual(set(self.lineage_table()["Name"]), {"Sales", "Lake"})
        self.app.selectbox(key=scope).select("Downstream").run()
        self.assertNotIn("Lake", self.lineage_table()["Name"].tolist())
        self.app.selectbox(key=scope).select("Workspace").run()
        self.assertIn("Unrelated ontology", self.lineage_table()["Name"].tolist())
        self.app.text_input(key=WAREHOUSE.key + ":lineage:search").set_value("PREPARE").run()
        self.assertEqual(self.lineage_table()["Name"].tolist(), ["Prepare Sales"])
        self.app.text_input(key=WAREHOUSE.key + ":lineage:search").set_value("").run()
        self.app.multiselect(key=WAREHOUSE.key + ":lineage:types").set_value(["Notebook"]).run()
        self.assertEqual(self.lineage_table()["Name"].tolist(), ["Prepare Sales"])
        self.app.text_input(key=WAREHOUSE.key + ":lineage:search").set_value("no match").run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("No lineage items match" in item.value for item in self.app.info))
        self.details.scan_result.assert_called_once()
        self.details.connections.assert_called_once()

    def test_missing_scanner_item_is_explicit_not_a_claim_of_no_lineage(self):
        self.details.start_lineage_scan.return_value = "55555555-5555-5555-5555-555555555555"
        self.details.scan_status.return_value = {"status": "Succeeded"}
        self.details.scan_result.return_value = {"workspaces": [{"id": WORKSPACE_ID}]}
        self.app.toggle(key="admin_view").set_value(True).run()
        open_tab(self.app, "Lineage")
        self.assertFalse(self.app.exception)
        self.assertTrue(any("not returned by the scanner" in item.value for item in self.app.warning))
        self.assertTrue(self.app.get("component_instance"))

    def test_initial_render_and_full_query_flow(self):
        self.assertFalse(self.app.exception)
        self.assertTrue(any(button.label == "Sales" for button in self.app.button))
        self.assertFalse(any(button.label == "Open OneLake catalog" for button in self.app.button))
        self.assertEqual(len(self.app.get("link_button")), 0)
        self.client.search.assert_called_once_with("", "All")
        connect_sql(self.app)
        self.client.resolve_endpoint.assert_called_once_with(WAREHOUSE)
        click(self.app, "Run query")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[-1].value["n"].tolist(), [1, 2])
        self.assertTrue(any("2 rows" in caption.value for caption in self.app.caption))

    def test_asset_change_clears_connection_and_results(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        self.app.button(key=f"select_asset_{LAKEHOUSE.key}").click().run()
        self.assertFalse(self.app.exception)
        self.assertNotIn("endpoint", self.app.session_state)
        self.assertNotIn("result", self.app.session_state)
        self.assertFalse(any(button.label == "Run query" for button in self.app.button))

    def test_unsupported_asset_is_browsable_but_not_connectable(self):
        self.app.button(key=f"select_asset_{REPORT.key}").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(any(button.label == "Connect to selected asset" for button in self.app.button))
        self.assertTrue(any("support Warehouse and Lakehouse" in info.value for info in self.app.info))

    def test_failed_search_does_not_leave_stale_assets(self):
        self.client.search.side_effect = AppError("HTTP 403")
        click(self.app, "Search catalog")
        self.assertFalse(self.app.exception)
        self.assertNotIn("assets", self.app.session_state)
        self.assertIn("403", self.app.error[0].value)

    def test_failed_query_removes_previous_results(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        self.client.query.side_effect = AppError("Read-only SELECT required")
        click(self.app, "Run query")
        self.assertFalse(self.app.exception)
        self.assertNotIn("result", self.app.session_state)
        self.assertIn("Query failed", self.app.error[0].value)

    def test_pagination_merges_without_duplicates(self):
        self.client.search.return_value = CatalogPage([WAREHOUSE], "next-page")
        click(self.app, "Search catalog")
        self.client.search.return_value = CatalogPage([WAREHOUSE, LAKEHOUSE], None)
        click(self.app, "Load more assets")
        self.client.search.assert_called_with(continuation_token="next-page")
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.session_state.assets), 2)

    def test_footer_load_more_is_disabled_when_all_assets_loaded(self):
        self.assertTrue(next(button for button in self.app.button if button.label == "Load more assets").disabled)
        self.client.search.assert_called_once_with("", "All")

    def test_pagination_failure_keeps_rows_and_allows_explicit_retry(self):
        self.client.search.return_value = CatalogPage([WAREHOUSE], "next-page")
        click(self.app, "Search catalog")
        self.client.search.side_effect = AppError("HTTP 429")
        click(self.app, "Load more assets")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.assets, [WAREHOUSE])
        self.assertEqual(self.app.session_state.continuation, "next-page")
        self.assertTrue(any("429" in item.value for item in self.app.error))
        self.client.search.side_effect = None
        self.client.search.return_value = CatalogPage([LAKEHOUSE], None)
        click(self.app, "Load more assets")
        self.assertEqual(len(self.app.session_state.assets), 2)
        self.assertTrue(next(button for button in self.app.button if button.label == "Load more assets").disabled)

    def test_empty_automatic_catalog_keeps_headers_and_does_not_reload(self):
        self.client.search.return_value = CatalogPage([], None)
        click(self.app, "Reset session / changed CLI account")
        self.assertFalse(self.app.exception)
        self.assertTrue(any("No matching assets found" in item.value for item in self.app.info))
        self.assertEqual(self.app.text_input(key="filter_name").value, "")
        self.assertEqual(self.app.text_input(key="filter_workspace").value, "")
        calls = self.client.search.call_count
        self.app.run()
        self.assertEqual(self.client.search.call_count, calls)

    def test_truncation_is_visible(self):
        self.client.query.return_value = QueryResult(pd.DataFrame({"n": [1]}), True)
        connect_sql(self.app)
        click(self.app, "Run query")
        self.assertTrue(any("truncated" in warning.value for warning in self.app.warning))

    def test_reset_clears_assets_and_results(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        click(self.app, "Reset session / changed CLI account")
        self.assertFalse(self.app.exception)
        self.assertNotIn("endpoint", self.app.session_state)
        self.assertNotIn("result", self.app.session_state)
        self.assertEqual(len(self.app.session_state.assets), 3)
        self.assertEqual(self.client.search.call_count, 2)

    def test_identity_is_displayed_without_credentials(self):
        self.assertTrue(any("Signed in through Azure CLI" in item.value for item in self.app.success))
        text = "\n".join(item.value for item in self.app.text)
        self.assertIn("Username: reader@example.com", text)
        self.assertIn(f"Tenant: {WORKSPACE_ID}", text)
        self.assertIn("Account type: user", text)
        self.assertTrue(any("Everything stays inside Streamlit" in item.value for item in self.app.info))
        self.client.signed_in_account.assert_called_once()

    def test_rerunning_does_not_clear_connection_or_reload_assets(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        self.app.run()
        self.assertFalse(self.app.exception)
        self.client.search.assert_called_once_with("", "All")
        self.assertIn("endpoint", self.app.session_state)
        self.assertIn("result", self.app.session_state)
        self.assertEqual(len(self.app.get("link_button")), 0)

    def test_initial_catalog_failure_can_be_retried_inside_app(self):
        self.client.search.side_effect = AppError("HTTP 403")
        click(self.app, "Reset session / changed CLI account")
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.session_state.catalog_attempted)
        self.assertTrue(any("Catalog search failed" in item.value for item in self.app.error))
        calls = self.client.search.call_count
        self.app.run()
        self.assertEqual(self.client.search.call_count, calls)
        self.client.search.side_effect = None
        click(self.app, "Search catalog")
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.session_state.assets), 3)

    def test_search_filter_is_sent_to_catalog_api(self):
        self.app.text_input[0].set_value("Sales")
        self.app.selectbox[0].select("Warehouse")
        click(self.app, "Search catalog")
        self.client.search.assert_called_with("Sales", "Warehouse")
        self.assertFalse(self.app.exception)

    def test_asset_names_select_in_place_without_dropdown_or_navigation(self):
        self.assertEqual(len(self.app.selectbox), 1)
        self.assertEqual(self.app.selectbox[0].label, "Asset type")
        click(self.app, "Lake")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.selected_asset, LAKEHOUSE.key)
        self.assertTrue(any(item.value == "Lake" for item in self.app.subheader))
        self.assertEqual(len(self.app.get("link_button")), 0)
        self.client.search.assert_called_once()

    def test_name_updates_details_without_opening_a_dialog_or_connecting(self):
        click(self.app, "Lake")
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.get("dialog"))
        self.assertTrue(any(item.value == "Lake" for item in self.app.subheader))
        self.details.metadata.assert_called_with(LAKEHOUSE)
        self.assertTrue(any(button.label == "Connect via SQL endpoint" for button in self.app.button))
        self.assertTrue(any(button.label == "Connect via Table API" for button in self.app.button))
        self.client.list_table_schemas.assert_not_called()
        self.client.resolve_endpoint.assert_not_called()

    def test_endpoint_sections_only_appear_after_connection(self):
        self.assertFalse(any(header.value in ("SQL endpoint", "OneLake Table API", "XMLA / DAX")
                             for header in self.app.header))
        self.assertFalse(any(button.label == "Connect to selected asset" for button in self.app.button))
        connect_sql(self.app)
        self.assertTrue(any(header.value == "SQL endpoint" for header in self.app.header))
        self.assertFalse(any(button.label == "List tables" for button in self.app.button))
        click(self.app, "Sales")
        click(self.app, "Connect via Table API")
        self.assertTrue(any(header.value == "OneLake Table API" for header in self.app.header))
        self.assertFalse(any(button.label == "Run query" for button in self.app.button))
        self.assertFalse(any(button.label == "Connect to selected asset" for button in self.app.button))
        click(self.app, "Sales")
        click(self.app, "Connect via SQL endpoint")
        self.assertTrue(any(button.label == "Run query" for button in self.app.button))
        self.assertFalse(any(button.label == "List tables" for button in self.app.button))

    def test_name_column_filter_is_case_insensitive(self):
        self.app.text_input(key="filter_name").set_value("  lAkE  ").run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any(button.label == "Lake" for button in self.app.button))
        self.assertFalse(any(button.label == "Sales" for button in self.app.button))
        self.assertTrue(any("Showing 1 of 3" in item.value for item in self.app.caption))
        self.client.search.assert_called_once()

    def test_type_column_filter_supports_multiple_types(self):
        self.app.multiselect(key="filter_types").set_value(["Warehouse", "Report"]).run()
        names = {button.label for button in self.app.button}
        self.assertIn("Sales", names)
        self.assertIn("Report", names)
        self.assertNotIn("Lake", names)
        self.assertFalse(self.app.exception)

    def test_long_item_types_remain_available_in_filters_and_details(self):
        long_type = "MirroredAzureDatabricksCatalog"
        asset = Asset(REPORT.id, "Shared catalog", long_type, WORKSPACE_ID, "Data workspace", "")
        self.client.search.return_value = CatalogPage([WAREHOUSE, asset], None)
        click(self.app, "Search catalog")
        self.app.multiselect(key="filter_types").set_value([long_type]).run()
        self.assertFalse(self.app.exception)
        self.assertIn(long_type, self.app.multiselect(key="filter_types").options)
        self.assertTrue(any(button.key == f"select_asset_{asset.key}" for button in self.app.button))
        self.assertFalse(any(button.key == f"select_asset_{WAREHOUSE.key}" for button in self.app.button))
        self.app.button(key=f"select_asset_{asset.key}").click().run()
        self.assertTrue(any(long_type in item.value for item in self.app.caption))

    def test_header_filters_combine_workspace_type_and_description(self):
        other = Asset(
            LAKEHOUSE.id, LAKEHOUSE.name, LAKEHOUSE.type,
            "55555555-5555-5555-5555-555555555555", "Finance", "Annual revenue"
        )
        self.client.search.return_value = CatalogPage([WAREHOUSE, LAKEHOUSE, other], None)
        click(self.app, "Search catalog")
        self.app.text_input(key="filter_workspace").set_value("finANCE")
        self.app.text_input(key="filter_description").set_value("REVENUE")
        self.app.multiselect(key="filter_types").set_value(["Lakehouse"]).run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any(button.key == f"select_asset_{other.key}" for button in self.app.button))
        self.assertFalse(any(button.key == f"select_asset_{LAKEHOUSE.key}" for button in self.app.button))
        self.assertTrue(any("Showing 1 of 3" in item.value for item in self.app.caption))

    def test_no_filter_matches_can_be_cleared(self):
        self.app.text_input(key="filter_name").set_value("not an asset").run()
        self.assertTrue(any("No loaded assets match" in item.value for item in self.app.info))
        click(self.app, "Clear column filters")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.text_input(key="filter_name").value, "")
        self.assertEqual(self.app.multiselect(key="filter_types").value, [])
        self.assertTrue(any("Showing 3 of 3" in item.value for item in self.app.caption))

    def test_filtering_out_connected_asset_keeps_connection_and_results(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        self.app.text_input(key="filter_name").set_value("no matches").run()
        self.assertFalse(self.app.exception)
        self.assertIn("endpoint", self.app.session_state)
        self.assertIn("result", self.app.session_state)
        self.assertTrue(any(button.label == "Run query" for button in self.app.button))

    def test_new_catalog_search_resets_header_filters(self):
        self.app.text_input(key="filter_name").set_value("Lake")
        self.app.multiselect(key="filter_types").set_value(["Lakehouse"]).run()
        click(self.app, "Search catalog")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.text_input(key="filter_name").value, "")
        self.assertEqual(self.app.multiselect(key="filter_types").value, [])

    def test_menu_sql_choice_connects_the_clicked_asset(self):
        click(self.app, "Lake")
        click(self.app, "Connect via SQL endpoint")
        self.assertFalse(self.app.exception)
        self.client.resolve_endpoint.assert_called_once_with(LAKEHOUSE)
        self.client.test_connection.assert_called_once()
        self.assertEqual(self.app.session_state.connection_mode, "SQL endpoint")
        self.assertTrue(any(button.label == "Connect via Table API" for button in self.app.button))
        self.assertTrue(any(button.label == "Run query" for button in self.app.button))

    def test_selecting_assets_never_connects_until_an_endpoint_is_chosen(self):
        click(self.app, "Lake")
        click(self.app, "Sales")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.selected_asset, WAREHOUSE.key)
        self.assertNotIn("connection_mode", self.app.session_state)
        self.assertFalse(any(button.label == "Cancel" for button in self.app.button))
        self.client.list_table_schemas.assert_not_called()
        self.client.resolve_endpoint.assert_not_called()

    def test_selecting_different_asset_returns_to_overview(self):
        open_tab(self.app, "Monitor")
        click(self.app, "Lake")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.explorer_tab, "Overview")
        self.details.metadata.assert_called_with(LAKEHOUSE)
        self.details.monitoring.assert_called_once_with(WAREHOUSE)

    def test_list_and_selected_asset_tools_live_in_separate_workspace_panes(self):
        workspace = next(
            block for block in self.app.get("flex_container")
            if block.proto.id.endswith("-catalog_workspace")
        )
        columns = workspace.get("column")
        left = columns[0]
        right = next(
            column for column in columns
            if any(block.proto.id.endswith("-asset_detail") for block in column.get("flex_container"))
        )
        self.assertEqual(left.proto.weight, 0.25)
        self.assertEqual(right.proto.weight, 0.75)
        self.assertTrue(any(button.key == f"select_asset_{WAREHOUSE.key}" for button in left.get("button")))
        self.assertFalse(any(button.key == f"select_asset_{WAREHOUSE.key}" for button in right.get("button")))
        self.assertTrue(any(item.value == WAREHOUSE.name for item in right.get("subheader")))
        connect_sql(self.app)
        detail = next(
            block for block in self.app.get("flex_container")
            if block.proto.id.endswith("-asset_detail")
        )
        self.assertTrue(any(item.label == "T-SQL" for item in detail.get("text_area")))
        self.assertTrue(any(button.label == "Run query" for button in detail.get("button")))

    def test_empty_catalog_keeps_wide_table_without_detail_placeholder(self):
        self.client.search.return_value = CatalogPage([], None)
        click(self.app, "Search catalog")
        self.assertFalse(self.app.exception)
        self.assertTrue(any(block.proto.id.endswith("-catalog_wide") for block in self.app.get("flex_container")))
        self.assertFalse(any(block.proto.id.endswith("-asset_detail") for block in self.app.get("flex_container")))
        self.assertFalse(any(button.label == "Run query" for button in self.app.button))

    def test_table_api_connection_and_metadata_browser(self):
        click(self.app, "Lake")
        click(self.app, "Connect via Table API")
        self.assertFalse(self.app.exception)
        self.client.list_table_schemas.assert_called_once_with(LAKEHOUSE)
        self.client.resolve_endpoint.assert_not_called()
        self.assertEqual(self.app.session_state.connection_mode, "Table API")
        click(self.app, "List tables")
        self.client.list_schema_tables.assert_called_once_with(LAKEHOUSE, "dbo")
        click(self.app, "Inspect table")
        self.assertFalse(self.app.exception)
        self.client.get_table_metadata.assert_called_once_with(LAKEHOUSE, "dbo", "SalesTable")
        self.assertTrue(self.app.json)

    def test_switching_to_table_api_clears_sql_connection_and_results(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        click(self.app, "Sales")
        click(self.app, "Connect via Table API")
        self.assertFalse(self.app.exception)
        self.assertNotIn("endpoint", self.app.session_state)
        self.assertNotIn("result", self.app.session_state)
        self.assertEqual(self.app.session_state.connection_mode, "Table API")

    def test_failed_table_connection_is_visible_and_clears_previous_mode(self):
        connect_sql(self.app)
        self.client.list_table_schemas.side_effect = AppError("HTTP 403")
        click(self.app, "Sales")
        click(self.app, "Connect via Table API")
        self.assertFalse(self.app.exception)
        self.assertNotIn("connection_mode", self.app.session_state)
        self.assertNotIn("endpoint", self.app.session_state)
        self.assertTrue(any("403" in error.value for error in self.app.error))

    def test_unsupported_menu_disables_both_connections(self):
        click(self.app, "Report")
        for label in ("Connect via SQL endpoint", "Connect via Table API"):
            self.assertTrue(next(button for button in self.app.button if button.label == label).disabled)

    def test_empty_table_api_schemas_are_successful_but_explained(self):
        self.client.list_table_schemas.return_value = []
        click(self.app, "Lake")
        click(self.app, "Connect via Table API")
        self.assertFalse(self.app.exception)
        self.assertTrue(any("no schemas" in item.value for item in self.app.info))

    def test_table_listing_failure_does_not_leave_stale_tables(self):
        click(self.app, "Lake")
        click(self.app, "Connect via Table API")
        click(self.app, "List tables")
        self.client.list_schema_tables.side_effect = AppError("HTTP 404")
        click(self.app, "List tables")
        self.assertFalse(self.app.exception)
        self.assertNotIn("schema_tables", self.app.session_state)
        self.assertTrue(any("404" in item.value for item in self.app.error))

    def test_same_name_in_different_workspaces_selects_correct_asset(self):
        other = Asset(
            WAREHOUSE.id, WAREHOUSE.name, WAREHOUSE.type,
            "55555555-5555-5555-5555-555555555555", "Other workspace", ""
        )
        self.client.search.return_value = CatalogPage([WAREHOUSE, other], None)
        click(self.app, "Search catalog")
        self.app.button(key=f"select_asset_{other.key}").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.selected_asset, other.key)
        click(self.app, "Connect via SQL endpoint")
        self.client.resolve_endpoint.assert_called_once_with(other)

    def test_clicking_selected_name_keeps_connection_and_results(self):
        connect_sql(self.app)
        click(self.app, "Run query")
        click(self.app, "Sales")
        self.assertFalse(self.app.exception)
        self.assertIn("endpoint", self.app.session_state)
        self.assertIn("result", self.app.session_state)

    def test_failed_identity_verification_is_explicit(self):
        self.client.signed_in_account.side_effect = AppError("Run az login")
        self.client.search.reset_mock()
        click(self.app, "Reset session / changed CLI account")
        self.assertFalse(self.app.exception)
        self.assertNotIn("signed_in_account", self.app.session_state)
        self.assertTrue(any("Cannot verify" in item.value for item in self.app.error))
        self.assertFalse(any("Signed in through Azure CLI" in item.value for item in self.app.success))
        self.client.search.assert_not_called()
        self.assertTrue(next(
            button for button in self.app.button if button.label == "Search catalog"
        ).disabled)

    def test_expired_identity_is_rechecked(self):
        self.app.session_state["signed_in_account"] = SignedInAccount(
            "old@example.com", WORKSPACE_ID, "user", int(time.time()) - 1
        )
        self.app.run()
        self.assertEqual(self.client.signed_in_account.call_count, 2)
        self.assertEqual(self.app.session_state.signed_in_account.username, "reader@example.com")

    def test_reset_refreshes_displayed_identity(self):
        self.client.signed_in_account.return_value = SignedInAccount(
            "new@example.com", WORKSPACE_ID, "user", int(time.time()) + 3600
        )
        click(self.app, "Reset session / changed CLI account")
        self.assertTrue(any("new@example.com" in item.value for item in self.app.text))


if __name__ == "__main__":
    unittest.main()
