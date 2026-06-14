# Single-ticker rescan (per-row ⟳)

**Date:** 2026-06-14
**Status:** Approved design — ready for implementation plan

## Problem

The Discover (and Portfolio) board can only be rebuilt by a full "Rescan all" /
"Rescan portfolio", which re-scores the entire universe (minutes cold). There's no
way to refresh just one company whose price/news moved — you have to rescan
everything. We want a per-row **⟳** button that re-scores a single ticker, persists
it durably, patches that row in place, and records the ticker's technical/network
signal for evaluation.

## Decisions (locked)

- **Entry point:** a per-row ⟳ button on each board row.
- **Board update:** patch just that row and re-sort (no full refetch).
- **Persistence:** durable — write the fresh row back into the scope's saved snapshot.
- **Where:** the shared `ScoreBoard`, so it shows on **both** Discover and Portfolio.
- **Evaluation:** also record the rescanned ticker's technical/network signal to the
  prediction store, like the full rescan does for the portfolio.

## Approach

Reuse the existing single-ticker primitives rather than the SSE whole-universe stream:

- `score_one(ticker, settings, cache)` ([`backend/app/screener/service.py:117`](../../../backend/app/screener/service.py))
  already computes a single ticker's `StockScore` with the **same** network blending
  the board uses.
- `record_deterministic_pair(stock, settings, cache, store)`
  ([`backend/app/evaluation/signals.py:42`](../../../backend/app/evaluation/signals.py))
  already records the technical (and, when present, network) call for one ticker —
  it's the per-ticker body of `snapshot_watchlist`.
- `load_snapshot` / `save_snapshot` ([`backend/app/screener/store.py`](../../../backend/app/screener/store.py))
  persist boards keyed by scope.

So the work is: a small store helper to upsert one row, one new POST route that wires
these together, and the frontend button + hook + cache patch.

A streaming endpoint (extending `iter_scan`) was rejected: a progress bar for one
item is pointless, and `_persist_rescan`/`merge_sector` are built for whole-board /
sector merges, not a single row.

## Backend

### 1. `store.upsert_score(score, scope, cache) -> ScreenBoard`

New helper in [`backend/app/screener/store.py`](../../../backend/app/screener/store.py),
in the style of the existing `merge_sector`:

- `snap_scope = "portfolio" if scope == "portfolio" else "all"`.
- `board = load_snapshot(cache, snap_scope) or ScreenBoard(scope=snap_scope)`.
- Replace the item whose ticker matches `score.ticker` **case-insensitively**; if none
  matches, append it.
- Re-sort items by `score` descending (matches `iter_scan`'s ordering).
- `save_snapshot(board, cache)`; return the board.
- The board-level `as_of`/`scanned`/`skipped` are **left untouched** — the whole board
  wasn't rescanned, only one row. The row carries its own fresh `as_of` (set by
  `score_stock`).

### 2. `record_deterministic_pair(..., score=None)` — optional precomputed score

Small backward-compatible refactor in
[`backend/app/evaluation/signals.py`](../../../backend/app/evaluation/signals.py):
add a keyword-only `score: StockScore | None = None` parameter; the body uses
`score = score if score is not None else score_one(stock.ticker, settings, cache)`.
This lets the new route pass the score it already computed instead of scoring the
ticker a second time. Existing call site (`snapshot_watchlist`) is unchanged.

### 3. Route `POST /api/screen/rescan/{ticker}`

New route in [`backend/app/api/routes.py`](../../../backend/app/api/routes.py),
near `screen_rescan` / `get_score`:

```python
@router.post("/screen/rescan/{ticker}", response_model=StockScore)
def rescan_ticker(
    ticker: str,
    scope: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> StockScore:
    """Re-score one ticker (no LLM), persist it into the scope's saved snapshot, and
    record its technical/network signal for evaluation. Returns the fresh score so the
    board patches the single row in place."""
    settings = store.load()
    sym = ticker.upper().strip()
    try:
        stock = get_stock_data(sym, SCAN_PERIOD, settings.indicator_params, cache)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    score = score_one(sym, settings, cache)
    upsert_score(score, scope, cache)
    if settings.evaluation.enabled and stock.candles:
        try:
            record_deterministic_pair(stock, settings, cache, prediction_store, score=score)
        except Exception:  # noqa: BLE001 — eval recording is best-effort
            logger.warning("single-rescan eval recording failed for %s", sym)
    return score
```

- 404 on no-data, same convention as `GET /score/{ticker}`.
- Eval recording is gated on `settings.evaluation.enabled` (matching
  `POST /evaluation/snapshot`) and is best-effort — a recording failure never fails
  the rescan.
- The ticker is recorded regardless of watch status — the user explicitly asked to
  refresh *this* row, so its signal should land on the Evaluation page.

## Frontend

### 4. API client

[`frontend/src/api/client.ts`](../../../frontend/src/api/client.ts):

```ts
rescanTicker: (ticker: string, scope?: string) =>
  http<StockScore>(
    `/screen/rescan/${encodeURIComponent(ticker)}${scope ? `?scope=${scope}` : ''}`,
    { method: 'POST' },
  ),
```

### 5. Hook `useRescanTicker(scope?)`

New hook in [`frontend/src/hooks/queries.ts`](../../../frontend/src/hooks/queries.ts):
a mutation `mutationFn: (ticker) => api.rescanTicker(ticker, scope)` whose `onSuccess`
patches every cached `['screen', …]` query via
`qc.setQueriesData({ queryKey: ['screen'] }, …)`:

- For each cached `ScreenBoard`, map `items`: replace the row whose ticker matches the
  fresh score (case-insensitive) with the fresh `StockScore`; leave boards that don't
  contain the ticker unchanged.
- Re-sort the patched board's `items` by `score` descending.
- No refetch / no `invalidateQueries` — matches the "patch just that row" decision.

The in-flight ticker is exposed for the spinner: `rescanning = mut.isPending ? mut.variables ?? null : null`.

### 6. `ScoreBoard` per-row ⟳ button

[`frontend/src/components/ScoreBoard.tsx`](../../../frontend/src/components/ScoreBoard.tsx):
two new optional props:

```ts
/** Re-score a single row. Omit to hide the per-row ⟳ button. */
onRescan?: (t: string) => void;
/** Ticker currently being rescanned — that row's ⟳ shows a spinner and is disabled. */
rescanning?: string | null;
```

In the actions cell (alongside ★/×), when `onRescan` is set, render a ⟳ button:

- `onClick` calls `e.stopPropagation()` then `onRescan(s.ticker)` — so clicking it does
  **not** trigger the row's deep-dive navigation.
- Disabled when `rescanning === s.ticker`; shows a spinner glyph (e.g. ⟳ → ⏳ / a
  spinning class) in that state.
- `title` / `aria-label`: "Rescan {ticker}".

### 7. Wire into pages

- [`frontend/src/pages/Discover.tsx`](../../../frontend/src/pages/Discover.tsx):
  `const rescanOne = useRescanTicker();` (scope `all`) → pass
  `onRescan={(t) => rescanOne.mutate(t)}` and
  `rescanning={rescanOne.isPending ? rescanOne.variables ?? null : null}` to `ScoreBoard`.
- [`frontend/src/pages/Portfolio.tsx`](../../../frontend/src/pages/Portfolio.tsx):
  `const rescanOne = useRescanTicker('portfolio');` → pass the same `onRescan` /
  `rescanning` to **both** the Watchlist and Extended `ScoreBoard`s (one mutation
  instance; the spinner lights up whichever board holds the in-flight ticker).

## Data flow

```
click ⟳ on row  →  useRescanTicker.mutate(ticker)
                 →  POST /api/screen/rescan/{ticker}?scope=…
                       score_one(ticker)            # fresh, network-blended
                       upsert_score(score, scope)   # durable: into saved snapshot, re-sorted
                       record_deterministic_pair    # technical + network → prediction store
                       → returns fresh StockScore
                 →  onSuccess: setQueriesData(['screen']) replace row + re-sort
                 →  row updates in place; spinner clears
```

## Error handling

- No data for ticker → 404 → mutation `isError`; the row stays as-is. (Optional: a small
  inline error; not required for v1 — the button just re-enables.)
- Eval recording failure → logged, swallowed; the rescan still succeeds and returns the
  score.
- Network signal failure inside `score_one` → already degrades to the base technical
  score (existing best-effort behavior).

## Testing

**Backend**
- `upsert_score`: replaces an existing row, appends a new one, re-sorts by score,
  creates a fresh board when no snapshot exists, and routes `portfolio` vs `all` scope
  to the right snapshot key.
- `record_deterministic_pair(score=…)`: uses the precomputed score (does not call
  `score_one` again — assert via a spy/monkeypatch).
- Route `POST /screen/rescan/{ticker}`: 200 returns the fresh score and persists it into
  the snapshot; records technical/network predictions when evaluation is enabled; skips
  recording when disabled; 404 on a bad ticker; uses the test conftest's sandboxed
  `DATA_DIR`.

**Frontend**
- `useRescanTicker`: `onSuccess` replaces the row in a cached `['screen']` board and
  re-sorts; leaves boards without the ticker untouched.
- `ScoreBoard`: renders ⟳ only when `onRescan` is given; ⟳ click calls `onRescan` and
  does not navigate (stopPropagation); the in-flight row's ⟳ is disabled/spinning when
  `rescanning === ticker`.
- `client.test.ts`: `rescanTicker` issues `POST /screen/rescan/{TICKER}` with the scope
  query when given.

## Non-goals

- No whole-board network re-blend — only the rescanned row's stored score changes; its
  neighbors' stored scores are not recomputed.
- No streaming / progress UI — a single ticker is fast; a spinner on the row is enough.
- No change to the board-level `as_of` header (that still reflects the last full scan).
- No UI confirmation toast for the eval recording — it's a silent best-effort side
  effect that surfaces on the Evaluation page.
