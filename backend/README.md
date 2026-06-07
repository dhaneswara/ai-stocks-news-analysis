# Backend — MarketCortex

FastAPI service: US-stock data + indicators + news + multi-provider LLM analysis,
opportunity screening, a company knowledge graph, and recommendation-accuracy evaluation.

## Setup

    cd backend
    python -m venv .venv
    .venv\Scripts\Activate.ps1      # PowerShell  (macOS/Linux: source .venv/bin/activate)
    pip install -e ".[dev]"

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
- `POST /api/analyze/{ticker}?period=2y` — runs the LLM analysis (and records the call for evaluation)
- `GET  /api/score/{ticker}` — no-LLM opportunity score for one ticker (Discover parity, network-blended)
- `GET  /api/settings` · `PUT /api/settings`
- `GET  /api/providers` · `POST /api/providers/{id}/test`
- `GET  /api/truth/mood` — current Truth Social mood + post count
- `GET  /api/screen?sector=&direction=&limit=` — read the latest opportunity board
- `POST /api/screen/rescan?sector=` — trigger a fresh scan and persist the result
- `GET  /api/screen/sectors` — list available sectors from the universe file
- `POST /api/universe/refresh` — rescrape the S&P 500 constituents from Wikipedia (validated, atomic)
- `GET  /api/graph?scope=focus` — read the cached knowledge graph
- `POST /api/graph/rebuild` — rebuild the focus graph via LLM + bake the network signal into the board
- `GET  /api/graph/company/{ticker}` — one-hop ego graph for a single company (explore / expand)
- `GET`/`POST /api/graph/saved` · `GET`/`DELETE /api/graph/saved/{root}` — saved explored subgraphs
- `POST /api/graph/import` — import an external ontology model (JSON `{name, payload}`) as a removable overlay set
- `GET  /api/graph/imports` · `DELETE /api/graph/imports?set_id=` — list / remove import sets
- `GET  /api/graph?scope=imported` — read the imported overlay (and `?scope=focus` returns the snapshot **merged** with it)
- `GET  /api/evaluation` — recommendation-accuracy board (runs lazy scoring first)
- `POST /api/evaluation/{ticker}/{call_date}/explain` — on-demand LLM post-mortem on a missed call
- `DELETE /api/evaluation/{ticker}` — stop tracking a company (clears its recorded calls)
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
row opens the existing per-ticker LLM deep-dive on the Dashboard.

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
A `POST /api/screen/rescan` from the frontend triggers the same scan on demand; a sector
rescan merges fresh rows back into the full board without clobbering other sectors.

### Knowledge-graph daily build (network signal)

After the screener snapshot, build the AI company knowledge graph and bake its **network
signal** into the board (an LLM extracts inter-company relationships from each focus company's
news; a capped, explainable signal then tilts buy/sell/hold by neighbour condition):

```
python -m app.network            # build graph (focus set) + apply network signal to the board
python -m app.network --dry-run  # build + log built/skipped/edges, do not save
```

**IMPORTANT — run this AFTER `python -m app.screener`.** The screener produces the base board;
`app.network` then bakes network influence onto that fresh board. If the screener runs *after*
the network job, the board reverts to base-only until the next network build. The interactive
**Rescan** re-applies the cached graph instantly (pure, no LLM), so only the daily cron ordering
needs care. Only `app.network` and `POST /api/graph/rebuild` make LLM calls; all read paths
(board, deep-dive, `GET /api/graph`) are cache-only. Disable with `Settings.network.enabled = false`.

The interactive **Graph** tab is a separate, read-only research view on the same data: type a
company to get its one-hop ego graph, click a node to **expand** its neighbours on demand (free
if already extracted today), and **save/load** explored subgraphs per company. The explorer
never touches the daily board signal.

#### Import external ontology models

The Graph tab's **Import** sub-tab accepts a small **app-defined JSON model** (paste or `.json`
upload; a copy-paste **ChatGPT prompt template** is provided in the UI — this is *not* real
OWL/RDF) and merges it into the graph as a removable, named **overlay set**
(`graph_imported:<id>`, ~10y TTL). On import (`app/network/import_model.py`), each entity is
resolved to a universe ticker where possible (else kept as a labelled `ext:` node with metadata),
relation types map to the six canonical types or `other`, weight/confidence are clamped, and every
edge is tagged `origin="imported"`. The overlay is unioned into the focus graph **at read time**
via `effective_graph` — so imported edges feed the network signal (board rebuild/rescan, the daily
`app.network` job, **and** the Dashboard's per-ticker score) like native edges, while the saved
`graph_snapshot:focus` stays extracted-only (rebuilds stay idempotent; imports survive them).
Manage sets via `POST`/`GET`/`DELETE /api/graph/imports`.

#### Schedule it daily (Windows Task Scheduler)

Create a Basic Task -> Daily (e.g. **5:15 PM**, *after* the 5:00 PM screener task) -> Start a program:

- Program/script: `D:\workspace\ai-stocks-news-analysis\backend\.venv\Scripts\python.exe`
- Add arguments: `-m app.network`
- Start in: `D:\workspace\ai-stocks-news-analysis\backend`

(macOS/Linux: add a cron entry that runs after the screener cron, from `backend/`.)

The graph is stored in the existing SQLite `Cache` (key `graph_snapshot:focus`; 7-day TTL).

### Caveats

> *Decision support only — not financial advice.* The board is a **screen**, not a
> recommendation system. Ranking ≠ prediction; the score is a heuristic ordering, not a
> probability of return. Data is end-of-day (daily cadence, not intraday). A Trump mention
> **boosts attention** (raises the score) but never votes on direction — the call stays
> driven by technicals alone.

## Recommendation evaluation

Every `POST /api/analyze/{ticker}` is recorded (recommendation, confidence, and the price +
trading date at that moment) so the app can later check how accurate the call was. The
**Evaluation** tab then scores each recorded call against what the price actually did at
**1, 5, and 20 trading days** and rolls the results up per company.

- **Hit:** `buy` is right if the price rose, `sell` if it fell, `hold` if it stayed within a
  band (default ±2%).
- **Score (0–100):** magnitude-aware — 50 is neutral, higher for bigger correct moves, lower
  for bigger wrong ones (scaled by `score_scale_pct`, default 5%).
- **Per company:** hit-rate, average score, a **Strong / Mixed / Weak** grade, and an
  **overconfident** flag (set when missed calls were, on average, at least as confident as
  the correct ones). Confidence is a separate calibration stat — it is *not* folded into the score.
- **Explain a miss:** `POST /api/evaluation/{ticker}/{call_date}/explain` runs one cached LLM
  post-mortem on why the call was likely wrong (missed catalyst, regime shift, …).

Config lives in `Settings.evaluation` (`enabled`, `horizons` = `[1, 5, 20]`, `hold_band_pct`,
`score_scale_pct`); no secrets, so nothing is masked. Recorded calls and their verdicts are
stored in two SQLite tables (`predictions`, `prediction_evals`) in the app DB under `DATA_DIR`.

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
> only the calls you actually ran (no synthetic backfill), and a single-day horizon is noisy
> by nature.

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
```
