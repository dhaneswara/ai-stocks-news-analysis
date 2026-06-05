# Company Knowledge Graph — AI Relationship Ontology & Network Signal — Design

- **Date:** 2026-06-06
- **Status:** Approved
- **Builds on:** the Discover opportunity board (`app/screener/` + `app/analysis/scoring.py`
  + `screen_snapshot`), the Trump/Truth-Social AI-signal pattern (`app/analysis/political.py`:
  one cached LLM call/day, attach-to-`StockData`, feed analyzer prompt, degrade silently), the
  LLM provider protocol (`app/llm/base.py` `complete(system, user) -> str` + `extract_json`),
  the SQLite KV `Cache`, and `services/stock_service.get_stock_data` (which already fetches
  news). Reuses every one of these unchanged.

## Overview

An **AI-driven ontology layer**: a **knowledge graph** whose nodes are companies in the
universe and whose edges are **business relationships extracted from news** — "Apple makes
Google the default search engine in Safari," "TSMC supplies Nvidia," "AMD competes with
Intel." Once built, the graph **propagates signal across edges** so a company's
**BUY / SELL / HOLD** is nudged by the condition of its neighbours, not just its own
technicals.

The design rests on one structural insight: **only edge *extraction* needs an LLM;
*propagation* is pure and instant.** So we cache the expensive part (the graph) and re-run the
cheap part (propagation) freely — Rescan stays fast.

Propagation is **hybrid**: each edge blends the **news event's own lean** (the Apple–Google
deal is bullish *for Google*) with a read of the **neighbour's current technical condition**
(a key supplier flashing SELL drags you down). The result is a capped **`network` signal
family** folded into the existing scorer: it can **tilt** a borderline call (HOLD→BUY) and
always carries a **plain reason + news citation**, but is weighted so it rarely overrides
strong technicals on its own.

This is **decision support, not financial advice.** Edges extracted from headlines are noisy;
the graph surfaces *relationship context*, never an auto-trade, and every nudge is explainable.

### Phasing

One spec, **two implementation plans** (the repo's usual rhythm):

- **Phase A — decision-impacting core:** schemas, AI extraction, pure propagation, the
  `network/` package + runner, propagation baked into Rescan/rebuild, the graph API, board
  chips, deep-dive panel, analyzer integration, tests. *Delivers the actual BUY/SELL/HOLD
  impact.*
- **Phase B — visualization:** the interactive node-link graph page, nav, rebuild
  button/status, filters. Pure presentation on top of the Phase A API.

## Locked decisions

| Decision | Choice |
|---|---|
| Propagation semantics | **Hybrid** — edge news-event sentiment **+** neighbour's current technical condition |
| Extraction scope | **Focus set (~30–50)** = `watchlist` ∪ top `focus_top_n` board names; **all 503 remain valid nodes/neighbours** (already scored) |
| Influence strength | **Tilt + flag** — a capped, weighted directional vote; can shift borderline calls, rarely overrides; always cites a reason |
| UI | **Both** — board chips + deep-dive panel **and** an interactive graph page |
| Extraction approach | **AI-from-news** — one LLM call per focus company over its existing ~10 headlines |
| Edge orientation | The focus company is always the **`source` (X)**; `type` describes the **neighbour's (Y's) role relative to X**; `sentiment` is judged **for X** |
| Propagation hops | **One hop only**, reading neighbours' **base** (pre-network) scores — no feedback loops |
| Node grounding | Closed to the universe — LLM-named companies are **resolved to a universe ticker, else dropped** (no invented nodes) |
| Graph build cadence | Daily batch (`python -m app.network`, OS-scheduled by the user) **+** on-demand "Rebuild graph"; result cached as `graph_snapshot` |
| LLM cost | ~30–50 small cached calls per build; **none** on the board read path |

## New data models (`models/schemas.py`)

```jsonc
// RelationType — closed vocabulary of edge types
"supplier" | "customer" | "partner" | "competitor" | "owner" | "subsidiary"

// GraphEdge — one extracted, typed, directional relationship (source-centric)
{
  "source": "AAPL",          // always a focus company (the ticker we extracted from)
  "target": "GOOGL",         // resolved to a universe ticker, else the edge is dropped
  "type": "partner",         // the TARGET's role relative to the SOURCE
  "sentiment": "negative",   // the news event's effect ON THE SOURCE (positive=good for source)
  "weight": 0.6,             // 0..1 materiality of the relationship
  "confidence": 0.7,         // 0..1 extraction confidence
  "evidence": "Apple to pay Google ~$20B/yr to stay Safari's default search",  // headline
  "url": "https://news.google.com/...",   // citation
  "as_of": "2026-06-06T21:00:00Z"
}

// KnowledgeGraph — a built snapshot
{
  "as_of": "2026-06-06T21:05:00Z",
  "scope": "focus",
  "nodes": ["AAPL", "GOOGL", "TSM", ...],   // tickers appearing as source or resolved target
  "edges": [ /* GraphEdge */ ],
  "built": 31, "skipped": 2                  // focus companies extracted / extraction failures
}

// NetworkInfluence — one neighbour's contribution to a target's network signal (explainability)
{
  "neighbour": "TSM", "name": "Taiwan Semiconductor",
  "type": "supplier", "edge_sentiment": "negative",
  "neighbour_direction": "sell",   // neighbour's BASE buy/sell/hold
  "signed": -0.42,                 // this edge's net directional contribution after sign rules
  "reason": "supplier TSM bearish (flashing SELL) + negative supply news"
}

// NetworkSignal — the aggregated network family for one focus company
// (numbers below are the running example: bearish supplier TSM contributes ≈ -0.42,
//  the costly GOOGL partner deal ≈ -0.22  ->  signed = clamp(sum) ≈ -0.64)
{
  "ticker": "AAPL",
  "intensity": 0.92,               // 0..1, feeds the 0–100 score (clamped sum of edge intensities)
  "signed": -0.64,                 // -1..1 directional vote (bounded)
  "influences": [ /* NetworkInfluence, strongest-first */ ],
  "reasons": ["supplier TSM bearish", "partner GOOGL deal a cost (bearish)"]
}

// NetworkConfig — added to Settings (no secrets -> no masking, like ScreenerConfig)
{
  "enabled": true,
  "focus_top_n": 30,               // top board names to extract, in addition to the watchlist
  "max_edges_per_company": 8,
  "min_confidence": 0.4,           // drop edges below this
  "weight": 0.5,                   // the network family's weight in the blend — the TILT CAP
  "alpha_event": 0.6,              // blend: weight on the edge's news-event term
  "beta_state": 0.4                // blend: weight on the neighbour-state term  (alpha+beta=1)
}
```

**Modifications to existing models:**

- **`StockScore` gains `net: float = 0.0`** — the −1..1 directional vote `score_stock` already
  computes internally but currently discards. Propagation needs it to re-blend exactly, and it
  is the neighbour-state input for one-hop propagation. (`score_stock` is updated to populate
  it; default keeps old snapshots loadable.)
- **`StockScore` gains `network: NetworkSignal | None = None`** — set on focus companies after
  propagation; powers the board chip badge.
- **`StockData` gains `network: NetworkSignal | None = None`** — the viewed company's
  influences, for the deep-dive (populated in `run_analysis`, like `market_mood`).
- **`AnalysisResult` gains `network: NetworkSignal | None = None`** — surfaced to the
  Dashboard, like `market_mood`.
- **`Settings` gains `network: NetworkConfig = Field(default_factory=NetworkConfig)`**.

## AI extraction (`app/analysis/relationships.py`) — mirrors `political.py`

A function that turns one company's headlines into typed, cited edges, with **one cached LLM
call per company per day**:

```python
extract_relationships(
    stock: StockData,                  # has .news already
    resolver: TickerResolver,          # universe name/ticker -> canonical universe ticker
    provider: LLMProvider, model: str, provider_name: str,
    cache: Cache, cfg: NetworkConfig, *, now: datetime | None = None,
) -> list[GraphEdge]
```

- **Cache key** `relationships:{provider}:{model}:{ticker}:{date}` (TTL 24h) — a same-day
  re-run is free, exactly like `summarize_market_mood`.
- **Prompt** (system/user, `extract_json` to parse — no function calling, matching the repo):

  ```
  SYSTEM: You extract business relationships between public companies from news headlines about
          ONE company (the SOURCE). Classify each relationship's type and judge the news event's
          likely effect ON THE SOURCE company. Respond with ONLY a single JSON object.
  USER:   {name} ({ticker}). Recent headlines:
          - [date] headline (source)
          ...
          Return JSON: {"edges":[{"target_name","target_ticker"?,"type","sentiment",
                                   "weight":0..1,"confidence":0..1,"evidence"}]}
          - "type" = the TARGET's role relative to {ticker}: supplier|customer|partner|
            competitor|owner|subsidiary.
          - "sentiment" = the event's effect on {ticker}: positive=good for {ticker}.
          - Only relationships actually supported by the headlines. "evidence" = a short quote.
          - Empty list if none.
  ```

- **Node grounding (closed vocabulary):** the prompt does **not** dump all 503 tickers (token
  cost). Instead the LLM names companies, and a deterministic **`TickerResolver`** (built from
  `load_universe()`) maps each to a canonical universe ticker — exact ticker match first, then
  normalized company-name match (reusing `political._clean_company`-style suffix stripping).
  **Unresolvable targets, and self-edges, are dropped.** This guarantees every node is a real
  universe company without bloating the prompt.
- **Filter/cap:** drop edges below `min_confidence`; keep the top `max_edges_per_company` by
  `weight × confidence`.
- **Degrade silently:** any error (LLM failure, bad JSON, validation) → **empty edge list**
  for that company; the graph still builds from the rest. Same contract as `political.py`.

## Propagation (`app/analysis/network.py`) — pure, deterministic, no I/O

The reusable primitive, in the style of `scoring.py`. Edge orientation: **`source` (X) is the
focus company, `type` describes the neighbour (Y), `sentiment` is X-centric.**

### Sign rules — the only flip is `competitor`

| Edge type (Y relative to X) | Neighbour-state effect on X | `type_sign` |
|---|---|---|
| supplier · customer · partner · owner · subsidiary | move **with** Y — Y's trouble flows to X | **+1** |
| competitor | move **against** Y — Y's strength steals X's share | **−1** |

### Hybrid blend (per focus company X)

```
for each edge e = (X→Y, type, sentiment, weight, confidence):
    state = type_sign(type) * net(Y)        # Y's BASE directional vote ∈[-1,1]; 0 if Y unscored
    event = {positive:+1, neutral:0, negative:-1}[sentiment]   # X-centric
    w     = weight * confidence
    e.signed    = w * (alpha_event*event + beta_state*state)
    e.intensity = w * max(|event|, |state|)
    -> record a NetworkInfluence(neighbour=Y, type, edge_sentiment, neighbour_direction, e.signed, reason)

network.signed    = clamp(Σ e.signed, -1, 1)
network.intensity = clamp(Σ e.intensity, 0, 1)
network.reasons   = top influences rendered as short human chips
```

### Folding into the scorer — exact re-blend (no recompute of base families)

`network` is a **directional** family (unlike attention-only volume/catalyst) but capped by
`w_net = NetworkConfig.weight`. Adding one family to `score_stock`'s own formula gives a closed
form needing only the stored `base_score` and `base_net`:

```
W_base = Σ weights of all base families          # from ScreenerConfig.weights
W_dir  = Σ weights of directional base families  # extremes + trend + momentum

final_score = (base_score*W_base + 100*network.intensity*w_net) / (W_base + w_net)
final_net   = clamp( (base_net*W_dir + network.signed*w_net)    / (W_dir  + w_net), -1, 1)
final_dir   = buy  if final_net >  τ
              sell if final_net < -τ
              hold otherwise            # τ = the existing _DIRECTION_THRESHOLD (0.1)
```

```python
apply_network(board: ScreenBoard, graph: KnowledgeGraph, settings: Settings) -> ScreenBoard
    # W_base/W_dir come from settings.screener.weights; cap/blend from settings.network
    # 1. index base scores: ticker -> StockScore (has .net, .score, .components)
    # 2. for each focus company with edges in `graph`:
    #        sig = compute_network_signal(edges_of(X), base_index, settings.network)
    #        re-blend X's score/net/direction via the closed form above
    #        set X.network = sig; prepend sig.reasons to X.reasons; add "network" to components
    # 3. re-sort board by score desc; return a new board (pure; base rows untouched)
```

### Robustness, by construction

- **No feedback loops** — reads neighbours' **base** scores, one hop.
- **Graceful when a neighbour isn't scored** (off-universe / skipped): `state`→0, the
  X-centric `event` term still applies.
- **Disabled / no graph** → `apply_network` is a no-op; the board is exactly today's board.

## Orchestration & persistence (`app/network/`) — mirrors `app/screener/`

```python
# app/network/service.py
build_graph(scope: str | None, settings: Settings, cache: Cache) -> KnowledgeGraph
    # focus = settings.watchlist ∪ top focus_top_n tickers from load_snapshot(cache,"all")
    #         (fallback to watchlist if no board snapshot yet)
    # resolver = TickerResolver(load_universe())
    # for ticker in focus:
    #     try: stock = get_stock_data(ticker, "1y", settings.indicator_params, cache)  # news incl.
    #          edges += extract_relationships(stock, resolver, provider, model, name, cache, cfg)
    #          built += 1
    #     except Exception: skipped += 1; continue        # never abort the whole build
    # return KnowledgeGraph(nodes=…, edges=…, built, skipped, as_of=now)

# app/network/store.py — reuses the existing Cache (SQLite KV), key `graph_snapshot:<scope>`,
#   long TTL (7d) refreshed by the daily job (mirrors screener/store.py exactly).
save_graph(graph, cache) ; load_graph(cache, scope="focus") -> KnowledgeGraph | None

# app/network/runner.py + __main__.py — the scheduled job (mirror app/screener.__main__)
#   python -m app.network [--dry-run]
#   run(): graph = build_graph(None, settings, cache); save_graph(graph)
#          board = load_snapshot(cache,"all")
#          if board: save_snapshot(apply_network(board, graph, settings), cache)   # bake in
```

**Scheduling order matters.** `python -m app.network` must run **after** `python -m app.screener`
so it bakes influence onto the *fresh* base board; the existing screener runner does **not**
apply network and would otherwise leave a base-only board until the next network run. The
interactive **Rescan** re-applies network from the cached graph (pure, instant), so manual
refreshes never lose it — only the daily cron ordering needs care, and it is documented with the
OS schedule entry.

## Integration points

- **`POST /api/screen/rescan`** (existing route, extended): after `run_scan`, if a
  `graph_snapshot` exists, call `apply_network(board, graph, settings)` before saving — so a
  base-only Rescan **keeps** network influence instantly (propagation is pure). The sector
  merge path applies network after merging.
- **`run_analysis`** (deep-dive, in `services/analysis_service`): after assembling `StockData`,
  if the viewed ticker has edges in the cached graph, compute its `NetworkSignal` (from the
  graph + base board) and set `stock.network`. The analyzer surfaces it.
- **`analyzer.build_user_prompt`**: a new `_format_network(stock.network)` section (like
  `_format_mood` / `_format_mentions`), weighed as a **stock-specific, noisy, low-certainty**
  factor that must **not** override strong technicals and must **not** create dated chart
  signals. `analyze(...)` copies `stock.network` onto the `AnalysisResult` (like `market_mood`).

## API (`api/routes.py`)

```
GET  /api/graph?scope=focus     -> KnowledgeGraph     (reads graph_snapshot; none -> empty graph)
POST /api/graph/rebuild         -> KnowledgeGraph     (LLM build over focus set, then
                                                        apply_network onto the board; saves BOTH
                                                        snapshots; returns graph + built/skipped)
```

`GET /api/graph` is instant. `POST /api/graph/rebuild` is the only slow (LLM) call — the
"Rebuild graph" button and the daily runner. The board (`GET /api/screen`) and deep-dive
(`POST /api/analyze/{ticker}`) need **no new endpoints**; they carry `network` on their
existing payloads. `NetworkConfig` rides on the existing `GET/PUT /api/settings`.

## Data flow

```
# Daily (OS scheduler, post-close) — populate graph + bake influence into the board:
python -m app.screener         -> base board snapshot (no LLM)           [existing]
python -m app.network          -> build_graph (focus set, ~30–50 LLM)    [new]
                                  -> apply_network onto board -> save both snapshots

# Interactive:
GET /api/screen                -> snapshot already network-adjusted -> chips show 🔗 reasons (instant)
POST /api/screen/rescan        -> run_scan -> apply_network(cached graph) -> save   (fast, no LLM)
POST /api/graph/rebuild        -> re-extract edges (LLM) -> apply_network -> save   (slow, on demand)
GET  /api/graph                -> KnowledgeGraph for the visual page                (instant)
click row -> Dashboard?ticker= -> POST /api/analyze/{ticker} -> AnalysisResult.network panel
```

## Frontend

- **Board chips** (`components/DiscoverBoard.tsx`): network reasons already arrive via
  `StockScore.reasons`; render a small **🔗 "network"** badge to distinguish a
  relationship-driven nudge from a technical one. `types.ts` gains `NetworkSignal` etc.
- **Deep-dive "Network influence" panel** (Dashboard, near `ReasoningPanel.tsx`): lists each
  neighbour — edge type, the news **event + citation link**, the neighbour's current direction,
  and its net contribution — from `AnalysisResult.network.influences`. Mirrors the existing
  mood/mentions panels; renders nothing when absent.
- **Interactive graph page** (Phase B — `pages/Graph.tsx` + route in `App.tsx` + nav link):
  a **node-link diagram** — nodes = companies (colour by buy/sell/hold, size by score), edges =
  typed relationships (arrowed source→target, colour/style by type, tooltip = event +
  citation). Click a node → side panel of its `NetworkInfluence`s + a link to its Dashboard.
  Header: **"Rebuild graph"** button (calls `POST /api/graph/rebuild`, spinner) with
  `as_of` / built / skipped status (same UX as Rescan), plus **sector / edge-type filters**.
  - **Library:** `react-force-graph-2d` (canvas, ~50 nodes, minimal code) — exact version
    pinned for **Node 20**, consistent with the toolchain discipline (Vite 5 / vitest 2 /
    react-router v7). Cytoscape.js is the heavier-control fallback if richer styling is needed.
  - **Plumbing:** `api/client.ts` (`getGraph`, `rebuildGraph`), `hooks/queries.ts`
    (`useGraph`, `useRebuildGraph`).

## Error handling / degradation

- Per-company extraction failure during a build → **skip + count** (`skipped`); never abort.
- LLM/JSON/validation failure for a company → empty edges (silent), graph builds from the rest.
- Unresolvable or self-referential target → edge dropped at resolution.
- No `graph_snapshot` yet → `apply_network` is a no-op; board = today's board; graph page shows
  an empty state prompting a first **Rebuild**; deep-dive shows no network panel.
- Neighbour not scored → its state term is 0 (event term still applies).
- `NetworkConfig.enabled = false` → extraction, propagation, and all network UI are skipped end
  to end; the app behaves exactly as before this feature.

## Testing (TDD, the repo's hermetic conventions)

- **`network.py` (the bulk, pure):** table-driven sign tests per edge type (competitor flips,
  others don't); the hybrid blend (event-only, state-only, combined; α/β respected); clamping;
  the **exact re-blend** (network off → board unchanged; a strong bearish neighbour tilts a
  HOLD→SELL but a capped weight cannot flip a strong BUY); unscored-neighbour fallback;
  empty-graph no-op.
- **`relationships.py`:** stubbed provider returning canned JSON → parsing, `TickerResolver`
  (ticker-exact, name-normalized, drop-unresolvable, drop-self), `min_confidence` filter,
  `max_edges` cap, degrade-to-empty on error. Hermetic via an autouse stub in `conftest.py`
  (like the Truth-Social tests).
- **`network/service.build_graph`:** tiny fake universe + stubbed `get_stock_data` + stubbed
  extractor → graph with correct nodes/edges; a raising company is skipped and counted; focus
  set = watchlist ∪ top-N.
- **`network/store`:** `save_graph` / `load_graph` round-trip; empty when absent.
- **API:** `GET /api/graph` (empty + populated); `POST /api/graph/rebuild` (stubbed happy
  path, returns built/skipped, board re-saved network-adjusted); `NetworkConfig` settings
  round-trip; `screen/rescan` applies network when a graph exists.
- **Frontend:** board renders the 🔗 badge; deep-dive renders the influence panel from a
  fixture; graph page light smoke (consistent with the repo — no new render-test requirement).

## Build order

**Phase A — core (own plan):**

1. Schemas: `RelationType`, `GraphEdge`, `KnowledgeGraph`, `NetworkInfluence`, `NetworkSignal`,
   `NetworkConfig`; `StockScore.net` + `.network`; `StockData.network`; `AnalysisResult.network`;
   `Settings.network`. Populate `StockScore.net` in `score_stock`.
2. `analysis/network.py` — sign rules, hybrid blend, `compute_network_signal`, `apply_network`
   (TDD — the largest test surface).
3. `analysis/relationships.py` — `TickerResolver` + `extract_relationships` (TDD, stubbed LLM).
4. `network/service.build_graph` (stubbed deps) + `network/store` (TDD).
5. `network/runner.py` + `__main__.py` (mirror `app/screener`); document the OS schedule.
6. API: `GET /api/graph`, `POST /api/graph/rebuild`; extend `screen/rescan` to apply network
   (TDD).
7. Deep-dive integration: `run_analysis` enrichment + `analyzer._format_network` +
   `AnalysisResult.network`.
8. Frontend core: `types` + `client` + `hooks`; board 🔗 badge; deep-dive influence panel.

**Phase B — visualization (own plan):**

9. `react-force-graph-2d` (pinned), `pages/Graph.tsx`, route + nav, node/edge rendering,
   node-click side panel, "Rebuild graph" button + status, sector/edge-type filters.

## Caveats

- **Not financial advice.** The graph is *relationship context*, not a recommendation; the
  `DISCLAIMER` still rides on every `AnalysisResult`. The network signal is **tilt + flag** —
  capped so noisy edges rarely override technicals, and always accompanied by a citation.
- **Edge quality is bounded by headlines.** Google-News RSS gives ~10 headlines/ticker, which
  rarely state relationships cleanly → a **sparse, partly-noisy** graph. We lean on
  `confidence` + `min_confidence` + citations and accept sparsity. Richer extraction
  (full-text, or a curated seed graph for structural edges) is a **future enhancement** the
  `GraphEdge` model already accommodates.
- **Focus-set scope.** Edges are extracted only for the watchlist + top board names; deep-dives
  on a name outside that scope show "no network signal yet." On-demand single-ticker extraction
  is a noted future enhancement (cheap — one cached call).
- **Daily cadence, not intraday.** The graph is "as of the last build," matching the daily
  swing-trading cadence of the rest of the app.
- **One-hop propagation.** Multi-hop contagion (a supplier's supplier) is deliberately out of
  scope — it amplifies noise and hurts explainability. One hop keeps every nudge traceable to a
  named neighbour and a cited headline.
- **Cost.** ~30–50 small cached LLM calls per graph build (same order as the deep-dive path),
  **zero** on the board read path. Propagation and all board/deep-dive reads add no LLM cost.
- **Sentiment is a model judgment.** "Good or bad for the source" is inferred by the LLM from a
  headline; it can be wrong. Confidence weighting and the tilt cap bound the damage; the
  citation lets the user check.
```