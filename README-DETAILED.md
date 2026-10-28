# Detailed setup and usage

[Back to the overview and quick start](README.md).

### XMLA bridge setup (optional for SQL/catalog-only use)

Actual XMLA uses the official `Microsoft.AnalysisServices.AdomdClient` NuGet
package (19.118.3) through a small local .NET bridge; no extra Python package is
required. Install the **.NET 8 x64 runtime** to run it and a **.NET 8+ SDK** to
build it. A newer SDK alone does not necessarily install the .NET 8 runtime.

```powershell
dotnet restore .\xmla_bridge\XmlaBridge.csproj --source https://www.nuget.org/api/v2/
dotnet build .\xmla_bridge\XmlaBridge.csproj -c Release --no-restore
```

The official NuGet v2 source above was verified in this environment. If your
normal NuGet source works, `dotnet restore` without `--source` is also sufficient.
The wrapper explains missing runtime/build prerequisites explicitly. Tokens are
sent through subprocess stdin only, never command-line arguments or saved files.

## Workflow

### Appearance

The sidebar **Fabric-inspired style** toggle switches between:

- **On (default):** a light Fabric-inspired presentation with the workload
  sample's green palette, Segoe UI typography, neutral canvas and white surfaces,
  compact rows with item-type icons/badges, subtle borders, accessible focus
  indicators and a selected-asset detail surface.
- **Off:** original Streamlit colors and controls, including teal list headers
  and alternating row shading. The full-width split layout stays the same.

The app uses the full available browser width rather than a centered page with a
maximum content width. Initially, the full-width catalog shows Name, Type,
Workspace and Description columns without selecting an item or fetching its
details. Clicking an item opens a compact asset list on the left and the selected
asset's metadata and query tools on the right. Use the **X / Close details** button
in the pane's top-right corner to collapse it and restore the wide table.
Closing does not disconnect the endpoint or discard results, cached metadata,
filters or table/tab selections; select the same item to reopen them.
A new catalog search returns to the wide table and clears the connection/results.
The sidebar
starts collapsed to leave room for the workspace; expand it for CLI identity,
Developer/Admin settings and appearance controls. When less than 900 pixels of
workspace width are available, the panes stack with the list above the details.

Style changes keep your current search inputs, column filters, selected asset,
Admin/Developer mode, endpoint connection and results. The setting lasts for the
Streamlit session; resetting the whole session restores the default. The
read-only disclaimer and permission checks remain active in both styles.
Item icons and names are left-aligned in both styles. Long names are visually
truncated within the compact list, with the full name,
type, workspace and description available in the item's tooltip and detail pane.
The wide table has filters in all four column headers. With details open, the
Name field filters the compact list directly; **Filters** contains the full Type,
Workspace and Description filters. Rows have their own vertical scrollbar, with
the list header and footer outside it. On desktop, the row viewport adapts to
window height. The compact list has no horizontal scrollbar; the wide table's
header and rows scroll together horizontally on narrow screens. The outer card
does not add an extra scrollbar.
**Connect** uses a filled teal primary button in both styles, retaining the
theme's hover and keyboard-focus treatment.
The Fabric layout reserves space beneath Streamlit's fixed toolbar so the page
header and breadcrumb remain fully visible on desktop and narrow screens.

This is an original Streamlit interpretation of the
[Fabric workload sample's Fluent UI theme](https://github.com/microsoft/Microsoft-Fabric-workload-development-sample/blob/main/Frontend/src/theme.tsx)
and [Fluent design principles](https://fluent2.microsoft.design/design-principles),
[typography](https://fluent2.microsoft.design/typography), and
[layout guidance](https://fluent2.microsoft.design/layout). It does not import
React/Fluent components, embed the Fabric portal, or claim to be an official
Microsoft workload. No external fonts or tracking are loaded by the style.
Non-Windows systems use the font fallback when Segoe UI is unavailable.

Item rows and detail headings use the original Microsoft Fabric item SVGs from
[`@fabric-msft/svg-icons` 8.2.0](https://www.npmjs.com/package/@fabric-msft/svg-icons),
the package linked by [Microsoft's icon guidance](https://learn.microsoft.com/en-us/fabric/fundamentals/icons).
The selected item keeps its type icon and is identified by its highlighted row
and selection tooltip. The SVGs are bundled locally, not fetched from a CDN at
runtime, and are not recolored, cropped or distorted. Unmapped/new item types
use Microsoft's generic item icon, with the actual type still shown in metadata.
These icons identify Fabric items; they are not this app's logo or branding.
The package declares MIT licensing; its metadata, source/integrity manifest and
license attribution are retained in [assets/fabric-icons](./assets/fabric-icons/).
Streamlit Material icons remain in use for actions such as Connect and Close.

### Discover and connect

1. The integrated OneLake catalog appears immediately and automatically loads the
   first asset page using your Azure CLI identity. No Open button, redirect,
   new tab, or additional portal sign-in is needed. The initial fetch happens
   once per session; failed requests can be retried explicitly. The initial view
   is the wide table, with no detail pane or automatic item-metadata requests.
2. Expand **Search all workspaces** above the workspace and use **Search catalog**
   to refine catalog entries across workspaces.
   Search by name, description, or workspace; optionally filter by item type,
   including Warehouse, Lakehouse or SemanticModel. The table footer includes **Load more assets** and **Clear column
   filters**; loading more is disabled when there are no further pages. Only the
   list rows scroll vertically, keeping its header and footer visible.
   Use the wide table's column-header filters, or **Name** and **Filters** in the
   compact list, to filter loaded assets by Name, Type, Workspace and Description.
   Text filters are case-insensitive, Type supports multiple selections, and all
   active column filters apply together. **Clear column filters** resets them;
   a new API search also resets them. Filtering does not disconnect an active
   asset, even if its row is hidden by the filters.
3. Click an asset name in the wide table or compact list to display its details on the right
   immediately, without a dialog or connection attempt. Selecting a different
   asset opens its Overview tab. Open **Connect** in the detail toolbar and choose
   **Connect via SQL endpoint**, **Connect via Table API**, or **Connect via XMLA / DAX**.
   Names are link-style in-app buttons, not portal links; the highlighted row identifies
   the selected asset. SQL/Table API support Warehouse and Lakehouse items;
   XMLA supports SemanticModel items.
   Unsupported items explain the limitation and disable the connection choices.
   Choosing a different asset or connection mode clears the old connection/results.
   Selecting the endpoint connects immediately: there is no separate connection
   section or second connect button. The right pane shows the selected
   connection's SQL/DAX editor or Table API metadata browser above the metadata
   tabs after success. Endpoint choices remain available to switch connections.
   The top-right **X / Close details** restores the wide catalog. Reopening the
   same item keeps its connection/results; selecting another item clears them.
4. Edit the initial table-discovery query, then **Run query** to see a table and
   optionally download CSV. One SELECT, CTE, or set-operation query is allowed.
   Semantic models instead show the DAX editor and **Run DAX query**.
5. Use the asset explorer's **Overview**, **Tables & columns**, **Lineage**,
   **Permissions**, **Monitor**, and **Domains** tabs in the right pane.
   Opening a tab automatically
   fetches its data; hidden tabs make no requests. Overview opens initially.
   **Tables & columns** appears only for workspace Warehouse/Lakehouse items,
   which this demo can browse through OneLake Table API. It is not shown for
   semantic models, reports, notebooks, ontologies, plans, agents or other
   unsupported item types. This is a connector-capability distinction, not a
   claim that those services cannot contain tables; semantic models still
   support read-only DAX through **Connect via XMLA / DAX**.
   Schemas, tables, columns and domain membership load as you make selections.
   Results are timestamped and cached per item/tab/Developer-or-Admin view, so
   revisiting a tab does not repeat requests. Table/domain selections survive
   switching tabs. Use the single **Refresh tab** control to reload only that
   tab's metadata, never to trigger an item/model data refresh. A failed fetch
   clears the old payload and displays the error; failures remain cached until
   you explicitly refresh, avoiding repeated denied requests on unrelated reruns.
   Overview keeps raw item/workspace/endpoint JSON in collapsible sections to
   leave room for the description and other metadata.

This is a native Streamlit catalog experience built on the Fabric Catalog Search
API, not an iframe, embedded Microsoft portal, or full replica of its governance
features. Browse the asset table, choose an asset, and inspect its details without
leaving the app.
Other asset types are browsable and expose supported metadata APIs, but do not
have SQL/XMLA connectors in this version.

## Developer and Admin views

The sidebar **Admin view** toggle defaults to off (**Developer view**).
The expanded capabilities list explains the available scope and prerequisites.
This changes which UI/API surfaces are enabled; it does not impersonate a different
user, downgrade/elevate the CLI identity, or grant additional permissions.

| Surface | Developer view | Additional Admin view capabilities |
| --- | --- | --- |
| Catalog | Items discoverable by the CLI identity; filter by workspace/item | Same permission-scoped catalog, not an unrestricted tenant inventory |
| Overview | Item/workspace metadata, endpoint properties where supported | Same |
| Tables and queries | OneLake schemas/tables/columns, read-only SQL or XMLA subject to data permissions | Same; tenant admin does not automatically grant data access |
| Permissions | Workspace role assignments (Member/Admin required) | Selected-item access details through the preview Admin API |
| Lineage | Item source connections (the read API can require item Write permission) | Explicit metadata scan of the selected workspace |
| Monitor | Supported job history or semantic-model refresh history | Same; no refresh/job execution buttons |
| Domains | Core domain metadata with Domain.Read.All | Admin domain listing and domain-workspace assignments |

Admin calls require the actual Fabric tenant-administrator role and delegated
`Tenant.Read.All` consent. Enabling the toggle alone verifies neither. Developer
view does not call tenant-admin APIs or display cached admin-only results.
Permissions are API-reported assignments, **not** a complete effective-access
calculation; nested groups, item shares, OneLake policies, SQL grants and RLS/OLS
can differ.

The lineage scanner uses the Power BI audience, requests metadata only for the
selected workspace, and never modifies its artifacts. Opening **Lineage** in
Admin view starts the metadata scan, checks its status automatically and displays
the results after success. Switch between **Graph** and **Table**, choose
**Upstream & downstream**, **Upstream**, **Downstream**, or **Workspace** scope,
and filter by name/type/location or item type without rescanning. The graph uses
item names/types, locally bundled official Fabric icons on every card, and
highlights the selected item. Unknown types use the official generic icon.
Scanner aliases such as `warehouses` and SQL analytics endpoints use the
warehouse icon. The graph supports drag-to-pan, zoom, Fit, Full screen and
keyboard navigation (+/- to zoom, arrows to pan, Home to fit).
The table shows names, types,
upstream/downstream relation, location, metadata modification time, endorsement,
sensitivity-label IDs and item/workspace IDs where returned. Modification time
is not a data refresh timestamp. Unresolved cross-workspace items retain their
IDs instead of being matched by name.

The graph pane is a locally served Streamlit component using pinned
`@viz-js/viz` 3.31.0 (Graphviz WebAssembly), because the native Streamlit chart
does not expose image registration. No system Graphviz installation, runtime
CDN, new Python dependency, or external transfer of lineage data is required.
Icon bytes remain original SVGs. Renderer integrity hashes, package metadata,
build provenance and third-party licenses are retained in
`assets/lineage-chart/`. The component has a restrictive content-security policy
and resolves icons to bundled data URIs before displaying the graph. Graph
labels use Arial, whose layout metrics are supported by the bundled renderer.
Non-fatal renderer warnings are shown separately without hiding a successful
graph; rendering failures remain explicit errors.

Polling is bounded to 10 checks with one-second
intervals and a 20-second polling budget (network requests have their own
timeouts). Failed or still-running scans show an explicit error; **Refresh tab**
resumes a pending scan or starts a new scan after completion/failure. Cached
results/errors prevent new scans on unrelated
rerenders. Terminal scan cleanup is idempotent and does not remove a newer
pending scan. Detailed model schema requires tenant metadata-scanning settings.

Edges are extracted only from relationships actually returned: legacy Power BI
dataset/dataflow/source/tile links and Fabric item collections' `relations`
(`dependentOnArtifactId`, `workspaceId`, `relationType`). Live responses can
include Lakehouses, SQL analytics endpoints, notebooks, pipelines, ontologies
and other Fabric types. Arrows run from a reported dependency to the dependent
item. The original relationship type is retained: **Association**,
**WeakAssociation** and **CascadeDelete** are dependencies, not proof of data
movement or notebook execution. **Reported relationship details** exposes edge
names, types and IDs.

The public scanner's coverage can differ from Fabric's native portal; missing
items/edges do not prove that no dependencies exist. This is item-level lineage,
not table/column lineage or a complete cross-workspace impact analysis. Use
**Open workspace in Fabric**, then the workspace's Lineage view, for the portal
experience (browser sign-in is separate from Azure CLI). Source connections are
shown separately under **Source connection bindings (not lineage)** and never
treated as a complete lineage graph. Raw scan metadata is available in Admin view.
Governance/catalog metadata can lag; timestamps describe retrieval, not source
freshness.

Monitor shows semantic-model refresh history (up to 100 entries) or supported
Fabric scheduler job history, typically up to 100 completed runs. It is not
complete usage telemetry, SQL query history or real-time capacity/CU monitoring.
Domain assignments are organizational metadata, not access controls.

## Connection choices

- **SQL endpoint** resolves the SQL hostname from Fabric metadata and verifies a
  SQL connection before showing the read-only T-SQL editor and row results.
- **Table API** verifies a REST connection by listing schemas using the OneLake
  Delta metadata API. Choose a schema, select **List tables**, choose a table, then
  **Inspect table** to see column metadata. It uses the actual item GUID, not the
  Lakehouse SQL analytics endpoint GUID. API pagination is followed automatically.
- **XMLA / DAX** verifies an actual XMLA connection to the selected semantic model
  with a constant DAX query before displaying the DAX editor. It does not use a
  REST executeQueries fallback. It requires a supported Fabric/Power BI capacity,
  XMLA enabled (read-only is sufficient), and semantic-model Build/read access.
  XMLA uses the Power BI token audience rather than the Fabric or SQL audience.
  The workspace URL uses the documented `Workspace Name - GUID` disambiguation,
  URI-encoded. The catalog uses the model's friendly name: GUID-only catalogs
  returned `PowerBIEntityNotFound` during live testing. Duplicate model names may
  require their exact XMLA catalog names from SSMS rather than a guessed suffix.
  The query-only bridge and its Python wrapper both reject XMLA command XML,
  DDL and multiple result sets. They do not downgrade the CLI user's underlying
  permissions or establish a server-enforced read-only session; using a capacity
  with XMLA set to Read Only is recommended.
- Table API authentication uses the `https://storage.azure.com/.default` audience;
  SQL and Fabric REST use their separate token audiences. OneLake table read
  permissions may differ from SQL permissions, so one connection can work while
  the other returns an authorization error.
- This version's Table API connector is **metadata-only**. It does not retrieve
  table rows, issue SQL through REST, or implement the separate preview `/read`
  and Arrow `/readStream` APIs. Use SQL for row queries in this version.

## Identity and permissions

- Uses `AzureCliCredential`, never a service account, SQL password, or app secret.
  Fabric API and SQL tokens use separate audiences and are acquired as needed.
- The integrated catalog and SQL connections both use the Azure CLI account.
  After changing CLI accounts, use **Reset session / changed CLI account**.
- The sidebar automatically checks CLI account metadata and acquires a Fabric
  token, then displays **Signed in through Azure CLI**, username, tenant ID, and
  account type. Status is rechecked near token expiry or when you reset the session.
  No passwords or tokens are displayed. Token availability does not prove asset
  permissions or that the browser portal is signed in.
- No Fabric website sign-in is required for this app. If you independently visit
  the Fabric website, it uses separate browser cookies; CLI tokens do not sign
  that website in.
- Catalog search requires the delegated `Catalog.Read.All` scope. Tenant policy or
  missing consent may block the Azure CLI client. Endpoint metadata also requires
  permission to read the selected Warehouse or Lakehouse through Fabric REST APIs.
  Ask your administrator if these requests return 401/403; no permission bypass
  or discovery fallback is attempted.
- Seeing an asset in the catalog does **not** establish permission to query its
  data. SQL access, row-level security, column-level security, and other endpoint
  controls are enforced by Fabric under your identity.
- Use a SQL principal with only the required read permissions. SQL parsing blocks
  common write statements and SELECT INTO, but is **not a security sandbox**.
  Connections are never committed and are closed after each operation.
- Do not deploy this version as a shared service. Every visitor would otherwise
  use the host's Azure CLI account. Multi-user hosting needs per-user Entra sign-in
  and delegated tokens instead.
- Tokens are not displayed, persisted to files, or put in connection strings.
  Results remain in the local Streamlit session; CSV downloads may contain
  sensitive data. Restarting/resetting the session clears in-app results.

## Limits and troubleshooting

- SQL requires outbound TCP 1433 and an active Fabric capacity/endpoint.
- Connections use TLS with certificate validation, a 15-second login timeout,
  and a 60-second SQL query timeout.
- A query fetches at most the selected row limit plus one row to detect truncation
  (maximum display limit: 10,000). This caps retrieval, **not server-side work**:
  use `TOP`, filters, and aggregation for large tables.
- Duplicate or unnamed result columns get unique display labels so they can be
  rendered and exported without losing values.
- Catalog results are paged at 100 entries. Indexing can lag behind item changes,
  and the API does not cover every Fabric item type (including Dataflows).
- Lakehouse SQL provisioning must report `Success` before connecting.
- This version targets the public Fabric cloud only.
- **Live XMLA limitation:** the bridge builds successfully and guardrails are
  tested, but constant DAX probes against three discovered models failed with
  `AdomdConnectionException` / `0x80131500` ("Authentication failed for all
  authenticators"). The models were on an active F8 capacity, and Power BI REST
  authentication succeeded. This does not identify a specific tenant policy or
  prove XMLA is enabled. Check the capacity and tenant XMLA settings, model
  Read/Build access and licensing. Sanitized XMLA exception/activity diagnostics
  are shown in the app; no REST fallback or permission bypass is attempted.
- Azure CLI sign-in and token errors, API errors, and SQL errors are shown in the
  UI. For throttling, wait for the displayed retry interval and try again.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use fake credentials, HTTP responses, and SQL/XMLA connections. When the
bridge is built, additional tests execute its input guardrails without connecting
to a tenant. They do not require your tenant or change any Fabric data.

## References

- [OneLake catalog REST API overview](https://learn.microsoft.com/rest/api/fabric/articles/onelakecatalog/overview)
- [Catalog Search API](https://learn.microsoft.com/rest/api/fabric/core/catalog/search)
- [Get Warehouse metadata](https://learn.microsoft.com/rest/api/fabric/warehouse/items/get-warehouse)
- [Get Lakehouse metadata](https://learn.microsoft.com/rest/api/fabric/lakehouse/items/get-lakehouse)
- [OneLake Table API overview](https://learn.microsoft.com/fabric/onelake/table-apis/table-apis-overview)
- [OneLake Delta metadata API](https://learn.microsoft.com/fabric/onelake/table-apis/delta-table-apis-overview)
- [Core item metadata](https://learn.microsoft.com/rest/api/fabric/core/items/get-item)
- [Workspace role assignments](https://learn.microsoft.com/rest/api/fabric/core/workspaces/list-workspace-role-assignments)
- [Admin item access details (preview)](https://learn.microsoft.com/rest/api/fabric/admin/items/list-item-access-details)
- [Fabric item job history](https://learn.microsoft.com/rest/api/fabric/core/job-scheduler/list-item-job-instances)
- [Core domains](https://learn.microsoft.com/rest/api/fabric/core/domains/list-domains)
- [Admin workspace metadata scanner](https://learn.microsoft.com/rest/api/power-bi/admin/workspace-info-post-workspace-info)
- [XMLA endpoint prerequisites and addressing](https://learn.microsoft.com/fabric/enterprise/powerbi/service-premium-connect-tools)
