from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic, sleep
from typing import Any

import pandas as pd
import pyodbc
import requests
import streamlit as st
from azure.core.exceptions import AzureError

from catalog_details import (
    CatalogDetails, lineage_edges, lineage_key, lineage_nodes, lineage_relations,
)
from fabric_client import CONNECTABLE_TYPES, AppError, Asset, FabricClient
from lineage_chart import show_lineage_chart


ERRORS = (AppError, AzureError, requests.RequestException, pyodbc.Error)


def load_panel(label: str, key: str, action: Callable[[], Any]) -> Any:
    cache = st.session_state.setdefault("explorer_cache", {})
    st.markdown(f"**{label}**")
    if key not in cache:
        try:
            with st.spinner(f"Loading {label.lower()}..."):
                data = action()
            cache[key] = {"data": data, "at": datetime.now(timezone.utc).isoformat()}
        except ERRORS as exc:
            cache[key] = {"error": str(exc)}
    entry = cache.get(key)
    if entry is None:
        return None
    if "error" in entry:
        st.error(entry["error"])
        return None
    st.caption(f"Retrieved at {entry['at']} (UTC). Cached until you refresh this tab.")
    return entry["data"]


def choose_item(
    label: str, options: list[str], key: str, format_func: Callable[[str], str] = str
) -> str:
    selections = st.session_state.setdefault("explorer_selections", {})
    previous = selections.get(key)
    index = options.index(previous) if previous in options else 0
    value = st.selectbox(label, options, index=index, key=key, format_func=format_func)
    selections[key] = value
    return value


def scan_lineage(details: CatalogDetails, asset: Asset) -> dict[str, Any]:
    pending = st.session_state.setdefault("explorer_pending_scans", {})
    scan_id = pending.get(asset.workspace_id)
    if scan_id is None:
        scan_id = details.start_lineage_scan(asset)
        pending[asset.workspace_id] = scan_id
    deadline = monotonic() + 20
    for attempt in range(10):
        status = details.scan_status(scan_id)
        if status["status"] == "Succeeded":
            result = details.scan_result(scan_id)
            if pending.get(asset.workspace_id) == scan_id:
                pending.pop(asset.workspace_id, None)
            return result
        if status["status"] == "Failed":
            if pending.get(asset.workspace_id) == scan_id:
                pending.pop(asset.workspace_id, None)
            raise AppError(f"Lineage scan failed: {status.get('error', 'No failure detail returned.')}")
        if attempt == 9 or monotonic() >= deadline:
            raise AppError(
                "The lineage scan is still running after bounded polling. "
                "Use Refresh tab to check this scan again; no artifact was changed."
            )
        sleep(1)
    raise AppError("Lineage scan did not return a result.")


def show_records(records: list[dict[str, Any]], empty: str = "No records returned.") -> None:
    if not records:
        st.info(empty)
        return
    frame = pd.json_normalize(records)
    for column in frame.columns:
        frame[column] = frame[column].map(
            lambda value: json.dumps(value, ensure_ascii=True) if isinstance(value, (list, dict)) else value
        )
    st.dataframe(frame, hide_index=True, width="stretch")


def show_lineage(scan: dict[str, Any], asset: Asset) -> None:
    edges = lineage_edges(scan, asset.workspace_id)
    nodes = lineage_nodes(scan, asset.workspace_id)
    reported = asset.key in nodes
    nodes.setdefault(asset.key, {
        "Name": asset.name, "Type": asset.type, "Location": asset.workspace_name,
        "Item ID": asset.id, "Workspace ID": asset.workspace_id,
        "Modified": "", "Endorsement": "", "Sensitivity label ID": "",
    })
    relations = lineage_relations(edges, asset.key)
    if not reported:
        st.warning(
            "The selected item was not returned by the scanner. Its catalog card is shown for context, "
            "but missing API coverage does not prove that it has no dependencies."
        )
    if len(relations) == 1:
        st.info(
            "No supported relationships were returned for this item. This does not prove "
            "that it has no dependencies. Choose Workspace to explore the other returned items."
        )
    prefix = asset.key + ":lineage:"
    view_column, scope_column, search_column = st.columns([1.2, 2, 2])
    with view_column:
        view = st.segmented_control(
            "Lineage view", ["Graph", "Table"], default="Graph", required=True, key=prefix + "view",
        )
    with scope_column:
        scope = st.selectbox(
            "Lineage scope", ["Upstream & downstream", "Upstream", "Downstream", "Workspace"],
            key=prefix + "scope",
        )
    with search_column:
        search = st.text_input("Filter lineage", key=prefix + "search", placeholder="Name, type or location")
    types = st.multiselect("Lineage item types", sorted({node["Type"] for node in nodes.values()}), key=prefix + "types")
    visible = {}
    for key, node in nodes.items():
        relation = relations.get(key, "Other workspace item")
        in_scope = (
            scope == "Workspace" or relation == "Selected item"
            or (scope == "Upstream & downstream" and key in relations)
            or (scope in ("Upstream", "Downstream") and scope in relation)
        )
        matches = not search or search.casefold() in " ".join(
            node[field] for field in ("Name", "Type", "Location")
        ).casefold()
        if in_scope and matches and (not types or node["Type"] in types):
            visible[key] = node
    visible_edges = [
        edge for edge in edges
        if lineage_key(edge, "From") in visible and lineage_key(edge, "To") in visible
    ]
    st.caption(
        f"{len(visible)} items / {len(visible_edges)} reported relationships shown. "
        "Arrows point from a dependency to its dependent item. Association and CascadeDelete "
        "relationships are not proof of data movement. Filters hide nodes and their edges."
    )
    if not visible:
        st.info("No lineage items match these filters.")
    elif view == "Graph":
        show_lineage_chart(
            visible_edges, visible, asset.key,
            f"Reported upstream and downstream dependencies for {asset.name}. The selected item is highlighted.",
        )
    else:
        rows = [
            {
                "Name": node["Name"], "Type": node["Type"],
                "Relation": relations.get(key, "Other workspace item"),
                **{field: node[field] or "Not returned" for field in (
                    "Location", "Modified", "Endorsement", "Sensitivity label ID", "Item ID", "Workspace ID",
                )},
            }
            for key, node in visible.items()
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "Modified is the artifact metadata timestamp, not its last data refresh. "
            "Sensitivity labels are IDs when no display name is supplied."
        )
    with st.expander("Reported relationship details"):
        show_records([
            {
                "From": nodes[lineage_key(edge, "From")]["Name"],
                "To": nodes[lineage_key(edge, "To")]["Name"],
                "Relationship": edge["Relationship"],
                "From ID": edge["From"], "To ID": edge["To"],
                "From workspace": edge["From workspace"], "To workspace": edge["To workspace"],
            }
            for edge in visible_edges
        ], "No reported edges in the current scope.")


def asset_explorer(client: FabricClient, asset: Asset, admin: bool) -> None:
    details = CatalogDetails(client)
    with st.container(key="asset_explorer"):
        st.caption(
            "Read-only. Opening a tab loads its data automatically."
        )
        labels = ["Overview"]
        if asset.type in CONNECTABLE_TYPES and asset.workspace_id:
            labels.append("Tables & columns")
        labels.extend(["Lineage", "Permissions", "Monitor", "Domains"])
        if st.session_state.get("explorer_tab", "Overview") not in labels:
            st.session_state.explorer_tab = "Overview"
        tabs = st.tabs(
            labels, key="explorer_tab", on_change="rerun",
        )
        active = next(index for index, tab in enumerate(tabs) if tab.open)
        section = labels[active]
        prefix = f"{asset.key}:{'admin' if admin else 'developer'}:{section}:"
        with tabs[active]:
            if st.button(
                "Refresh tab", key="refresh_explorer_tab", icon=":material/refresh:",
                help="Reload this tab's metadata only. This never triggers an item or model data refresh.",
            ):
                cache = st.session_state.setdefault("explorer_cache", {})
                for key in list(cache):
                    if key.startswith(prefix):
                        del cache[key]
            if section == "Overview":
                st.write(asset.description or "No catalog description supplied.")
                if not asset.workspace_id:
                    st.info("This catalog entry is not a workspace item.")
                else:
                    metadata = load_panel("Item metadata", prefix + "metadata", lambda: details.metadata(asset))
                    if metadata is not None:
                        with st.expander("Item metadata JSON"):
                            st.json(metadata)
                    workspace = load_panel("Workspace metadata", prefix + "workspace", lambda: details.workspace(asset))
                    if workspace is not None:
                        with st.expander("Workspace metadata JSON"):
                            st.json(workspace)
                    if asset.type in CONNECTABLE_TYPES:
                        endpoint = load_panel(
                            "Endpoint properties", prefix + "endpoint_metadata",
                            lambda: details.endpoint_metadata(asset),
                        )
                        if endpoint is not None:
                            with st.expander("Endpoint properties JSON"):
                                st.json(endpoint)
                st.caption(
                    "The API can expose identity, logical IDs and sensitivity-label IDs where supported. "
                    "Missing fields are not evidence that a label, owner or endorsement is absent."
                )
            elif section == "Tables & columns":
                if asset.type in CONNECTABLE_TYPES and asset.workspace_id:
                    schemas = load_panel("Schemas", prefix + "schemas", lambda: client.list_table_schemas(asset))
                    if schemas is not None:
                        if not schemas:
                            st.info("No schemas are visible through OneLake Table API.")
                        else:
                            schema = choose_item(
                                "Explore schema", [item["name"] for item in schemas], asset.key + ":schema"
                            )
                            table_list = load_panel(
                                "Tables", prefix + "tables:" + schema,
                                lambda: client.list_schema_tables(asset, schema),
                            )
                            if table_list is not None:
                                show_records(table_list, "No tables are visible in this schema.")
                                if table_list:
                                    table = choose_item(
                                        "Explore table", [item["name"] for item in table_list],
                                        asset.key + ":table:" + schema,
                                    )
                                    metadata = load_panel(
                                        "Columns", prefix + "columns:" + json.dumps([schema, table]),
                                        lambda: client.get_table_metadata(asset, schema, table),
                                    )
                                    if metadata is not None:
                                        columns = metadata.get("columns")
                                        if isinstance(columns, list):
                                            show_records(columns, "No column definitions were returned.")
                                        with st.expander("Full table metadata"):
                                            st.json(metadata)
                    st.caption("Metadata only. Use the SQL connection editor for data previews and queries.")
            elif section == "Lineage":
                if not admin:
                    st.info("Enable Admin view for workspace lineage scanning. No admin API is called in Developer view.")
                elif asset.workspace_id:
                    st.caption(
                        "Read-only workspace metadata scan; requires a tenant-admin role and Tenant.Read.All. "
                        "Fabric item relations are displayed when the scanner returns them. "
                        "API coverage can differ from the portal; this is not table/column-level lineage."
                    )
                    result = load_panel(
                        "Workspace lineage", prefix + "scan", lambda: scan_lineage(details, asset)
                    )
                    if result is not None:
                        try:
                            show_lineage(result, asset)
                        except AppError as exc:
                            st.error(str(exc))
                        with st.expander("Raw workspace scan metadata"):
                            st.json(result)
                if asset.workspace_id:
                    st.link_button(
                        "Open workspace in Fabric",
                        f"https://app.fabric.microsoft.com/groups/{asset.workspace_id}/list",
                        help="Choose Lineage in the workspace for the portal's full experience. Browser sign-in is separate.",
                    )
                    with st.expander("Source connection bindings (not lineage)"):
                        connections = load_panel(
                            "Item connections", prefix + "connections", lambda: details.connections(asset)
                        )
                        if connections is not None:
                            show_records(connections, "No source connection bindings were returned.")
                        st.caption(
                            "These are connection bindings, not item lineage. "
                            "This read operation can require item Write permission."
                        )
                else:
                    st.info("Lineage requires an item belonging to a workspace.")
            elif section == "Permissions":
                st.info(
                    "These are reported assignments, not a calculation of your effective access. "
                    "Nested groups, sharing, SQL grants, OneLake policies and RLS/OLS can differ."
                )
                if asset.workspace_id:
                    roles = load_panel(
                        "Workspace roles", prefix + "roles", lambda: details.workspace_roles(asset)
                    )
                    if roles is not None:
                        show_records(roles)
                    st.caption("Workspace roles require Member or Admin access to this workspace.")
                    if admin:
                        access = load_panel(
                            "Item access (admin)", prefix + "admin_access", lambda: details.item_access(asset)
                        )
                        if access is not None:
                            show_records(access)
                        st.caption("Preview Admin API. Requires tenant admin and Tenant.Read.All.")
                if not admin:
                    st.caption("Item-wide access details are hidden in Developer view.")
            elif section == "Monitor":
                if asset.workspace_id:
                    runs = load_panel(
                        "Monitoring history", prefix + "monitor", lambda: details.monitoring(asset)
                    )
                    if runs is not None:
                        show_records(runs, "No runs were returned by this API.")
                st.caption(
                    "Semantic models show up to 100 refresh entries; other supported items show scheduler "
                    "job history (typically up to 100 completed runs). This is not SQL query history, "
                    "complete usage telemetry, or real-time capacity/CU monitoring."
                )
            elif section == "Domains":
                domain_list = load_panel("Domains", prefix + "domains", lambda: details.domains(admin))
                if domain_list is not None:
                    show_records(domain_list, "No domains returned.")
                    if domain_list:
                        names = {item["id"]: item.get("displayName", item["id"]) for item in domain_list}
                        domain_id = choose_item(
                            "Domain", list(names), asset.key + ":domain:" + str(admin), names.__getitem__
                        )
                        st.json(next(item for item in domain_list if item["id"] == domain_id))
                        if admin:
                            workspaces = load_panel(
                                "Domain workspaces", prefix + "domain_workspaces:" + domain_id,
                                lambda: details.domain_workspaces(domain_id),
                            )
                            if workspaces is not None:
                                show_records(workspaces)
                st.caption(
                    "Domain grouping is not a security boundary. Developer view uses Core Domain.Read.All; "
                    "domain workspace membership uses the tenant-admin API only. No assignments are changed."
                )
