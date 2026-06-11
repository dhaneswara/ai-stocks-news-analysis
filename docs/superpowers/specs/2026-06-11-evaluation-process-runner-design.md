# Evaluation Process Runner — Design

- **Date:** 2026-06-11
- **Status:** Approved
- **Scope:** One new SSE endpoint (`GET /api/analyze/watchlist/stream`) + one new frontend
  command-bar component on the Evaluation page with four process buttons. Reuses the
  existing snapshot/rescan endpoints and the existing per-ticker analysis/agent services;
  no schema/table changes.

## Overview

Every signal source the Evaluation page scores has a different trigger today, scattered
across the app: technical/network calls are snapshotted only as a side-effect of
Discover's **Rescan all**, and LLM calls (fast and deep) are produced one company at a
time on the Dashboard. Feeding the scoreboard for a 10-ticker watchlist means visiting
two pages and clicking through every company.

This feature puts a **command bar at the top of the Evaluation page** with one button per
process, each operating on the whole watchlist:

1. **Snapshot technical/network** — record today's deterministic BUY/SELL/HOLD calls
   (existing endpoint).
2. **Fast LLM analysis** — run the single-shot LLM analysis for every watchlist ticker.
3. **Deep LLM analysis** — run the agentic deep analysis for every watchlist ticker.
4. **Full Discover rescan** — rebuild the S&P 500 board, then snapshot (the same chain
   Discover runs).

The two LLM batches stream per-ticker progress live to the page and **skip tickers that
already have a call recorded for the latest trading day**, so re-clicking after a partial
failure resumes where it left off instead of burning tokens.

## Locked decisions

| Decision | Choice |
|---|---|
| Which processes | **All four buttons** (user choice): technical/network snapshot, fast LLM batch, deep LLM batch, full Discover rescan. |
| Re-run policy | **Skip already-done.** A ticker is skipped when a prediction with the **matching source** exists for its **last candle date** (`llm_fast` for fast mode, `llm_deep` for deep mode — a deep call never suppresses a fast call or vice versa; the fast-vs-deep comparison needs both). No force-rerun UI; the Dashboard remains the per-ticker escape hatch. |
| Batch architecture | **One backend SSE endpoint**, mode-parameterized (`fast`/`deep`). Skip logic lives where the prediction store and candle dates live. Frontend mirrors the existing `streamDeepAnalysis` EventSource pattern. |
| Execution | **Sequential, one ticker at a time** — avoids provider rate limits, keeps progress legible. |
| Concurrency guard | **One process at a time, frontend-enforced**: all four buttons disable while any run is pending. No backend lock (single-user app; upserts are idempotent anyway). |
| Period | `"2y"` — the existing backend default for both `/analyze/{ticker}` and the deep stream. |
| Mid-run stop | A **Stop** button while an LLM batch runs closes the EventSource; the in-flight ticker completes server-side and records, remaining tickers are not started. Skip-already-done makes a later re-click resume from the gap. |
| Evaluation disabled | The LLM batch endpoint emits a run-level `error` event and runs nothing — these buttons exist to feed the scoreboard; analyses that can't record would waste tokens. |

## Current state (verified by reading the code)

- **Snapshot exists:** `POST /api/evaluation/snapshot` (`routes.py`) →
  `snapshot_watchlist(settings, cache, store)` (`app/evaluation/signals.py`) records the
  technical + network call per watchlist ticker with per-ticker fault isolation and
  returns `{recorded, skipped[]}`; returns `{..., disabled: true}` when
  `settings.evaluation.enabled` is false. Frontend hook `useSnapshotEvaluation()` and type
  `SnapshotResult` exist; Discover chains it after `useRescan()`.
- **Fast path:** `run_analysis(ticker, period, settings, cache, prediction_store)`
  (`app/services/analysis_service.py`) pre-flights provider config (raises `LLMError`),
  caches per `(ticker, provider, model, period, today)` for 24h, and on the fresh path
  records `llm_fast` + the deterministic pair. **The cache-hit path returns early and
  records nothing** (the first fresh run already recorded).
- **Deep path:** `GET /analyze/{ticker}/deep/stream` builds
  `gather_stock_context(...)` + `ToolContext` + `ReActAgent`, iterates
  `agent.stream(provider, cfg.model, provider_id, ctx)` yielding `AgentEvent`s
  (`step`/`final`/`error`), and on `final` calls `_persist_deep_final(event, stock,
  settings, cache, prediction_store, trace_store)` (`routes.py`) — persists the trace,
  records the prediction as `llm_deep` (or honestly `llm_fast` when the trace shows
  `fell_back`/is missing), and records the deterministic pair. SSE serialization via
  `_sse(event)`.
- **Skip primitive:** `PredictionStore.get_prediction(ticker, call_date, source)`
  (`app/evaluation/store.py`) returns the row or `None`. Source constants
  `SOURCE_LLM_FAST` / `SOURCE_LLM_DEEP` live there.
- **Call-date convention:** predictions are keyed by the **last candle's** `time`
  (`record_prediction`, `record_deterministic_pair`) — the latest trading day, not the
  calendar day. The skip check must use the same key, hence fetching stock data first.
- **Rescan:** `POST /api/screen/rescan` (no body; optional `sector` query). Frontend
  `useRescan()` exists; Discover's button runs
  `rescan.mutate(sector, { onSuccess: () => snapshot.mutate() })`.
- **Route shape safety:** existing routes are `POST /analyze/{ticker}` (one segment) and
  `GET /analyze/{ticker}/deep/stream` (three segments); a new
  `GET /analyze/watchlist/stream` (two segments) collides with neither.
- **Frontend SSE precedent:** `streamDeepAnalysis(ticker, period, handlers)` in
  `api/client.ts` wires named `EventSource` listeners, closes on terminal events, and
  returns a closer the caller must invoke on unmount. `useDeepAnalyze` wraps it in hook
  state. `AgentEvent` is a single flexible type (a `type` discriminant + optional fields).
- **Frontend page:** `pages/Evaluation.tsx` renders the scoreboard panel; Discover's
  command bar uses `.panel.commandbar` + `.board-controls` styles. `useWatchlist()`
  exposes the list from settings.

## Design

### Backend — `GET /api/analyze/watchlist/stream?mode=fast|deep&period=2y` (SSE)

GET because `EventSource` cannot POST (same reason the deep stream is GET).

**Validation & pre-flight (before the stream starts — normal HTTP errors):**

- `mode` not in `{"fast", "deep"}` → 422 (FastAPI `Literal` query param).

**Pre-flight (in-stream run-level `error` event — `EventSource` can't read HTTP error
bodies once streaming):**

- `settings.evaluation.enabled` is false → `error` "Evaluation recording is disabled in
  Settings — enable it first."
- Provider config invalid (`build_provider` / missing key raises `LLMError`) → `error`
  with the provider message. Checked **once** up front so a misconfigured provider yields
  one event, not N identical per-ticker failures.

**Event protocol** (one flexible Pydantic model `WatchlistRunEvent` in `schemas.py`,
mirroring `AgentEvent`'s shape — a `type` discriminant + optional fields; serialized with
the existing `_sse`-style helper):

- `event: start` — `{total, tickers: [...]}` (the upper-cased watchlist).
- `event: ticker` — `{ticker, index, total, status}` where `status` is
  `running` → then one of `done` (+ `recommendation`, `confidence`, and for deep
  `fell_back`), `skipped`, or `failed` (+ `error` message).
- `event: done` — `{analyzed, skipped, failed}` summary; terminal.
- `event: error` — `{message}`; run-level, terminal.

**Per-ticker loop (sequential; each ticker isolated in `try/except` — one bad ticker
emits `failed` and the loop continues, mirroring `snapshot_watchlist`):**

1. `get_stock_data(ticker, period, ...)` (cached) → last candle date. No candles →
   `failed`.
2. **Skip check:** `store.get_prediction(ticker, last_candle_date, source)` where
   `source` is `SOURCE_LLM_FAST` (fast) / `SOURCE_LLM_DEEP` (deep) → `skipped`.
3. **fast:** `run_analysis(ticker, period, settings, cache, prediction_store)` → `done`
   with the result's recommendation/confidence. (Its 24h cache is a second safety net —
   e.g. same-day provider switch re-records without re-paying for unchanged tickers only
   when the key matches; the explicit skip in step 2 is the primary, provider-agnostic
   guard.)
4. **deep:** build `ToolContext` + `ReActAgent`, consume `agent.stream(...)` internally
   (step events are *not* forwarded — ticker-level progress only); on `final` call
   `_persist_deep_final(...)` (trace persisted; fell-back runs recorded as `llm_fast` —
   still reported `done` with `fell_back: true`). An `LLMError` mid-stream → `failed` for
   that ticker.
5. Empty watchlist: `start {total: 0}` then `done {0, 0, 0}` (the frontend disables the
   buttons anyway; the endpoint stays well-defined).

**Client disconnect (Stop button / tab close):** starlette cancels the generator at the
next `yield` — the in-flight ticker's synchronous work completes and records; remaining
tickers never start. Documented behavior, relied on by the Stop button.

`_persist_deep_final` is currently a private helper in `routes.py`; the new endpoint
lives in the same module and reuses it directly (no move needed).

### Frontend

**Types (`types.ts`):** `WatchlistRunEvent` (type/ticker/index/total/status/
recommendation/confidence/fell_back/error/analyzed/skipped/failed/message/tickers),
`TickerRunStatus = 'running' | 'done' | 'skipped' | 'failed'`.

**Client (`api/client.ts`):** `streamWatchlistRun(mode: 'fast' | 'deep', handlers):
() => void` — mirrors `streamDeepAnalysis`: named listeners for
`start`/`ticker`/`done`/`error`, closes on terminal events, returns a closer.

**Hook (`hooks/useWatchlistRun.ts` + test):** wraps the stream in state, modeled on
`useDeepAnalyze`:

- `state: { phase: 'idle' | 'running' | 'done' | 'error', total, statuses:
  Record<ticker, {status, recommendation?, error?}>, summary?, message? }`
- `start(mode)` opens the stream (ignored while running), `stop()` invokes the closer and
  sets phase `done` with the statuses as they stand (chips remain, "stopped" noted in
  place of the summary); the closer is also invoked on unmount.
- On the terminal `done`/`error` event: invalidate `['evaluation']` so the board refreshes
  with the new calls.

**Component (`components/EvaluationCommandBar.tsx` + test):** a `.panel.commandbar`
rendered by `Evaluation.tsx` above the scoreboard panel:

- Label: "Run on your watchlist (N tickers)".
- Four buttons: **Snapshot technical/network** (`useSnapshotEvaluation`),
  **Fast LLM analysis** (`run.start('fast')`), **Deep LLM analysis — slow**
  (`run.start('deep')`), **Full Discover rescan** (`useRescan` with no sector,
  `onSuccess: () => snapshot.mutate()`).
- All four disabled while *any* of: snapshot pending, rescan pending, run phase
  `running`. Empty watchlist → all disabled + hint "Add tickers to your watchlist first
  (★ on the Dashboard)."
- While an LLM batch runs: a **Stop** button + a progress strip — one chip per ticker
  (`⏳ TICK` running, `✓ TICK BUY` done, `− TICK skipped`, `✗ TICK` failed with the error
  in the chip's `title`), plus "3/10" position text.
- After: summary line "Analyzed X · skipped Y · failed Z." Run-level error → `.error`
  line. Snapshot/rescan results reuse Discover's result-line copy.
- Small `styles.css` additions for the chip states (reuse `.reason-chip` as the base).

**Page (`pages/Evaluation.tsx`):** render `<EvaluationCommandBar />` above the existing
scoreboard panel. No other page changes.

## Edge cases

- **Weekend/holiday runs:** "today" never matches a candle date; the key is the **last
  candle date**, so Friday's calls correctly cause weekend skips (no double-record, no
  weekend token burn).
- **Deep fell back to fast:** recorded as `llm_fast` (honest labeling preserved), reported
  `done` + `fell_back: true`. Consequence: that ticker is *not* skipped by a later deep
  run (no `llm_deep` row exists) — correct, the deep call genuinely hasn't happened yet.
- **Fast batch after a Dashboard analyze today:** skip check catches it (the Dashboard
  run recorded `llm_fast` for the same candle date) — no second LLM call.
- **Analysis cached but never recorded** (evaluation was disabled during an earlier
  Dashboard run today, then enabled): skip check misses, `run_analysis` hits its 24h
  cache and returns **without recording** — status `done`, nothing recorded, zero tokens.
  Self-heals on the next trading day. Accepted v1 limitation (fixing it would require
  recording on the cache-hit path, which lacks the `stock` context).
- **Ticker fails mid-batch** (bad symbol, fetch error, LLM error): `failed` event, loop
  continues; the summary counts it.
- **Mixed sources don't interfere:** fast mode only skips on `llm_fast` rows, deep only
  on `llm_deep`.
- **Stop mid-run:** in-flight ticker completes and records server-side; chips for
  not-started tickers stay pending; re-click resumes via skip.
- **Two browser tabs racing:** no backend lock; worst case both run and upserts collapse
  to the same rows. The per-tab button disable covers the realistic single-user case.

## Error handling

- Run-level (provider config, evaluation disabled): single in-stream `error` event →
  `.error` line in the command bar; nothing runs.
- Per-ticker: isolated `try/except` → `failed` chip + summary count; never aborts the run.
- Recording/trace persistence inside the deep path keeps its existing
  never-break-the-stream guards (`_persist_deep_final`).
- Frontend stream/connection failure: `onError` → run marked `error` with a usable
  message (mirrors `streamDeepAnalysis`).
- Snapshot/rescan buttons surface mutation errors as inline `.error` lines (existing
  pattern).

## Out of scope (v1)

- Parallel/concurrent ticker execution and provider rate-limit tuning.
- A force-rerun toggle (Dashboard per-ticker analysis is the escape hatch).
- Backend run lock / cross-tab coordination.
- A CLI for the LLM batches (`python -m app.screener` / `app.evaluation` already cover
  the unattended deterministic flows; unattended LLM spend is deliberately manual).
- Forwarding deep-agent step events to the batch UI (ticker-level status only).
- Recording on `run_analysis`'s cache-hit path.

## Testing

**Backend (pytest, new `tests/test_api_watchlist_run.py`; parse SSE bodies the same way
the existing deep-stream API tests do; temp DB + `dependency_overrides`):**

- 422 on bad `mode`.
- Run-level error events: evaluation disabled; provider pre-flight failure (one event,
  no per-ticker noise).
- Fast happy path: N tickers → `start`, per-ticker `running`→`done`, `done` summary;
  predictions recorded as `llm_fast` (monkeypatched analyzer/LLM).
- Skip: existing `llm_fast` row at the last candle date → `skipped`, analyzer **not
  called** (assert via monkeypatch counter); an `llm_deep` row does **not** cause a fast
  skip (cross-source independence, both directions).
- Per-ticker isolation: first ticker's fetch raises → `failed`, second still `done`,
  summary `{1 analyzed, 0 skipped, 1 failed}`.
- Deep happy path: agent consumed, prediction recorded as `llm_deep`, trace persisted.
- Deep fell-back: recorded as `llm_fast`, event carries `fell_back: true`.
- Empty watchlist: `start {total: 0}` + `done {0,0,0}`.

**Frontend (vitest + testing-library, mocked `EventSource` following
`useDeepAnalyze.test.tsx`):**

- `streamWatchlistRun` wires listeners, closes on `done`/`error` (client test).
- `useWatchlistRun`: event sequence drives statuses; `stop()` and unmount invoke the
  closer; terminal events invalidate `['evaluation']`.
- `EvaluationCommandBar`: four buttons render; all disable while any process pends;
  empty-watchlist hint + disabled state; progress chips render running/done/skipped/
  failed from events; summary line on `done`; run-level `error` line; snapshot result
  line; rescan chains snapshot on success.
- `Evaluation.tsx` renders the command bar above the scoreboard.

**Docs:** README evaluation bullet gains the "run everything from the Evaluation page"
sentence; `frontend/README.md` page list + `backend/README.md` endpoint table updated.

**Gates:** `pytest -q` (backend), `npx vitest run`, `npm run build` (frontend) — all green.
