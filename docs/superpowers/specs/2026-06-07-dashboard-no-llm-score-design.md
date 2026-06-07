# Dashboard no-LLM opportunity score (Discover parity) — Design

- **Date:** 2026-06-07
- **Status:** Approved
- **Builds on:** the Discover opportunity board (pure `score_stock` scorer, `StockScore` schema, `ScreenerConfig`) and the company knowledge-graph / network-signal feature (`compute_network_signal` + `apply_network`, `effective_graph` overlay), all merged to `master`. Reuses the Dashboard's existing `useStock` data load, the SQLite `Cache`, and the screener snapshot. Parent specs: `2026-06-05-discover-opportunity-board-design.md`, `2026-06-06-company-knowledge-graph-design.md`.

## Overview

Today the Dashboard's only per-ticker assessment is the **LLM deep-dive** (behind the *Analyze with LLM* button). The Discover board, by contrast, shows an **instant, no-LLM opportunity score** (0–100 + buy/sell/hold + reason chips + a 🔗 network badge) for every stock. This feature brings that same no-LLM score onto the Dashboard for the currently-loaded ticker, shown **automatically** in the summary header — so the user gets an immediate, free read on any ticker, with the LLM analysis remaining the optional richer step.

The scorer (`score_stock`) is already pure and reusable. The only new backend work is a **single-ticker scoring path** (the board only scores the whole universe today) plus computing/blending the network signal for that one ticker exactly as the board does, so the Dashboard number **matches** the Discover number for the same ticker.

This is **decision support, not financial advice** — same posture as the rest of the app. The score is purely the existing deterministic technical signal; nothing new is invented.

## Locked decisions

| Decision | Choice |
|---|---|
| Score source | **On-demand single-ticker endpoint** `GET /api/score/{ticker}`. Works for ANY ticker (even off the S&P 500 board), always fresh, no LLM. (Not a board-snapshot lookup — that misses off-board/un-scanned tickers and can be stale.) |
| Network parity | **Full parity** — compute the network signal for the ticker and **blend** it into the score (same math the board bakes via `apply_network`), so the Dashboard score/call match Discover. Implemented by extracting the per-row blend into a shared helper (DRY). |
| Trigger | **Automatic on ticker load** (no button). It's instant and LLM-free, mirroring how Discover displays it. The *Analyze with LLM* button path is untouched. |
| Placement | **Compact chip in the summary header**, next to the price / `IndicatorBar`. Mirrors a Discover row's score cells: score bar + number + call badge + top-3 reason chips + a 🔗 badge (influences in a tooltip), NOT the full `NetworkPanel`. |
| Period | `SCAN_PERIOD = "1y"` (the board's period) so the score matches the board, even though the chart loads 5y. |
| Criticality | Non-critical UI: on error the chip silently does not render; the Dashboard is otherwise unaffected. |

## Architecture

### Backend

**Extract the per-row network blend (DRY)** — `app/analysis/network.py`:

```python
def blend_network_into_score(s: StockScore, sig: NetworkSignal, settings: Settings) -> StockScore:
    """Fold a computed network signal into one row's score/direction — the closed-form re-blend
    from base_score/base_net (never the already-blended values), so it stays idempotent."""
    # body lifted verbatim from apply_network's per-row block (final_score/final_net/direction/
    # components["network"]/reasons/network), returning s.model_copy(update={...}).
```

`apply_network`'s loop body becomes `sig = compute_network_signal(...)` → `blend_network_into_score(s, sig, settings)`. **No behavior change to the board** (existing network tests must stay green); the helper is now reusable.

**Single-ticker scorer** — `score_one(ticker, settings, cache) -> StockScore` in `app/screener/service.py` (beside `run_scan`):

```
get_stock_data(ticker, SCAN_PERIOD, settings.indicator_params, cache)   # cached; same period as the board
posts = truth_social.fetch_recent_posts_cached(...) if ts.enabled else []
mentions = political.find_mentions(posts, ticker, stock.company_name)
score = score_stock(stock, mentions, settings.screener)
score.sector = <universe entry's sector if found, else "">             # best-effort, like run_scan
if settings.network.enabled:
    graph = effective_graph(cache, "focus")
    board = load_snapshot(cache, "all")
    base_index = {s.ticker: s for s in (board.items if board else [])}
    edges = [e for e in graph.edges if e.source == ticker]
    if edges:
        sig = compute_network_signal(ticker, edges, base_index, settings.network)
        score = blend_network_into_score(score, sig, settings)
return score
```

Mirrors the network enrichment already in `services/analysis_service.run_analysis` (graph from `effective_graph`, neighbours from the `"all"` snapshot, source-only edges). Degrades to the base score when the graph/board are absent.

The network block inside `score_one` is **best-effort** (wrap it so a missing/corrupt graph or snapshot degrades to the base score, never raises). Only `get_stock_data`'s `ValueError` (bad ticker / no data) propagates to the route.

**Route** — `app/api/routes.py` (mirrors `GET /stock/{ticker}`, which catches `ValueError` → 404):

```python
@router.get("/score/{ticker}", response_model=StockScore)
def get_score(
    ticker: str, cache: Cache = Depends(get_cache), store: SettingsStore = Depends(get_settings_store)
) -> StockScore:
    try:
        return score_one(ticker.upper().strip(), store.load(), cache)
    except ValueError as exc:   # no data for ticker -> 404, same convention as GET /stock/{ticker}
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

### Frontend

- **Types:** `StockScore` already exists in `types.ts` — no change.
- **Client** (`api/client.ts`): `getScore: (ticker) => http<StockScore>(\`/score/${encodeURIComponent(ticker)}\`)`.
- **Hook** (`hooks/queries.ts`): `useScore(ticker)` → `useQuery({ queryKey: ['score', ticker], queryFn: () => api.getScore(ticker), enabled: ticker.length > 0, retry: false })`.
- **Shared `ScoreBar`** — extract the private `ScoreBar` from `DiscoverBoard.tsx` into `components/ScoreBar.tsx`; `DiscoverBoard` imports it (behavior unchanged).
- **`ScoreChip`** — new `components/ScoreChip.tsx` taking a `StockScore`: `<ScoreBar>` + `score.toFixed(0)` + a `badge {direction}` (BUY/SELL/HOLD) + `reasons.slice(0,3)` chips + a `🔗` chip (`title` = top network influences) shown when `score.network?.reasons?.length`. Pure/presentational.
- **Dashboard** (`pages/Dashboard.tsx`): `const score = useScore(ticker);` and render `{score.data && <ScoreChip score={score.data} />}` as a new line inside `.summary-id`, directly under the `.hero-quote`. No interaction with the LLM `analyze` flow.
- **CSS** (`styles.css`): a compact `.score-chip` row (reuse existing `.score-bar`, `.badge`, `.reason-chip`).

## Data flow

```
ticker set (watchlist pick / ?ticker= deep-link)
  -> useStock(ticker)  (existing: chart + summary)
  -> useScore(ticker)  GET /api/score/{ticker}
       -> score_one: score_stock(stock, mentions, cfg)
                     + (if network) compute_network_signal -> blend_network_into_score
       -> StockScore (network-blended, matches the board)
  -> <ScoreChip> in the summary header
Analyze with LLM button -> unchanged (separate useAnalyze path)
```

## Error handling / states

- **No data / bad ticker:** `score_one` raises → route 404 → `useScore` errors → chip not rendered (Dashboard otherwise fine). No error banner needed (non-critical).
- **Network disabled or `"all"` snapshot missing:** base technical score only (network state term effectively 0) — consistent with `run_analysis`.
- **Off-board ticker:** scores fine on-demand; `sector` may be `""`; the chip omits sector (it isn't shown in the chip anyway).
- **Ticker change:** `['score', ticker]` re-queries automatically; stale score never shown for the wrong ticker.

## Testing (TDD, repo-consistent)

**Backend**
- `blend_network_into_score`: given a `StockScore` (base_score/base_net) + a `NetworkSignal`, returns the blended score/net/direction/`components["network"]`/network — and `apply_network`'s existing tests still pass (proves the extraction is behavior-preserving).
- `score_one`: returns a base `StockScore` for a stubbed `get_stock_data` (no graph); blends when a focus graph + `"all"` snapshot with a source edge exist; best-effort `sector`; raises/propagates on a bad ticker.
- route `GET /api/score/{ticker}`: 200 returns a `StockScore`; with an overlay/graph present the blended value matches a board-style compute; 404 on a data failure — using `app.dependency_overrides[get_cache]` + a tmp `Cache` (repo pattern).

**Frontend**
- `ScoreBar` extraction: `DiscoverBoard.test.tsx` still passes (board renders).
- `ScoreChip`: renders score, call badge, reason chips; shows the 🔗 chip only when `network.reasons` is non-empty.
- `api/client.test.ts`: `getScore` hits `/score/{ticker}`.
- `Dashboard.test.tsx`: with `useScore` mocked to a `StockScore`, the chip renders on ticker load; with it erroring/empty, the Dashboard still renders.

## Build order

1. **`blend_network_into_score`** extraction in `analysis/network.py` + refactor `apply_network` to use it + test (board unchanged).
2. **`score_one`** in `screener/service.py` + tests (base + network-blended + degrade).
3. **Route** `GET /api/score/{ticker}` + tests (tmp `Cache`).
4. **Client + hook** (`getScore`, `useScore`) + client test.
5. **`ScoreBar`** extraction (shared component) + Discover still green.
6. **`ScoreChip`** component + test.
7. **Dashboard** wiring (render chip in summary) + CSS + test.
8. Final: `pytest` + `npx vitest run` + `npm run build` green.

## Caveats

- **Not financial advice.** The chip is the existing deterministic technical/network score, shown for convenience.
- **Recompute, not lookup.** `score_one` recomputes from cached data rather than reading the board row; numbers match because it uses the same `SCAN_PERIOD`, scorer, and blend. (A board-snapshot lookup was rejected — it misses off-board/un-scanned tickers.)
- **Network needs the daily artifacts.** The blend only tilts when the focus graph (`python -m app.network`) and the `"all"` snapshot exist; otherwise the base score shows. Same dependency as the board and the LLM path.
- **No new persistence.** The score is computed per request (cheap, no LLM); not cached beyond `get_stock_data`'s existing cache. (A short-TTL score cache is a possible later optimization — YAGNI now.)
