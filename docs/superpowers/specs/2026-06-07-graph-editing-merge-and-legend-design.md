# Editable, durable company graph — merge imports, manual edit, canvas legend — Design

- **Date:** 2026-06-07
- **Status:** Approved
- **Builds on:** the company knowledge-graph feature (Phase A + Phase B viz), the company-rooted
  graph explorer, and the **external ontology import** feature — all merged to `master`. Reuses
  `KnowledgeGraph`/`GraphEdge`/`NodeMeta`, the import overlay store (`graph_imported:*`), the
  user-saved store (`graph_user_saved:*`), the Discover board (`ScreenBoard` of `StockScore`, which
  carries `name`), and the `/graph` page (`GraphCanvas`/`GraphSidebar`/`pages/Graph.tsx`/
  `lib/graphView.ts`). Parent specs: `2026-06-07-graph-ontology-import-design.md`,
  `2026-06-06-company-rooted-graph-explore-design.md`.

## Overview

Three connected gaps in the graph explorer, all about making a **company graph a single, durable,
editable artifact the user owns**:

1. **Imports don't persist into a saved graph.** Today an import lives only in the global overlay
   (`graph_imported:*`) and is blended into the view at render time. **Save** persists only the
   `working` graph, so imported edges *look* saved but aren't — deleting the import set removes them
   everywhere, including from company graphs the user saved earlier. This is real data loss.
2. **No manual editing.** The user can't add or delete their own nodes/relationships.
3. **No on-canvas legend.** Colour meaning lives only in a small sidebar hint.

This feature adds: a **"Merge into graph"** action with a **conflict-resolution preview** (links
imported companies to the Discover list, collapses clashing nodes, persists on Save); **right-click
add/delete** of nodes and relationships via a side-panel form; and a **collapsible canvas legend**.
It also fixes the **Copy-prompt target** so imports can iteratively expand any selected node.

Same posture as the rest of the app: **decision support, not financial advice.** Manual/merged
edits live in the per-company saved graph and do **not** feed the global Discover/Dashboard scores
(only the existing global import overlay does — unchanged).

## Locked decisions

| Decision | Choice |
|---|---|
| Import → saved graph | **"Merge into graph" button** per import-set row. Global sets + the score overlay are untouched (still feed scores). Merge bakes a set into the `working` graph so **Save** persists it; the user may then delete the global set and keep the data. |
| Merge conflicts & linking | **Preview with manual linking.** Same-ticker nodes auto-merge (the real ticker keeps identity). Imported externals get a suggested Discover ticker (editable dropdown, or keep external). Duplicate relationships keep the existing one by default, with a *use imported* toggle. Apply → commits to `working`; Save persists. |
| Linking authority | **The Discover board.** Reconciliation matches imported node labels against `StockScore.name`/`ticker` already loaded on the page — all frontend, no new resolver. |
| Manual add/delete | **Right-click → side-panel form.** Right-click node → *Add relationship* / *Delete node*; right-click edge → *Delete relationship*. New nodes are created as relationship targets (ticker, Discover company, or `man:<slug>` concept). |
| Provenance | `GraphEdge.origin` gains `"manual"`; `NodeMeta.source` gains `"manual"`. Edge style encodes origin (solid / dashed / dotted). |
| Manual/merged scoring | **Exploration-only.** Manual edits and merged-in edges live in the saved company graph; they do not feed `apply_network`. (Consistent with the merge choice; the global overlay remains the scoring path.) |
| Iterative imports | **Copy-prompt follows the selected node.** The Import tab targets the selected node (fallback root), so selecting NVDA copies an NVDA prompt → import → merge → NVDA expands onto its existing node. |
| Legend | **Collapsible on-canvas overlay.** Replaces the duplicate colour line in the sidebar empty-state. |
| Persistence | Edits mutate `working` (already auto-restored via `explorerStore` localStorage). **Save** stays the durable backend version. A subtle **"unsaved changes"** hint signals when a Save is due. |

## Why merge-time reconciliation (the load-bearing decision)

Imports already resolve entities to tickers at import time via `TickerResolver` (by symbol or
normalised name); anything unmatched becomes an `ext:<slug>` node. The clash the user hit happens
**when an import meets an existing working graph**:

- **Same id** (`NVDA` ↔ `NVDA`): `mergeGraph` already unions by id — but today `node_meta` lets the
  *later* graph win, which could relabel a real ticker as an imported node. Fix: on merge, **existing
  node_meta wins** so a ticker keeps its native identity (board colour/score/Dashboard link).
- **Same company, different id** (`NVDA` ↔ `ext:nvidia`): two nodes for one company. The importer
  couldn't match the name. The page already holds the **full Discover board with names**, so the
  merge can *suggest* `ext:nvidia → NVDA` and let the user confirm — collapsing them onto one node.
- **Duplicate relationship** (same `source,target,type`, different `sentiment`/`weight`): a genuine
  attribute conflict; the user chooses keep-existing (default) or use-imported.

Doing this **at merge time, in the frontend, with a preview** (rather than silently at import, or
via a heavyweight backend merge) is the load-bearing choice: the working graph is frontend state,
the Discover list is already loaded there, and the user gets to resolve ambiguous links explicitly.
Reconciliation is implemented as **pure, unit-tested functions** so the canvas/UI stay thin.

## Data model (`app/models/schemas.py` + `frontend/src/types.ts`) — additive

```python
class NodeMeta(BaseModel):
    label: str = ""
    kind: str = ""
    source: Literal["native", "imported", "manual"] = "native"   # + "manual"

class GraphEdge(BaseModel):
    ...
    origin: Literal["extracted", "imported", "manual"] = "extracted"   # + "manual"
```

```ts
export interface NodeMeta { label: string; kind: string; source: 'native' | 'imported' | 'manual'; }
export interface GraphEdge {
  ...
  origin?: 'extracted' | 'imported' | 'manual';
}
```

Backward-compatible: a new `Literal` member only *adds* a value; all existing saved graphs,
snapshots, and import sets deserialize unchanged. A **manual edge** is built with
`confidence 0.9` (user-asserted), `weight 0.5`, `sentiment` = the chosen Effect, `evidence` = the
optional note, `url` = "", `as_of` = now (ISO), `origin "manual"`. A **manual concept node** uses id
`man:<slug>` with `node_meta { label, kind: "concept", source: "manual" }`.

## Merge reconciliation (`frontend/src/lib/graphMerge.ts`, new, pure)

```ts
export interface MergeLinkRow {
  importId: string;            // import-set node id, e.g. 'ext:nvidia' or 'NVDA'
  label: string;               // display label (node_meta label or id)
  external: boolean;           // ext:/man: or has imported node_meta
  suggestion: string | null;   // suggested ticker (Discover/working match) or null
  resolved: string;            // current choice: a ticker id, or importId to keep-as-is
}

export interface MergeSummary {
  addedNodes: number;
  addedEdges: number;
  duplicates: number;          // (s,t,type) edges present in both
  linked: number;              // import nodes re-pointed to a ticker
  merged: number;              // import tickers already present in working (auto-merge)
}

export type DupPolicy = 'keep' | 'import';

export function normalizeName(s: string): string;       // modelled on backend _normalize
export function planMerge(
  working: KnowledgeGraph, importSet: KnowledgeGraph, board: StockScore[],
): { links: MergeLinkRow[] };
export function applyMerge(
  working: KnowledgeGraph, importSet: KnowledgeGraph,
  resolved: Record<string, string>, opts: { dupPolicy: DupPolicy },
): { graph: KnowledgeGraph; summary: MergeSummary };
```

**`normalizeName`** — lowercase → strip suffix words (`inc|corp|corporation|co|ltd|plc|company|
companies|holdings|group|the|class [abc]`) → drop non-`[a-z0-9 ]` → trim. Applied to **both** the
import label and each board `name`, so internal consistency (not byte-parity with the backend) is
what matters.

**`planMerge`** — builds the editable scaffold:
- board maps: `ticker.toUpperCase() → ticker` and `normalizeName(name) → ticker`; plus a working-node
  label/id set.
- For each import node id: if it's an `ext:`/`man:` (external) node, emit a `MergeLinkRow` with
  `suggestion` = board name/symbol match, else a working-node label match, else `null`; default
  `resolved = suggestion ?? importId` (keep external). Import nodes that are already tickers need no
  row (they merge or add directly).

**`applyMerge`** — pure; used live for the preview counts *and* for the final commit:
1. `linkMap[id] = resolved[id] ?? id`.
2. Rewrite the import set through `linkMap`: nodes mapped + de-duped; `node_meta` re-keyed (drop the
   entry when the new key is a ticker — it adopts board identity); edges' `source`/`target`
   remapped, self-loops dropped, de-duped by `(s,t,type)`.
3. Union into `working`: nodes unioned (`addedNodes` = new ones); **node_meta — working wins on
   clash** (`{...importMeta, ...workingMeta}`); edges — index working by `(s,t,type)`; each import
   edge that collides is a `duplicate` (replace attributes iff `dupPolicy==='import'`, keeping
   `origin`), else appended (`addedEdges`). `linked` = rows re-pointed to a ticker; `merged` = import
   tickers already in working.
4. Returns the merged `KnowledgeGraph` (keeps working's `scope`/`as_of`) + the `MergeSummary`.

## Manual edit helpers (`frontend/src/lib/graphView.ts`, pure additions)

```ts
export function resolveManualTarget(
  input: string, graph: KnowledgeGraph, board: StockScore[],
): { id: string; label: string; external: boolean; isNew: boolean };
export function addManualEdge(graph: KnowledgeGraph, edge: GraphEdge): KnowledgeGraph;
export function addManualNode(graph: KnowledgeGraph, meta: { id: string; label: string; kind?: string }): KnowledgeGraph;
export function deleteNode(graph: KnowledgeGraph, id: string): KnowledgeGraph;
export function deleteEdge(graph: KnowledgeGraph, ref: { source: string; target: string; type: RelationType }): KnowledgeGraph;
```

- **`resolveManualTarget`** (same linking philosophy as merge): existing node (id case-insensitive or
  label match) → reuse; else board match (symbol or `normalizeName`) → that ticker; else a tickerish
  symbol (`^[A-Z0-9.\-]{1,10}$`, upper-cased) → ticker node; else concept node `man:<slug>` with a
  label. `isNew` flags whether the node must be created.
- **`addManualEdge`** — appends `edge` (origin `"manual"`), creating any missing endpoint node
  (+`node_meta` for `man:`/`ext:` ones); de-dupes by `(s,t,type)` (existing edge kept).
- **`deleteNode`** — removes the node, its `node_meta`, and every incident edge.
- **`deleteEdge`** — removes exactly the matching `(s,t,type)` edge.

## Canvas legend (`frontend/src/components/GraphLegend.tsx`, new)

A small, **collapsible** overlay absolutely positioned in a corner of `.graph-canvas`
(semi-transparent, panel-styled; collapse state in component `useState`, default expanded):

- **Nodes (colour = call):** buy `#3fb950` · sell `#f85149` · hold `#8b949e` · unknown `#484f58` ·
  external/concept `#6e7681`. Size = opportunity score.
- **Edges (colour = news effect):** positive `#3fb950` · negative `#f85149` · neutral `#6e7681`.
- **Edge style (source):** solid = from news (`extracted`) · dashed = imported · dotted = manual.

The duplicate colour line in `GraphSidebar`'s empty-state is removed (the "Click a node…" hint
stays).

## Context menu (`frontend/src/components/GraphContextMenu.tsx`, new)

A generic absolutely-positioned menu: `{ items: {label, onClick, danger?}[], x, y, onClose }`.
Closes on outside-click / Escape. `GraphCanvas` opens it from
`onNodeRightClick(node, e)` → *Add relationship*, *Delete node*; and
`onLinkRightClick(link, e)` → *Delete relationship*. Each handler calls `e.preventDefault()`; the
canvas wrapper also sets `onContextMenu={e => e.preventDefault()}` to suppress the browser menu.
Menu items invoke callbacks supplied by `pages/Graph.tsx`.

## Merge preview (`frontend/src/components/MergePreview.tsx`, new)

Rendered in the **Import** tab while a merge is pending. Given `working`, the fetched `importSet`,
and `board`, it runs `planMerge` once for the link rows, then calls `applyMerge` **live** on every
change to show counts and to produce the graph that *Apply* commits:

- **Link list** — one row per external import node: label + a `<select>` (suggestion preselected;
  options = *keep external* + Discover companies, searchable by typing in a filter input).
- **Summary** — "+N nodes, +M edges · K linked · J already in graph · D duplicate relationships".
- **Duplicate policy** — a two-option toggle: *keep mine* (default) / *use imported*.
- **Apply** → `onApply(merged.graph)`; **Cancel** → `onCancel()`.

## Page wiring (`frontend/src/pages/Graph.tsx`)

New state: `mergeSetId: string | null` + `mergeImport: KnowledgeGraph | null` (the fetched set),
`addingFrom: string | null` (relationship-form source), `dirty: boolean` (unsaved edits). Handlers:

- `startMerge(id)` → `await client.getImportSet(id)` → set `mergeSetId`/`mergeImport` (Import tab
  shows `MergePreview`). `applyMerge` result commits via `setWorking`; `setDirty(true)`; clear merge
  state.
- `addRelationship(sourceId)` (from context menu) → `setAddingFrom(sourceId)`, focus the form.
- Form submit → `resolveManualTarget(input,…)` → build the manual `GraphEdge` → `setWorking(
  addManualEdge(working, edge))`; `setDirty(true)`; `setAddingFrom(null)`.
- `removeNode(id)` → confirm if it has incident edges → `setWorking(deleteNode(working,id))`; if
  `selectedId===id` clear it; `setDirty(true)`.
- `removeEdge(ref)` → `setWorking(deleteEdge(working,ref))`; `setDirty(true)`.
- `dirty` reset on successful `doSave`, `doLoadSaved`, `loadRoot`, `clearGraph`.
- **Prompt target fix:** pass `promptDefault={selectedId || root || ''}` (selected wins). The Import
  tab also shows an editable **target** field bound to that value, used by *Copy ChatGPT prompt*.

## API (`app/api/routes.py` + `app/network/store.py`)

| Method + path | Returns | Notes |
|---|---|---|
| `GET /api/graph/imports/{set_id}` | `KnowledgeGraph` | The chosen set's graph, for merging. 404 if unknown. |

```python
# store.py — expose the existing private loader
def load_import_graph(set_id: str, cache: Cache) -> KnowledgeGraph | None:
    loaded = _load_import_set(set_id, cache)
    return loaded[1] if loaded else None
```

No other backend changes — all merge/manual logic is frontend. (`POST/GET/DELETE /graph/imports`,
scoring, and `effective_graph` are untouched.) `api/client.ts` gains
`getImportSet(id): Promise<KnowledgeGraph>`; no new TanStack hook (called on demand in `startMerge`).

## Data flow

```
Merge:  click "Merge into graph" on set row
        -> client.getImportSet(id)  (GET /api/graph/imports/{id})
        -> MergePreview: planMerge(working, set, board.items) -> link rows
        -> user adjusts dropdowns / dup policy; applyMerge(...) recomputes summary live
        -> Apply -> setWorking(merged.graph); dirty=true
        -> Save (existing) -> POST /api/graph/saved -> durable version (imports now baked in)
        -> user may DELETE the global set; the saved graph keeps the data
Iterate: select NVDA -> Copy prompt (NVDA) -> ChatGPT -> Import (new set)
        -> Merge into graph -> reconciliation merges onto the existing NVDA node
Manual: right-click node -> Add relationship -> form -> resolveManualTarget -> addManualEdge -> dirty
        right-click node/edge -> Delete -> deleteNode/deleteEdge -> dirty
View:   GraphCanvas colours nodes by call / external; edges by sentiment; style by origin
        GraphLegend overlay explains the colours
```

## Error handling / states

- **Unknown set on merge:** `getImportSet` 404 → inline "Couldn't load that set." in the Import tab;
  no preview.
- **Empty working graph:** merging with nothing loaded simply makes the reconciled import the working
  graph (no clashes; linking still applies).
- **No suggestion for an external node:** dropdown defaults to *keep external*; the node merges in as
  a grey `ext:` node (unchanged behaviour) — never silently dropped.
- **Manual target ambiguity:** `resolveManualTarget` is deterministic and documented; typing a full
  company name that isn't an exact Discover match yields a `man:` concept node (the user can instead
  type the symbol). No fuzzy guessing → no wrong-company links.
- **Delete with edges:** `removeNode` confirms before removing a node that has incident edges.
- **Duplicate relationship on merge:** never both kept — policy decides; counted in the summary (no
  silent loss).
- **Unsaved edits:** the `dirty` hint makes the durable-Save step explicit; edits still survive
  reload via `explorerStore` even before Save.

## Testing (TDD, repo-consistent)

**Backend**
- `store.load_import_graph` returns a stored set's graph; `None` for unknown.
- route `GET /api/graph/imports/{id}` returns the graph (200) / 404 (unknown), using
  `app.dependency_overrides[get_cache]` + a tmp `Cache` (as in `test_api_graph.py`).
- schema round-trip: `GraphEdge(origin="manual")` and `NodeMeta(source="manual")` validate; existing
  fixtures still deserialize.

**Frontend (`lib/graphMerge.test.ts`)**
- `normalizeName` strips suffixes/punctuation consistently.
- `planMerge`: external node with a board-name match gets the right `suggestion`; a pure ticker node
  yields no row; no match → `suggestion: null`.
- `applyMerge`: same-ticker auto-merge keeps native `node_meta` (no downgrade); `ext:→ticker` link
  re-points edges and drops the `ext:` node/meta; duplicate `(s,t,type)` honours `keep` vs `import`;
  self-loops from linking are dropped; counts in `MergeSummary` are correct.

**Frontend (`lib/graphView.test.ts`)**
- `resolveManualTarget`: existing-node reuse; board symbol/name → ticker; tickerish → ticker node;
  free text → `man:<slug>`.
- `addManualEdge` creates missing endpoints + `origin "manual"` and de-dupes; `addManualNode` adds
  `man:` meta; `deleteNode` removes incident edges + meta; `deleteEdge` removes only the match.

**Frontend (components)**
- `GraphLegend.test.tsx`: renders the colour/style keys; collapse toggle hides/shows the body.
- `GraphContextMenu.test.tsx`: renders items; click fires `onClick`; outside-click/Escape `onClose`.
- `MergePreview.test.tsx`: link rows render with preselected suggestions; changing a dropdown updates
  the summary; *Apply* calls back with the merged graph; dup-policy toggle flips the count.
- `GraphSidebar.test.tsx` (extend): add-relationship form submits a correct edge; *Copy ChatGPT
  prompt* uses the selected-node target.

## Build order

1. **Schemas** — `origin += "manual"`, `NodeMeta.source += "manual"` (backend) + `types.ts` mirror.
2. **`store.load_import_graph`** + `GET /api/graph/imports/{id}` route + backend tests.
3. **`api/client.ts`** `getImportSet` + client test.
4. **`lib/graphView.ts`** manual helpers + `resolveManualTarget` + tests.
5. **`lib/graphMerge.ts`** `normalizeName`/`planMerge`/`applyMerge` + tests.
6. **`GraphLegend`** + **`GraphContextMenu`** components + tests; mount legend in `GraphCanvas`,
   wire right-click handlers + manual/imported link dashing + external node styling.
7. **`MergePreview`** component + test.
8. **`GraphSidebar`** — add-relationship form, *Merge into graph* button per set row, target field,
   drop the duplicate legend line + tests.
9. **`pages/Graph.tsx`** — wire merge/manual/dirty state, prompt target, `MergePreview` in Import tab.
10. **`styles.css`** — context menu, legend overlay, merge preview, relationship form, unsaved hint.
11. Final: `pytest` + `npm run build` (`tsc -b`) + `npx vitest run` green; live browser smoke
    (isolated temp `DATA_DIR`, back up + restore the real cache — same protocol as prior graph
    phases). Note: `npx tsc --noEmit` is a no-op here; the type gate is `tsc -b` (via `npm run
    build`).

## Caveats

- **Manual/merged edges don't move global scores.** By design they live in the per-company saved
  graph, not the focus snapshot/overlay that `apply_network` reads. The existing global import sets
  remain the way to influence Discover/Dashboard scores.
- **Linking is name/symbol-exact, not fuzzy.** Auto-suggestions only fire on an exact normalised
  match; everything else is a manual dropdown choice — deliberately, to avoid wrong-company links.
- **Reconciliation duplicates a little normalisation logic** in JS (`normalizeName`) rather than
  calling the backend `TickerResolver`. Accepted: the board (with names) is already on the page, and
  both sides of the match use the same JS function.
- **Save is still explicit.** Edits auto-survive reload (localStorage) but only **Save** writes a
  durable backend version; the `dirty` hint mitigates surprise. (Auto-save-on-edit is a possible
  later toggle — YAGNI now.)
- **Local only.** Saved graphs and import sets live in the same SQLite cache DB; not synced/exported.
