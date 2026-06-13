# Graph page improvements — design

**Date:** 2026-06-13
**Status:** Approved (design)

Four focused improvements to the Graph page (`/graph`): a dated LLM import prompt,
a renamed copy button, a reordered detail panel, and a new "Revalidate
relationships" node action.

## Motivation

- The copy-paste research prompt only says "recent news", which gives the LLM no
  temporal anchor — it doesn't know the current year, so it can pull stale facts.
- The button is named "Copy ChatGPT prompt", but the prompt is generic and works
  with any LLM (Gemini, Claude, etc.).
- In the Explore detail panel, "Open in Dashboard" is buried at the bottom, after
  the network-influence list; it reads more naturally right under the ticker score.
- "Expand neighbours" is additive-only and the LLM relationship extraction is
  cached for 24h, so there is no way to refresh a company's relationships and prune
  ones that have gone stale.

## 1. Dated LLM prompt

**File:** `frontend/src/lib/importPrompt.ts`

Rename the exported function `chatGptPrompt` → `llmPrompt`. New signature:

```ts
export function llmPrompt(
  company: string,
  opts?: { recencyDays?: number; now?: Date },
): string
```

Defaults: `recencyDays = 90`, `now = new Date()`. The function computes
`from = now − recencyDays days` and formats both `from` and `now` as `YYYY-MM-DD`
(UTC, via `toISOString().slice(0, 10)`).

Prompt body changes:

- Opening line becomes:
  `Research <C> and its business relationships with other companies, based on real
  news published between <FROM> and <TODAY> (about the last <N> days). Today is
  <TODAY>.`
  This gives the model an explicit window **and** the current year.
- The `as_of` example value in the JSON skeleton becomes the literal today date
  (e.g. `"as_of": "2026-06-13"`) instead of the `<YYYY-MM-DD>` placeholder, so the
  model echoes a current date.

The rest of the JSON contract (nodes/edges shape, rules) is unchanged.

**Wiring:** `Graph.tsx` adds `useSettings()` and passes
`recencyDays={settings.data?.news.news_recency_days ?? 90}` to `GraphSidebar`.
`now` is left to default (`new Date()`) inside the component; unit tests pass a
fixed `now` for determinism.

## 2. Rename the copy button

**File:** `frontend/src/components/GraphSidebar.tsx`

Button label "Copy ChatGPT prompt" → **"Copy LLM prompt"**. Update the import and
call site from `chatGptPrompt` → `llmPrompt`. The file stays `importPrompt.ts`.

## 3. Reorder the Explore detail panel

**File:** `frontend/src/components/GraphSidebar.tsx`

Within the `selected` detail block, move the `Open in Dashboard →` `<Link>` so it
sits immediately **after the score line** and **before** the action buttons.

New order:

1. `<h4>` label + direction badge
2. watchlist toggle (ticker nodes only)
3. score line (`score N`, when on-board)
4. **Open in Dashboard →**
5. action row: Expand neighbours · Revalidate relationships
6. network-influence list (or "No outgoing network edges.")

## 4. Revalidate relationships

Behavior chosen: **Refresh & replace**, **keep orphan nodes**.

### Backend

**File:** `backend/app/analysis/relationships.py`

`extract_relationships(..., refresh: bool = False)`. When `refresh` is true, skip
the cache **read** (the early `cache.get(key)` return) but still recompute and
`cache.set` the fresh result. No other behavior changes.

**File:** `backend/app/network/service.py`

`build_company_graph(ticker, settings, cache, *, now=None, refresh=False)` threads
`refresh` into the `extract_relationships` call.

**File:** `backend/app/api/routes.py`

`GET /graph/company/{ticker}` gains a `refresh: bool = False` query param, passed
to `build_company_graph`.

### Frontend

**File:** `frontend/src/lib/graphView.ts` — new pure helper:

```ts
export function revalidateGraph(
  working: KnowledgeGraph,
  ticker: string,
  fragment: KnowledgeGraph,
): KnowledgeGraph
```

Logic:

1. Keep every working edge **except** the source ticker's `extracted`-origin
   outgoing edges (an edge counts as extracted when `origin` is `'extracted'` or
   missing). Manual and imported edges from the ticker are preserved, as are all
   edges from other sources.
2. Merge the fresh `fragment` edges (all `extracted` from the backend), deduping by
   `source|target|type` against the kept edges, and union in any new
   nodes / `node_meta`.
3. Orphan neighbour nodes (left with no edges) are **kept** — the user prunes them
   via right-click if desired.

Implementable as: drop the source's extracted edges from `working`, then reuse the
existing `mergeGraph` dedupe to fold in the fragment.

**File:** `frontend/src/api/client.ts`

`getCompanyGraph(ticker: string, refresh = false)` appends `?refresh=true` when set.

**File:** `frontend/src/hooks/queries.ts`

`useEgoGraph` mutation function takes `{ ticker: string; refresh?: boolean }`.

**File:** `frontend/src/pages/Graph.tsx`

- `expand` updates to call `ego.mutateAsync({ ticker, refresh: false })`.
- New `revalidate(ticker)` handler: `ego.mutateAsync({ ticker, refresh: true })` →
  `setWorking((w) => revalidateGraph(w, ticker, frag))` → mark `expanded` + `dirty`
  → notice "No relationships found for <ticker>." when the fragment has no edges.
- Pass `onRevalidate={revalidate}` to `GraphSidebar`.

**File:** `frontend/src/components/GraphSidebar.tsx`

- New prop `onRevalidate: (id: string) => void`.
- In the detail panel, render **Expand neighbours** and **Revalidate
  relationships** in one `.graph-actions` row. The Revalidate button is shown only
  for ticker nodes (`!selected.id.includes(':')`) and is `disabled={loading}`.

## Testing

- `frontend/src/lib/importPrompt.test.ts` — with a fixed `now` and `recencyDays`,
  the prompt contains the computed from/today dates and the current year; the JSON
  contract assertions still hold; empty company still falls back to `[COMPANY]`.
- `frontend/src/lib/graphView.test.ts` — `revalidateGraph` replaces the ticker's
  extracted edges, preserves its manual/imported edges and other sources' edges,
  keeps orphan nodes, and adds new fragment nodes/edges.
- `frontend/src/components/GraphSidebar.test.tsx` — copy button reads "Copy LLM
  prompt"; Revalidate button fires `onRevalidate` for a ticker node and is absent
  for a `man:`/`ext:` concept node.
- Backend (`backend/tests/test_network_service.py` or `test_api_graph.py`) — a
  second `build_company_graph` call with `refresh=True` re-invokes the provider
  even when a cache entry exists (assert provider called twice / fresh edges).

## Non-goals

- No change to how Expand merges (still additive).
- No automatic orphan-node pruning.
- "Open in Dashboard" remains shown for all selected nodes (pre-existing behavior);
  only its position changes.
- No change to the active-ontology / scoring pipeline.
