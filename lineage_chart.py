from pathlib import Path

import streamlit.components.v1 as components

from catalog_details import lineage_dot
from item_icons import item_icon_name, item_icon_uri


CHART_DIRECTORY = Path(__file__).resolve().parent / "assets" / "lineage-chart"
_chart = components.declare_component("fabric_lineage_graph", path=str(CHART_DIRECTORY))


def show_lineage_chart(
    edges: list[dict[str, str]], nodes: dict[str, dict[str, str]], selected_key: str,
    description: str,
) -> None:
    icons = {
        name + ".svg": item_icon_uri(name)
        for name in {item_icon_name(node["Type"]) for node in nodes.values()}
    }
    _chart(
        dot=lineage_dot(edges, nodes, selected_key), icons=icons, description=description,
        key=selected_key + ":lineage:graph", default=None,
    )
