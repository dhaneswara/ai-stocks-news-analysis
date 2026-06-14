# 📈 MarketCortex

A personal web app for **swing/long-term US-stock decision support**. It pulls price
data, fundamentals, and recent news for a stock, computes simple technical indicators,
and asks an **LLM (Anthropic / OpenAI / Gemini / DeepSeek / local Ollama)** to produce a structured
analysis — a plain-language summary, a read on the news, and **buy/sell signals drawn
directly on an interactive chart** with the reasoning shown on the page. It can also send
**scheduled buy/sell alerts** to Telegram, rank opportunities across the S&P 500 — or focus
on just your own **portfolio** (your watchlist plus the companies in your active knowledge
graph), scored the same way but in seconds — map inter-company relationships as a
**knowledge graph**, run an **agentic Deep Analysis** that
pulls evidence on demand, and **grade how accurate its own past calls turn out to be — for
every signal source it produces** (fast LLM, deep LLM, technical screen, network-blended). Or
just **chat with it** — a multi-turn assistant that reasons step-by-step across any stock or
theme and pulls whatever the question needs (prices, news, geopolitics, the knowledge graph,
your portfolio).

> ⚠️ **Decision support, not financial advice.** The LLM can be confidently wrong, and the
> on-chart/alert signals are mechanical heuristics + retrospective reasoning — **not** a
> backtested, validated strategy. This project does not execute trades.

---

## Features

- **Interactive dashboard** — candlestick chart (TradingView Lightweight Charts) with a
  **timeframe selector (1M / 3M / 6M / 1Y / 2Y / 5Y)**, SMA50/200 overlays, and LLM-drawn
  **buy ▲ / sell ▼ markers**. Click a marker — or a row in the dedicated **Signals** list — to
  read that signal's reasoning. Your **last analysis restores automatically** when you reopen a
  ticker — the reasoning, the Signals list, and the chart's buy/sell markers reappear, tagged
  *as of* its call date — a pure read that costs no tokens and never affects evaluation history,
  so you can review past calls without re-running. Manage your watchlist from a compact,
  searchable **Watchlist (N) ▾** dropdown: star (★) the loaded ticker to add it, filter and pick,
  or remove with ×. The header shows a **Signals strip** as soon as a
  ticker loads: the instant **no-LLM opportunity score** (same 0–100 score + reason chips as
  the Discover board) plus the latest call from **every signal source side by side** —
  technical, network-blended, fast LLM, and deep LLM — with an agree/conflict badge and a 👑
  on the source that has historically been most accurate for that ticker (crowned once a
  source has at least 3 scored outcomes).
- **LLM analysis** — runs over the chart's **selected timeframe** and weighs the latest news
  *together with* the technicals/fundamentals. Returns a plain-language summary, news
  interpretation, sentiment, a current buy/sell/hold recommendation with confidence, the
  **key factors driving it** ("why now"), dated buy/sell signals (timed **buy-low / sell-high**,
  with a deterministic guard that drops incoherent ones), and risks. A separate **Deep
  Analysis** button runs the same question as an **agentic ReAct loop**: the LLM pulls extra
  evidence on demand (targeted news search, deeper fundamentals, price windows, the app's own
  signals) with its Thought → Action → Observation trace **streamed live** to the page; the
  result renders exactly like the fast path, it falls back to the single-shot analyzer if the
  agent derails, and each run's trace is persisted for later review. Both paths feed the
  Evaluation scoreboard, and both prompts include the model's **own scored track record** on
  that ticker (recent hits/misses + an overconfidence note) so it can calibrate itself.
- **AI Chat assistant** — a **Chat** tab for free-form, multi-turn conversation about your
  stocks. Unlike the per-ticker analysis it isn't bound to one symbol: ask about any company,
  sector, or theme ("how does geopolitics affect NVDA?", "compare AMD vs NVDA using the
  ontology", "what's the strongest opportunity in my watchlist?") and the assistant runs an
  **agentic ReAct loop**, pulling exactly the data it needs from the app — price/fundamentals/
  technicals, news search, the Trump/Truth-Social mood, the ontology graph + network signal, the
  no-LLM opportunity score, the portfolio board, and the model's own evaluation track record —
  with its **Thought → Action → Observation steps streamed live** and a Markdown answer. The
  conversation remembers prior turns so you can ask follow-ups; it is **exploratory only** —
  nothing it does is recorded to the evaluation scoreboard. (History is kept in the browser for
  the session and clears on reload.)
- **Per-stock news** — recent headlines via Google News RSS.
- **Multi-provider, switchable in the UI** — Anthropic, OpenAI, Gemini, DeepSeek, or local
  Ollama; API keys are stored locally and masked in the UI.
- **Scheduled alerts** — a CLI evaluates indicator rules (RSI 30/70 crossings, golden/death
  cross) on your watchlist and sends deduplicated Telegram alerts (with best-effort LLM
  reasoning), scheduled via the OS.
- **Trump / Truth Social signal** — the analyzer optionally folds Donald Trump's recent
  Truth Social posts into each stock's analysis as two inputs: a market-wide **mood**
  (risk-on / risk-off, derived once per provider/day and shared across tickers) and a
  per-ticker **mention** scan (when he names the company or ticker). Both are weighed by
  the LLM alongside the technicals, fundamentals, and news.
  Source: the public archive mirror `https://ix.cnn.io/data/truth-social/truth_archive.json`
  (~5-min updates, no auth). Toggle and lookback window (default 48 h) are in **Settings →
  Truth Social signal**. Preview: `GET /api/truth/mood`.
  *Caveats:* political-post inference is noisy — one weighted input among many, never an
  auto-trigger. Mention matching uses `$CASHTAG` + bare ticker + company name with word
  boundaries (very short tickers and multi-word names can over- or under-match). The read
  is "as of the day's first analysis per ticker" (mirrors the per-day cache); real-time
  reaction to a breaking post is out of scope.
- **Portfolio — your focused board** — a **Portfolio** tab scores just your own universe:
  your **watchlist plus the ticker nodes in your active ontology** (non-ticker `ext:`/`man:`
  nodes are excluded). Because it covers only those names instead of all ~503 S&P 500
  constituents, a rescan takes **seconds, not minutes**. The board reuses the same shared
  `ScoreBoard` UI as Discover — each row shows score, call, and reason chips; click any row
  to open the full Dashboard deep-dive. An as-of line, a **Rescan portfolio** button (which
  also chains the technical/network snapshot), and a **Stop** button while scanning complete
  the bar; when the portfolio is empty an inline prompt directs you to add to your watchlist
  or activate an ontology. The portfolio board is cached separately under scope `"portfolio"`.
  Beyond its own tab, the portfolio data is the **primary scoring source** via base-index
  precedence: a `combined_base_index` (portfolio board overlaid on the broad Discover `all`
  board, portfolio wins) feeds the single-ticker score chip on the Dashboard Signals strip,
  the fast/deep LLM prompts' network section, and Graph node colours/scores — each falling
  back to the broad Discover scan for any ticker not in the portfolio.
  *Note:* the portfolio board snapshot is refreshed only by **Rescan portfolio** — it is not
  auto-re-baked on an ontology change (since the ontology is the portfolio's very membership,
  a real rescan is needed to re-score it).
- **Discover — opportunity board** — a **Discover** tab auto-ranks the S&P 500 (or a
  sector slice) by a 0–100 opportunity score computed with a fast, no-LLM scorer (RSI /
  52-wk extremes, golden/death cross + SMA alignment, 1-month momentum, breakout proximity,
  volume surge, and an optional Trump-mention boost). Each row shows the score, a
  buy/sell/hold call, and plain-language reason chips; an **Exchange** column (NASDAQ / NYSE /
  etc.) and an **S&P** column badge each row as **S&P 500** or **Custom**. A **search box**
  above the board filters rows by ticker or company name (client-side). **Custom (non-S&P 500)
  companies** can be added via an **"Add company"** form — enter a ticker and the app
  auto-fetches the name, exchange, sector, and current price from market data and saves it
  permanently; it is then scanned on the Discover board alongside the S&P 500 and flagged
  **Custom**, removable via an × on its row. Clicking a row deep-links into the existing
  per-ticker LLM analysis. Filter by sector/direction and use the **Show** control
  (25 / 50 / 100 / All) to set how many ranked names appear; **Update S&P 500 list** rescrapes
  the current constituents from Wikipedia (validated, atomic write). A **Rescan** button
  triggers a fresh scan on demand; the daily snapshot can also be refreshed automatically via
  `python -m app.screener` (see [backend/README.md](backend/README.md)). Every button on the
  page has a tooltip.
  *Caveats:* decision support only — the board is a screen, not a recommendation system;
  ranking ≠ prediction; data is end-of-day (not intraday); a Trump mention boosts attention
  but never determines the buy/sell direction.
- **Company knowledge graph / network signal** — a capped, **explainable network signal**
  tilts the Discover board's buy/sell/hold by a company's neighbours (e.g. a key supplier's
  bad news weighs on the customer). The graph that drives all analysis is a **named, versioned
  ontology** you build and maintain on the **Graph** tab: start from a company (one-hop live
  news extraction), expand neighbours — or **revalidate** a company's relationships to
  re-extract them against the latest news — on demand, right-click to add relationships or
  **add custom companies** (ticker + optional name, fully expandable), delete nodes/edges, and
  merge stored **import sets** via the conflict-resolution MergePreview. Save the canvas
  under a user-chosen name (toolbar: name field + **Save / Save as / New / Export**; up to 5
  versions kept per name). The **Ontologies** sidebar tab shows every saved ontology — **ACTIVE** badge
  on the live one, **Set active** per row, a "None (network signal off)" row, and version
  history (load an old version to inspect it; the canvas marks itself dirty until you save).
  **Exactly one ontology is active** — it is the only graph Discover scoring, Dashboard score
  chip, fast/deep LLM prompts' network section, and portfolio snapshots consume. **No active
  ontology = no network signal anywhere.** Activating, saving over, or deleting any version of
  the active ontology immediately **re-bakes** the Discover snapshot — no rescan needed. A hint
  on the canvas shows which ontology analysis is currently using (or "no network signal") when
  the canvas isn't the live active revision. Company nodes also expose **☆ Add / ★ Remove
  watchlist** in the right-click menu and the node detail panel. Import sets (paste/upload a
  LLM-generated JSON graph via the Import sub-tab) are reusable building blocks to merge
  into a canvas and save — they only feed scores once merged into the active ontology. The
  toolbar **Export** button downloads the current canvas as a JSON file in that same import-set
  shape — copy it to another machine and bring it in via the Import sub-tab (then merge → Save →
  Set active) to recreate the graph there. Daily
  re-bake: `python -m app.network` (after the screener — no LLM; see
  [backend/README.md](backend/README.md)).
- **Signal-source scoreboard (evaluation)** — every CALL the app produces is recorded and
  scored against what the price actually did at **1, 5, and 20 trading days** — not just LLM
  calls: **fast LLM**, **deep (agentic) LLM**, the deterministic **technical** screen, and the
  **network-blended** call are all tracked under identical rules, so *"which signal should I
  trust?"* becomes a measured answer instead of a feeling. The **Evaluation** tab shows
  per-source scoreboard cards (calls / scored / hit-rate / grade), per-company boards with a
  by-source breakdown and a source filter, an **overconfidence** flag for the LLM calls, and a
  source-aware **"Explain miss"** LLM post-mortem, plus a confirm-guarded **Clear all results**
  reset that wipes every recorded call and score — start the experiment over once you're done
  testing. The **action bar on the Evaluation page** runs processes across your whole
  **portfolio (watchlist + active ontology)** on demand — its buttons are **Rescan portfolio**
  (re-scores the portfolio and chains the technical/network snapshot), **Fast LLM analysis**,
  and **Deep LLM analysis** (live per-ticker progress, a Stop button, and already-recorded
  tickers skipped so reruns only fill gaps); the old standalone snapshot button and the
  full-Discover-rescan button are gone — **Rescan portfolio** covers both. A deep run that
  silently fell back to the fast path is honestly recorded as fast so the deep-vs-fast
  comparison never lies.
  Every process **keeps running while you browse other pages** — the LLM batches, the rescan
  (including its chained snapshot) and the snapshot all live at app level, with a pulsing
  masthead chip showing live progress from anywhere (a browser refresh or closed tab still
  ends an LLM batch after the in-flight ticker; rerun to resume from the gap). Rescans stream
  **live scan progress** the same way — a ticking `scanned/total` counter naming the in-flight
  ticker on the Discover bar, the Evaluation action bar and the masthead chip, plus a **Stop**
  button (stopping saves nothing; cached tickers make the redo fast).
  The snapshot's network call blends the active ontology and the Discover-board snapshot,
  so it records the freshest state right after a rescan (which is why Discover chains it).
  The Evaluation and Discover bars show whether the **US market is open and the next close in
  your local timezone**, and the Dashboard warns while the market is open — run after the
  close so calls are recorded against final daily prices (the app covers S&P 500 names, so
  the US session is the one that matters; holidays not modeled).
  Scoring runs automatically when you open the page, and can also run unattended via
  `python -m app.evaluation`.
  *Caveats:* a "hit" is a simple directional check (buy⇢up, sell⇢down, hold⇢flat within a
  band) over end-of-day prices — not risk-adjusted or benchmark-relative — and only scores the
  calls you actually ran; the per-ticker 👑 needs at least 3 scored outcomes before any source
  is crowned, and a source's chip reads *N of M scored — awaiting maturity* until its calls
  mature, so expect sparse data for the first weeks.
- **Free/minimal data** — `yfinance` for prices/fundamentals, Google News RSS for news.

## Architecture

```
┌─────────────────────────┐      REST/JSON      ┌──────────────────────────────┐
│ Frontend (React+Vite+TS) │  ───────────────▶  │ Backend (FastAPI, Python)      │
│  Dashboard · Portfolio · │  ◀───────────────  │  data · indicators · news      │
│  Discover · Graph · Chat │                    │  LLM providers · analyzer      │
│  Evaluation · Settings   │                    │  settings/cache (SQLite)       │
└─────────────────────────┘                    │  alerts·screener·network·eval  │
                                                └──────────────────────────────┘
```

- **Backend** (`backend/`) — FastAPI REST API + the `python -m app.alerts`,
  `python -m app.screener`, `python -m app.network`, and `python -m app.evaluation` CLIs.
  See [backend/README.md](backend/README.md).
- **Frontend** (`frontend/`) — React app (Dashboard · Portfolio · Discover · Graph · Evaluation ·
  Chat · Settings). See [frontend/README.md](frontend/README.md).
- **Design docs** — specs and implementation plans under [docs/superpowers/](docs/superpowers/).

## Prerequisites

- **Python 3.11+** (3.12/3.13 recommended). Avoid interpreters too new for prebuilt
  wheels — on a brand-new Python (e.g. 3.14) or **Windows on ARM**, `pip install` can
  fall back to source builds that need a C/Rust toolchain. If that happens, create the
  venv with an older arm64/x64 build instead (e.g. `py -3.12 -m venv .venv`).
- **Node.js 20.x** (the frontend toolchain is pinned to Vite 5 for Node 20 compatibility)
- Optional: a provider API key (Anthropic/OpenAI/Gemini/DeepSeek) **or** [Ollama](https://ollama.com)
  running locally for free, key-less analysis.

## Quick start (Windows)

From the project root:

```powershell
.\start.ps1
```

On first run this creates the backend virtual environment, installs backend + frontend
dependencies, then launches **both servers, each in its own window**:

- Backend → http://localhost:8000 (interactive API docs at `/docs`)
- Frontend → http://localhost:5173

Then open **http://localhost:5173**.

## Manual setup

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

### Frontend (in a second terminal)

```powershell
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

(Set `frontend/.env` `VITE_API_BASE` only if the backend isn't at `http://localhost:8000/api`.)

## Configure & use

1. Open http://localhost:5173 and go to **Settings**.
2. **Provider:** pick Anthropic / OpenAI / Gemini / DeepSeek and paste an API key (or pick **Ollama**
   and run `ollama serve` + `ollama pull llama3.1` — no key needed). Click **Test connection**.
3. On the **Dashboard**, enter a ticker (or use the watchlist), then click **Analyze with LLM**
   for a fast call — or **Deep Analysis** to watch the agent pull data step-by-step — to draw
   buy/sell markers and show the reasoning + news. The **Signals strip** in the header is the
   one place to compare all four calls (technical / network / fast / deep) before you act.
4. **Discover (optional):** open the **Discover** tab and click **Rescan** to build
   today's opportunity board across the full S&P 500. Click any row to open the
   LLM deep-dive for that ticker. You can also **add a custom company** (non-S&P 500) via
   the "Add company" form — the app auto-fills its name, exchange, and sector. For an
   automatic daily refresh, schedule `python -m app.screener` post-close (see
   [backend/README.md](backend/README.md)).
5. **Portfolio (optional):** open the **Portfolio** tab and click **Rescan portfolio** to
   score just your watchlist plus the companies in your active ontology — the scan takes
   seconds. The portfolio board becomes the primary scoring source for the Dashboard Signals
   strip, LLM prompts, and Graph node colours (falling back to the broad Discover scan for
   any ticker not in the portfolio). Build your watchlist on the Dashboard and your ontology
   on the Graph tab, then rescan here to keep it current.
6. **Alerts (optional):** in **Settings → Alerts**, enable alerts, paste a Telegram bot token
   (from [@BotFather](https://t.me/BotFather)) + your chat id, set RSI thresholds, and click
   **Send test alert**. Then schedule `python -m app.alerts` daily (see
   [backend/README.md](backend/README.md) for Windows Task Scheduler / cron steps).
7. **Evaluation (optional):** after a few days of analyses and rescans, open the
   **Evaluation** tab to see how accurate the calls were — per source (technical / network /
   LLM fast / LLM deep) and per company (1/5/20-day hit-rate, score, grade) — and click
   **Explain miss** on a bad one. The action bar runs on your **portfolio (watchlist + active
   ontology)**: click **Rescan portfolio** (re-scores and snapshots), **Fast LLM analysis**,
   or **Deep LLM analysis** — all without visiting the other pages. For unattended scoring,
   schedule `python -m app.evaluation` (see [backend/README.md](backend/README.md)).
8. **Chat (optional):** open the **Chat** tab and ask anything about your stocks in plain
   language — e.g. *"How does geopolitics affect NVDA?"*, *"Compare AMD vs NVDA using the
   ontology"*, or *"What's the strongest opportunity in my watchlist?"*. The assistant streams
   its reasoning steps as it pulls the data it needs and answers in Markdown; follow-up
   questions keep the conversation's context. It's exploratory — nothing it does is recorded —
   and the conversation clears on reload.

## Testing

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q      # backend suite
cd frontend; npx vitest run                            # frontend unit tests
cd frontend; npm run build                             # type-check + bundle
```

## Project layout

```
ai-stocks-news-analysis/
  backend/      FastAPI service + alerts/screener/network/evaluation CLIs (Python)
  frontend/     React + Vite + TypeScript dashboard
  docs/         design specs and implementation plans
  start.ps1     one-command launcher (Windows)
```

## Roadmap — recommended for the next release

Curated, high-value additions (roughly in priority order):

1. **More alert channels** — email (SMTP) and Slack/Discord webhooks alongside Telegram
   (the `Notifier` interface is already pluggable).
2. **Deeper backtesting** — the **Evaluation** page now tracks LLM-recommendation accuracy
   forward (1/5/20-day hit-rate + score). Extend it with **risk-adjusted / benchmark-relative**
   metrics and a true historical replay of the *indicator-rule* signals.
3. **Per-provider accuracy** — the Evaluation page already breaks accuracy out **by signal
   source** (technical / network / fast LLM / deep LLM) and records which provider/model made
   each call; also break the rollups out by provider to see which LLM is most reliable.
4. **Portfolio board enhancements** — the new Portfolio page already provides a focused
   multi-ticker board (watchlist + active ontology, rescanned in seconds). Remaining
   enhancements: inline price and RSI columns so you can compare current technicals at a
   glance without opening each ticker.
5. **Richer indicators** — MACD and Bollinger Bands (compute + chart overlays + new alert
   rules); make the indicator set user-configurable.
6. **Portfolio tracking** — enter holdings and show P/L plus position-aware context in the
   analysis. (This is distinct from the new Portfolio *scan* page, which scores opportunities
   across your watchlist + ontology — not about holdings or P/L.)
7. **Auth + deployment** — optional login and a Docker compose / one-box deploy so it can
   run as an always-on service (enabling true server-side scheduled jobs without the OS scheduler).
8. **Export** — download an analysis (chart + reasoning + news) as PDF/CSV.

## License & disclaimer

For personal/educational use. **Not financial advice.** Use at your own risk; verify
everything independently before making any investment decision.
