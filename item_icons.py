import base64
from functools import cache
from pathlib import Path


ICON_DIRECTORY = Path(__file__).resolve().parent / "assets" / "fabric-icons"
ITEM_ICONS = {
    "Warehouse": "data_warehouse",
    "Lakehouse": "lakehouse",
    "SemanticModel": "semantic_model",
    "Report": "report",
    "PaginatedReport": "paginated_report",
    "Dashboard": "dashboard",
    "Notebook": "notebook",
    "DataPipeline": "pipeline",
    "Dataflow": "dataflow",
    "DataflowGen2": "dataflow_gen2",
    "Eventhouse": "event_house",
    "Eventstream": "eventstream",
    "KQLDatabase": "kql_database",
    "KQLQueryset": "kql_queryset",
    "KQLDashboard": "real_time_dashboard",
    "RealTimeDashboard": "real_time_dashboard",
    "Ontology": "ontology",
    "Plan": "planning",
    "DataAgent": "data_agent",
    "OperationsAgent": "operations_agent",
    "SQLDatabase": "sql_database",
    "MirroredDatabase": "mirrored_generic_database",
    "MirroredCatalog": "mirrored_catalog",
    "MirroredAzureDatabricksCatalog": "mirrored_catalog",
    "AzureDatabricksStorage": "mirrored_generic_storage",
    "MirroredAzureDatabricksStorage": "mirrored_generic_storage",
    "Environment": "environment",
    "MLExperiment": "experiments",
    "MLModel": "model",
    "SparkJobDefinition": "spark_job_direction",
    "CopyJob": "copy_job",
    "VariableLibrary": "variable_library",
    "UserDataFunction": "user_data_function",
    "FunctionSet": "function_set",
    "Datamart": "datamart",
    "Scorecard": "scorecard",
}
GENERIC_ICON = "generic_placeholder"
ICON_TYPE_ALIASES = {
    "warehouses": "Warehouse",
    "lakehouses": "Lakehouse",
    "SQLAnalyticsEndpoint": "Warehouse",
}


def item_icon_name(item_type: str) -> str:
    return ITEM_ICONS.get(ICON_TYPE_ALIASES.get(item_type, item_type), GENERIC_ICON)


@cache
def item_icon_uri(icon_name: str) -> str:
    encoded = base64.b64encode((ICON_DIRECTORY / f"{icon_name}_20_item.svg").read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def item_icon_styles() -> str:
    rules = [
        '[class*="st-key-catalog_row_"] [data-testid="stIconMaterial"] {'
        'font-size: 0; width: 20px; height: 20px; min-width: 20px; '
        'display: inline-block; flex-shrink: 0; background-size: contain; '
        'background-repeat: no-repeat; background-position: center;}'
    ]
    for name in sorted(set(ITEM_ICONS.values()) | {GENERIC_ICON}):
        rules.append(
            f'[class*="st-key-catalog_row_"][class*="_icon_{name}_"] '
            f'[data-testid="stIconMaterial"] {{background-image: url("{item_icon_uri(name)}");}}'
        )
    return "<style>" + "\n".join(rules) + "</style>"
