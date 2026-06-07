# LLM Recommendation Evaluation — Design

- **Date:** 2026-06-07
- **Status:** Approved
- **Scope:** New backend subsystem (`app/evaluation/`, mirroring `app/alerts/`,
  `app/screener/`, `app/network/`) + one new frontend page (`/evaluation`). Adds two
  SQLite tables, one `Settings` sub-config, a recording side-effect on the existing
  `/analyze` route, two new read/action endpoints, a CLI runner, and the page.

## Overview

Today every "Analyze with LLM" run is computed on the fly and cached for only 24h, then
gone — there is **no record** of what the LLM recommended or when. This feature starts
**recording** each call (recommendation, confidence, the price + trading date at that
moment), later fetches what the price actually did at **1, 5, and 20 trading days**, judges
whether each call was right, and **scores** it. A new **Evaluation** page tracks many
companies — each with its hit-rate, average score, an at-a-glance grade, and its individual
calls — plus an on-demand button that asks the LLM **why** a bad call went wrong.

This makes the app's core promise auditable: if it said SELL and the price rose, the call is
marked a miss and the company's score drops.

## Locked decisions

| Decision | Choice |
|---|---|
| Capture trigger | **Auto-record on every analyze.** Recording is a silent side-effect of `POST /analyze/{ticker}`; no user action, no frontend change to trigger it. One record per `(ticker, call_date)` — re-analyzing the same day upserts (latest wins). |
| Evaluation timing | **Both.** A single `evaluate_pending()` service is called (a) lazily by `GET /api/evaluation` before returning the board, and (b) by a CLI `python -m app.evaluation` for unattended/batch runs. |
| Horizons | **Multiple: 1, 5, 20 trading days.** Configurable list. Once a horizon matures, its verdict is computed once and stored as **final** (never drifts). |
| LLM post-mortem | **On-demand per call.** A button on a missed call runs ONE LLM "why was this wrong?" call; the result is cached so it runs once per call. |
| Storage shape | **Two normalized SQLite tables** (`predictions`, `prediction_evals`) in the app DB (same `DB_PATH` as `alert_log`), via a `PredictionStore` mirroring `AlertState`. Post-mortems cache in the existing `cache` table (no new table). |
| Scoring | Per call × horizon: `return_pct`, a binary `hit` (buy⇢up / sell⇢down / hold⇢flat), and a magnitude-aware `score` 0–100 (50 = neutral). Confidence is a **separate calibration stat**, not folded into the per-call score. |
| Page | Route `/evaluation`, nav "Evaluation". Summary board (one row per company) + expandable per-company calls with per-horizon outcome chips. Reuses existing `.board` / `.badge` / `.score-bar` / `.panel` styles. |
| Config | New `EvaluationConfig` on `Settings` (no secrets → no masking): `enabled`, `horizons`, `hold_band_pct`, `score_scale_pct`. |

## Current state (verified by reading the code)

- **Analysis is not persisted.** `run_analysis(ticker, period, settings, cache)` in
  `backend/app/services/analysis_service.py` computes an `AnalysisResult` and caches the
  JSON for 24h (`ANALYSIS_TTL_SECONDS`); the cache-hit path returns early before building
  `stock`. The fresh path (after the early return) has both `stock` (a `StockData`) and
  `result` (an `AnalysisResult`) in scope.
- **`AnalysisResult`** (`backend/app/models/schemas.py`) fields used here: `ticker`,
  `provider`, `model`, `current_recommendation` (`buy|sell|hold`), `confidence` (0..1),
  `sentiment` (`bullish|neutral|bearish`).
- **`StockData`** carries `candles: list[Candle]` (each `Candle` has `time` = `YYYY-MM-DD`
  trading day and `close`) and `price`. The **last candle** gives an unambiguous,
  trading-day-aligned call date and entry price.
- **Price history:** `fetch_history(ticker, period="2y")` in `backend/app/data/market.py`
  returns a daily OHLCV DataFrame indexed by trading day. Indexing the candle/date series
  lets us find the close `h` trading days after the call date.
- **Storage precedent:** `AlertState` (`backend/app/alerts/state.py`) opens
  `sqlite3.connect(db_path)`, sets `PRAGMA busy_timeout = 5000`, `CREATE TABLE IF NOT
  EXISTS`, and uses `INSERT OR REPLACE`. `DB_PATH`, `DATA_DIR`, `get_cache`,
  `get_settings_store` live in `app/deps.py`.
- **CLI precedent:** `python -m app.alerts` (`backend/app/alerts/__main__.py`) builds deps
  from `app.deps`, runs a `run_*()` function, logs a summary dict. `app/screener` and
  `app/network` follow the same shape.
- **Settings:** single JSON row; sub-configs (`alerts`, `screener`, `network`,
  `truth_signal`) are nested Pydantic models with `Field(default_factory=...)`.
- **Frontend:** routes in `frontend/src/App.tsx`; api methods in `frontend/src/api/client.ts`
  (`http<T>` helper); hooks in `frontend/src/hooks/queries.ts`; types in
  `frontend/src/types.ts`; board styling on `.board` (table), `.badge.buy/.sell/.hold`,
  `.score-bar`, `.panel`. `DiscoverBoard.tsx` is the closest table precedent.

## Design

### Data model

Two relational tables in the app SQLite DB (`DB_PATH`), created by `PredictionStore`:

**`predictions`** — one row per analyzed call:

```sql
CREATE TABLE IF NOT EXISTS predictions (
  ticker TEXT,
  call_date TEXT,          -- last candle date at analyze time (YYYY-MM-DD, a trading day)
  provider TEXT,
  model TEXT,
  recommendation TEXT,     -- buy | sell | hold
  confidence REAL,         -- 0..1
  sentiment TEXT,          -- bullish | neutral | bearish
  entry_price REAL,        -- close on call_date
  created_at REAL,         -- unix ts
  PRIMARY KEY (ticker, call_date)
)
```

**`prediction_evals`** — one row per (prediction, horizon), written when that horizon matures:

```sql
CREATE TABLE IF NOT EXISTS prediction_evals (
  ticker TEXT,
  call_date TEXT,
  horizon INTEGER,         -- trading days (e.g., 1, 5, 20)
  eval_date TEXT,          -- trading day = call_date + horizon
  exit_price REAL,         -- close on eval_date
  return_pct REAL,         -- (exit - entry) / entry * 100
  hit INTEGER,             -- 0 | 1
  score REAL,              -- 0..100
  PRIMARY KEY (ticker, call_date, horizon)
)
```

A horizon's row exists **only once it has matured**; a missing row = "pending". Because the
unit of work is "compute a missing matured horizon," evaluation is naturally idempotent.

LLM post-mortems are **not** a table — they cache in the existing `cache` table under key
`prediction_explain:{TICKER}:{call_date}` with a long TTL.

### `EvaluationConfig` (new, on `Settings`)

```python
class EvaluationConfig(BaseModel):
    enabled: bool = True
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 20])
    hold_band_pct: float = 2.0     # |return%| <= this is "flat" (the hold target)
    score_scale_pct: float = 5.0   # the move size (in %) that maps to a full 0 or 100
```

Added to `Settings` as `evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)`.
No secrets, so no masking in the settings round-trip.

### Capture flow (automatic)

Recording happens inside `run_analysis`, on the **fresh-compute path only** (where both
`stock` and `result` exist). Signature gains an optional, backward-compatible parameter:

```python
def run_analysis(ticker, period, settings, cache, prediction_store=None) -> AnalysisResult:
    ...
    # cache-hit path returns early — no recording needed (already recorded earlier today)
    ...
    result = analyze(stock, provider, model=cfg.model, provider_name=provider_id)
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    if prediction_store is not None and settings.evaluation.enabled:
        try:
            record_prediction(stock, result, prediction_store)
        except Exception:
            logger.warning("prediction recording failed for %s", ticker)  # degrade silently
    return result
```

- The `/analyze` route obtains the store from `app.deps.get_prediction_store()` and passes
  it. Existing `run_analysis` callers/tests that omit the param are unaffected (no recording).
- `record_prediction(stock, result, store)` builds the row from the **last candle**:
  `call_date = stock.candles[-1].time`, `entry_price = stock.candles[-1].close`, plus
  `result.current_recommendation / confidence / sentiment / provider / model`, then upserts.
- **Upsert semantics:** `INSERT OR REPLACE` on `(ticker, call_date)`. If an existing row's
  `entry_price` differs from the new one, delete that prediction's `prediction_evals` rows
  first (defensive — within a single day `entry_price` is identical and no horizon has
  matured, so in practice this never discards real verdicts).
- Cache-hit path does not record: a same-day repeat already has its row. Switching provider
  changes the cache key → fresh path → upsert updates provider/model/recommendation.

### Evaluation flow (lazy + CLI)

One service function does the work; two triggers call it.

```python
def evaluate_pending(store, cache, settings) -> dict:
    """For every prediction with a not-yet-matured horizon, fetch history once per ticker,
    and for each configured horizon whose eval row is missing, find the close at
    call_date + horizon trading days. If found, compute and store a FINAL eval row.
    If not enough trading days exist yet, leave it pending. Per-ticker try/except so a
    single bad fetch never breaks the run; pending rows are retried on the next run."""
```

- **Maturity & indexing:** fetch `fetch_history(ticker, period)` once per ticker (period
  wide enough to cover the oldest pending call, e.g. `"2y"`), take the sorted list of
  trading-day dates, find the index of `call_date`, and read the close at `index + horizon`.
  If that index exists → matured → compute & store. Else → pending.
- **Triggers:**
  - **Lazy:** `GET /api/evaluation` calls `evaluate_pending(...)` then `build_board(...)`.
  - **CLI:** `python -m app.evaluation [--dry-run]` builds deps from `app.deps`, calls
    `evaluate_pending(...)`, logs the summary dict. `--dry-run` computes but does not persist.
- **Cost in steady state:** only missing-and-matured horizons are computed; already-final
  rows are skipped, so a typical page load scores just a few newly-matured horizons.

### Scoring

For a matured `(prediction, horizon)` let `r` = `return_pct` (percent, e.g. `3.0` = +3%),
`b` = `hold_band_pct` (default 2.0), `s` = `score_scale_pct` (default 5.0).

**Hit (binary), matching the user's mental model:**
- `buy`  → hit if `r > 0`
- `sell` → hit if `r < 0`
- `hold` → hit if `abs(r) <= b`

**Score (0–100), magnitude-aware, `50` = neutral / at the hit boundary:**
- directional (`buy`/`sell`): `aligned = (+1 if buy else -1) * r`; `score = clamp(50 + 50 * (aligned / s), 0, 100)`.
  A correct move of size `s` → 100; a wrong move of size `s` → 0; no move → 50.
- `hold`: `closeness = (b - abs(r)) / b`; `score = clamp(50 + 50 * closeness, 0, 100)`.
  Perfectly flat → 100; `abs(r) = b` → 50; `abs(r) = 2b` → 0.

**Per-company rollup** (`CompanyRollup`), over that company's **matured** evals:
- `n_calls` (predictions), `n_matured` (matured eval rows)
- `hit_rate` = hits / n_matured (percent)
- `avg_score` = mean(score)
- `grade` from `avg_score`: **Strong** if `>= 60`, **Weak** if `<= 40`, else **Mixed**
  (thresholds are documented constants in the scoring module; green/red/gold respectively)
- `overconfident` (bool): `True` when mean confidence on **misses** `>=` mean confidence on
  **hits** (with ≥1 of each) — the calibration "indication" the user asked for.

### API surface

Endpoints added under `/api` (in the existing routes module or a small evaluation router
included by `app/main.py`):

- `GET /api/evaluation` → `EvaluationBoard`. Runs `evaluate_pending` first, then returns
  `{ as_of, companies: CompanyEvaluation[] }` where each `CompanyEvaluation` =
  `{ rollup: CompanyRollup, calls: PredictionRecord[] }` and each `PredictionRecord` =
  `{ ticker, call_date, provider, model, recommendation, confidence, sentiment,
  entry_price, results: HorizonResult[] }`, `HorizonResult` =
  `{ horizon, status: "pending"|"final", eval_date?, return_pct?, hit?, score? }`.
- `POST /api/evaluation/{ticker}/{call_date}/explain` → `{ explanation: str }`. Rebuilds
  context (the call, the realized per-horizon returns, news around the window) and asks the
  active LLM for a short "why this was likely wrong"; caches the result. Reuses the existing
  provider plumbing (`build_provider`, `complete(system, user)`).
- `DELETE /api/evaluation/{ticker}` → `{ deleted: int }`. Clears that company's
  `predictions` + `prediction_evals` rows (stop tracking / cleanup). Reversible — analyzing
  again starts a fresh record.

### Frontend page (`/evaluation`, nav "Evaluation")

- **Route + nav:** add `<Route path="/evaluation" element={<Evaluation />} />` in `App.tsx`
  and a `NavLink` "Evaluation" in the masthead.
- **Data:** `useEvaluation()` query (`api.getEvaluation()`), `useExplainPrediction()`
  mutation (`api.explainPrediction(ticker, callDate)`), `useDeleteTracked()` mutation
  (`api.deleteTracked(ticker)`, invalidates `['evaluation']`).
- **Layout:**
  - **Summary board** (`.board` table): one row per company — ticker, # calls, hit-rate,
    `score-bar` for avg score, a grade `.badge` (Strong/Mixed/Weak), an "overconfident"
    flag, and the latest recommendation badge. Row click expands that company.
  - **Per-company detail:** the company's calls, each showing the recommendation `.badge`,
    confidence, and **three per-horizon outcome chips** (1d / 5d / 20d): a pending chip, or
    a ✓/✗ with the return %. An **"Explain miss"** button shows on calls that have at least
    one matured miss; clicking it loads the cached/produced post-mortem inline. A small
    "stop tracking" control per company calls `useDeleteTracked`.
  - **Empty state:** "No tracked calls yet — analyze a company on the Dashboard to start."
- **Types** (`types.ts`): `HorizonResult`, `PredictionRecord`, `CompanyRollup`,
  `CompanyEvaluation`, `EvaluationBoard`.

### File structure

Backend (new `app/evaluation/` package, mirroring `app/alerts/`):
- `backend/app/evaluation/__init__.py`
- `backend/app/evaluation/store.py` — `PredictionStore(db_path)`: table DDL, `upsert`,
  `record_eval`, query helpers (`all_predictions`, `evals_for`, `delete_ticker`).
- `backend/app/evaluation/scoring.py` — pure `hit(...)`, `score(...)`, `grade(...)`,
  `rollup(...)`; grade-threshold constants.
- `backend/app/evaluation/service.py` — `record_prediction`, `evaluate_pending`,
  `build_board`, `explain_prediction`.
- `backend/app/evaluation/runner.py` — thin `run_evaluation(...)` used by the CLI.
- `backend/app/evaluation/__main__.py` — `python -m app.evaluation [--dry-run]`.

Backend (modify):
- `backend/app/models/schemas.py` — `EvaluationConfig` + the response models + add
  `evaluation` to `Settings`.
- `backend/app/services/analysis_service.py` — optional `prediction_store` param + record.
- `backend/app/deps.py` — `get_prediction_store()` singleton.
- `backend/app/api/routes.py` (+ `app/main.py` if a new router) — the three endpoints; wire
  the store into the `/analyze` route.

Frontend (new):
- `frontend/src/pages/Evaluation.tsx`
- `frontend/src/components/EvaluationBoard.tsx` (summary table; keeps the page lean)
- test files alongside (see Testing).

Frontend (modify):
- `frontend/src/App.tsx` (route + nav), `frontend/src/api/client.ts` (3 methods),
  `frontend/src/hooks/queries.ts` (3 hooks), `frontend/src/types.ts` (types),
  `frontend/src/styles.css` (outcome chips + any small additions).

## Edge cases

- **Re-analyze same day:** upsert keeps one row; entry identical, no matured horizon yet → no
  data loss.
- **Switch provider/model:** different analysis cache key → fresh path → upsert updates
  provider/model/recommendation for that `(ticker, call_date)` (latest wins).
- **Weekends/holidays:** call_date is always a trading day (last candle); horizons are
  trading-day offsets via the candle index, so calendar gaps are handled naturally.
- **Not enough history yet:** horizon stays pending; retried each run until it matures.
- **Fetch failure / delisting during eval:** that ticker is skipped (try/except), nothing
  bogus stored; retried next run.
- **Hold exactly at the band edge** (`abs(r) == b`): counts as a hit; score = 50.
- **No matured evals for a company:** rollup shows counts with hit-rate/avg-score as "—"
  (not 0) and grade hidden until there is ≥1 matured eval.
- **Explain on a call with no miss:** the button is not shown (only appears when ≥1 matured
  horizon is a miss).

## Error handling

- Recording failures never break `/analyze` (wrapped, logged, swallowed).
- `evaluate_pending` is per-ticker fault-isolated; the board still renders for healthy
  tickers.
- `GET /api/evaluation` returns an empty `companies` list (not an error) when nothing is
  tracked yet.
- Frontend surfaces query/mutation errors as inline `.error` lines (mirrors Dashboard).

## Out of scope (v1)

- Per-provider / per-model breakdown of rollups (provider/model are stored, not split out).
- A dedicated Settings UI section for `EvaluationConfig` (editable via `PUT /settings`; no
  toggle card in v1).
- Intraday horizons, dividend/total-return adjustment, benchmark-relative scoring, CSV export.
- Folding confidence into the per-call score (kept as a separate calibration stat for v1).
- Backtesting over calls that were never actually made (only real recorded calls are scored).

## Testing

**Backend (pytest):**
- `scoring.py`: hit rules for buy/sell/hold incl. the `hold_band` edge; score mapping at
  `aligned = +s, 0, -s` and beyond (clamping); grade thresholds; `overconfident` calibration;
  rollup aggregation with mixed pending/final.
- `service.py`: `record_prediction` builds the row from the last candle and upserts (dedup);
  `evaluate_pending` matures only horizons with enough trading days, stores final rows, is
  idempotent on re-run, and skips a ticker whose fetch raises (monkeypatch `fetch_history`).
- `store.py`: table creation, upsert replace + child-eval clear on entry change, `delete_ticker`.
- API: `GET /api/evaluation` shape + lazy eval; `explain` caches; `DELETE` removes rows.
  Use a temp DB / `dependency_overrides` so tests don't touch the real `app.db`.
- `run_analysis` records when a store is passed and `evaluation.enabled`, and does **not**
  when the store is omitted (backward compat).

**Frontend (vitest + testing-library):**
- Board renders company rows with hit-rate, avg-score bar, grade badge.
- Expanding a company shows its calls with three horizon chips (pending vs ✓/✗ + return).
- "Explain miss" appears only on calls with a matured miss and renders the returned text.
- Empty state when `companies` is `[]`.

**Gates:** `pytest -q` (backend), `tsc --noEmit`, `vitest run`, `vite build` (frontend) — all green.
