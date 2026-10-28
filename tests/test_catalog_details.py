import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from catalog_details import (
    CatalogDetails, lineage_dot, lineage_edges, lineage_key, lineage_nodes, lineage_relations,
)
from fabric_client import FABRIC_API, POWERBI_SCOPE, AppError, Asset, FabricClient


WORKSPACE = "11111111-1111-1111-1111-111111111111"
ITEM = "22222222-2222-2222-2222-222222222222"
SCAN = "33333333-3333-3333-3333-333333333333"
ASSET = Asset(ITEM, "Warehouse", "Warehouse", WORKSPACE, "Workspace", "")
MODEL = Asset(ITEM, "Model", "SemanticModel", WORKSPACE, "Workspace", "")


class DetailsTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec=FabricClient)
        self.details = CatalogDetails(self.client)

    def test_metadata_and_workspace_use_core_paths(self):
        self.client._request.return_value = {"id": ITEM}
        self.details.metadata(ASSET)
        self.client._request.assert_called_with(
            "GET", f"/workspaces/{WORKSPACE}/items/{ITEM}",
            params={"include": "DefaultIdentity"}, service="fabric",
            skill="onelake-catalog-govern-cli",
        )
        self.details.workspace(ASSET)
        self.assertEqual(self.client._request.call_args.args[1], f"/workspaces/{WORKSPACE}")

    def test_endpoint_properties_are_type_specific(self):
        self.details.endpoint_metadata(ASSET)
        self.assertEqual(self.client._request.call_args.args[1], f"/workspaces/{WORKSPACE}/warehouses/{ITEM}")
        with self.assertRaises(AppError):
            self.details.endpoint_metadata(MODEL)

    def test_role_assignments_follow_tokens_without_following_external_urls(self):
        self.client._request.side_effect = [
            {"value": [{"role": "Viewer"}], "continuationToken": "next"},
            {"value": [{"role": "Member"}]},
        ]
        result = self.details.workspace_roles(ASSET)
        self.assertEqual(len(result), 2)
        self.assertEqual(self.client._request.call_args.kwargs["params"], {"continuationToken": "next"})

    def test_admin_item_access_uses_access_details_and_type(self):
        self.client._request.return_value = {"accessDetails": [{"principal": {"id": ITEM}}]}
        self.assertEqual(len(self.details.item_access(ASSET)), 1)
        self.assertEqual(
            self.client._request.call_args.args[1], f"/admin/workspaces/{WORKSPACE}/items/{ITEM}/users"
        )
        self.assertEqual(self.client._request.call_args.kwargs["params"], {"type": "Warehouse"})

    def test_admin_and_developer_domains_are_separate_api_surfaces(self):
        self.client._request.return_value = {"value": [{"id": ITEM}]}
        self.details.domains(False)
        self.assertEqual(self.client._request.call_args.args[1], "/domains")
        self.client._request.return_value = {"domains": [{"id": ITEM}]}
        self.details.domains(True)
        self.assertEqual(self.client._request.call_args.args[1], "/admin/domains")
        self.assertEqual(self.client._request.call_args.kwargs["params"], {"preview": "false"})

    def test_domain_workspaces_uses_admin_route(self):
        self.client._request.return_value = {"value": []}
        self.assertEqual(self.details.domain_workspaces(ITEM), [])
        self.assertEqual(self.client._request.call_args.args[1], f"/admin/domains/{ITEM}/workspaces")

    def test_monitoring_uses_jobs_or_model_refreshes(self):
        self.client._request.return_value = {"value": []}
        self.details.monitoring(ASSET)
        self.assertEqual(
            self.client._request.call_args.args[1], f"/workspaces/{WORKSPACE}/items/{ITEM}/jobs/instances"
        )
        self.details.monitoring(MODEL)
        self.assertEqual(self.client._request.call_args.kwargs["service"], "powerbi")
        self.assertEqual(
            self.client._request.call_args.args[1], f"/groups/{WORKSPACE}/datasets/{ITEM}/refreshes"
        )

    def test_scan_is_workspace_scoped_metadata_request_not_refresh(self):
        self.client._request.return_value = {"id": SCAN}
        self.assertEqual(self.details.start_lineage_scan(ASSET), SCAN)
        call = self.client._request.call_args
        self.assertEqual(call.args, ("POST", "/admin/workspaces/getInfo"))
        self.assertEqual(call.kwargs["body"], {"workspaces": [WORKSPACE]})
        self.assertEqual(call.kwargs["service"], "powerbi")
        self.assertEqual(call.kwargs["expected_status"], 202)
        self.assertNotIn("datasetExpressions", call.kwargs["params"])

    def test_scan_states_are_explicit_and_no_automatic_unbounded_polling(self):
        for state in ("NotStarted", "Running", "Succeeded", "Failed"):
            self.client._request.return_value = {"status": state}
            self.assertEqual(self.details.scan_status(SCAN)["status"], state)
        self.client._request.return_value = {"status": "Unknown"}
        with self.assertRaises(AppError):
            self.details.scan_status(SCAN)
        self.client._request.return_value = {"workspaces": []}
        self.assertEqual(self.details.scan_result(SCAN), {"workspaces": []})

    def test_permission_errors_propagate(self):
        self.client._request.side_effect = AppError("HTTP 403")
        with self.assertRaisesRegex(AppError, "403"):
            self.details.item_access(ASSET)
        self.client._request.assert_called_once()

    def test_malformed_collections_and_repeated_pages_fail(self):
        for data in ({}, {"value": {}}, {"value": [1]}):
            self.client._request.return_value = data
            with self.subTest(data=data), self.assertRaises(AppError):
                self.details.workspace_roles(ASSET)
        self.client._request.side_effect = [
            {"value": [], "continuationToken": "same"},
            {"value": [], "continuationToken": "same"},
        ]
        with self.assertRaisesRegex(AppError, "repeated"):
            self.details.workspace_roles(ASSET)

    def test_continuation_uri_can_only_supply_token_for_original_api(self):
        path = f"/workspaces/{WORKSPACE}/roleAssignments"
        self.client._request.side_effect = [
            {"value": [], "continuationUri": FABRIC_API + path + "?continuationToken=next"},
            {"value": []},
        ]
        self.assertEqual(self.details.workspace_roles(ASSET), [])
        self.assertEqual(self.client._request.call_args.kwargs["params"], {"continuationToken": "next"})
        for uri in (
            "https://attacker.example/?continuationToken=secret",
            FABRIC_API + "/admin/items?continuationToken=next",
            FABRIC_API + path,
        ):
            self.client._request.side_effect = None
            self.client._request.return_value = {"value": [], "continuationUri": uri}
            with self.subTest(uri=uri), self.assertRaises(AppError):
                self.details.workspace_roles(ASSET)

    def test_scan_edges_only_include_reported_relationships_in_selected_workspace(self):
        scan = {"workspaces": [
            {"id": WORKSPACE, "datasets": [{"id": ITEM, "datasourceUsages": [{"datasourceInstanceId": "source"}]}],
             "reports": [{"id": "report", "datasetId": ITEM}]},
            {"id": "other", "reports": [{"id": "hidden", "datasetId": "othermodel"}]},
        ]}
        edges = lineage_edges(scan, WORKSPACE)
        self.assertEqual(len(edges), 2)
        self.assertEqual(edges[0]["From"], "source")
        self.assertEqual(edges[1]["To"], "report")
        self.assertIn("digraph", lineage_dot(edges))
        with self.assertRaises(AppError):
            lineage_edges({}, WORKSPACE)
        for field in ("reports", "datasets"):
            with self.subTest(field=field), self.assertRaises(AppError):
                lineage_edges({"workspaces": [{"id": WORKSPACE, field: None}]}, WORKSPACE)

    def test_fabric_collections_and_dependency_relations_are_not_discarded(self):
        scan = {"workspaces": [{
            "id": WORKSPACE, "name": "Analytics",
            "Lakehouse": [{"id": "gold", "name": "Gold"}],
            "Notebook": [{
                "id": "notebook", "name": "03_gold", "lastUpdatedDate": "2026-10-28T10:00:00Z",
                "relations": [{"dependentOnArtifactId": "gold", "workspaceId": WORKSPACE, "relationType": "Datasource"}],
            }],
            "DataPipeline": [{
                "id": "pipeline", "name": "Daily pipeline",
                "relations": [{"dependentOnArtifactId": "notebook", "relationType": "Association"}],
            }],
            "SQLAnalyticsEndpoint": [{
                "id": "sql", "name": "Gold SQL",
                "relations": [{"dependentOnArtifactId": "gold", "relationType": "CascadeDelete"}],
            }],
            "datasets": [{
                "id": "model", "name": "Sales model",
                "relations": [{"dependentOnArtifactId": "gold", "relationType": "Association"}],
                "endorsementDetails": {"endorsement": "Certified"},
                "sensitivityLabel": {"labelId": "label-id"},
            }],
            "reports": [{"id": "report", "name": "Sales report", "datasetId": "model"}],
        }]}
        edges = lineage_edges(scan, WORKSPACE)
        nodes = lineage_nodes(scan, WORKSPACE)
        self.assertEqual(len(edges), 5)
        self.assertEqual({edge["Relationship"] for edge in edges}, {"Datasource", "Association", "CascadeDelete", "feeds"})
        self.assertEqual(nodes[WORKSPACE + ":notebook"]["Name"], "03_gold")
        self.assertEqual(nodes[WORKSPACE + ":notebook"]["Modified"], "2026-10-28T10:00:00Z")
        self.assertEqual(nodes[WORKSPACE + ":model"]["Type"], "SemanticModel")
        self.assertEqual(nodes[WORKSPACE + ":model"]["Endorsement"], "Certified")
        self.assertEqual(nodes[WORKSPACE + ":model"]["Sensitivity label ID"], "label-id")
        relations = lineage_relations(edges, WORKSPACE + ":gold")
        self.assertEqual(relations[WORKSPACE + ":gold"], "Selected item")
        for item in ("notebook", "pipeline", "sql", "model", "report"):
            self.assertEqual(relations[WORKSPACE + ":" + item], "Downstream")
        dot = lineage_dot(edges, nodes, WORKSPACE + ":gold")
        self.assertIn("Sales model", dot)
        self.assertIn("03_gold", dot)
        self.assertIn("penwidth=3", dot)

    def test_cross_workspace_ids_do_not_conflate_local_and_external_items(self):
        scan = {"workspaces": [{
            "id": WORKSPACE,
            "dataflows": [{"id": "flow", "name": "Local flow"}],
            "datasets": [{
                "id": "model", "name": "Model",
                "upstreamDataflows": [{"targetDataflowId": "flow", "groupId": "external"}],
            }],
        }]}
        edges = lineage_edges(scan, WORKSPACE)
        nodes = lineage_nodes(scan, WORKSPACE)
        self.assertEqual(lineage_key(edges[0], "From"), "external:flow")
        self.assertEqual(nodes["external:flow"]["Location"], "external")
        self.assertEqual(nodes[WORKSPACE + ":flow"]["Name"], "Local flow")
        self.assertNotIn(WORKSPACE + ":model", lineage_relations(edges, WORKSPACE + ":flow"))

    def test_graph_traversal_handles_cycles_and_both_directions(self):
        scan = {"workspaces": [{
            "id": WORKSPACE, "Notebook": [
                {"id": "a", "name": "A", "relations": [{"dependentOnArtifactId": "b", "relationType": "Association"}]},
                {"id": "b", "name": "B", "relations": [{"dependentOnArtifactId": "a", "relationType": "Association"}]},
            ],
        }]}
        relations = lineage_relations(lineage_edges(scan, WORKSPACE), WORKSPACE + ":a")
        self.assertEqual(relations, {
            WORKSPACE + ":a": "Selected item", WORKSPACE + ":b": "Upstream & downstream",
        })

    def test_source_names_and_dashboard_relationships_are_preserved(self):
        scan = {
            "workspaces": [{
                "id": WORKSPACE, "datasets": [{"id": "model", "datasourceUsages": [{"datasourceInstanceId": "source"}]}],
                "dashboards": [{"id": "dashboard", "displayName": "Overview", "tiles": [{"reportId": "report", "datasetId": "model"}]}],
            }],
            "datasourceInstances": [{"datasourceId": "source", "datasourceType": "Sql", "connectionDetails": {"server": "sql.example", "database": "Sales"}}],
        }
        edges = lineage_edges(scan, WORKSPACE)
        nodes = lineage_nodes(scan, WORKSPACE)
        self.assertEqual(nodes[":source"]["Name"], "sql.example / Sales")
        self.assertEqual(nodes[WORKSPACE + ":dashboard"]["Name"], "Overview")
        self.assertEqual(len(edges), 3)

    def test_future_fabric_item_types_and_escaped_names_render_without_invented_edges(self):
        scan = {"workspaces": [{
            "id": WORKSPACE, "FutureItem": [{"id": "future", "name": 'A "quoted" <item>'}],
            "users": [{"displayName": "Not an artifact"}],
        }]}
        nodes = lineage_nodes(scan, WORKSPACE)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(lineage_edges(scan, WORKSPACE), [])
        self.assertIn(r'A \"quoted\" <item>', lineage_dot([], nodes))

    def test_invalid_fabric_relationship_metadata_is_an_explicit_error(self):
        for relations in (None, {}, [1], [{"dependentOnArtifactId": "source"}]):
            scan = {"workspaces": [{
                "id": WORKSPACE, "Notebook": [{"id": "notebook", "name": "Notebook", "relations": relations}],
            }]}
            with self.subTest(relations=relations), self.assertRaises(AppError):
                lineage_edges(scan, WORKSPACE)
        with self.assertRaisesRegex(AppError, "not included"):
            lineage_edges({"workspaces": []}, WORKSPACE)

    @patch("fabric_client.requests.request")
    @patch("fabric_client.AzureCliCredential")
    def test_powerbi_uses_its_own_audience_and_accepts_202(self, credential, request):
        credential.return_value.get_token.return_value = SimpleNamespace(token="not-a-secret")
        request.return_value = Mock(status_code=202, headers={})
        request.return_value.json.return_value = {"id": SCAN}
        details = CatalogDetails(FabricClient())
        self.assertEqual(details.start_lineage_scan(ASSET), SCAN)
        credential.return_value.get_token.assert_called_once_with(POWERBI_SCOPE)
        self.assertEqual(request.call_args.args[1], "https://api.powerbi.com/v1.0/myorg/admin/workspaces/getInfo")
        self.assertFalse(request.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()
