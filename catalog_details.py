from __future__ import annotations

import json
import textwrap
from html import escape
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fabric_client import FABRIC_API, AppError, Asset, FabricClient, _guid, _text
from item_icons import item_icon_name


class CatalogDetails:
    def __init__(self, client: FabricClient) -> None:
        self.client = client

    def _read(
        self, path: str, *, params: dict[str, str] | None = None, service: str = "fabric"
    ) -> dict[str, Any]:
        return self.client._request(
            "GET", path, params=params, service=service, skill="onelake-catalog-govern-cli"
        )

    def _list(
        self, path: str, *, field: str = "value", params: dict[str, str] | None = None,
        service: str = "fabric",
    ) -> list[dict[str, Any]]:
        query = dict(params or {})
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        while True:
            data = self._read(path, params=query or None, service=service)
            page = data.get(field)
            if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
                raise AppError(f"The API returned invalid '{field}' metadata.")
            records.extend(page)
            token = data.get("continuationToken")
            uri = data.get("continuationUri")
            if not token and uri:
                if not isinstance(uri, str):
                    raise AppError("Invalid pagination URI.")
                parsed = urlsplit(uri)
                expected = urlsplit(FABRIC_API + path)
                if service != "fabric" or (
                    parsed.scheme, parsed.netloc, parsed.path
                ) != (expected.scheme, expected.netloc, expected.path):
                    raise AppError("The API returned an untrusted pagination URI.")
                token = parse_qs(parsed.query).get("continuationToken", [None])[0]
                if not token:
                    raise AppError("The pagination URI is missing its continuation token.")
            if not token:
                return records
            if not isinstance(token, str) or token in seen:
                raise AppError("The API returned an invalid or repeated pagination token.")
            seen.add(token)
            query["continuationToken"] = token

    @staticmethod
    def _item_path(asset: Asset) -> str:
        if not asset.workspace_id:
            raise AppError("Select an item belonging to a workspace.")
        return f"/workspaces/{_guid(asset.workspace_id)}/items/{_guid(asset.id)}"

    def metadata(self, asset: Asset) -> dict[str, Any]:
        return self._read(self._item_path(asset), params={"include": "DefaultIdentity"})

    def workspace(self, asset: Asset) -> dict[str, Any]:
        return self._read(f"/workspaces/{_guid(asset.workspace_id)}")

    def endpoint_metadata(self, asset: Asset) -> dict[str, Any]:
        routes = {"Warehouse": "warehouses", "Lakehouse": "lakehouses"}
        if asset.type not in routes:
            raise AppError("Endpoint properties are available for Warehouse and Lakehouse items.")
        return self._read(
            f"/workspaces/{_guid(asset.workspace_id)}/{routes[asset.type]}/{_guid(asset.id)}"
        )

    def workspace_roles(self, asset: Asset) -> list[dict[str, Any]]:
        return self._list(f"/workspaces/{_guid(asset.workspace_id)}/roleAssignments")

    def item_access(self, asset: Asset) -> list[dict[str, Any]]:
        return self._list(
            "/admin" + self._item_path(asset) + "/users",
            field="accessDetails",
            params={"type": asset.type},
        )

    def connections(self, asset: Asset) -> list[dict[str, Any]]:
        return self._list(self._item_path(asset) + "/connections")

    def monitoring(self, asset: Asset) -> list[dict[str, Any]]:
        if asset.type == "SemanticModel":
            return self._list(
                f"/groups/{_guid(asset.workspace_id)}/datasets/{_guid(asset.id)}/refreshes",
                params={"$top": "100"}, service="powerbi",
            )
        return self._list(self._item_path(asset) + "/jobs/instances")

    def domains(self, admin: bool = False) -> list[dict[str, Any]]:
        if admin:
            return self._list("/admin/domains", field="domains", params={"preview": "false"})
        return self._list("/domains")

    def domain_workspaces(self, domain_id: str) -> list[dict[str, Any]]:
        return self._list(f"/admin/domains/{_guid(domain_id)}/workspaces")

    def start_lineage_scan(self, asset: Asset) -> str:
        data = self.client._request(
            "POST", "/admin/workspaces/getInfo", service="powerbi", expected_status=202,
            params={"lineage": "true", "datasourceDetails": "true", "datasetSchema": "true",
                    "getArtifactUsers": "false"},
            body={"workspaces": [_guid(asset.workspace_id)]},
            skill="onelake-catalog-govern-cli",
        )
        return _guid(_text(data, "id"))

    def scan_status(self, scan_id: str) -> dict[str, Any]:
        data = self._read(f"/admin/workspaces/scanStatus/{_guid(scan_id)}", service="powerbi")
        status = _text(data, "status")
        if status not in ("NotStarted", "Running", "Succeeded", "Failed"):
            raise AppError(f"Unexpected lineage scan status: {status}")
        return data

    def scan_result(self, scan_id: str) -> dict[str, Any]:
        return self._read(f"/admin/workspaces/scanResult/{_guid(scan_id)}", service="powerbi")


SCANNER_TYPES = {
    "datasets": "SemanticModel", "dataflows": "Dataflow", "reports": "Report",
    "dashboards": "Dashboard", "datamarts": "Datamart",
}


def _scan_workspace(scan: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    workspaces = scan.get("workspaces")
    if not isinstance(workspaces, list):
        raise AppError("Lineage scan returned no workspace list.")
    for workspace in workspaces:
        if isinstance(workspace, dict) and workspace.get("id") == workspace_id:
            return workspace
    raise AppError("The selected workspace was not included in the lineage scan result.")


def _scan_artifacts(workspace: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    artifacts: list[tuple[str, dict[str, Any]]] = []
    for collection, items in workspace.items():
        # Newer scanner responses use item-type names for Fabric collections.
        if collection not in SCANNER_TYPES and not (
            isinstance(items, list) and any(
                isinstance(item, dict) and "id" in item and ("name" in item or "relations" in item)
                for item in items
            )
        ):
            continue
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise AppError(f"Lineage scan returned invalid '{collection}' metadata.")
        for item in items:
            _text(item, "id")
            artifacts.append((SCANNER_TYPES.get(collection, collection), item))
    return artifacts


def _scan_records(item: dict[str, Any], field: str) -> list[dict[str, Any]]:
    records = item.get(field, [])
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise AppError(f"Lineage scan returned invalid '{field}' metadata.")
    return records


def lineage_edges(scan: dict[str, Any], workspace_id: str) -> list[dict[str, str]]:
    """Keep reported dependency direction and relationship types, including Fabric relations."""
    workspace = _scan_workspace(scan, workspace_id)
    edges: list[dict[str, str]] = []
    for _, item in _scan_artifacts(workspace):
        target = _text(item, "id")

        def add(source: str, relationship: str, source_workspace: str = workspace_id) -> None:
            edge = {
                "From": source, "To": target, "Relationship": relationship,
                "From workspace": source_workspace, "To workspace": workspace_id,
            }
            if edge not in edges:
                edges.append(edge)

        if item.get("datasetId"):
            add(_text(item, "datasetId"), "feeds", item.get("datasetWorkspaceId") or workspace_id)
        for source in _scan_records(item, "upstreamDataflows"):
            add(_text(source, "targetDataflowId"), "upstream dataflow", source.get("groupId") or workspace_id)
        for usage in _scan_records(item, "datasourceUsages"):
            add(_text(usage, "datasourceInstanceId"), "data source", "")
        for relation in _scan_records(item, "relations"):
            add(
                _text(relation, "dependentOnArtifactId"), _text(relation, "relationType"),
                relation.get("workspaceId") or workspace_id,
            )
        for tile in _scan_records(item, "tiles"):
            for field in ("reportId", "datasetId"):
                if tile.get(field):
                    add(_text(tile, field), "dashboard tile")
    return edges


def lineage_key(edge: dict[str, str], side: str) -> str:
    return f"{edge[side + ' workspace']}:{edge[side]}"


def lineage_nodes(scan: dict[str, Any], workspace_id: str) -> dict[str, dict[str, str]]:
    workspace = _scan_workspace(scan, workspace_id)
    location = workspace.get("name") or workspace_id
    nodes: dict[str, dict[str, str]] = {}
    for kind, item in _scan_artifacts(workspace):
        endorsement = item.get("endorsementDetails") or {}
        sensitivity = item.get("sensitivityLabel") or {}
        if not isinstance(endorsement, dict) or not isinstance(sensitivity, dict):
            raise AppError("Lineage scan returned invalid governance metadata.")
        nodes[f"{workspace_id}:{item['id']}"] = {
            "Name": item.get("name") or item.get("displayName") or item["id"],
            "Type": kind, "Location": location, "Item ID": item["id"],
            "Workspace ID": workspace_id,
            "Modified": item.get("modifiedDateTime") or item.get("lastUpdatedDate") or "",
            "Endorsement": endorsement.get("endorsement") or "",
            "Sensitivity label ID": sensitivity.get("labelId") or "",
        }
    for edge in lineage_edges(scan, workspace_id):
        for side in ("From", "To"):
            key = lineage_key(edge, side)
            source_workspace = edge[side + " workspace"]
            nodes.setdefault(key, {
                "Name": edge[side], "Type": "Data source" if not source_workspace else "Unresolved item",
                "Location": source_workspace or "External data source",
                "Item ID": edge[side], "Workspace ID": source_workspace,
                "Modified": "", "Endorsement": "", "Sensitivity label ID": "",
            })
    for source in _scan_records(scan, "datasourceInstances"):
        key = ":" + _text(source, "datasourceId")
        if key in nodes:
            details = source.get("connectionDetails") or {}
            if not isinstance(details, dict):
                raise AppError("Lineage scan returned invalid datasource connection metadata.")
            name = " / ".join(
                str(details[field]) for field in ("server", "database", "url", "path")
                if details.get(field)
            )
            nodes[key]["Name"] = name or source["datasourceId"]
            nodes[key]["Type"] = source.get("datasourceType") or "Data source"
    return nodes


def lineage_relations(edges: list[dict[str, str]], selected_key: str) -> dict[str, str]:
    def walk(reverse: bool) -> set[str]:
        neighbors: dict[str, set[str]] = {}
        for edge in edges:
            source, target = lineage_key(edge, "From"), lineage_key(edge, "To")
            if reverse:
                source, target = target, source
            neighbors.setdefault(source, set()).add(target)
        visited = {selected_key}
        pending = [selected_key]
        while pending:
            for neighbor in neighbors.get(pending.pop(), set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
        return visited - {selected_key}

    upstream, downstream = walk(True), walk(False)
    return {
        **{key: "Upstream" for key in upstream},
        **{key: "Downstream" for key in downstream},
        **{key: "Upstream & downstream" for key in upstream & downstream},
        selected_key: "Selected item",
    }


def lineage_dot(
    edges: list[dict[str, str]], nodes: dict[str, dict[str, str]] | None = None,
    selected_key: str = "",
) -> str:
    statements = [
        'graph [rankdir=LR, bgcolor="transparent", nodesep=0.4, ranksep=0.8];',
        'node [shape=box, style="rounded,filled", fontname="Arial", fontsize=12, '
        'color="#c8d6d1", fillcolor="#f5faf8", fontcolor="#243a33", margin="0.2,0.12"];',
        'edge [color="#6c8c82", fontname="Arial", fontsize=9, fontcolor="#49695f"];',
    ]
    if nodes is not None:
        for key, node in nodes.items():
            name = '<BR ALIGN="LEFT"/>'.join(escape(line) for line in textwrap.wrap(node["Name"], width=30))
            label = (
                '<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3"><TR>'
                f'<TD WIDTH="28" HEIGHT="28"><IMG SRC="{item_icon_name(node["Type"])}.svg"/></TD>'
                f'<TD ALIGN="LEFT">{name}<BR ALIGN="LEFT"/>'
                f'<FONT POINT-SIZE="10">{escape(node["Type"])}</FONT></TD>'
                '</TR></TABLE>'
            )
            attributes = f"label=<{label}>, tooltip={json.dumps(node['Name'] + ' | ' + node['Item ID'])}"
            if key == selected_key:
                attributes += ', color="#117865", fillcolor="#e3f7ef", penwidth=3'
            statements.append(f"{json.dumps(key)} [{attributes}];")
    for edge in edges:
        source = lineage_key(edge, "From") if nodes is not None else edge["From"]
        target = lineage_key(edge, "To") if nodes is not None else edge["To"]
        statements.append(
            f"{json.dumps(source)} -> {json.dumps(target)} "
            f'[label={json.dumps(edge["Relationship"])}];'
        )
    return "digraph lineage { " + " ".join(statements) + " }"
