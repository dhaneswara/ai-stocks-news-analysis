# Company-Rooted Graph Explorer (build-from-a-company, expand, save/load) — Design

- **Date:** 2026-06-06
- **Status:** Approved
- **Builds on:** the company knowledge-graph feature (Phase A backend + Phase B viz, both merged
  to `master`). Reuses the cached extraction unit `extract_relationships` (one company, cached per
  ticker/day), the `KnowledgeGraph`/`GraphEdge` schemas, the SQLite `Cache`, and the existing
  `/graph` page (`GraphCanvas`/`GraphSidebar`/`lib/graphView.ts`). Parent specs:
  `2026-06-06-company-knowledge-graph-design.md`, `2026-06-06-company-knowledge-graph-phase-b-viz-design.md`.

## Overview

Today the graph is built as a single **flat batch** over a fixed focus set (watchlist ∪ top-N
board names) and the `/graph` page renders that one snapshot. This feature adds an **interactive,
company-rooted explorer**: type a root company, see its direct neighbours, then **click any node
to expand it one hop** — growing the subgraph outward on demand. You can **save** the explored
subgraph (keyed by root company, with a short version history) and **load** it back later.

The atomic LLM unit already exists — `extract_relationships` is *one company, cached per
ticker/day* — so a single primitive ("ego graph for ticker X") powers **both** rooting and
expanding. Expansion is cheap: free when that company was already extracted today, otherwise one
LLM call. The frontend accumulates the explored subgraph in state; the backend stays stateless.

This is a **pure research / visualization tool**. It **never** changes the Discover board's
BUY/SELL/HOLD — the scheduled daily focus-graph build remains the sole signal source. Nodes still
*show* their current direction/score (from the board) and any existing network signal. Same
**decision support, not financial advice** posture as the rest of the app.

## Locked decisions

| Decision | Choice |
|---|---|
| Expansion model | **Manual on-demand.** Type a root → one-hop ego graph; select a node → "Expand neighbours" → fetch + merge its one-hop ego graph. Cache-aware (free if extracted today). |
| Save/load model | **Per-company with version history.** Keyed by root ticker; keep the **last 5** versions; saving appends (newest-first), each version captures the **full explored subgraph** + which nodes were expanded. |
| Signal coupling | **Pure research view.** Exploring/saving never alters the board signal; the daily focus-graph keeps driving buy/sell. Nodes still show current direction/score. |
| Coexistence | **Coexist** with the daily batch build (it still powers the signal). `/graph` evolves into the explorer; "Load focus set" keeps the daily snapshot viewable. |
| Backend statefulness | **Stateless.** Backend exposes a per-ticker ego-graph primitive + saved-graph CRUD; the in-progress exploration lives only in frontend state until saved. |
| Persistence | New `graph_user_saved:<ROOT>` keys, **long TTL (~10y)**, distinct from the 7-day `graph_snapshot:` so user saves never collide and don't auto-expire. |
| Expand affordance | A **sidebar button** on the selected node (double-click on canvas is a possible later add). |

## Architecture

### Backend

**`build_company_graph(ticker, settings, cache, *, now=None) -> KnowledgeGraph`** — new function in
`app/network/service.py`, alongside the existing `build_graph`:

```
ticker (e.g. "TSLA")
  -> resolve provider/model + TickerResolver(load_universe())   (degrade -> empty graph on failure)
  -> get_stock_data(ticker, NETWORK_PERIOD, ...)                 (cached; news included)
  -> extract_relationships(stock, resolver, provider, model, ...) (cached per ticker/day)
  -> KnowledgeGraph(scope="company:<TICKER>",
                    nodes = sorted({ticker} ∪ {e.target}),
                    edges = those edges, built=1/skipped per try/except)
```

Mirrors `build_graph`'s degrade philosophy: any provider/settings/universe failure → empty graph;
a per-ticker `try/except` so a bad name returns an empty fragment rather than raising. **This one
primitive serves both "start from company" and "expand a node"** (expanding node Y = calling it for Y).

**Saved-graph store** — new functions in `app/network/store.py` (separate key prefix from the
auto snapshot):

```
save_company_graph(version, cache)      # append newest-first to graph_user_saved:<ROOT>, cap 5; update index
load_company_graph(root, cache, version=None) -> SavedGraphVersion | None   # latest if version None
list_saved_graphs(cache) -> list[SavedGraphSummary]   # [{root, versions:[{saved_at}]}] via index key
delete_saved_graph(root, cache, version=None) -> bool  # delete one version or the whole root
```

- Key `graph_user_saved:<ROOT>` → JSON list of `SavedGraphVersion` (newest first, max 5).
- Key `graph_user_saved:__index__` → JSON list of roots that have saves (kept in sync on save/delete).
- TTL = `_USER_SAVE_TTL_SECONDS = 3650 * 24 * 60 * 60` (~10y). (`Cache.set` requires a TTL; this
  is effectively permanent and clearly distinct from the 7-day snapshot.)

### Schemas (`app/models/schemas.py`)

```python
class SavedGraphVersion(BaseModel):
    root: str
    saved_at: str                       # ISO; passed in by the route (now), not generated in tests
    expanded: list[str] = []            # tickers the user explicitly expanded (for UI restore/labeling)
    graph: KnowledgeGraph               # the full accumulated subgraph (nodes + edges)

class SavedGraphSummary(BaseModel):     # for the list endpoint
    root: str
    versions: list[str] = []            # saved_at timestamps, newest first
```

### Frontend (`/graph` becomes the explorer)

- **Working state** = an accumulated `KnowledgeGraph` (nodes + edges) held in React, seeded by a
  root load and grown by expands; plus `expandedIds: Set<string>` and the current `root`.
- **`lib/graphView.ts`** gains a pure **`mergeGraph(into, fragment) -> KnowledgeGraph`**: union of
  nodes; edges deduped by `(source,target,type)`. All existing helpers
  (`mergeNodes`/`toLinks`/`applyFilters`/colour+size) are reused unchanged.
- **`GraphSidebar`** gains: a **root input** ("Start from company"), an **Expand neighbours**
  button on the selected node, **Save** / **Load** controls, a **saved-graphs list** (roots) with
  a **version dropdown**, and a **"Load focus set"** button (seeds working state from the daily
  `GET /api/graph` snapshot). The existing sector + edge-type filters and selected-node detail stay.
  The existing **Rebuild graph** (focus snapshot, LLM) button is **retained** as a secondary action
  — it still refreshes the daily signal source; "Load focus set" then pulls that snapshot in.
- **`GraphCanvas`** is unchanged (still mocked in tests).

## Data flow

```
Root:   type TSLA -> egoGraph.mutateAsync("TSLA") GET /api/graph/company/TSLA
                  -> working = fragment; root="TSLA"; expanded={}
                  -> mergeNodes(working, board) + toLinks + applyFilters -> GraphCanvas
Expand: select NVDA -> "Expand neighbours" -> GET /api/graph/company/NVDA
                    -> working = mergeGraph(working, fragment); expanded += NVDA -> re-render
Save:   POST /api/graph/saved {root, expanded:[...], graph: working}
                    -> appended to graph_user_saved:TSLA (cap 5)
Load:   pick root (+version) -> GET /api/graph/saved/TSLA?version=<saved_at>
                    -> working = saved.graph; root/expanded restored -> re-render
Focus:  "Load focus set" -> GET /api/graph -> working = daily snapshot (existing behaviour)
```

`useScreen(undefined, undefined, 0)` (full uncapped board) and `useSectors()` continue to supply
node colour/size and the sector filter, exactly as the current page does. The board-signal path is
untouched.

## API (`app/api/routes.py`)

| Method + path | Returns | Notes |
|---|---|---|
| `GET /api/graph/company/{ticker}` | `KnowledgeGraph` | One-hop ego graph; powers root + expand. Empty graph (root as lone node) when no relationships. |
| `POST /api/graph/saved` | `SavedGraphVersion` | Body `{root, expanded, graph}`; route stamps `saved_at`; appends (cap 5). |
| `GET /api/graph/saved` | `list[SavedGraphSummary]` | Roots + their version timestamps. |
| `GET /api/graph/saved/{root}` | `SavedGraphVersion` | `?version=<saved_at>`; latest if omitted. 404 if none. |
| `DELETE /api/graph/saved/{root}` | `{deleted: bool}` | `?version=` deletes one; omitted deletes the root. |

`{ticker}`/`{root}` are upper-cased server-side. The existing `GET /api/graph`,
`POST /api/graph/rebuild` (focus snapshot) are unchanged.

### Frontend plumbing

- `api/client.ts` — add `getCompanyGraph(ticker)`, `saveGraph({root, expanded, graph})`,
  `listSavedGraphs()`, `loadSavedGraph(root, version?)`, `deleteSavedGraph(root, version?)`.
- `hooks/queries.ts` — root-load and expand are **imperative + accumulative** (each targets a
  different ticker and merges into working state), so model the ego-graph fetch as a **mutation**
  (`useEgoGraph` → `mutateAsync(ticker)`) rather than a per-ticker `useQuery`. Add `useSaveGraph`,
  `useSavedGraphs` (query, key `['savedGraphs']`), `useLoadSavedGraph`, `useDeleteSavedGraph`
  (save/delete invalidate `['savedGraphs']`). Existing `useScreen`/`useSectors`/`useGraph` reused.
- CSS — reuse `.graph-*` classes; add minor controls styling only.

## Error handling / states

- **No relationships for a ticker:** `build_company_graph` returns a graph with just the root node
  and no edges → UI shows the lone root + "No relationships found for X". Expanding a leaf with no
  edges shows the same inline note; the node stays.
- **Invalid / off-universe root:** `get_stock_data` failure → empty fragment + inline "Couldn't
  load X". A valid-but-off-universe root still works as a source; its targets remain
  universe-constrained (closed vocab). Off-board nodes render dim (`onBoard=false`) — already handled.
- **Provider/settings failure:** degrade to empty fragment (mirrors `build_graph`); inline error.
- **Re-expanding an already-expanded node:** idempotent — `mergeGraph` dedupes nodes and edges.
- **Save guard:** Save disabled when the working graph is empty. Loading replaces working state
  (root/expanded restored). Deleting the last version removes the root from the index.
- **History cap:** the 6th save evicts the oldest version for that root.

## Testing (TDD, repo-consistent)

**Backend**
- `build_company_graph`: returns one-hop ego graph reusing the cached extraction (stubbed
  provider); root-only graph when no edges; degrades to empty on provider/data failure.
- saved-graph store: append + newest-first ordering; **cap at 5** (oldest evicted); `load` latest
  vs by `version`; `list` reflects the index; `delete` one version and whole root; long TTL set.
- routes: each endpoint's URL/method/shape — using **`app.dependency_overrides[get_cache]` with a
  tmp `Cache`** so the suite does **not** write the real `backend/data/app.db` (also retro-fixes
  the known Phase-A test-pollution pattern for the touched graph routes).

**Frontend**
- `lib/graphView.test.ts`: `mergeGraph` unions nodes and dedupes edges by `(source,target,type)`;
  empty-fragment is a no-op; existing helpers untouched.
- `api/client.test.ts`: new client methods hit the right URL + method (incl. `?version=`).
- `components/GraphSidebar.test.tsx`: root input fires; Expand button fires for the selected node;
  Save/Load/Delete fire; version dropdown renders; "Load focus set" fires.
- `pages/Graph.test.tsx`: root load renders canvas; expand merges (node/edge counts grow); save
  calls the API with the working graph; load replaces the working graph; with `GraphCanvas` + `api`
  mocked (existing pattern).

## Build order

1. **Schemas** — `SavedGraphVersion`, `SavedGraphSummary`.
2. **`build_company_graph`** in `network/service.py` + tests (reuse cached extraction; degrade).
3. **Saved-graph store** in `network/store.py` + tests (history cap, list/load/delete, long TTL).
4. **Routes** (`/api/graph/company/{ticker}`, `/api/graph/saved` CRUD) + tests with
   `dependency_overrides` + tmp `Cache`.
5. **`lib/graphView.ts`** `mergeGraph` + tests.
6. **`api/client.ts`** + **`hooks/queries.ts`** + client tests.
7. **`GraphSidebar`** controls (root input, expand, save/load/history, load-focus) + tests.
8. **`pages/Graph.tsx`** — accumulate working state, expand/save/load wiring, empty/error states + tests.
9. Final: `pytest` + `npm run build` + `npx vitest run` green; live browser smoke (seed an isolated
   temp `DATA_DIR`, back up + restore the real cache — same protocol as Phase B).

## Caveats

- **Pure research tool.** Changes nothing about the board signal; the daily focus-graph build is
  unchanged and remains the only signal source. *Not financial advice.*
- **Outgoing-edge semantics.** Edges are extracted from the *source's* news, so expanding node Y
  reveals Y's *outgoing* one-hop edges. Incoming edges to Y appear only if the other endpoint was
  also expanded. This is the existing extraction contract — expected, not a regression.
- **Cost is user-controlled.** Each manual expand is ≤1 LLM call (cached per ticker/day); no
  automatic fan-out. Auto depth-N build is deliberately out of scope (future convenience).
- **Scale.** A force layout stays legible for the dozens-of-nodes explorations this targets;
  unbounded expansion is on the user. No clustering/virtualization (YAGNI).
- **Saves are local.** Stored in the same SQLite cache DB as everything else; not synced or
  exported. History is capped to 5 per root by design.
