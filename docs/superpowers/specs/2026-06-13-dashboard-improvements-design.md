# Dashboard Improvements — Design Spec

- **Date:** 2026-06-13
- **Status:** Proposed (awaiting review)
- **Author:** giri + Claude
- **Area:** `frontend/src` (Dashboard, TickerBar, SignalsStrip), `backend/app/services`, `backend/app/analysis`, `backend/app/api`, `backend/app/evaluation/store.py`

## 1. Summary

Four Dashboard-page improvements, three small and one moderate:

1. **NET "collecting data" wording (#1)** — frontend-only tooltip reword. The chip already
   shows the right call; the track-record tail just reads as "no data" when the real state is
   "recorded, not yet matured."
2. **Watchlist UI (#2)** — replace the inline wrapping chip row with a compact, collapsible,
   searchable dropdown so a long watchlist stays one line.
3. **Gold Deep Analysis button (#3)** — give the Deep Analysis button the same solid-gold
   resting style as the primary "Analyze with LLM" button.
4. **Durable last-analysis persistence + auto-restore (#4)** — the core item. Persist the full
   `AnalysisResult` per ticker and auto-restore it (read-only) on the Dashboard, so the
   Analysis panel, the "Signals — click for reasoning" list, and the chart buy/sell arrows all
   survive an app restart **without re-running** — viewing costs zero tokens and never records
   or affects evaluation. Also fixes a related eval-deletion footgun in the prediction store.

## 2. Background

- The full `AnalysisResult` (summary, `signals` → chart markers, reasoning) lives ONLY in
  in-memory React state (`frontend/src/state/dashboardState.tsx`, reset on full reload) and a
  24h backend cache (`run_analysis` in `app/services/analysis_service.py`, key
  `analysis:{ticker}:{provider}:{model}:{period}:{today}`) that the frontend never reads back.
- The persisted prediction store (`app/evaluation/store.py`) keeps only a compact record
  (recommendation/confidence/sentiment/entry_price), which is why the `SignalsStrip` survives a
  restart but the Analysis panel / signal list / chart arrows go blank
  (`Dashboard.tsx:154,166,179` all read `analysis?.signals`).
- `build_signals` (`app/evaluation/signals.py:142`) computes `hit_rate` from **matured evals
  only** (`store.all_evals()`); a call recorded today has no matured evals yet, so
  `SourceTrack.hit_rate` is `null` and `SignalsStrip.tsx:28` renders `· collecting data`.
  `SourceTrack` already carries `n_calls` and `n_matured`.
- `upsert_prediction` (`store.py:114`) deletes a call's `prediction_evals` whenever the entry
  price changes on re-record. For today's call that's harmless (nothing matured yet), but it
  silently wipes already-scored evals if the same `call_date` is re-recorded at a different
  price after maturing (e.g. a data revision, or a re-run while the last candle's date is
  unchanged). This is the "footgun."
- The deep path produces a full `AnalysisResult` rendered through the same chart-markers +
  `ReasoningPanel` path (`Dashboard.tsx:72`, `useDeepAnalyze`).

## 3. Goals / Non-goals

**Goals**
- Past analysis (text + signal reasoning + chart markers) visible on app start without
  re-running and without any token cost or evaluation side-effect.
- A long watchlist no longer overflows the command bar.
- Clear, honest NET tooltip wording.
- Deep Analysis button reads as gold.
- Re-running analysis can never destroy already-scored evals.

**Non-goals (this iteration)**
- No analysis history browser (we keep only the latest snapshot per ticker per source).
- No change to how analyses are computed, cached, or scored.
- No new evaluation horizons or scoring math.

## 4. Design

### 4.1 NET wording (#1) — frontend only

In `SignalsStrip.tsx`, replace the `· collecting data` branch. Reaching it implies
`n_calls ≥ 1`, so show the real state from `SourceTrack`:

- matured: `· {hit_rate}% hit rate over {n_matured} scored` (unchanged)
- recorded, none matured: `· {n_matured} of {n_calls} scored — awaiting maturity`

MSFT then reads `NET: HOLD on 2026-06-12 · 0 of 1 scored — awaiting maturity`. No backend
change. Add a `SignalsStrip.test.tsx` case for the unmatured branch.

### 4.2 Watchlist dropdown (#2)

New `frontend/src/components/WatchlistMenu.tsx`, used by `TickerBar` in place of the inline
`.watch` row:

- Trigger: `Watchlist (N) ▾` button (`aria-expanded`, `aria-haspopup`). Disabled and showing
  `Watchlist (0)` when empty.
- Popover (absolute, anchored under the trigger): a type-to-filter text input + a
  scrollable list capped to ~8 rows then scroll. Each row = ticker; clicking selects and
  closes; a trailing `×` removes (does not close). Current ticker highlighted.
- Closes on `Escape` and outside-click (a `mousedown` document listener gated on open).
- Props mirror today's `TickerBar` (`watchlist`, `current`, `onSelect`, `onRemove`); the ☆/★
  star and Analyze/Deep buttons stay in `TickerBar` unchanged.
- CSS added under the existing `.tickerbar` block in `styles.css`, reusing
  `--panel-brd`/`--gold-tint`/`--gold-line`.
- Tests in `TickerBar.test.tsx` (or a new `WatchlistMenu.test.tsx`): opens, filters, selects,
  removes without closing, closes on Escape and outside-click, empty-state disabled.

### 4.3 Gold Deep Analysis button (#3)

The Deep Analysis button in `TickerBar.tsx` currently has `className="secondary"` (grey
outline). Drop `secondary` so it inherits the default solid-gold `button` style, matching
"Analyze with LLM". Keep its `title` and the `Deep analyzing…` label for differentiation. No
CSS change needed. Update the `TickerBar.test.tsx` assertion if it keys on the class.

### 4.4 Durable last-analysis store + auto-restore (#4)

**Backend — new snapshot store (separate from the eval store)**

- New module `app/services/analysis_snapshot_store.py` with `AnalysisSnapshotStore`, backed by
  its own sibling SQLite file `analysis_snapshots.db` under `DATA_DIR` (kept separate from the
  eval store so "never touches evaluation" holds at the storage layer):
  - `analysis_snapshots(ticker TEXT, source TEXT, call_date TEXT, period TEXT, provider TEXT,
    model TEXT, created_at REAL, result_json TEXT, PRIMARY KEY (ticker, source))`
  - `upsert(ticker, source, call_date, period, provider, model, result)` — `INSERT OR REPLACE`.
  - `latest(ticker)` — the most-recent row across sources for a ticker, or `None`.
  - Same locking pattern as `PredictionStore` (single shared connection + `threading.Lock`).
  - An `@lru_cache` singleton accessor `get_analysis_snapshot_store()`, FastAPI dependency
    `get_analysis_snapshot_store` with a test override (mirrors `get_prediction_store`).
- Writes are **best-effort** (try/except, "must never break analysis"), wired in:
  - `run_analysis` — both the fresh-compute path and the cache-hit path upsert
    `source="llm_fast"`.
  - The deep path's final-result handler (in `app/api/routes.py` deep stream) upserts
    `source="llm_deep"`.
- New endpoint `GET /api/analysis/{ticker}` → `200` with body `LastAnalysis | null`:
  `{ result: AnalysisResult, source, call_date, created_at }`, or JSON `null` when there is no
  snapshot (200, not 204, so the `useQuery` client gets a clean parseable body). Pure read — no
  compute, no recording. New `LastAnalysis` schema (`response_model=Optional[LastAnalysis]`).

**Frontend — auto-restore**

- `api.getLastAnalysis(ticker)` + `useLastAnalysis(ticker)` query (`['analysis', ticker]`,
  `retry: false`, enabled when ticker set). Invalidate `['analysis', ticker]` from
  `useAnalyze`/deep success so a fresh run refreshes the snapshot.
- In `Dashboard.tsx`, compute `shown = analysis ?? restored?.result` where `restored` is the
  query data. The Analysis panel, the chart `signals`, and the "Signals — click for reasoning"
  list all read `shown` instead of `analysis`. `selected` (signal click) keys off `shown`.
- When `analysis` is null but `restored` exists, render a subtle header badge in the Analysis
  panel: `Last analysis · as of {call_date} · {fast|deep}`. Running Analyze/Deep sets
  `analysis` and the badge disappears (fresh result wins).
- Ticker change resets `analysis`/`selected` as today; the query key swap makes `restored`
  follow the new ticker automatically.
- Tests: `useLastAnalysis` hook; `Dashboard.test.tsx` — restored analysis fills panel + markers
  + signal list when in-session analysis is null; the "as of" badge shows only when restored;
  a fresh run overrides and hides the badge.

**Backend — footgun fix (eval immutability)**

- In `upsert_prediction`, make a prediction **immutable once it has any matured eval**: if a row
  for `(ticker, call_date, source)` already exists AND a `prediction_evals` row exists for it,
  the re-record is a **no-op** (entry/recommendation unchanged, evals preserved). Otherwise
  upsert normally. This removes the entry-change `DELETE FROM prediction_evals` branch — when no
  evals exist it deleted nothing anyway, and when they exist we now preserve them.
- Rationale: re-running analysis must never destroy scored history. Correcting an entry after
  scoring is better served by an explicit re-evaluation than a silent side-effect.
- Tests in `test_evaluation_record.py`/store tests: re-record at a different price *after* an
  eval exists → eval preserved + entry unchanged; re-record *before* any eval → entry updates
  (nothing to lose); update any existing test that asserted the delete-on-entry-change behavior.

## 5. Data flow (item #4)

```
Click Analyze ─▶ run_analysis ─▶ AnalysisResult
                     │                 ├─▶ record_prediction (eval store; immutable-once-scored)
                     │                 └─▶ snapshot_store.upsert(fast)   [best-effort]
                     ▼
            (cache 24h)            Dashboard sets in-session `analysis` (wins)

App restart / fresh load ─▶ useLastAnalysis(ticker) ─▶ GET /api/analysis/{ticker}
                                                          └─▶ snapshot_store.latest()
        Dashboard `shown = analysis ?? restored.result` ─▶ panel + markers + signal list + badge
        (pure read: zero tokens, no recording, no eval impact)
```

## 6. Error handling

- Snapshot write failures are caught and logged; analysis still returns (parity with
  `_record_calls`).
- `GET /api/analysis/{ticker}` returns `null` cleanly when no snapshot exists; the hook is
  `retry: false` and the Dashboard treats absence as "no restored analysis" (panel shows the
  existing "Click Analyze…" empty state).
- A malformed/old `result_json` that fails `AnalysisResult.model_validate_json` is treated as
  no snapshot (logged), never a 500.

## 7. Testing summary

- Backend: snapshot store upsert/latest; `GET /api/analysis/{ticker}` (hit + null);
  `run_analysis` writes a snapshot on both compute and cache-hit; snapshot write failure does
  not break analysis; immutable-once-scored upsert behavior.
- Frontend: `SignalsStrip` unmatured wording; `WatchlistMenu` open/filter/select/remove/close;
  Deep Analysis button class; `useLastAnalysis`; `Dashboard` restore + badge + fresh-run override.

## 8. Files touched (anticipated)

- `frontend/src/components/SignalsStrip.tsx` (+test)
- `frontend/src/components/WatchlistMenu.tsx` (new, +test), `TickerBar.tsx` (+test), `styles.css`
- `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`, `frontend/src/types.ts`
- `frontend/src/pages/Dashboard.tsx` (+`Dashboard.test.tsx`)
- `backend/app/services/analysis_snapshot_store.py` (new, +test)
- `backend/app/services/analysis_service.py`, `backend/app/api/routes.py`,
  `backend/app/models/schemas.py`
- `backend/app/evaluation/store.py` (+ store/record tests)
