import base64
import hashlib
import json
import unittest
import xml.etree.ElementTree as ET

from item_icons import (
    GENERIC_ICON,
    ICON_DIRECTORY,
    ITEM_ICONS,
    item_icon_name,
    item_icon_styles,
    item_icon_uri,
)


class ItemIconTests(unittest.TestCase):
    def test_screenshot_item_types_map_to_their_official_icons(self):
        for item_type, name in {
            "Warehouse": "data_warehouse",
            "Lakehouse": "lakehouse",
            "SemanticModel": "semantic_model",
            "Ontology": "ontology",
            "Plan": "planning",
            "DataAgent": "data_agent",
            "DataPipeline": "pipeline",
            "warehouses": "data_warehouse",
            "lakehouses": "lakehouse",
            "SQLAnalyticsEndpoint": "data_warehouse",
        }.items():
            with self.subTest(item_type=item_type):
                self.assertEqual(item_icon_name(item_type), name)

    def test_unmapped_types_use_an_explicit_generic_item_icon(self):
        self.assertEqual(item_icon_name("FutureFabricItem"), GENERIC_ICON)

    def test_all_bundled_assets_match_upstream_integrity_hashes(self):
        manifest = json.loads((ICON_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "8.2.0")
        self.assertEqual(
            {entry["file"] for entry in manifest["files"]},
            {f"{name}_20_item.svg" for name in set(ITEM_ICONS.values()) | {GENERIC_ICON}},
        )
        for entry in manifest["files"]:
            with self.subTest(file=entry["file"]):
                data = (ICON_DIRECTORY / entry["file"]).read_bytes()
                digest = base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")
                self.assertEqual(digest, entry["sha256_base64"])

    def test_assets_are_original_square_svgs_without_active_or_remote_content(self):
        for name in set(ITEM_ICONS.values()) | {GENERIC_ICON}:
            with self.subTest(name=name):
                root = ET.parse(ICON_DIRECTORY / f"{name}_20_item.svg").getroot()
                self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
                self.assertEqual(root.attrib["width"], "20")
                self.assertEqual(root.attrib["height"], "20")
                for element in root.iter():
                    self.assertNotIn(element.tag.split("}")[-1], ("script", "foreignObject"))
                    for attribute, value in element.attrib.items():
                        self.assertFalse(attribute.lower().startswith("on"))
                        if attribute.split("}")[-1] == "href":
                            self.assertTrue(value.startswith("#"))

    def test_icon_data_uris_preserve_original_bytes_and_need_no_runtime_cdn(self):
        for name in set(ITEM_ICONS.values()) | {GENERIC_ICON}:
            with self.subTest(name=name):
                uri = item_icon_uri(name)
                self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
                self.assertEqual(
                    base64.b64decode(uri.split(",", 1)[1]),
                    (ICON_DIRECTORY / f"{name}_20_item.svg").read_bytes(),
                )
        css = item_icon_styles()
        self.assertIn("_icon_ontology_", css)
        self.assertNotIn('url("http', css)

    def test_upstream_license_metadata_and_attribution_are_retained(self):
        package = json.loads((ICON_DIRECTORY / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["name"], "@fabric-msft/svg-icons")
        self.assertEqual(package["version"], "8.2.0")
        self.assertEqual(package["license"], "MIT")
        self.assertIn("MIT License", (ICON_DIRECTORY / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8"))
