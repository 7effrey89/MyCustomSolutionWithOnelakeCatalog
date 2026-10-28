from item_icons import item_icon_styles


CATALOG_STYLES = """
<style>
[data-testid="stMainBlockContainer"] {
    max-width: none;
    padding: calc(3.75rem + 1rem) 1rem 1.5rem;
}
.st-key-catalog_workspace { container: catalog-workspace / inline-size; min-width: 0; }
.st-key-asset_detail { min-width: 0; min-height: max(560px, calc(100dvh - 360px)); }
.st-key-asset_toolbar { border-bottom: 1px solid rgba(128, 128, 128, 0.2); padding-bottom: 12px; }
.st-key-asset_identity { min-width: 0; }
.st-key-asset_identity [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; }
.st-key-asset_identity [data-testid="stColumn"]:first-child { flex: 0 0 40px; width: 40px; min-width: 0 !important; }
.st-key-asset_identity [data-testid="stColumn"]:last-child { flex: 1 1 0; min-width: 0 !important; }
.st-key-asset_identity h3 { overflow-wrap: anywhere; }
.st-key-asset_explorer { min-width: 0; }
.st-key-asset_explorer iframe[title="lineage_chart.fabric_lineage_graph"] { width: 100%; max-width: 100%; }
@container catalog-workspace (min-width: 900px) {
    .st-key-catalog_rows {
        --catalog-rows-height: clamp(220px, calc(100dvh - 700px), 1000px);
    }
    .st-key-catalog_workspace [data-testid="stHorizontalBlock"]:has(.st-key-catalog_table) {
        flex-wrap: nowrap;
        align-items: flex-start;
    }
    .st-key-catalog_workspace [data-testid="stColumn"]:has(.st-key-catalog_table) {
        flex: 0 0 clamp(280px, 26%, 360px);
        min-width: 0;
    }
    .st-key-catalog_workspace [data-testid="stColumn"]:has(.st-key-asset_detail) {
        flex: 1 1 0;
        min-width: 0;
    }
}
@container catalog-workspace (max-width: 899px) {
    .st-key-catalog_rows { --catalog-rows-height: 320px; }
    .st-key-catalog_workspace [data-testid="stHorizontalBlock"]:has(.st-key-catalog_table) {
        flex-wrap: wrap;
    }
    .st-key-catalog_workspace [data-testid="stColumn"]:has(:is(.st-key-catalog_table, .st-key-asset_detail)) {
        flex: 1 1 100%;
        min-width: 0;
        width: 100%;
    }
    .st-key-asset_detail { min-height: 0; }
}
.st-key-catalog_table { overflow: visible; }
.st-key-catalog_grid {
    min-width: 0;
    max-width: 100%;
    overflow: visible;
}
.st-key-catalog_wide .st-key-catalog_grid {
    overflow-x: auto;
    overflow-y: hidden;
}
.st-key-catalog_wide :is(.st-key-catalog_header, .st-key-catalog_rows) { min-width: 900px; }
.st-key-catalog_wide .st-key-catalog_rows [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; }
.st-key-catalog_wide .st-key-catalog_rows [data-testid="stColumn"] { min-width: 0 !important; }
.st-key-catalog_wide .st-key-catalog_rows [data-testid="stText"] {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.st-key-catalog_wide .st-key-catalog_rows [data-testid="stText"] > span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.st-key-catalog_header {
    background: rgba(8, 127, 140, 0.16);
    border-bottom: 2px solid #087f8c;
    border-radius: 6px 6px 0 0;
    padding: 0.65rem;
}
.st-key-catalog_footer {
    background: rgba(8, 127, 140, 0.06);
    border-top: 1px solid rgba(128, 128, 128, 0.2);
    padding: 0.5rem 0.65rem;
}
[class*="st-key-catalog_row_"] {
    padding: 0.3rem 0.65rem;
    border-bottom: 1px solid rgba(128, 128, 128, 0.2);
}
[class*="st-key-catalog_row_odd_"] {
    background: rgba(8, 127, 140, 0.05);
}
[class*="st-key-catalog_row_selected_"] {
    background: rgba(8, 127, 140, 0.18);
    border-left: 3px solid #087f8c;
}
.st-key-catalog_table button[kind="tertiary"] {
    color: #087f8c;
    text-decoration: underline;
    text-underline-offset: 3px;
    justify-content: flex-start;
    text-align: left;
    width: 100%;
}
.st-key-catalog_rows button[kind="tertiary"] > div {
    justify-content: flex-start;
    min-width: 0;
}
.st-key-catalog_rows button [data-testid="stMarkdownContainer"] {
    min-width: 0;
    overflow: hidden;
}
.st-key-catalog_rows button p {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.st-key-catalog_header [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; }
.st-key-catalog_header [data-testid="stColumn"] { min-width: 0 !important; }
.st-key-catalog_compact .st-key-catalog_header [data-testid="stColumn"]:last-child {
    flex: 0 0 112px;
    width: 112px;
}
.st-key-catalog_grid .st-key-catalog_rows {
    height: var(--catalog-rows-height, 320px);
    max-height: var(--catalog-rows-height, 320px);
    flex: 0 0 auto;
    overflow-x: hidden;
    overflow-y: auto;
}
.st-key-catalog_rows [data-testid="stButton"] { min-width: 0; }
.st-key-catalog_table [data-testid="stVerticalBlock"] { gap: 8px; }
.st-key-asset_toolbar [data-testid="stColumn"] { min-width: 0 !important; }
.st-key-asset_toolbar [data-testid="stColumn"]:first-child { flex: 0 0 136px; width: 136px; }
.st-key-asset_toolbar [data-testid="stColumn"]:nth-child(2) { flex: 1 1 180px; }
.st-key-asset_toolbar [data-testid="stColumn"]:last-child { flex: 0 0 36px; width: 36px; }
.st-key-asset_toolbar [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; }
.st-key-asset_close button { width: 32px; min-width: 32px; padding: 4px; }
.st-key-asset_close button [data-testid="stMarkdownContainer"] {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
@media (max-width: 640px) {
    [data-testid="stMainBlockContainer"] { padding-inline: 12px; }
    .st-key-asset_toolbar [data-testid="stHorizontalBlock"] {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 36px;
    }
    .st-key-asset_toolbar [data-testid="stColumn"]:first-child { grid-column: 1; grid-row: 1; }
    .st-key-asset_toolbar [data-testid="stColumn"]:nth-child(2) { grid-column: 1 / -1; grid-row: 2; }
    .st-key-asset_toolbar [data-testid="stColumn"]:last-child { grid-column: 2; grid-row: 1; }
}
</style>
""" + item_icon_styles()

FABRIC_STYLES = CATALOG_STYLES + """
<style>
:is([data-testid="stApp"], [role="dialog"], [data-baseweb="popover"]) {
    --fabric-brand: #117865;
    --fabric-brand-hover: #0c695a;
    --fabric-brand-soft: #e3f7ef;
    --fabric-canvas: #f5f5f5;
    --fabric-surface: #ffffff;
    --fabric-text: #242424;
    --fabric-muted: #616161;
    --fabric-border: #d1d1d1;
    --st-primary-color: #117865;
    --primary-color: #117865;
    color-scheme: light;
    background: var(--fabric-canvas);
    color: var(--fabric-text);
    font-family: "Segoe UI", "Segoe UI Web", Arial, sans-serif;
}
:is([data-testid="stApp"], [role="dialog"], [data-baseweb="popover"]) :is(p, label, input, textarea, button, select, h1, h2, h3) {
    font-family: "Segoe UI", "Segoe UI Web", Arial, sans-serif;
}
[data-testid="stAppViewContainer"] {
    background: var(--fabric-canvas);
}
[data-testid="stHeader"] {
    background: var(--fabric-canvas);
}
[data-testid="stMainBlockContainer"] {
    /* Reserve Streamlit's fixed toolbar before the content gutter. */
    padding: calc(3.75rem + 1rem) 1rem 1.5rem;
    max-width: none;
}
:is([data-testid="stApp"], [role="dialog"]) :is(h1, h2, h3) {
    color: var(--fabric-text);
    font-weight: 600;
    letter-spacing: normal;
}
:is([data-testid="stApp"], [role="dialog"]) h1 { font-size: 24px; padding: 0 0 8px; }
:is([data-testid="stApp"], [role="dialog"]) h2 { font-size: 20px; }
:is([data-testid="stApp"], [role="dialog"]) h3 { font-size: 16px; }
:is([data-testid="stApp"], [role="dialog"], [data-baseweb="popover"]) p { font-size: 14px; line-height: 1.5; }
:is([data-testid="stApp"], [role="dialog"]) [data-testid="stCaptionContainer"] p {
    color: var(--fabric-muted);
    font-size: 12px;
    line-height: 16px;
}
[data-testid="stSidebar"] {
    background: #fafafa;
    border-right: 1px solid var(--fabric-border);
}
[data-testid="stSidebar"] [data-testid="stText"] {
    font-size: 12px;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
}
.st-key-appearance_controls {
    background: var(--fabric-brand-soft);
    border: 1px solid #c0ecdd;
    border-radius: 8px;
    padding: 12px;
}
.st-key-app_heading {
    padding: 0 4px;
}
.st-key-app_heading [data-testid="stVerticalBlock"] { gap: 4px; }
.fabric-context {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    color: #616161;
    font: 12px "Segoe UI", Arial, sans-serif;
    margin-bottom: 4px;
}
.fabric-context strong { color: #117865; font-weight: 600; }
.fabric-context .fabric-demo-label {
    background: #f5f5f5;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 2px 8px;
}
[data-testid="stMain"] :is([data-testid="stExpander"], [data-testid="stForm"]) {
    background: var(--fabric-surface);
    border-color: var(--fabric-border);
    border-radius: 8px;
}
:is([data-testid="stApp"], [role="dialog"]) [data-testid="stExpander"] summary {
    color: var(--fabric-text);
    font-weight: 600;
}
:is([data-testid="stApp"], [role="dialog"]) [data-testid="stAlert"] {
    border-radius: 6px;
    border: 1px solid #e0e0e0;
}
:is([data-testid="stApp"], [role="dialog"]) button {
    border-radius: 4px;
    min-height: 32px;
    font-size: 14px;
}
:is([data-testid="stApp"], [role="dialog"]) button[kind="secondary"] {
    color: var(--fabric-text);
    background: var(--fabric-surface);
    border: 1px solid var(--fabric-border);
}
:is([data-testid="stApp"], [role="dialog"]) button[kind="secondary"]:hover:not(:disabled) {
    background: #f0f0f0;
    border-color: #8a8886;
}
:is([data-testid="stApp"], [role="dialog"]) button[kind="primary"] {
    color: #ffffff;
    background: var(--fabric-brand);
    border-color: var(--fabric-brand);
}
:is([data-testid="stApp"], [role="dialog"]) button[kind="primary"]:hover:not(:disabled) {
    background: var(--fabric-brand-hover);
    border-color: var(--fabric-brand-hover);
}
:is([data-testid="stApp"], [role="dialog"], [data-baseweb="popover"]) :is(button, input, textarea, [role="tab"], summary):focus-visible {
    outline: 2px solid #117865;
    outline-offset: 2px;
}
:is([data-testid="stApp"], [role="dialog"]) button:disabled { opacity: 0.5; }
:is([data-testid="stApp"], [role="dialog"]) :is([data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div) {
    border-radius: 4px;
    background: var(--fabric-surface);
    border-color: var(--fabric-border);
    color: var(--fabric-text);
}
:is([data-testid="stApp"], [role="dialog"]) :is(input, textarea) {
    background: var(--fabric-surface);
    color: var(--fabric-text);
    caret-color: var(--fabric-brand);
}
:is([data-testid="stApp"], [role="dialog"]) input::placeholder { color: #707070; opacity: 1; }
[data-testid="stApp"] textarea { font-family: Consolas, "Cascadia Code", monospace; }
[role="dialog"] {
    background: var(--fabric-surface);
    border: 1px solid var(--fabric-border);
    border-radius: 8px;
}
[data-baseweb="popover"] :is([role="listbox"], [role="option"], [data-baseweb="menu"]) {
    background: var(--fabric-surface);
    color: var(--fabric-text);
}
[data-baseweb="popover"] [role="option"]:hover { background: #f5f5f5; }
[data-baseweb="popover"] [role="option"][aria-selected="true"] { background: #e3f7ef; }
[data-testid="stApp"] [role="tablist"] {
    gap: 20px;
    border-bottom: 1px solid #e0e0e0;
}
[data-testid="stApp"] [role="tab"] {
    border-radius: 0;
    color: var(--fabric-muted);
}
[data-testid="stApp"] [role="tab"][aria-selected="true"] {
    color: var(--fabric-brand);
    font-weight: 600;
}
[data-testid="stApp"] [data-baseweb="tab-highlight"] {
    background-color: var(--fabric-brand);
    height: 2px;
}
.st-key-catalog_table {
    background: var(--fabric-surface);
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.st-key-asset_detail {
    background: var(--fabric-surface);
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 16px 20px;
}
.st-key-catalog_header {
    background: #fafafa;
    border-bottom: 1px solid #d1d1d1;
    border-radius: 0;
    padding: 8px;
}
.st-key-catalog_header label p { font-size: 12px; font-weight: 600; }
.st-key-catalog_rows [data-testid="stHorizontalBlock"],
.st-key-catalog_header [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap;
}
.st-key-catalog_rows [data-testid="stColumn"],
.st-key-catalog_header [data-testid="stColumn"] {
    min-width: 0 !important;
}
[class*="st-key-catalog_row_"] {
    background: #ffffff;
    padding: 2px 6px;
    border-bottom: 1px solid #f0f0f0;
    border-left: 3px solid transparent;
}
[class*="st-key-catalog_row_"]:hover { background: #f5f5f5; }
[class*="st-key-catalog_row_selected_"],
[class*="st-key-catalog_row_selected_"]:hover {
    background: #e3f7ef;
    border-left-color: #117865;
}
.st-key-catalog_rows [data-testid="stText"] {
    font-size: 14px;
    line-height: 20px;
    color: #424242;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.st-key-catalog_rows [data-testid="stText"] > span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font: inherit;
}
.st-key-catalog_table button[kind="tertiary"] {
    color: #0a5c50;
    text-decoration: none;
    justify-content: flex-start;
    text-align: left;
    width: 100%;
}
.st-key-catalog_rows button [data-testid="stMarkdownContainer"] {
    min-width: 0;
    overflow: hidden;
}
.st-key-catalog_rows button p {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.st-key-catalog_table button[kind="tertiary"]:hover { text-decoration: underline; }
[class*="st-key-catalog_kind_"] [data-testid="stText"] {
    display: inline-block;
    width: fit-content;
    max-width: 100%;
    box-sizing: border-box;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 12px;
    line-height: 16px;
    background: #fafafa;
    color: #424242;
}
[class*="st-key-catalog_kind_lakehouse_"] [data-testid="stText"] {
    background: #e3f7ef;
    border-color: #c0ecdd;
    color: #054d43;
}
[class*="st-key-catalog_kind_warehouse_"] [data-testid="stText"] {
    background: #edf4ff;
    border-color: #c7dcf8;
    color: #174e85;
}
[class*="st-key-catalog_kind_model_"] [data-testid="stText"] {
    background: #f4effa;
    border-color: #e0d2f0;
    color: #64428a;
}
.st-key-catalog_footer {
    background: #fafafa;
    border-top: 1px solid #e0e0e0;
    padding: 8px 16px;
}
@media (max-width: 768px) {
    [data-testid="stMainBlockContainer"] { padding: calc(3.75rem + 1rem) 12px 1.5rem; }
    .st-key-app_heading { padding: 0; }
    .st-key-asset_detail { padding: 12px; }
    [data-testid="stApp"] h1 { font-size: 22px; }
}
@media (prefers-reduced-motion: reduce) {
    [data-testid="stApp"] * { scroll-behavior: auto; transition: none; }
}
@media (forced-colors: active) {
    [class*="st-key-catalog_row_selected_"] { border-left-color: Highlight; }
}
</style>
"""
