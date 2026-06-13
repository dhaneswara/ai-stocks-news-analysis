# Backend — MarketCortex

FastAPI service: US-stock data + indicators + news + multi-provider LLM analysis (single-shot
**and** agentic Deep Analysis), opportunity screening (broad S&P 500 board **and** a focused
**portfolio board** for your watchlist + active ontology — the primary scoring source),
a company knowledge graph, and a **multi-source recommendation-accuracy scoreboard**.

## Setup

    cd backend
    python -m venv .venv
    .venv\Scripts\Activate.ps1      # PowerShell  (macOS/Linux: source .venv/bin/activate)
    pip install -e ".[dev]"

> Dependencies are pinned to install from prebuilt wheels everywhere: the server uses
> plain `uvicorn`, **not** `uvicorn[standard]` — the `httptools` extra ships no Windows
> ARM64 wheels, and the extras are performance-only (`uvloop` is a no-op on Windows).
> Don't re-add the extra without checking wheel availability for your platforms.

## Run

    uvicorn app.main:app --reload --port 8000

Open http://localhost:8000/docs for interactive API docs.

## Test

    pytest -v

## Configure providers

Provider keys/models are set via `PUT /api/settings` (the frontend Settings page),
stored in SQLite under `DATA_DIR` (gitignored). For local Ollama, run `ollama serve`
and pull a model (e.g. `ollama pull llama3.1`); no API key needed.

## Endpoints

- `GET  /api/health`
- `GET  /api/stock/{ticker}?period=2y`
- `POST /api/analyze/{ticker}?period=2y` — runs the fast LLM analysis (and records the call **plus a technical/network baseline** for evaluation)
- `GET  /api/analyze/{ticker}/deep/stream?period=2y` — agentic **Deep Analysis** streamed as Server-Sent Events (records as `llm_deep`; persists the agent trace)
- `GET  /api/analyze/watchlist/stream?mode=fast|deep&period=2y` — run the fast/deep analysis for **every portfolio ticker (watchlist + active ontology)** as one SSE batch (per-ticker progress events; a ticker whose matching-source call already exists for its latest trading day is skipped)
- `GET  /api/analysis/{ticker}` — the most recent persisted **analysis snapshot** for a ticker (the full result), for the Dashboard's read-only restore; returns `null` when none exists. Pure read — no compute, no recording, no evaluation impact
- `GET  /api/traces/{ticker}?limit=5` — recent persisted deep-analysis reasoning traces (newest first)
- `GET  /api/score/{ticker}` — no-LLM opportunity score for one ticker (Discover parity, network-blended)
- `GET  /api/signals/{ticker}` — every recorded CALL source for one ticker + per-source track records, agreement and the historically best source (powers the Dashboard Signals strip)
- `GET  /api/settings` · `PUT /api/settings`
- `GET  /api/providers` · `POST /api/providers/{id}/test`
- `GET  /api/truth/mood` — current Truth Social mood + post count
- `GET  /api/screen?sector=&direction=&limit=&scope=` — read the latest opportunity board; `scope=portfolio` reads the portfolio board (watchlist + active-ontology tickers)
- `POST /api/screen/rescan?scope=` — trigger a fresh scan and persist the result; `scope=` accepts `portfolio`, a sector name, or none (full S&P 500); `sector=` still accepted
- `GET  /api/screen/rescan/stream?scope=` — the same scan as SSE with live per-ticker progress (one `tick` per ticker, terminal `done`; the UI's rescan buttons use this); same `scope=` values
- `GET  /api/screen/sectors` — list available sectors from the universe file
- `GET  /api/portfolio/tickers` — the portfolio universe (watchlist ∪ active-ontology tickers); drives the Portfolio page empty-state and the Evaluation command-bar count
- `POST /api/universe/refresh` — rescrape the S&P 500 constituents from Wikipedia (validated, atomic)
- `GET  /api/universe/custom` — list custom (non-S&P 500) companies
- `POST /api/universe/custom` `{ticker}` — auto-fetch a company's name, exchange, sector, and price from market data and persist it permanently; returns 422 if the ticker is unknown
- `DELETE /api/universe/custom/{ticker}` — remove a custom company
- `GET  /api/graph` — the active ontology's graph (empty when no ontology is active)
- `GET  /api/graph/company/{ticker}` — one-hop ego graph for a single company (explore / expand); `?refresh=true` bypasses the 24h relationship cache to re-extract from the latest news (powers **Revalidate relationships**)
- `GET  /api/graph/ontologies` — list all saved ontologies (name, version count, active flag)
- `POST /api/graph/ontologies` — save (create or add a revision to) a named ontology; re-bakes the board if it is the active one
- `GET  /api/graph/ontologies/{name}?version=` — load one ontology (latest or a specific revision)
- `DELETE /api/graph/ontologies/{name}?version=` — delete a whole ontology or one revision; re-bakes the board if active
- `GET  /api/graph/active` — get the currently active ontology name (null = none)
- `PUT  /api/graph/active` — set (or clear) the active ontology; re-bakes the board immediately
- `POST /api/graph/import` — import an external ontology model (JSON `{name, payload}`) as a reusable import set
- `GET  /api/graph/imports` · `DELETE /api/graph/imports?set_id=` — list / remove import sets
- `GET  /api/graph/imports/{id}` — one import set's graph (for the merge-into-canvas MergePreview)
- `GET  /api/evaluation` — recommendation-accuracy board with per-source rollups (runs lazy scoring first)
- `POST /api/evaluation/snapshot` — record today's technical/network calls for the whole **portfolio** (watchlist + active ontology; fired by Rescan portfolio; no body)
- `DELETE /api/evaluation` — start over: delete every recorded call and score across all tickers (per-ticker variant: `DELETE /api/evaluation/{ticker}`)
- `POST /api/evaluation/{ticker}/{call_date}/explain?source=llm_fast` — on-demand LLM post-mortem on a missed call (source-aware)
- `DELETE /api/evaluation/{ticker}` — stop tracking a company (clears its recorded calls, all sources)
- `POST /api/alerts/test` — send a test alert through the configured channel

## Trump / Truth Social signal

When enabled, the analyzer fetches Donald Trump's recent Truth Social posts from the
public archive mirror `https://ix.cnn.io/data/truth-social/truth_archive.json` (~5-min
updates, no auth) and injects two inputs into each LLM analysis:

- **Market mood** — risk-on / risk-off, derived once per provider/day and shared across
  all tickers in that run.
- **Mention flag** — whether he named the company or its ticker in the lookback window.
  Matching uses `$CASHTAG` + bare uppercase ticker + company name with word boundaries.
  Very short tickers (1–2 chars, e.g. F, T) and multi-word company names match coarsely.

Configure via **Settings → Truth Social signal**: an **Enabled** toggle (on by default)
and a **lookback (hours)** window (default 48). Persisted under `Settings.truth_signal`.

The fetcher is isolated (`app/data/truth_social.py`) so the data source can be swapped (e.g.
`truthbrush` or a paid API). The mood read mirrors the per-day analysis cache — real-time
reaction to a breaking post is out of scope for this version.

> *Decision support only — not financial advice.* This is one weighted input among many;
> it never auto-triggers a trade or creates historical buy/sell chart markers.

## Discover — opportunity board

The **Discover** tab ranks the S&P 500 (or a sector slice) by a 0–100 opportunity score
computed with a pure, deterministic scorer — **no LLM call on the board path**. Clicking a
row opens the existing per-ticker LLM deep-dive on the Dashboard. Each row carries an
**`exchange`** field (friendly exchange name) and an **`in_sp500`** boolean; custom companies
(added via `POST /api/universe/custom`) are merged into `load_universe` and scanned in the
`all` board flagged non-member.

### Portfolio board

`GET /api/screen?scope=portfolio` reads the portfolio board — a separate cached snapshot
(key `screen_snapshot:portfolio`) that covers only the **portfolio universe**: the union of
`settings.watchlist` and the ticker nodes in the active ontology (non-ticker `ext:`/`man:`
nodes are excluded). Because this set is typically small (tens of names rather than ~503),
a rescan via `POST /api/screen/rescan?scope=portfolio` (or the SSE variant) completes in
**seconds**. `GET /api/portfolio/tickers` returns the current portfolio universe.

**Base-index precedence (`combined_base_index`):** the portfolio board is overlaid on the
broad `all` board (portfolio rows win), and this combined index is what `score_one`
(Dashboard score chip), the fast/deep LLM prompts' network section, and Graph node
colours/scores all read — falling back to the broad scan for any ticker absent from the
portfolio. This makes the focused, frequently-refreshed portfolio data the headline
scoring source.

> *Note:* the portfolio board snapshot is refreshed only by an explicit `scope=portfolio`
> rescan — it is **not** auto-re-baked on an ontology change (the ontology is the
> portfolio's very membership, so re-scoring requires a real rescan).

### Scorer — signal families

The scorer (`app/analysis/scoring.py`) blends five signal families into a single score:

| Family | Signals | Direction vote? |
|--------|---------|-----------------|
| **extremes** (weight 1.0) | RSI oversold/overbought, proximity to 52-wk low | yes |
| **trend** (weight 1.0) | Golden/death cross, price vs SMA50/200 alignment | yes |
| **momentum** (weight 0.8) | 1-month return, near 52-wk-high breakout | yes |
| **volume** (weight 0.4) | Last-bar vs 20-day average volume surge | no (attention only) |
| **catalyst** (weight 0.5) | Trump / Truth Social mention count | no (attention only) |

Weights and RSI thresholds live in `Settings.screener.weights`, `rsi_low`, and `rsi_high`
(defaults: `rsi_low=30`, `rsi_high=70`; configurable via `PUT /api/settings`).
The `buy`/`sell`/`hold` direction is derived from the *signed* net of the three directional
families only; volume surges and Trump mentions raise the score without ever flipping the call.

### Universe

`app/data/sp500.json` — a committed snapshot of S&P 500 constituents (`ticker`, `name`,
GICS `sector`). Ships the **full S&P 500** (~503 names across all 11 GICS sectors); the
loader (`app/data/universe.py`) is size-agnostic. Refresh from Wikipedia anytime with the
**Update S&P 500 list** button (`POST /api/universe/refresh` — validated, atomic write, then
the loader cache is cleared with no restart).

### Daily snapshot job

Schedule `python -m app.screener` post-market close (same mechanism as `python -m app.alerts`):

```
python -m app.screener                # scan all sectors + save snapshot
python -m app.screener --sector Tech  # limit to one GICS sector
python -m app.screener --dry-run      # log the top-10, do not save
```

#### Schedule it daily (Windows Task Scheduler)

Create a Basic Task -> Daily (e.g. 5:00 PM, after US close) -> Start a program:

- Program/script: `D:\workspace\ai-stocks-news-analysis\backend\.venv\Scripts\python.exe`
- Add arguments: `-m app.screener`
- Start in: `D:\workspace\ai-stocks-news-analysis\backend`

(macOS/Linux: add a cron entry running the same command from `backend/`.)

The snapshot is stored in the existing SQLite `Cache` (key `screen_snapshot:all`; 7-day TTL).
The frontend triggers the same scan on demand via `GET /api/screen/rescan/stream` (SSE, so the
minutes-long scan shows live per-ticker progress; `POST /api/screen/rescan` remains the
blocking variant); a sector rescan merges fresh rows back into the full board without
clobbering other sectors.

### Network re-bake (active ontology)

After the screener snapshot, re-blend the board against the **active ontology** to bake its
network signal in:

```
python -m app.network            # re-bake the board against the active ontology
python -m app.network --dry-run  # log the active ontology name + edge count; do not save
```

**IMPORTANT — run this AFTER `python -m app.screener`.** The screener produces the base board;
`app.network` then bakes network influence onto that fresh board. If the screener runs *after*
the network job, the board reverts to base-only until the next network re-bake. **No LLM call
is made** — the ontology is user-curated on the Graph page. Disable with
`Settings.network.enabled = false`.

The **interactive Graph tab** is where you build and manage the ontology: start from a company
(one-hop live news extraction), click **Expand neighbours** on demand (or **Revalidate
relationships** to re-extract a company's edges against the latest news, bypassing the daily
cache — stale extracted edges are replaced while your manual/imported edges are kept),
right-click to add relationships or **Add company…** (a real ticker node, also expandable),
delete nodes/edges, and
merge stored **import sets** via the conflict-resolution MergePreview. Save the canvas under a
user-chosen name (toolbar: name field + **Save / Save as / New / Export**). The **Ontologies** sidebar
tab lists every saved ontology, shows the **ACTIVE** badge, and lets you **Set active** per row
(or select "None (network signal off)"). Activating, saving over, or deleting any version of the
active ontology immediately **re-bakes** the Discover snapshot — no rescan or CLI run needed.
Ontologies are versioned (up to 5 revisions per name); a stale revision can be loaded and
inspected, and the canvas marks itself dirty until you save.

#### Import external ontology models (building blocks)

The Graph tab's **Import** sub-tab accepts a small **app-defined JSON model** (paste or `.json`
upload; a copy-paste **LLM prompt template** is provided in the UI — usable with any LLM
(ChatGPT, Gemini, Claude, …), and it embeds the current date range (from the news-recency
setting) so the model researches up-to-date news — this is *not* real OWL/RDF). On import (`app/network/import_model.py`), each entity is resolved to a universe
ticker where possible (else kept as a labelled `ext:` node with metadata), relation types map to
the six canonical types or `other`, weight/confidence are clamped, and every edge is tagged
`origin="imported"`. The saved import set is a **reusable building block** — it does **not**
feed the network signal until you merge it into the canvas and save it as the active ontology.
Merge via the MergePreview (links imported companies to the Discover list, collapses clashing
nodes, dedupes relationships). Manage sets via `POST`/`GET`/`DELETE /api/graph/imports`.

The reverse direction is the toolbar **Export** button: it serializes the current canvas to a
JSON file in this same import-model shape (frontend-only — no endpoint). Move that file to
another machine and bring it in through the Import sub-tab to recreate the graph there; it
re-imports through `POST /api/graph/import` like any other model (so the same resolution rules
apply — `man:`/`ext:` nodes become `ext:` nodes, `origin` is re-tagged `imported`, etc.).

#### Schedule it daily (Windows Task Scheduler)

Create a Basic Task -> Daily (e.g. **5:15 PM**, *after* the 5:00 PM screener task) -> Start a program:

- Program/script: `D:\workspace\ai-stocks-news-analysis\backend\.venv\Scripts\python.exe`
- Add arguments: `-m app.network`
- Start in: `D:\workspace\ai-stocks-news-analysis\backend`

(macOS/Linux: add a cron entry that runs after the screener cron, from `backend/`.)

### Caveats

> *Decision support only — not financial advice.* The board is a **screen**, not a
> recommendation system. Ranking ≠ prediction; the score is a heuristic ordering, not a
> probability of return. Data is end-of-day (daily cadence, not intraday). A Trump mention
> **boosts attention** (raises the score) but never votes on direction — the call stays
> driven by technicals alone.

## Deep Analysis (agentic ReAct)

`GET /api/analyze/{ticker}/deep/stream?period=2y` runs the analysis as a bounded **ReAct
agent**: the LLM reasons step-by-step and calls tools on demand (targeted news search, deeper
fundamentals, a price window with indicators, the app's own score/network signals), streamed
to the client as Server-Sent Events (`step` events, then a terminal `final` or `error`). The
final answer uses the same schema as the fast path; on any agent failure it **falls back to
the single-shot analyzer**, so the endpoint always terminates with a usable result. Each
completed run persists its full reasoning trace to the `agent_traces` table
(`GET /api/traces/{ticker}`) and records its prediction for evaluation — as `llm_deep`, or
honestly as `llm_fast` when the run fell back, so the deep-vs-fast accuracy comparison is
never polluted. The fast `POST /api/analyze` path is unchanged and remains the default.

## Recommendation evaluation — the signal-source scoreboard

Every CALL the app produces is recorded under a **source** tag and scored by the same rules,
so the Evaluation tab can answer *"which signal should I trust?"* with data. The sources:

| Source | What it is | Recorded when |
|--------|-----------|---------------|
| `llm_fast` | the single-shot **Analyze with LLM** call | `POST /api/analyze/{ticker}`, and portfolio-wide via `GET /api/analyze/watchlist/stream` |
| `llm_deep` | the agentic **Deep Analysis** result | the deep stream's terminal event (a fallback run records as `llm_fast`), and portfolio-wide via `GET /api/analyze/watchlist/stream` |
| `technical` | the deterministic screener's pre-network vote | alongside every LLM analysis, and for the whole portfolio via `POST /api/evaluation/snapshot` (fired by Rescan portfolio) |
| `network` | the network-blended call | same moments as `technical`, but only when a network signal actually influenced the score |

The portfolio snapshot reads the **portfolio universe** (`portfolio_universe` = watchlist ∪
active-ontology tickers) server-side and runs the same no-LLM scorer
as the Discover board over a 1-year window of (cached) yfinance data; calls are keyed to the
**last candle's** trading date, so a weekend run records under Friday. A same-day re-run
refreshes the row **only until a horizon matures** — once a call has any scored outcome it is
**immutable**, so re-running analysis can never move its entry/recommendation or wipe its
verdicts. The `network` call blends the active ontology and
the Discover-board snapshot, so it is freshest right after a rescan — which is why Discover
chains the snapshot automatically.

Each recorded call (recommendation, confidence, entry price + trading date) is scored against
what the price actually did at **1, 5, and 20 trading days** and rolled up per company *and*
per source.

- **Hit:** `buy` is right if the price rose, `sell` if it fell, `hold` if it stayed within a
  band (default ±2%).
- **Score (0–100):** magnitude-aware — 50 is neutral, higher for bigger correct moves, lower
  for bigger wrong ones (scaled by `score_scale_pct`, default 5%).
- **Per company:** hit-rate, average score, a **Strong / Mixed / Weak** grade, a
  **by-source breakdown**, and an **overconfident** flag (set when missed calls were, on
  average, at least as confident as the correct ones — computed from **LLM calls only**;
  deterministic rows store `|net|` as a conviction proxy, not a probability). Confidence is a
  separate calibration stat — it is *not* folded into the score.
- **Per source (board level):** overall scoreboard cards — calls / scored / hit-rate /
  average score / grade per source — which is also the **fast-vs-deep LLM comparison**.
- **Signals summary:** `GET /api/signals/{ticker}` returns each source's latest call + its
  per-ticker track record, an agreement summary (over sources fresh within ~5 trading days),
  and the **winner** — the source with the best average score for that ticker once it has
  **≥3 scored outcomes** (full ties crown nobody). This powers the Dashboard Signals strip.
- **Track-record prompt:** both LLM paths receive the model's own scored history on the
  ticker (last 5 matured calls + hit-rate + an overconfidence line) so it can calibrate
  itself; the prompt is byte-identical for tickers with no scored history.
- **Explain a miss:** `POST /api/evaluation/{ticker}/{call_date}/explain?source=…` runs one
  cached LLM post-mortem on why the call was likely wrong (missed catalyst, regime shift, …) —
  works on any source's row.

Config lives in `Settings.evaluation` (`enabled`, `horizons` = `[1, 5, 20]`, `hold_band_pct`,
`score_scale_pct`); no secrets, so nothing is masked. Recorded calls and their verdicts are
stored in two SQLite tables (`predictions`, `prediction_evals`) in the app DB under `DATA_DIR`;
both carry the `source` inside their primary keys (older databases are **migrated
automatically on first start** — existing history is preserved, tagged `llm_fast`). Deep
reasoning traces live in a third table, `agent_traces`. The full last analysis per ticker —
for the Dashboard's read-only restore — lives in a **separate** `analysis_snapshots.db` under
`DATA_DIR`, deliberately apart from the evaluation tables so viewing a past analysis never
touches scoring.

### Scoring job

Scoring happens **lazily** whenever the Evaluation page loads — only newly-matured horizons are
computed, and settled verdicts are final (idempotent). For unattended history, also run it
post-close:

```
python -m app.evaluation            # score any matured calls
python -m app.evaluation --dry-run  # compute + log a summary, do not persist
```

#### Schedule it daily (Windows Task Scheduler)

Create a Basic Task -> Daily (e.g. **5:45 PM**, after the screener/network tasks) -> Start a program:

- Program/script: `D:\workspace\ai-stocks-news-analysis\backend\.venv\Scripts\python.exe`
- Add arguments: `-m app.evaluation`
- Start in: `D:\workspace\ai-stocks-news-analysis\backend`

(macOS/Linux: add a cron entry running the same command from `backend/`.)

### Caveats

> *Decision support only — not financial advice.* A "hit" is a simple directional check over
> end-of-day prices — not risk-adjusted, dividend-adjusted, or benchmark-relative. It scores
> only the calls you actually ran (no synthetic backfill), a single-day horizon is noisy by
> nature, and per-source winners need **weeks of matured outcomes** before they mean anything
> (a source's chip reads *N of M scored — awaiting maturity* until its calls mature, and the
> per-source 👑 winner needs ≥3 scored outcomes).

## Scheduled alerts

Check your watchlist for buy/sell triggers and send Telegram alerts:

```
python -m app.alerts            # evaluate + send
python -m app.alerts --dry-run  # log instead of sending
python -m app.alerts --no-llm   # skip LLM reasoning
```

Configure in the frontend Settings -> Alerts (enable, Telegram bot token + chat id,
RSI thresholds), or via env vars `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`. Alerts are
deduplicated per (ticker, rule, day).

### Schedule it daily (Windows Task Scheduler)

Create a Basic Task -> Daily (e.g. 5:30 PM, after US close) -> Start a program:

- Program/script: `D:\workspace\ai-stocks-news-analysis\backend\.venv\Scripts\python.exe`
- Add arguments: `-m app.alerts`
- Start in: `D:\workspace\ai-stocks-news-analysis\backend`

(macOS/Linux: add a cron entry running the same command from `backend/`.)
