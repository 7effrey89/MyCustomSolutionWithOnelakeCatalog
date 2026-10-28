import base64
import hashlib
import json
import unittest
from unittest.mock import patch

from catalog_details import lineage_dot
from item_icons import GENERIC_ICON, item_icon_uri
from lineage_chart import CHART_DIRECTORY, show_lineage_chart
from ui_styles import CATALOG_STYLES


class LineageChartTests(unittest.TestCase):
    def test_graph_uses_original_local_icons_for_every_node_and_keeps_highlight(self):
        types = ("Lakehouse", "SemanticModel", "Notebook", "warehouses", "SQLAnalyticsEndpoint", "GraphModel")
        nodes = {
            f"ws:{index}": {"Name": kind, "Type": kind, "Item ID": str(index)}
            for index, kind in enumerate(types)
        }
        with patch("lineage_chart._chart") as chart:
            show_lineage_chart([], nodes, "ws:0", "Test lineage")
        args = chart.call_args.kwargs
        self.assertEqual(args["dot"].count("<IMG "), len(nodes))
        self.assertIn("penwidth=3", args["dot"])
        self.assertIn('fontname="Arial"', args["dot"])
        self.assertEqual(args["description"], "Test lineage")
        self.assertEqual(args["key"], "ws:0:lineage:graph")
        self.assertEqual(args["icons"]["lakehouse.svg"], item_icon_uri("lakehouse"))
        self.assertEqual(args["icons"][GENERIC_ICON + ".svg"], item_icon_uri(GENERIC_ICON))
        self.assertEqual(len(args["icons"]), 5)

    def test_names_and_types_are_escaped_inside_html_labels(self):
        dot = lineage_dot([], {
            "ws:item": {
                "Name": '<IMG SRC="https://invalid.example/x"/> & text',
                "Type": "<script>alert(1)</script>", "Item ID": "item",
            },
        })
        label = dot.split("label=<", 1)[1].split(">, tooltip=", 1)[0]
        self.assertEqual(label.count("<IMG "), 1)
        self.assertIn("&lt;IMG", label)
        self.assertIn("&lt;script&gt;", label)
        self.assertIn('SRC="generic_placeholder.svg"', label)

    def test_renderer_bundle_integrity_and_dependency_licenses_are_retained(self):
        manifest = json.loads((CHART_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "3.31.0")
        for entry in manifest["files"]:
            with self.subTest(file=entry["file"]):
                digest = base64.b64encode(hashlib.sha256((CHART_DIRECTORY / entry["file"]).read_bytes()).digest()).decode("ascii")
                self.assertEqual(digest, entry["sha256_base64"])
        self.assertIn("MIT", (CHART_DIRECTORY / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8"))
        self.assertIn("Eclipse Public License - v 2.0", (CHART_DIRECTORY / "Graphviz-COPYING.txt").read_text(encoding="utf-8"))

    def test_component_is_self_hosted_and_blocks_runtime_external_resources(self):
        html = (CHART_DIRECTORY / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="viz-global.js"', html)
        self.assertNotIn("https://", html)
        self.assertIn("connect-src 'none'", html)
        self.assertIn("img-src data:", html)
        script = (CHART_DIRECTORY / "chart.js").read_text(encoding="utf-8")
        self.assertIn('event.source !== window.parent', script)
        self.assertIn('image.setAttribute("href", uri)', script)
        self.assertNotIn("innerHTML", script)
        self.assertIn('result.errors.some(item => item.level === "error")', script)
        self.assertIn("warnings.hidden = result.errors.length === 0", script)

    def test_graph_iframe_tracks_parent_width_on_resize(self):
        self.assertIn(
            'iframe[title="lineage_chart.fabric_lineage_graph"] { width: 100%; max-width: 100%; }',
            CATALOG_STYLES,
        )
