# Company Knowledge Graph — Phase B (Interactive Graph Page) — Design

- **Date:** 2026-06-06
- **Status:** Approved
- **Builds on:** Phase A (merged to `master`): the graph API (`GET /api/graph` → `KnowledgeGraph`,
  `POST /api/graph/rebuild`), the board API (`GET /api/screen` → `ScreenBoard` of `StockScore`,
  `GET /api/screen/sectors`), and the frontend types (`KnowledgeGraph`, `GraphEdge`,
  `NetworkSignal`, `NetworkInfluence`, `StockScore`). Parent spec:
  `2026-06-06-company-knowledge-graph-design.md`.

## Overview

A **read-only visualization** of the company knowledge graph: an interactive node-link diagram
where nodes are companies (coloured by buy/sell/hold, sized by opportunity score) and edges are
the news-derived relationships (coloured by their effect on the source). It makes the otherwise
invisible "network" signal explorable — you can see at a glance which watched names are under
relationship pressure and trace *why* (which neighbour, what news) before opening the deep-dive.

**No backend changes.** All data already exists from Phase A; this phase is pure presentation
plus one existing write (`POST /api/graph/rebuild`). The board supplies each node's call/score;
the graph supplies the edges.

This is **decision support, not financial advice** — the same disclaimer posture as the rest of
the app; the page visualizes a heuristic relationship signal, never a recommendation.

## Locked decisions

| Decision | Choice |
|---|---|
| Page layout | **Right sidebar (always-on)** — graph canvas ~65–70% left; fixed right column holds controls + selected-node detail |
| Edge colour | **By news sentiment** (green = good for source, red = bad, grey = neutral); relationship *type* shown on hover + in the sidebar |
| Node encoding | Colour by `direction` (buy/sell/hold; off-board = dim grey), radius ∝ `score`, label = ticker |
| Library | **`react-force-graph-2d`** (canvas, ~30–50 nodes, minimal code), version pinned for **Node 20** |
| Selection | Click a node → highlight its edges + neighbours (dim the rest) → populate sidebar detail |
| Filters | Sector dropdown + edge-type toggles; both **hide** non-matching elements (not dim), with a live count |
| Backend | **None** — reuses Phase A endpoints; the only write is the existing `POST /api/graph/rebuild` |

## Data flow

```
Graph page mount
  -> useGraph()   GET /api/graph            -> KnowledgeGraph (nodes[], edges[])
  -> useScreen()  GET /api/screen?limit=0   -> ScreenBoard (StockScore per ticker: direction, score, net, network)
  -> useSectors() GET /api/screen/sectors   -> string[] (sector filter options)
  merge (pure, lib/graphView.ts):
     node = { id: ticker, score(from board), direction(from board), label: ticker }
     link = { source, target, sentiment, type, weight, confidence, evidence, url }
  -> GraphCanvas renders; click -> selected ticker -> GraphSidebar detail
  "Rebuild graph" -> useRebuildGraph() POST /api/graph/rebuild (slow, LLM) -> invalidate useGraph + useScreen
```

`GET /api/screen?limit=0` returns the full board (uncapped) so every graph node can be coloured;
nodes with no board row (off-universe targets) render dim grey at default size.

## Components (small, single-responsibility)

```
pages/Graph.tsx
  - Data: useGraph, useScreen, useSectors, useRebuildGraph (hooks/queries.ts).
  - State: selectedTicker | null; sectorFilter | null; enabledEdgeTypes: Set<RelationType>.
  - Composes <GraphCanvas> (left) + <GraphSidebar> (right) in the Layout-A flex shell.
  - Empty/loading/error states; passes filtered view-model down.

components/GraphCanvas.tsx
  - Thin wrapper over react-force-graph-2d: props { nodes, links, selectedTicker, onNodeClick }.
  - Node paint: colour by direction, radius by score, ticker label. Link: directional arrow,
    colour by sentiment, width by weight*confidence; hover tooltip = "type · sentiment · evidence".
  - Selection: highlight selected node's links + neighbours, dim others.
  - Mocked in tests (canvas can't render in jsdom — same pattern as PriceChart mock).

components/GraphSidebar.tsx  (presentational, unit-testable)
  - Header: "Rebuild graph" button (spinner + warning it runs the LLM) + as_of / built / skipped.
  - Filters: sector <select>; edge-type toggle chips (supplier/customer/partner/competitor/owner/subsidiary).
  - Selected-node detail: ticker + call badge + score; its NetworkInfluence list
    (neighbour · type · sentiment · signed contribution); "Open in Dashboard →" (?ticker= deep-link).
  - When nothing selected: a short hint + the colour legend.

lib/graphView.ts  (pure, fully unit-tested — no canvas, no network)
  - mergeNodes(graph, board) -> ViewNode[]   (joins graph nodes to StockScore for colour/size)
  - toLinks(graph) -> ViewLink[]
  - applyFilters(nodes, links, sector, enabledTypes) -> { nodes, links } (hide non-matching; drop
    links whose endpoints were filtered out)
  - sentimentColor(sentiment) / directionColor(direction) / nodeRadius(score)
```

## Frontend plumbing

- `types.ts` — reuse existing `KnowledgeGraph`/`GraphEdge`/`NetworkSignal`/`StockScore`; add small
  view-model types `ViewNode`/`ViewLink` in `lib/graphView.ts` (local, not API types).
- `api/client.ts` — add `getGraph(scope?)` → `GET /api/graph` and `rebuildGraph()` →
  `POST /api/graph/rebuild`. (`getScreen`/`getSectors` already exist.)
- `hooks/queries.ts` — add `useGraph`, `useRebuildGraph` (invalidates `['graph']` + `['screen']`).
  (`useScreen`/`useSectors` already exist.)
- `App.tsx` — add a **Graph** nav link + `<Route path="/graph" element={<Graph/>} />`.
- CSS — reuse existing panel/badge/button classes; add a minimal `.graph-*` layout shell
  (flex row, fixed sidebar width). No heavy new design system.

## Error handling / states

- **No snapshot** (`GET /api/graph` → empty `KnowledgeGraph`): canvas shows an empty state with a
  **Rebuild graph** call-to-action.
- **Loading**: spinner in the canvas area; sidebar controls disabled.
- **Error** (graph or board fetch fails): inline message in the canvas area; Rebuild still offered.
- **Board missing / node off-board**: node renders dim grey at default size (no crash; merge
  treats a missing `StockScore` as unknown).
- **Rebuild failure** (`502` from the LLM path): toast/inline error, graph unchanged.
- **Empty after filters**: "No nodes match these filters" with a reset affordance.

## Testing (TDD, repo-consistent — light, no canvas in jsdom)

- `lib/graphView.test.ts` (the bulk): `mergeNodes` joins board scores + marks off-board nodes;
  `applyFilters` hides by sector and edge-type and drops orphaned links; colour/size mappers.
- `components/GraphSidebar.test.tsx`: renders the selected-node detail from a `NetworkSignal`
  fixture (neighbours, link to Dashboard); filter toggles fire callbacks; empty-selection legend.
- `pages/Graph.test.tsx`: smoke test with `GraphCanvas` mocked (`vi.mock`) and `api` mocked —
  asserts empty state with no graph, and node/edge counts when populated; Rebuild calls the API.
- `api/client.test.ts`: `getGraph` / `rebuildGraph` hit the right URL + method.
- Consistent with the repo: `react-force-graph-2d` mocked like `PriceChart`; no pixel/canvas tests.

## Build order

1. Add the dependency `react-force-graph-2d` (pinned, Node-20 compatible); confirm `npm run build`.
2. `lib/graphView.ts` + tests (pure helpers — merge, filter, colour/size). TDD.
3. `api/client.ts` (`getGraph`, `rebuildGraph`) + `hooks/queries.ts` (`useGraph`, `useRebuildGraph`) + client tests.
4. `components/GraphSidebar.tsx` + test (controls + selected-node detail).
5. `components/GraphCanvas.tsx` (force-graph wrapper; mocked in tests).
6. `pages/Graph.tsx` (compose, state, empty/loading/error) + smoke test.
7. `App.tsx` nav link + route. Final: `npm run build` + `npx vitest run` green; live smoke in the browser.

## Caveats

- **Read-only.** The page changes nothing except triggering the existing rebuild. Same
  *not financial advice* posture as the rest of the app.
- **Scale.** Tuned for the focus-set graph (~30–50 nodes); a force layout stays legible there.
  A much larger graph would need clustering/virtualization — out of scope (YAGNI).
- **Off-board nodes.** Extracted targets outside the scored board show as dim/unknown — expected;
  their state term was already 0 in propagation.
- **One dependency added.** `react-force-graph-2d` is the only new package; pinned for Node 20 to
  preserve the existing toolchain discipline. Cytoscape.js is the documented fallback if richer
  styling is ever needed.
- **No backend/test-surface changes.** Backend stays at its Phase A behaviour; this phase adds
  frontend files only.
