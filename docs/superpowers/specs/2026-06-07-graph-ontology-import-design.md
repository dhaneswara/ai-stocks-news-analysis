# External Ontology Import (enrich the knowledge graph from outside tools) — Design

- **Date:** 2026-06-07
- **Status:** Approved
- **Builds on:** the company knowledge-graph feature (Phase A backend + Phase B viz) and the
  company-rooted graph explorer, all merged to `master`. Reuses `KnowledgeGraph`/`GraphEdge`, the
  `TickerResolver` closed-vocabulary resolver, the SQLite `Cache`, the user-saved store pattern
  (`graph_user_saved:*` + index + long TTL), the network-scoring path (`apply_network`), and the
  `/graph` page (`GraphCanvas`/`GraphSidebar`/`lib/graphView.ts`). Parent specs:
  `2026-06-06-company-knowledge-graph-design.md`,
  `2026-06-06-company-knowledge-graph-phase-b-viz-design.md`,
  `2026-06-06-company-rooted-graph-explore-design.md`.

## Overview

Users research company relationships with **external tools** (e.g. ask ChatGPT to study a company
and its links to others) and want to fold that result back into this app's graph. This feature adds
a **manual import path**: paste/upload a small JSON "ontology model" that the app validates,
resolves against its ticker universe, tags as imported, and **merges into the graph**.

There is **no live integration** with any external tool — the unit of exchange is a file/blob the
user produces elsewhere. To make that easy, the import UI ships a **copy-paste ChatGPT prompt
template** that makes the model emit exactly the schema below.

Critically, the app's "graph ontology" today is a **closed-vocabulary property graph** (nodes are
universe tickers; edges are one of six `RelationType`s), *not* a formal W3C OWL ontology. So
"loading an OWL model" is implemented as **importing an app-defined JSON model** — the pragmatic
80/20 that ChatGPT can emit reliably without a heavyweight RDF parser.

Imported relationships **feed the network signal** (buy/sell tilt + the evaluation tracker) exactly
like app-extracted edges — this is a deliberate, user-chosen departure from the explorer's
"pure research view" posture. Because of that, persistence and provenance are designed carefully
(below). Same **decision support, not financial advice** posture as the rest of the app.

## Locked decisions

| Decision | Choice |
|---|---|
| Import format | **App-defined JSON schema** (not real OWL/RDF). No `rdflib`/`owlready2` dependency. A ChatGPT prompt template ships in-app to produce it. |
| Entity policy | **Hybrid resolve-and-keep.** Resolve each entity via `TickerResolver`; matched → canonical ticker node (lights up from the board); unmatched → kept as an external node `ext:<slug>` with a `node_meta` label/kind. |
| Relation types | **Six + a single `"other"`.** Map known synonyms to the six; everything else → `"other"`. `RelationType` gains `"other"` (7 total). |
| Scoring impact | **Imported edges feed scoring like native edges.** No down-weighting. They are tagged `origin="imported"` for display/management, not excluded from `apply_network`. |
| Persistence | **Separate persistent overlay**, merged at read time. New `graph_imported:*` keys + index, long TTL (~10y). The focus snapshot stays extracted-only so rebuilds stay idempotent and imports are never clobbered. |
| Import grouping | **Named import sets.** Each import is one removable, listable set; all active sets union into one global overlay. Reconciles the per-topic mental model with global scoring. |
| Failure posture | **Degrade, don't crash.** Malformed nodes/edges are skipped and counted; a bad import never raises. Set size capped (1000 edges). |

## Why a separate overlay (the load-bearing decision)

The network signal reads **only** the focus snapshot: `apply_network` consumes
`load_graph(cache, "focus")` (`graph_snapshot:focus`). That snapshot is **overwritten** by both the
Rebuild button (`POST /api/graph/rebuild` → `save_graph`) and the scheduled job
(`network/runner.run` → `save_graph`), and it carries a 7-day TTL. Therefore:

- **Rejected — merge into the focus snapshot:** trivial, but imports are wiped on the next rebuild,
  the next daily job, or after 7 days. Fatal for curated data.
- **Rejected — attach to per-company saved graphs (`graph_user_saved:*`):** survives, but
  `apply_network` never reads those, so it cannot satisfy "feed scoring."
- **Chosen — persistent overlay merged at read time:** imports live in their own long-TTL store and
  are unioned into the focus graph *at the point of consumption* (scoring + the `/graph` view). The
  saved snapshot stays extracted-only, so the re-blend stays idempotent (no double counting) and the
  overlay survives every rebuild.

`_type_sign` already treats every type except `competitor` as `+1`, so `"other"` and any imported
type score sanely. Edge contribution is `weight × confidence`, so imports **must** carry usable
values — defaulted to `0.5` and clamped to `0..1` when absent. An imported edge influences a
ticker's score only when its **source** is a board ticker (the `event` term applies; the `state`
term is `0` whenever the target is off-board) — expected, not a bug.

## The import JSON schema (the contract)

```json
{
  "name": "OpenAI–Nvidia supply chain",
  "as_of": "2026-06-07",
  "nodes": [
    { "id": "NVDA",   "label": "NVIDIA", "kind": "company" },
    { "id": "OpenAI", "label": "OpenAI", "kind": "private_company" }
  ],
  "edges": [
    { "source": "NVDA", "target": "OpenAI", "type": "customer",
      "sentiment": "positive", "weight": 0.8, "confidence": 0.7,
      "evidence": "OpenAI is among the largest buyers of NVIDIA data-center GPUs",
      "url": "https://example.com/article" }
  ]
}
```

- `name`, `as_of`, `kind`, `evidence`, `url` optional. `weight`/`confidence` default `0.5`.
- `kind` ∈ `company | private_company | product | person | sector` (free string; used only for the
  node label/styling — unknown values are kept verbatim).
- Node `id`s are arbitrary strings local to the file; edges reference them. Resolution happens on
  import (below), so the file may use tickers or plain names interchangeably.

## Normalization pipeline (`app/network/import_model.py`, pure)

`normalize_import(payload, resolver, *, now) -> (KnowledgeGraph, ImportReport)`:

1. **Parse leniently.** Non-dict payload → empty graph + a warning. Missing `nodes`/`edges` → treat
   as empty lists.
2. **Resolve nodes.** For each node, `resolver.resolve(label or id, id_if_tickerish)`:
   - match → node id = canonical **ticker**; no `node_meta` entry (it joins the board like a native
     node).
   - no match → node id = `ext:<slug(label or id)>`; add `node_meta[id] = {label, kind,
     source:"imported"}`. `slug` = lowercased, non-alphanumerics → `-`.
   - Build an `id → resolved-id` map for edge remapping.
3. **Normalize edges.** Remap `source`/`target` through the map (an edge endpoint absent from
   `nodes` is resolved on the fly the same way). Then:
   - `type` → `map_relation_type(raw)`: identity for the six; a small synonym table
     (`invests_in|stake|investor|acquired|acquires|owns → owner`;
     `licenses|licensee|licensor|alliance|collaborat* → partner`;
     `vendor|supplies|supplier_of → supplier`; `buys_from|client → customer`;
     `rival|competes* → competitor`; `unit|division|owned_by → subsidiary`); else `"other"`.
   - `sentiment` ∈ {positive,negative,neutral}, else `neutral`. `weight`/`confidence` → float,
     default `0.5`, clamp `0..1`. `evidence` truncated to 200 chars. `url` passthrough.
   - `origin="imported"`; `as_of` = payload `as_of` or `now`.
   - Drop edges where source == target, or where **both** endpoints are unresolved `ext:` *and*
     carry no label (i.e. nothing meaningful). Dedupe by `(source,target,type)`.
4. **Cap.** Keep at most `MAX_IMPORT_EDGES = 1000` (sorted by `weight*confidence` desc); record any
   truncation in the report.
5. **Report.** `ImportReport{nodes_added, edges_added, dropped, warnings:list[str]}`.

## Schemas (`app/models/schemas.py`) — all additive, backward-compatible

```python
RelationType = Literal["supplier","customer","partner","competitor","owner","subsidiary","other"]

class NodeMeta(BaseModel):
    label: str = ""
    kind: str = ""
    source: Literal["native","imported"] = "native"

class GraphEdge(BaseModel):
    ...                                   # unchanged fields
    origin: Literal["extracted","imported"] = "extracted"   # NEW (default keeps old data valid)

class KnowledgeGraph(BaseModel):
    ...                                   # unchanged fields
    node_meta: dict[str, NodeMeta] = {}   # NEW; only non-ticker/imported nodes get entries

class ImportSetSummary(BaseModel):
    id: str            # = created_at ISO
    name: str = ""
    as_of: str = ""
    created_at: str = ""
    node_count: int = 0
    edge_count: int = 0

class ImportReport(BaseModel):
    id: str = ""
    name: str = ""
    nodes_added: int = 0
    edges_added: int = 0
    dropped: int = 0
    warnings: list[str] = []
```

Existing saved graphs and snapshots deserialize unchanged: new `Literal`s only *add* a member,
`node_meta` defaults to `{}`, `origin` defaults to `"extracted"`.

## Store (`app/network/store.py`) — overlay, mirrors the user-saved pattern

```
add_import_set(name, graph, cache, *, now) -> ImportSetSummary   # store set + update index
list_import_sets(cache) -> list[ImportSetSummary]
delete_import_set(id, cache) -> bool
load_overlay(cache) -> KnowledgeGraph                            # union of all active sets
merge_graphs(a, b) -> KnowledgeGraph                             # backend twin of lib/graphView.mergeGraph
effective_graph(cache) -> KnowledgeGraph                         # merge_graphs(load_graph(focus), load_overlay())
```

- Key `graph_imported:<ID>` → JSON `{summary, graph}`; `graph_imported:__index__` → JSON list of ids.
- TTL = `_USER_SAVE_TTL_SECONDS` (~10y), reused. `Cache` has no delete → delete writes empty + drops
  the id from the index (same trick as `delete_saved_graph`).
- `merge_graphs`: union `nodes`; dedupe `edges` by `(source,target,type)`; **union `node_meta`**
  (later wins on key clash). `load_overlay` folds every set through `merge_graphs`.

## API (`app/api/routes.py`)

| Method + path | Returns | Notes |
|---|---|---|
| `POST /api/graph/import` | `ImportReport` | Body `{name?, payload}`; `payload` is the raw import JSON. Route normalizes → `add_import_set` (stamps `created_at`/`id`) → returns counts + warnings. |
| `GET /api/graph/imports` | `list[ImportSetSummary]` | All active import sets. |
| `DELETE /api/graph/imports/{id}` | `{deleted: bool}` | Remove one set. |

**Wiring (the overlay takes effect):** replace the graph fed to `apply_network` with
`effective_graph(cache)` at the three scoring sites — `rebuild_graph`, `screen_rescan`,
`network/runner.run`. `GET /api/graph` gains overlay-awareness via its existing `scope` param:
`scope="focus"` returns `effective_graph(cache)` (so the view matches what scoring sees) and
`scope="imported"` returns `load_overlay(cache)` (powers the explorer's incident-union, below).
`save_graph`/`build_graph` are **untouched** (snapshot stays extracted-only → idempotent re-blend).
Other `/api/graph/*` routes unchanged.

## Frontend

- **`types.ts`** — add `"other"` to `RelationType`; add `origin` to `GraphEdge`; add `NodeMeta` and
  `node_meta` to `KnowledgeGraph`; add `ImportSetSummary`/`ImportReport`.
- **`lib/graphView.ts`** — `mergeNodes` consults `graph.node_meta`: a node with a meta entry (or any
  non-ticker `ext:` id) becomes `external: true` with its `label`/`kind` and `onBoard:false`;
  `ViewLink` carries `origin`; `mergeGraph` also unions `node_meta`. `ALL_TYPES` becomes the fixed 7.
- **`components/GraphCanvas.tsx`** — external nodes render distinct (grey fill, dashed ring, label
  shown); imported links render **dashed** so provenance is visible even though they score. Colour
  for `"other"` = neutral.
- **`components/GraphSidebar.tsx`** — new **Import** tab:
  - a **Copy ChatGPT prompt** button (prompt below; `[COMPANY]` pre-filled with the current
    root/selected ticker when present),
  - a **textarea** (paste JSON) **+** a `.json` file picker,
  - an **Import** button → client-side `JSON.parse`/shape-check → `POST` → show
    `ImportReport` summary (added/dropped/warnings),
  - a **list of import sets** (name + counts + date), each with a ✕ to delete.
- **Explorer integration (`pages/Graph.tsx`)** — fetch the overlay graph once via
  `useGraph("imported")` (`GET /api/graph?scope=imported`) and **union overlay edges incident to the
  nodes currently in the working graph** (either endpoint in the working node set) into the rendered
  view, so importing an A↔B model then exploring A surfaces the imported link. Pure, done in the
  existing `view` `useMemo`.
- **`api/client.ts` + `hooks/queries.ts`** — `importGraph({name,payload})`, `listImports()`,
  `deleteImport(id)`; `useImportGraph`, `useImports` (key `['graphImports']`), `useDeleteImport`
  (import/delete invalidate `['graphImports']` and `['graph']`/`['screen']` so the view + scores
  refresh).

### The ChatGPT prompt template (shipped in-app, behind **Copy**)

> Research **[COMPANY]** and its business relationships with other companies, based on recent, real
> news. Output **ONLY** a single JSON object — no prose, no code fences — in exactly this shape:
>
> ```json
> { "name": "<short label>", "as_of": "<YYYY-MM-DD>",
>   "nodes": [ {"id": "<ticker if public, else short name>", "label": "<display name>",
>               "kind": "company|private_company|product|person|sector"} ],
>   "edges": [ {"source": "<node id>", "target": "<node id>",
>     "type": "supplier|customer|partner|competitor|owner|subsidiary|other",
>     "sentiment": "positive|negative|neutral", "weight": 0.0, "confidence": 0.0,
>     "evidence": "<short fact or quote>", "url": "<source url>"} ] }
> ```
>
> Rules: use the official **stock ticker** as `id` for any public company (e.g. NVDA, AAPL); a short
> readable id otherwise. `type` = the target's role relative to the source. `sentiment` = the
> event's likely effect on the source company. `weight` = how material the relationship is (0–1);
> `confidence` = how sure you are it is real and current (0–1). Include only relationships supported
> by real information; add a source `url` where possible.

## Data flow

```
Import: paste/upload JSON -> client JSON.parse + shape check
        -> POST /api/graph/import {name, payload}
        -> normalize_import(payload, TickerResolver) -> fragment + report
        -> add_import_set(name, fragment) (graph_imported:<created_at>; index updated)
        -> ImportReport shown; ['graphImports']+['graph']+['screen'] invalidated
Score:  rebuild / rescan / daily job -> apply_network(board, effective_graph(cache), settings)
        effective_graph = merge_graphs(load_graph("focus"), load_overlay())  # snapshot stays pure
View:   GET /api/graph?scope=focus    -> effective_graph (overlay included)
        GET /api/graph?scope=imported -> load_overlay (explorer unions edges incident to current nodes)
Remove: DELETE /api/graph/imports/{id} -> set emptied + dropped from index
        -> next effective_graph no longer includes it -> scores/view revert
```

## Error handling / states

- **Invalid JSON (client):** parse error → inline message, no request sent.
- **Valid JSON, junk content:** server normalizes leniently; `ImportReport` reports `dropped` +
  `warnings` (e.g. "12 edges dropped: unknown nodes"). Never 500s.
- **Nothing resolved:** an import with zero usable edges still succeeds (empty set) and says so; the
  user can delete it.
- **Duplicate re-import:** creates a new set; `merge_graphs` dedupes overlapping edges in the overlay
  union, so scores don't double-count. Users prune via the set list.
- **Size cap hit:** keep top 1000 by `weight*confidence`; warning notes the count dropped (no silent
  truncation).
- **Off-board imported source:** edge is stored and shown but contributes to no board row's score
  (nothing iterates it as a source) — documented, expected.
- **Overlay empty:** `effective_graph == focus snapshot`; behaviour identical to today.

## Testing (TDD, repo-consistent)

**Backend**
- `import_model`: ticker resolution vs `ext:` namespacing; type→6+`other` synonym mapping; sentiment
  fallback; weight/confidence default+clamp; `origin="imported"`; same-endpoint + unresolved drops;
  dedupe; size cap + truncation warning; non-dict / missing-keys tolerance.
- store: `add_import_set` updates index; `list`/`delete` (empty + index drop); `load_overlay` unions
  multiple sets; `merge_graphs` unions nodes, dedupes edges, **unions node_meta**; long TTL set.
- routes (with `app.dependency_overrides[get_cache]` + a tmp `Cache`, as in `test_api_graph.py`):
  `POST /import` returns the report and `GET /api/graph` then reflects the overlay; an import with an
  on-board source **shifts** that row's `/api/screen` score and `network` influences; `DELETE`
  reverts it; `save_graph`/rebuild does **not** drop the overlay.

**Frontend**
- `lib/graphView.test.ts`: `mergeNodes` marks `node_meta`/`ext:` nodes `external` with label/kind;
  `mergeGraph` unions `node_meta`; type list is the 7.
- `api/client.test.ts`: `importGraph`/`listImports`/`deleteImport` hit the right URL+method.
- `components/GraphSidebar.test.tsx`: Import tab — paste→import calls API with parsed payload;
  malformed JSON shows an error and sends nothing; copy-prompt writes the template; set list renders
  and ✕ deletes.

## Build order

1. **Schemas** — `RelationType += "other"`, `NodeMeta`, `KnowledgeGraph.node_meta`,
   `GraphEdge.origin`, `ImportSetSummary`, `ImportReport`.
2. **`import_model.normalize_import`** + synonym table + tests (pure).
3. **Store** — `merge_graphs`, overlay CRUD, `load_overlay`, `effective_graph` + tests.
4. **Routes** — import/list/delete + swap `effective_graph` into the **2 route scoring sites**
   (`rebuild_graph`, `screen_rescan`); `GET /api/graph` returns `effective_graph` for
   `scope="focus"` and `load_overlay` for `scope="imported"` + tests (tmp `Cache`).
5. **`network/runner.run`** — use `effective_graph` for the bake-in `apply_network` (3rd scoring
   site) + test.
6. **`types.ts`** + **`lib/graphView.ts`** (`mergeNodes`/`mergeGraph`/types) + tests.
7. **`api/client.ts`** + **`hooks/queries.ts`** + client tests.
8. **`GraphSidebar`** Import tab (+ prompt copy, set list) + **`GraphCanvas`** import styling + tests.
9. **`pages/Graph.tsx`** — overlay-incident union into the view + wiring + tests.
10. Final: `pytest` + `npm run build` + `npx vitest run` green; live browser smoke (isolated temp
    `DATA_DIR`, back up + restore the real cache — same protocol as prior graph phases).

## Caveats

- **Not real OWL.** This imports an app-defined JSON model, not W3C OWL/RDF. A future
  OWL/Turtle→JSON converter could feed the same pipeline (out of scope).
- **Imported data is unverified and it moves your signal.** By choice, imports score like native
  edges; a careless model can tilt buy/sell and the evaluation tracker. Provenance tagging + the
  per-set remove are the mitigations; an opt-in "visual-only" mode is a possible later toggle.
- **Closed-vocabulary tickers still win.** Only entities resolvable to the universe light up with
  board colour/score; external nodes are contextual (grey), and an external **source** scores
  nothing.
- **Local only.** Overlay lives in the same SQLite cache DB; not synced or exported.
- **No schema versioning yet.** The import JSON is v1-implicit; if it changes, add a `version` field
  and branch in `normalize_import` (YAGNI now).
