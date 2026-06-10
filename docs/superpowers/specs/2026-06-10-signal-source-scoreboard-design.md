# Signal-Source Scoreboard — Design Spec

- **Date:** 2026-06-10
- **Status:** Proposed (awaiting review)
- **Author:** giri + Claude
- **Area:** `backend/app/evaluation`, `backend/app/api`, `backend/app/services`, `backend/app/analysis`, `frontend/src`

## 1. Summary

Make every BUY/SELL/HOLD the app produces **accountable to the same judge**. Today the
Evaluation page only tracks the fast single-shot LLM call; the Discover technical CALL, the
network-blended CALL, and Deep Analysis results are never scored against what prices actually
did. This iteration:

1. **Tags every prediction with a `source`** — `llm_fast` | `llm_deep` | `technical` |
   `network` — and records all four through the existing evaluation engine (identical
   1/5/20-day hit/score/grade math). This delivers the Deep Analysis spec's Phases 3–4
   (trace persistence + fast-vs-deep comparison) as a special case.
2. **Adds a Dashboard `SignalsStrip`** — all four calls for the loaded ticker side by side,
   agreement badge, and the historically most-accurate source crowned. One reconciliation
   point instead of page-hopping between conflicting indicators.
3. **Adds a source scoreboard to the Evaluation page** — overall per-source hit rates
   (including fast vs deep), source filter chips, per-company `by_source` breakdowns.
4. **Feeds the track record back into the LLM prompt** — recent matured calls + a
   calibration line ("you skew overconfident on this name"), injected into both fast and
   deep paths.

The user's daily flow stays the same; the app just starts *measuring* it. "Which CALL do I
trust?" becomes an empirical question the Evaluation page answers with data — and the
foundation the future monthly invest/divest advisor needs.

## 2. Background

- `predictions` / `prediction_evals` (SQLite, `app/evaluation/store.py`) key on
  `(ticker, call_date)`. Only `run_analysis` records (the fast LLM path). A same-day fast +
  deep pair would silently overwrite each other.
- The deep SSE endpoint (`GET /analyze/{ticker}/deep/stream`, `app/api/routes.py`) never
  calls `record_prediction` and never persists the `AgentTrace` — Phases 3–4 of
  `2026-06-08-agentic-deep-analysis-design.md` were specced but not built.
- Discover's technical call comes from `score_stock` (`app/analysis/scoring.py`):
  `direction` derived from the weighted directional vote `net` vs `_DIRECTION_THRESHOLD`,
  with pre-network values preserved as `base_score`/`base_net`. The network-blended call
  comes from `blend_network_into_score` (`app/analysis/network.py`), which recomputes
  `direction` from the blended `net` and attaches the `NetworkSignal` to `StockScore.network`.
- The watchlist is **frontend-only** (`useWatchlist` hook, localStorage); the backend cannot
  enumerate it.

## 3. Goals / Non-goals

**Goals**
- Deep Analysis usable daily *because* it is tracked; fair fast-vs-deep accuracy comparison.
- Technical and network calls scored by the identical evaluation rules.
- One Dashboard reconciliation point (SignalsStrip) with a data-crowned winner.
- The LLM sees its own per-ticker track record and calibration before answering.
- Existing evaluation history preserved through the schema migration.

**Non-goals (this iteration)**
- No blended "5th verdict" number (scoreboard + winner instead; an accuracy-weighted blend
  is future advisor work).
- No portfolio/holdings concept, no monthly invest/divest advisor (separate brainstorm).
- No scheduled/automatic snapshotting (recording piggybacks on the user's daily Rescan All
  and on analyses; a scheduler can be added later if gaps appear).
- No trace-history browser UI (traces are persisted + queryable; the live panel remains the
  daily surface).
- No whole-board tracking (watchlist + analyzed tickers only).

## 4. Decision log (from brainstorming)

| ID | Decision | Choice |
|----|----------|--------|
| D1 | Scope | Pieces 1+2+3 together: deep eval tracking + all-source scoreboard + track-record prompts. Monthly advisor deferred to its own spec. |
| D2 | Deterministic recording trigger | On **Rescan All** (fits the daily ritual; no new scheduler). Missed days are harmless gaps. |
| D3 | Tracking set | **Watchlist + analyzed tickers** — watchlist snapshotted at rescan; any LLM analysis also records a paired same-day technical/network baseline for its ticker. |
| D4 | Verdict UX | **Scoreboard + winner** — show all sources side by side, crown the historically best; no new invented number. |
| D5 | Data model | **Approach A**: one unified `predictions` table with a `source` column in the PK; one scoring engine for all sources. |
| D6 | Deep fallback labeling | A deep run that degrades to the single-shot fallback records as `llm_fast` (that is what produced the answer); only true agent finals record `llm_deep`. |

## 5. Data model & migration

`source TEXT NOT NULL DEFAULT 'llm_fast'` added to both tables:

- `predictions` PK → `(ticker, call_date, source)`
- `prediction_evals` PK → `(ticker, call_date, source, horizon)`

SQLite cannot alter primary keys, so `PredictionStore.__init__` performs a one-time rebuild
when `PRAGMA table_info` shows no `source` column: `CREATE TABLE <name>_new …` → `INSERT …
SELECT` (existing rows tagged `'llm_fast'`) → `DROP` → `ALTER … RENAME`, inside one
transaction under the store's existing lock. Existing history is preserved and truthfully
labeled (it was all fast LLM calls).

`PredictionRow` / `EvalRow` gain `source`; `upsert_prediction`, `has_eval`, `record_eval`,
`evals_for`, `get_prediction` take/return it. The "entry price changed → invalidate evals"
rule applies per `(ticker, call_date, source)`.

**Source values** (string constants in `app/evaluation/` — single definition point):
`llm_fast`, `llm_deep`, `technical`, `network`.

**Column semantics for deterministic rows:** `provider='rules'`, `model=''`,
`confidence=|net|` (clamped 0–1; `net` is the signed directional conviction),
`sentiment` mapped from direction (buy→positive, sell→negative, hold→neutral).
`call_date`/`entry_price` follow the exact `record_prediction` convention — the ticker's
last daily candle (`candles[-1].time` / `.close`) — so every source faces identical exit
math. The technical row's recommendation derives from `base_net` vs `_DIRECTION_THRESHOLD`;
the network row's from the blended `net` (i.e. `StockScore.direction` post-blend).

## 6. Recording paths (four)

1. **`llm_fast`** — `run_analysis` as today, now passing `source='llm_fast'`.
2. **`llm_deep`** — the deep SSE generator gains the prediction store + trace store. When
   the agent yields `final`: persist the `AgentTrace` to a new `agent_traces` table
   (`ticker, call_date, provider, model, trace_json, created_at`, PK `(ticker, call_date)` —
   the Deep Analysis spec's Phase 3, `AgentTraceStore` mirroring `PredictionStore`), then
   record the prediction — `source='llm_deep'` normally, **`'llm_fast'` if
   `stopped_reason='fallback'`** (D6). Recording failures are logged, never break the stream.
3. **`technical` + `network` at analysis time** — wherever an LLM prediction is recorded
   (fast or deep), a helper also records the deterministic pair for that ticker via the same
   scoring path `GET /api/score/{ticker}` uses (`score_one` + network blend; stock data is
   already cached, so this is cheap). The `network` row is recorded **only when
   `StockScore.network` is set** (a network signal actually influenced the score) —
   otherwise it would duplicate `technical`. Guarantees every LLM call has a same-day
   deterministic baseline, watchlist or not.
4. **`technical` + `network` at Rescan All** — new endpoint
   `POST /api/evaluation/snapshot {tickers: [...]}`. The Discover page fire-and-forgets it
   with the current watchlist after a successful rescan. Backend records the pair per ticker
   (same helper as path 3), per-ticker isolation: a failing ticker is skipped and reported,
   the rest record. Response: `{recorded: n, skipped: [{ticker, reason}, ...]}`.

`evaluate_pending`, the hit/score/grade formulas, horizons config, and the
`python -m app.evaluation` CLI are untouched apart from carrying `source` through keys —
every source is judged by the same code.

## 7. API

- **New** `POST /api/evaluation/snapshot` — body `{tickers: string[]}` → records
  technical/network rows (Section 6.4).
- **New** `GET /api/signals/{ticker}` → the SignalsStrip payload:

  ```jsonc
  {
    "ticker": "NVDA",
    "sources": {
      "technical": {"latest": {"call_date": "2026-06-09", "recommendation": "buy",
                     "confidence": 0.41},
                    "track": {"n_calls": 14, "n_matured": 9, "hit_rate": 66.7,
                              "avg_score": 61.2, "grade": "Mixed"}},
      "network":   { ... },          // null when never recorded
      "llm_fast":  { ... },
      "llm_deep":  null
    },
    "agreement": {"counted": 3, "agreeing": 2, "on": "buy", "conflict": false},
    "winner": "technical"            // null until some source has >= 3 matured evals
  }
  ```

  **Winner rule:** highest `avg_score` for *this ticker* among sources with
  `n_matured >= 3`; tie → larger `n_matured`; still tied → no crown. **Agreement:** computed
  over each source's latest call within the last 5 trading days (stale sources don't vote).
- **New** `GET /api/traces/{ticker}` → most recent stored `AgentTrace`s (default limit 5).
- **Extended** `GET /api/evaluation` — `PredictionRecord` gains `source`;
  `CompanyEvaluation` gains `by_source` rollups; board gains top-level `sources` summary
  (per source: `n_calls, n_matured, hit_rate, avg_score, grade`) powering the scoreboard and
  the fast-vs-deep comparison.
- **Extended** `POST /api/evaluation/{ticker}/{call_date}/explain` — gains a `source` query
  parameter (default `llm_fast` for backward compatibility; the UI passes the row's source).
  Post-mortem works on any source's row; the prompt mentions the source.
- **Unchanged:** `POST /analyze/{ticker}`, `POST /screen/rescan`, `GET /api/score/{ticker}`.

## 8. Frontend

- **`SignalsStrip`** (Dashboard summary header, **replacing** the lone `ScoreChip`; the
  `TECH` chip absorbs `ScoreChip`'s score number + reasons popover so nothing is lost):
  four compact chips — `TECH` / `NET` / `FAST` / `DEEP` — each colored by call
  (▲ buy / ▼ sell / — hold), latest-call date, hit-rate tooltip from `track`, 👑 on the
  winner, muted "—" chips for absent sources, and a strip-level agree/conflict badge.
  Backed by a `useSignals` hook; non-critical like `useScore` (absent on error, never blocks
  the page). Clicking FAST/DEEP scrolls to the analysis/trace panel.
- **Discover:** after a successful Rescan All, silently `POST /api/evaluation/snapshot` with
  the `useWatchlist` tickers; small toast "Recorded N watchlist signals for evaluation"
  (failure = quiet console warn, never blocks the board).
- **Evaluation page:** source scoreboard cards at the top (one per source: calls / matured /
  hit rate / avg score / grade — fast vs deep visible at a glance); source filter chips
  (All / Technical / Network / LLM fast / LLM deep); a source badge on every call row;
  `by_source` line inside each company rollup.
- **Deep Analysis panel:** unchanged live behavior; deep results now show up on the
  Evaluation page like any other call.

## 9. Track-record-aware prompts (piece 3)

New `build_track_record_block(ticker, store, settings) -> str | None` in
`app/evaluation/service.py`:

- Last **5 matured LLM calls** for the ticker (`llm_fast` + `llm_deep`, labeled), each as
  `date REC (conf %) → ret@5d ✓/✗, ret@20d ✓/✗`.
- One aggregate calibration line: overall hit rate at the **middle configured horizon**
  (5 trading days by default), and the overconfidence comparison (avg confidence on misses
  vs hits) when it flags.
- Closing instruction: "Calibrate this call's confidence accordingly."
- Returns `None` (block omitted entirely) unless evaluation is enabled **and** ≥1 matured
  LLM call exists for the ticker.

Injected as one section inside `build_user_prompt` (`app/analysis/analyzer.py`) — the deep
agent seeds its transcript with the same context block, so **both paths get it from one
insertion point**. Deterministic-source histories are *not* injected in v1 (the LLM already
receives live technical/network signals; their track records live on the scoreboard).
`run_analysis` passes the store down for this; when unavailable, prompt is unchanged.

## 10. Edge cases & error handling

- Recording never breaks analysis or the SSE stream (existing `try/except` + log pattern).
- Watchlist ticker absent from the board snapshot (never scanned / delisted): skipped +
  reported in the snapshot response; no phantom rows.
- Weekend/holiday: `call_date` = last trading day (existing candle convention), so the eval
  date-join always resolves; same-day re-runs upsert idempotently.
- Deep run twice a day: last `llm_deep` row wins (matches fast behavior).
- Sources with no history: SignalsStrip shows muted chips; winner stays null ("collecting
  data") until the ≥3-matured bar is met; scoreboard cards show "no data yet".
- Overconfidence flag remains primarily an LLM diagnostic (`confidence=|net|` is a proxy
  for deterministic rows); cross-source comparison leans on hit rate / avg score.
- Migration is transactional; a failure leaves the old tables intact (rebuild retried next
  startup).

## 11. Testing

Mirrors existing patterns (tmp-path SQLite stores, fixture `StockData`, mock providers):

- **Migration:** old-schema DB opens → rebuilt with `source`, rows tagged `llm_fast`,
  history intact; fast+deep same-day rows coexist post-migration.
- **Store:** upsert/eval keying per source; entry-price-change invalidation scoped to one
  source.
- **Recording:** fast→`llm_fast`; deep final→`llm_deep`; deep fallback→`llm_fast` (D6);
  paired technical/network on analysis; snapshot endpoint records technical always,
  network only when `StockScore.network` set; per-ticker isolation on failures.
- **Scoring:** `evaluate_pending` scores multi-source rows independently, identical math.
- **Board/signals:** `by_source` rollups; top-level `sources` summary; winner rule
  (≥3 matured, tie-breaks, null case); agreement (stale sources excluded).
- **Prompt block:** formatting; gate (None when no matured history); injection visible in
  `build_user_prompt` output; deep seed contains it.
- **Frontend:** SignalsStrip states (loading / absent / winner / conflict); eval page
  filter chips + scoreboard; snapshot call fired after rescan with watchlist tickers.

## 12. Build order (each independently shippable)

1. Store migration + `source` plumbing + fast/deep recording + `agent_traces` persistence
   (+ `GET /api/traces/{ticker}`).
2. Deterministic recording helper + `POST /api/evaluation/snapshot` + Discover rescan hook.
3. `GET /api/signals/{ticker}` + Dashboard `SignalsStrip`.
4. Evaluation page: `sources` summary, scoreboard cards, filter chips, `by_source` rollups.
5. `build_track_record_block` + prompt injection.

## 13. Risks / open items

- **Sparse early data:** the winner crown and fast-vs-deep verdict need weeks of matured
  calls to mean anything; the UI says "collecting data" rather than crowning prematurely.
- **Deterministic confidence proxy:** `|net|` is not a probability; acceptable because
  cross-source ranking uses hit rate/avg score.
- **Prompt-block size:** capped at 5 calls + 1 calibration line to keep the fast path's
  token cost flat.
- **Client disconnect mid-deep-stream:** recording happens when the generator yields
  `final`; a disconnect before that loses the run (pre-existing Deep Analysis open item,
  unchanged).
- **Future:** accuracy-weighted blended verdict + monthly invest/divest advisor (needs a
  holdings concept) build directly on this table — separate spec.
