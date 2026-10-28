import time
from urllib.parse import quote

import pyodbc
import requests
import streamlit as st
from azure.core.exceptions import AzureError

from fabric_client import (
    CATALOG_TYPES,
    CONNECTABLE_TYPES,
    AppError,
    Asset,
    FabricClient,
)
from explorer import asset_explorer
from item_icons import ICON_DIRECTORY, item_icon_name
from ui_styles import CATALOG_STYLES, FABRIC_STYLES
from xmla_client import XmlaClient, XmlaEndpoint, XmlaError


ERRORS = (AppError, AzureError, requests.RequestException, pyodbc.Error, XmlaError)
DEFAULT_SQL = """SELECT TOP (100)
    TABLE_SCHEMA,
    TABLE_NAME,
    TABLE_TYPE
FROM INFORMATION_SCHEMA.TABLES
ORDER BY TABLE_SCHEMA, TABLE_NAME;"""


def clear_query_state() -> None:
    for key in (
        "endpoint", "result", "elapsed", "result_asset", "result_sql",
        "connection_mode", "connection_notice", "connection_error",
        "connection_diagnostics",
        "table_schemas", "schema_tables", "table_metadata",
        "api_schema", "api_table",
        "xmla_endpoint", "dax_result", "dax_result_asset", "dax_executed", "dax_elapsed",
    ):
        st.session_state.pop(key, None)


def select_asset(asset_key: str) -> None:
    if st.session_state.get("selected_asset") != asset_key:
        clear_query_state()
        st.session_state.selected_asset = asset_key
        st.session_state.explorer_tab = "Overview"
    st.session_state.asset_details_open = True


def close_asset_details() -> None:
    st.session_state.asset_details_open = False
    # Keep selections when Streamlit temporarily unmounts the detail widgets.
    for key in ("explorer_tab", "api_schema", "api_table"):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def clear_catalog_filters() -> None:
    for key in ("filter_name", "filter_workspace", "filter_description"):
        st.session_state[key] = ""
    st.session_state.filter_types = []


def load_catalog(client: FabricClient, search: str = "", item_type: str = "All") -> None:
    st.session_state.catalog_attempted = True
    st.session_state.pop("catalog_error", None)
    try:
        with st.spinner("Loading your OneLake catalog..."):
            page = client.search(search, item_type)
        st.session_state.assets = page.assets
        st.session_state.continuation = page.continuation_token
    except ERRORS as exc:
        st.session_state.catalog_error = f"Catalog search failed: {exc}"


def load_more_assets() -> None:
    st.session_state.pop("catalog_error", None)
    try:
        token = st.session_state.get("continuation")
        if not token:
            raise AppError("No further catalog pages are available.")
        page = st.session_state.client.search(continuation_token=token)
        existing = {asset.key: asset for asset in st.session_state.assets}
        existing.update({asset.key: asset for asset in page.assets})
        st.session_state.assets = list(existing.values())
        st.session_state.continuation = page.continuation_token
    except ERRORS as exc:
        st.session_state.catalog_error = f"Loading more assets failed: {exc}"


def catalog_search(client: FabricClient, signed_in: bool) -> None:
    if signed_in and not st.session_state.get("catalog_attempted"):
        load_catalog(client)
    with st.expander("Search all workspaces"):
        with st.form("catalog_search"):
            search_area, type_area, action_area = st.columns([5, 2, 2], vertical_alignment="bottom")
            search = search_area.text_input(
                "Search name, description, or workspace", key="catalog_search_text",
                placeholder="Search your OneLake catalog",
            )
            item_type = type_area.selectbox(
                "Asset type", ("All", *CATALOG_TYPES), key="catalog_search_type"
            )
            with action_area:
                search_clicked = st.form_submit_button(
                    "Search catalog", disabled=not signed_in, width="stretch"
                )
        if search_clicked:
            clear_query_state()
            clear_catalog_filters()
            close_asset_details()
            for key in ("assets", "continuation", "selected_asset"):
                st.session_state.pop(key, None)
            load_catalog(client, search, item_type)


def catalog_browser(signed_in: bool, compact: bool) -> list[Asset]:
    with st.container(border=True, key="catalog_table"):
        st.subheader("Items")
        if st.session_state.get("catalog_error"):
            st.error(st.session_state.catalog_error)
            st.caption("Use Search all workspaces above to retry loading the catalog.")
        if not signed_in:
            st.info("Sign in with Azure CLI, then reset the session to load your assets.")
        assets: list[Asset] = st.session_state.get("assets", [])
        selected_key = st.session_state.get("selected_asset")
        st.caption("Select an item to explore. Filters apply to loaded assets.")
        with st.container(key="catalog_grid"):
            with st.container(key="catalog_header"):
                if compact:
                    name, filters = st.columns([3, 1], vertical_alignment="bottom")
                    item_type = workspace = description = filters.popover(
                        "Filters", icon=":material/filter_list:"
                    )
                else:
                    name, item_type, workspace, description = st.columns([3, 2, 3, 5])
                name_filter = name.text_input(
                    "Name", placeholder="Filter names", key="filter_name"
                ).strip().casefold()
                type_options = sorted(
                    {entry.type for entry in assets} | set(st.session_state.get("filter_types", []))
                )
                type_filter = item_type.multiselect(
                    "Type", type_options, placeholder="All types", key="filter_types"
                )
                workspace_filter = workspace.text_input(
                    "Workspace", placeholder="Filter workspaces", key="filter_workspace"
                ).strip().casefold()
                description_filter = description.text_input(
                    "Description", placeholder="Filter descriptions", key="filter_description"
                ).strip().casefold()
            visible_assets = [
                entry for entry in assets
                if name_filter in entry.name.casefold()
                and (not type_filter or entry.type in type_filter)
                and workspace_filter in entry.workspace_name.casefold()
                and description_filter in entry.description.casefold()
            ]
            with st.container(border=False, key="catalog_rows"):
                if not visible_assets:
                    if assets:
                        st.info("No loaded assets match these column filters. Clear or adjust the filters.")
                    elif "assets" in st.session_state:
                        st.info("No matching assets found. Try a broader search or check your tenant and permissions.")
                for index, entry in enumerate(visible_assets):
                    style = "selected" if entry.key == selected_key else ("odd" if index % 2 else "even")
                    row = st.container(key=f"catalog_row_{style}_icon_{item_icon_name(entry.type)}_{entry.key}")
                    with row:
                        if compact:
                            name = row
                        else:
                            name, item_type, workspace, description = st.columns(
                                [3, 2, 3, 5], vertical_alignment="center"
                            )
                        name.button(
                            entry.name,
                            key=f"select_asset_{entry.key}",
                            type="tertiary",
                            icon=":material/description:",
                            help=(
                                ("Selected | " if entry.key == selected_key else "")
                                + f"{entry.name} | {entry.type} | {entry.workspace_name} | {entry.id}\n{entry.description}"
                            ),
                            on_click=select_asset,
                            args=(entry.key,),
                            width="stretch",
                        )
                        if not compact:
                            kind = {
                                "Warehouse": "warehouse", "Lakehouse": "lakehouse", "SemanticModel": "model"
                            }.get(entry.type, "other")
                            with item_type.container(key=f"catalog_kind_{kind}_{entry.key}"):
                                st.text(entry.type)
                            workspace.text(entry.workspace_name)
                            description.text(entry.description)
        with st.container(key="catalog_footer"):
            if compact:
                st.caption(f"Showing {len(visible_assets)} of {len(assets)} loaded assets.")
                more, clear = st.columns(2)
            else:
                count, more, clear = st.columns([5, 2, 2], vertical_alignment="center")
                count.caption(f"Showing {len(visible_assets)} of {len(assets)} loaded assets.")
            more.button(
                "Load more assets",
                on_click=load_more_assets,
                disabled=not bool(st.session_state.get("continuation")) or not signed_in,
                width="stretch",
            )
            clear.button(
                "Clear column filters", on_click=clear_catalog_filters, width="stretch"
            )
        st.caption("Catalog indexing can lag behind new items.")
    return assets


def connect_asset(asset: Asset, mode: str) -> bool:
    clear_query_state()
    client = st.session_state.client
    try:
        if mode == "SQL endpoint":
            with st.spinner("Resolving the endpoint and testing SQL access..."):
                endpoint = client.resolve_endpoint(asset)
                database = client.test_connection(endpoint)
            st.session_state.endpoint = endpoint
            notice = f"SQL connection verified: {database}"
        elif mode == "Table API":
            with st.spinner("Connecting to OneLake Table API..."):
                schemas = client.list_table_schemas(asset)
            st.session_state.table_schemas = schemas
            notice = f"Table API connection verified: {len(schemas)} schemas available."
        elif mode == "XMLA / DAX":
            if asset.type != "SemanticModel" or not asset.workspace_id:
                raise AppError("XMLA connections require a workspace semantic model.")
            endpoint = XmlaEndpoint(
                server=(
                    "powerbi://api.powerbi.com/v1.0/myorg/"
                    + quote(f"{asset.workspace_name} - {asset.workspace_id}", safe="")
                ),
                catalog=asset.name,
                asset_key=asset.key,
            )
            with st.spinner("Verifying read-only XMLA access..."):
                XmlaClient(client.credential).connect(endpoint)
            st.session_state.xmla_endpoint = endpoint
            notice = "XMLA connection verified. DAX queries only; model changes are disabled."
        else:
            raise AppError("Choose SQL endpoint, Table API, or XMLA / DAX.")
        st.session_state.connection_mode = mode
        st.session_state.connection_notice = notice
        return True
    except ERRORS as exc:
        st.session_state.connection_error = f"{mode} connection failed: {exc}"
        if isinstance(exc, XmlaError) and exc.diagnostics:
            st.session_state.connection_diagnostics = exc.diagnostics
        return False


def connection_options(asset: Asset) -> None:
    st.subheader(asset.name)
    st.caption(f"{asset.type} | {asset.workspace_name}")
    supported = asset.type in CONNECTABLE_TYPES and bool(asset.workspace_id)
    if not supported:
        st.info("SQL endpoint and Table API connections support Warehouse and Lakehouse items.")
    for mode in ("SQL endpoint", "Table API"):
        if st.button(
            f"Connect via {mode}", key=f"menu_{mode}", disabled=not supported, width="stretch"
        ):
            if connect_asset(asset, mode):
                st.rerun()
    if st.button(
        "Connect via XMLA / DAX", key="menu_xmla",
        disabled=asset.type != "SemanticModel" or not bool(asset.workspace_id), width="stretch",
    ):
        if connect_asset(asset, "XMLA / DAX"):
            st.rerun()
    st.caption("Read-only. SQL: query rows. Table API: metadata. XMLA: semantic-model DAX.")


def table_api_browser(asset: Asset) -> None:
    st.header("OneLake Table API")
    st.info(
        "This connection uses OneLake's REST metadata API, not SQL. "
        "It returns schemas, tables, and columns, not table rows."
    )
    schemas = st.session_state.table_schemas
    if not schemas:
        st.info("The connection succeeded, but no schemas are visible to your identity.")
        return
    schema = st.selectbox("Schema", [item["name"] for item in schemas], key="api_schema")
    if st.button("List tables"):
        st.session_state.pop("schema_tables", None)
        st.session_state.pop("table_metadata", None)
        st.session_state.pop("api_table", None)
        try:
            with st.spinner("Listing OneLake tables..."):
                tables = st.session_state.client.list_schema_tables(asset, schema)
            st.session_state.schema_tables = (schema, tables)
        except ERRORS as exc:
            st.error(f"Listing tables failed: {exc}")
    table_page = st.session_state.get("schema_tables")
    if table_page is None or table_page[0] != schema:
        return
    tables = table_page[1]
    if not tables:
        st.info("No tables are visible in this schema.")
        return
    st.dataframe(
        [{"Name": item["name"], "Format": item.get("data_source_format", "")} for item in tables],
        hide_index=True,
        width="stretch",
    )
    table = st.selectbox("Table", [item["name"] for item in tables], key="api_table")
    if st.button("Inspect table"):
        st.session_state.pop("table_metadata", None)
        try:
            with st.spinner("Loading column metadata..."):
                metadata = st.session_state.client.get_table_metadata(asset, schema, table)
            st.session_state.table_metadata = (schema, table, metadata)
        except ERRORS as exc:
            st.error(f"Loading table metadata failed: {exc}")
    metadata_page = st.session_state.get("table_metadata")
    if metadata_page is not None and metadata_page[:2] == (schema, table):
        st.subheader(f"{schema}.{table}")
        st.json(metadata_page[2])


def dax_browser(asset: Asset) -> None:
    endpoint = st.session_state.get("xmla_endpoint")
    if endpoint is None or endpoint.asset_key != asset.key:
        return
    st.header("XMLA / DAX")
    st.caption(f"XMLA server: {endpoint.server} | Model: {endpoint.catalog} | Model ID: {asset.id}")
    st.info(
        "Actual XMLA connection using your CLI identity, not a REST executeQueries substitute. "
        "Requires a supported capacity with XMLA enabled and semantic-model Build permission. "
        "Only DAX queries are accepted; model changes and refresh operations are not offered."
    )
    with st.form("dax_query"):
        dax = st.text_area("DAX", value='EVALUATE ROW("Connected", 1)', height=210)
        limit = st.number_input("Maximum DAX rows", min_value=1, max_value=10000, value=1000)
        run = st.form_submit_button("Run DAX query", type="primary")
    if run:
        for key in ("dax_result", "dax_result_asset", "dax_executed", "dax_elapsed"):
            st.session_state.pop(key, None)
        try:
            with st.spinner("Executing read-only XMLA query..."):
                start = time.perf_counter()
                result = XmlaClient(st.session_state.client.credential).query(endpoint, dax, int(limit))
            st.session_state.dax_result = result
            st.session_state.dax_result_asset = asset.key
            st.session_state.dax_executed = dax
            st.session_state.dax_elapsed = time.perf_counter() - start
        except ERRORS as exc:
            st.error(f"DAX query failed: {exc}")
            if isinstance(exc, XmlaError) and exc.diagnostics:
                with st.expander("XMLA query diagnostics"):
                    st.json(exc.diagnostics)
    result = st.session_state.get("dax_result")
    if result is not None and st.session_state.get("dax_result_asset") == asset.key:
        st.subheader("DAX results")
        st.caption(
            f"{len(result.frame):,} rows displayed in {st.session_state.dax_elapsed:.2f} seconds. "
            "Results belong to the successful DAX query below."
        )
        with st.expander("Executed DAX"):
            st.code(st.session_state.dax_executed, language="dax")
        if result.truncated:
            st.warning("DAX results were truncated at your display limit.")
        st.dataframe(result.frame, hide_index=True, width="stretch")
        st.download_button(
            "Download DAX results as CSV", result.frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="dax_results.csv", mime="text/csv",
        )


def main() -> None:
    st.set_page_config(
        page_title="OneLake Catalog Explorer", page_icon=":material/database:",
        layout="wide", initial_sidebar_state="collapsed",
    )
    with st.sidebar:
        with st.container(key="appearance_controls"):
            fabric_style = st.toggle(
                "Fabric-inspired style", value=True, key="fabric_style",
                help="Switch appearance only. Filters, connections, permissions and results stay unchanged.",
            )
            st.caption("Fabric-inspired (light)" if fabric_style else "Original Streamlit")
    st.html(FABRIC_STYLES if fabric_style else CATALOG_STYLES)
    with st.container(key="app_heading"):
        if fabric_style:
            st.html(
                '<div class="fabric-context"><strong>DATA &amp; ANALYTICS</strong>'
                '<span aria-hidden="true">/</span><span>OneLake catalog</span>'
                '<span class="fabric-demo-label">Local read-only demo</span></div>'
            )
        st.title("OneLake Catalog Explorer")
        st.caption("Discover Fabric assets, inspect metadata and governance, and query SQL or XMLA.")
    st.warning(
        "Read-only demo: browsing, metadata inspection, SELECT and DAX queries only. "
        "No create, update, delete, refresh, permission changes or model writes are provided. "
        "Use read-only endpoint permissions; query validation is not a security boundary."
    )

    if "client" not in st.session_state:
        st.session_state.client = FabricClient()
    client = st.session_state.client

    with st.sidebar:
        st.header("Local sign-in")
        if st.button("Reset session / changed CLI account"):
            st.session_state.clear()
            st.rerun()
        account = st.session_state.get("signed_in_account")
        if account is None or account.expires_at <= time.time() + 60:
            st.session_state.pop("signed_in_account", None)
            try:
                with st.spinner("Checking Azure CLI sign-in..."):
                    account = client.signed_in_account()
                st.session_state.signed_in_account = account
            except ERRORS as exc:
                account = None
                st.error(f"Cannot verify Azure CLI sign-in: {exc}")
        if account is not None:
            st.success("Signed in through Azure CLI")
            st.text(f"Username: {account.username}")
            st.text(f"Tenant: {account.tenant_id}")
            st.text(f"Account type: {account.account_type}")
            st.caption(
                "A Fabric access token is available. This does not verify permissions "
                "to individual assets. Passwords and access tokens are never displayed."
            )
        else:
            st.warning("No verified Azure CLI sign-in.")
        st.code("az login --tenant <your-tenant-id>", language="powershell")
        st.info(
            "The identity above is used for the integrated catalog and SQL connections. "
            "Everything stays inside Streamlit; no separate Fabric portal sign-in is needed."
        )
        st.caption(
            "Single local user only. Discovery does not grant data access. "
            "Your Fabric and SQL permissions still apply."
        )
        admin = st.toggle("Admin view", value=False, key="admin_view")
        st.subheader("Admin view" if admin else "Developer view")
        if admin:
            st.warning(
                "Tenant-admin APIs are enabled on demand. Fabric still verifies your actual role, "
                "consent and permissions. Admin status does not grant SQL or model data access."
            )
        else:
            st.info(
                "Scoped to items your signed-in identity can discover and access. "
                "Workspace and item permissions still apply; no tenant-admin API calls."
            )
        with st.expander("What this view can show", expanded=True):
            st.markdown(
                "- **Catalog:** accessible items; use Workspace/Name filters to narrow scope.\n"
                "- **Item scope:** metadata, source connections, tables and query results "
                "(requires the corresponding item/data permissions).\n"
                "- **Workspace scope:** metadata and role assignments "
                "(roles require Member or Admin).\n"
                "- **Monitoring:** supported job or semantic-model refresh history.\n"
                "- **Domains:** Core domain metadata with Domain.Read.All."
            )
            if admin:
                st.markdown(
                    "- **Additional admin scope:** selected-item access details, selected-workspace "
                    "lineage scans, tenant domains and domain-workspace assignments "
                    "(tenant admin + Tenant.Read.All)."
                )
            st.caption(
                "These are available features, not a claim that every permission is granted. "
                "403/unsupported API errors are displayed. Switching views does not impersonate "
                "another user or change your actual permissions."
            )

    catalog_search(client, account is not None)
    assets = st.session_state.get("assets", [])
    by_key = {asset.key: asset for asset in assets}
    asset = by_key.get(st.session_state.get("selected_asset"))
    with st.container(key="catalog_workspace"):
        if not st.session_state.get("asset_details_open") or asset is None or account is None:
            close_asset_details()
            with st.container(key="catalog_wide"):
                catalog_browser(account is not None, compact=False)
            return
        catalog_area, detail_area = st.columns([1, 3], gap="small")
        with catalog_area:
            with st.container(key="catalog_compact"):
                catalog_browser(account is not None, compact=True)
        with detail_area:
            with st.container(border=True, key="asset_detail"):
                with st.container(key="asset_toolbar"):
                    connect, status, close = st.columns([1, 3, 0.25], vertical_alignment="center")
                    with connect.popover("Connect", type="primary", icon=":material/link:", width="stretch"):
                        connection_options(asset)
                    status.caption(
                        f"Connected via {st.session_state.connection_mode} | Read-only"
                        if st.session_state.get("connection_mode")
                        else "Read-only | Choose Connect to query an endpoint"
                    )
                    with close.container(key="asset_close"):
                        st.button(
                            "Close details", icon=":material/close:", type="tertiary",
                            key="close_asset_details", on_click=close_asset_details,
                            help="Close details and expand the catalog. The connection and results are kept.",
                        )
                with st.container(key="asset_identity"):
                    icon, identity = st.columns([1, 20], vertical_alignment="center")
                    icon.image(
                        str(ICON_DIRECTORY / f"{item_icon_name(asset.type)}_20_item.svg"),
                        width=40, alt=f"{asset.type} icon",
                    )
                    with identity:
                        st.caption(asset.type)
                        st.subheader(asset.name, anchor=False)
                        st.caption(f"Workspace: {asset.workspace_name} | Asset ID: {asset.id}")
                if st.session_state.get("connection_error"):
                    st.error(st.session_state.connection_error)
                    if st.session_state.get("connection_diagnostics"):
                        with st.expander("XMLA connection diagnostics"):
                            st.json(st.session_state.connection_diagnostics)
                endpoint_browser(client, asset)
                asset_explorer(client, asset, admin)


def endpoint_browser(client: FabricClient, asset: Asset) -> None:
    mode = st.session_state.get("connection_mode")
    if mode is None:
        return
    if st.session_state.get("connection_notice"):
        st.success(st.session_state.connection_notice)
    if mode == "Table API":
        table_api_browser(asset)
        return
    if mode == "XMLA / DAX":
        dax_browser(asset)
        return
    endpoint = st.session_state.get("endpoint")
    if endpoint is None or endpoint.asset_key != asset.key:
        return
    st.caption(f"Server: {endpoint.server} | Database: {endpoint.database}")
    st.header("SQL endpoint")
    st.warning(
        "Only one SELECT query is accepted (including CTEs and UNION). Use a read-only SQL "
        "identity: query validation is a convenience guard, not a database security boundary."
    )
    with st.form("sql_query"):
        sql = st.text_area("T-SQL", value=DEFAULT_SQL, height=210)
        max_rows = st.number_input("Maximum displayed rows", min_value=1, max_value=10000, value=1000)
        run = st.form_submit_button("Run query", type="primary")
    if run:
        for key in ("result", "result_asset", "result_sql", "elapsed"):
            st.session_state.pop(key, None)
        try:
            with st.spinner("Executing query (60-second timeout)..."):
                start = time.perf_counter()
                result = client.query(endpoint, sql, int(max_rows))
            st.session_state.result = result
            st.session_state.elapsed = time.perf_counter() - start
            st.session_state.result_asset = asset.key
            st.session_state.result_sql = sql
        except ERRORS as exc:
            st.error(f"Query failed: {exc}")
    result = st.session_state.get("result")
    if result is not None and st.session_state.get("result_asset") == asset.key:
        st.subheader("Query results")
        st.caption(
            f"{len(result.frame):,} rows displayed in {st.session_state.elapsed:.2f} seconds. "
            "Results belong to the last successful query shown below."
        )
        with st.expander("Executed SQL"):
            st.code(st.session_state.result_sql, language="sql")
        if result.truncated:
            st.warning("Results were truncated at your display limit. Add TOP or filters to refine the query.")
        st.dataframe(result.frame, hide_index=True, width="stretch")
        st.download_button(
            "Download results as CSV",
            result.frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="query_results.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
