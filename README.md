# 📈 MarketCortex

A personal web app for **swing/long-term US-stock decision support**. It pulls price
data, fundamentals, and recent news for a stock, computes simple technical indicators,
and asks an **LLM (Anthropic / OpenAI / Gemini / local Ollama)** to produce a structured
analysis — a plain-language summary, a read on the news, and **buy/sell signals drawn
directly on an interactive chart** with the reasoning shown on the page. It can also send
**scheduled buy/sell alerts** to Telegram, rank opportunities across the S&P 500, map
inter-company relationships as a **knowledge graph**, run an **agentic Deep Analysis** that
pulls evidence on demand, and **grade how accurate its own past calls turn out to be — for
every signal source it produces** (fast LLM, deep LLM, technical screen, network-blended).

> ⚠️ **Decision support, not financial advice.** The LLM can be confidently wrong, and the
> on-chart/alert signals are mechanical heuristics + retrospective reasoning — **not** a
> backtested, validated strategy. This project does not execute trades.

---

## Features

- **Interactive dashboard** — candlestick chart (TradingView Lightweight Charts) with a
  **timeframe selector (1M / 3M / 6M / 1Y / 2Y / 5Y)**, SMA50/200 overlays, and LLM-drawn
  **buy ▲ / sell ▼ markers**. Click a marker — or a row in the dedicated **Signals** list — to
  read that signal's reasoning. Manage your **watchlist inline**: star (★) the loaded ticker
  to add it, or remove a chip with ×. The header shows a **Signals strip** as soon as a
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
- **Per-stock news** — recent headlines via Google News RSS.
- **Multi-provider, switchable in the UI** — Anthropic, OpenAI, Gemini, or local Ollama;
  API keys are stored locally and masked in the UI.
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
- **Discover — opportunity board** — a **Discover** tab auto-ranks the S&P 500 (or a
  sector slice) by a 0–100 opportunity score computed with a fast, no-LLM scorer (RSI /
  52-wk extremes, golden/death cross + SMA alignment, 1-month momentum, breakout proximity,
  volume surge, and an optional Trump-mention boost). Each row shows the score, a
  buy/sell/hold call, and plain-language reason chips. Clicking a row deep-links into the
  existing per-ticker LLM analysis. Filter by sector/direction and use the **Show** control
  (25 / 50 / 100 / All) to set how many ranked names appear; **Update S&P 500 list** rescrapes
  the current constituents from Wikipedia (validated, atomic write). A **Rescan** button
  triggers a fresh scan on demand; the daily snapshot can also be refreshed automatically via
  `python -m app.screener` (see [backend/README.md](backend/README.md)).
  *Caveats:* decision support only — the board is a screen, not a recommendation system;
  ranking ≠ prediction; data is end-of-day (not intraday); a Trump mention boosts attention
  but never determines the buy/sell direction.
- **Company knowledge graph / network signal** — an LLM extracts inter-company relationships
  (supplier, customer, partner, competitor, owner, subsidiary) from each focus company's news;
  a capped, **explainable network signal** then tilts the Discover board's buy/sell/hold by a
  company's neighbours (e.g. a key supplier's bad news weighs on the customer). The **Graph**
  tab visualises it and lets you **explore from any company** — a one-hop ego graph, on-demand
  neighbour expansion, and save/load of explored subgraphs per company (with version history).
  Only relationship extraction uses an LLM; propagation is pure and instant. Daily build:
  `python -m app.network` (after the screener — see [backend/README.md](backend/README.md)).
  You can also **import an external ontology model**: paste or upload a small JSON graph (e.g.
  produced by ChatGPT — the Import tab ships a copy-paste prompt template), and it's merged into
  the graph as a removable **overlay** that feeds the network signal like native edges. Entities
  are resolved to your tickers where possible, others kept as labelled external nodes; merge
  imported sets into a saved company graph (with conflict resolution + Discover linking), edit
  nodes/relationships by right-click, and an on-canvas legend.
- **Signal-source scoreboard (evaluation)** — every CALL the app produces is recorded and
  scored against what the price actually did at **1, 5, and 20 trading days** — not just LLM
  calls: **fast LLM**, **deep (agentic) LLM**, the deterministic **technical** screen, and the
  **network-blended** call are all tracked under identical rules, so *"which signal should I
  trust?"* becomes a measured answer instead of a feeling. The **Evaluation** tab shows
  per-source scoreboard cards (calls / scored / hit-rate / grade), per-company boards with a
  by-source breakdown and a source filter, an **overconfidence** flag for the LLM calls, and a
  source-aware **"Explain miss"** LLM post-mortem. Your watchlist's technical/network calls are
  snapshotted automatically every time you **Rescan** Discover; a deep run that silently fell
  back to the fast path is honestly recorded as fast so the deep-vs-fast comparison never lies.
  Scoring runs automatically when you open the page, and can also run unattended via
  `python -m app.evaluation`.
  *Caveats:* a "hit" is a simple directional check (buy⇢up, sell⇢down, hold⇢flat within a
  band) over end-of-day prices — not risk-adjusted or benchmark-relative — and only scores the
  calls you actually ran; the per-ticker 👑 needs at least 3 scored outcomes before any source
  is crowned, so expect "collecting data" for the first weeks.
- **Free/minimal data** — `yfinance` for prices/fundamentals, Google News RSS for news.

## Architecture

```
┌─────────────────────────┐      REST/JSON      ┌──────────────────────────────┐
│ Frontend (React+Vite+TS) │  ───────────────▶  │ Backend (FastAPI, Python)      │
│  Dashboard·Discover·Graph│  ◀───────────────  │  data · indicators · news      │
│  Evaluation · Settings   │                    │  LLM providers · analyzer      │
└─────────────────────────┘                    │  settings/cache (SQLite)       │
                                                │  alerts·screener·network·eval  │
                                                └──────────────────────────────┘
```

- **Backend** (`backend/`) — FastAPI REST API + the `python -m app.alerts`,
  `python -m app.screener`, `python -m app.network`, and `python -m app.evaluation` CLIs.
  See [backend/README.md](backend/README.md).
- **Frontend** (`frontend/`) — React app (Dashboard · Discover · Graph · Evaluation ·
  Settings). See [frontend/README.md](frontend/README.md).
- **Design docs** — specs and implementation plans under [docs/superpowers/](docs/superpowers/).

## Prerequisites

- **Python 3.11+** (3.13 recommended)
- **Node.js 20.x** (the frontend toolchain is pinned to Vite 5 for Node 20 compatibility)
- Optional: a provider API key (Anthropic/OpenAI/Gemini) **or** [Ollama](https://ollama.com)
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
2. **Provider:** pick Anthropic / OpenAI / Gemini and paste an API key (or pick **Ollama**
   and run `ollama serve` + `ollama pull llama3.1` — no key needed). Click **Test connection**.
3. On the **Dashboard**, enter a ticker (or use the watchlist), then click **Analyze with LLM**
   for a fast call — or **Deep Analysis** to watch the agent pull data step-by-step — to draw
   buy/sell markers and show the reasoning + news. The **Signals strip** in the header is the
   one place to compare all four calls (technical / network / fast / deep) before you act.
4. **Discover (optional):** open the **Discover** tab and click **Rescan all** to build
   today's opportunity board across the full S&P 500. Click any row to open the
   LLM deep-dive for that ticker. Each rescan also snapshots your watchlist's
   technical/network calls into the Evaluation scoreboard. For an automatic daily refresh,
   schedule `python -m app.screener` post-close (see [backend/README.md](backend/README.md)).
5. **Alerts (optional):** in **Settings → Alerts**, enable alerts, paste a Telegram bot token
   (from [@BotFather](https://t.me/BotFather)) + your chat id, set RSI thresholds, and click
   **Send test alert**. Then schedule `python -m app.alerts` daily (see
   [backend/README.md](backend/README.md) for Windows Task Scheduler / cron steps).
6. **Evaluation (optional):** after a few days of analyses and rescans, open the
   **Evaluation** tab to see how accurate the calls were — per source (technical / network /
   LLM fast / LLM deep) and per company (1/5/20-day hit-rate, score, grade) — and click
   **Explain miss** on a bad one. For unattended scoring, schedule
   `python -m app.evaluation` (see [backend/README.md](backend/README.md)).

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
4. **Watchlist overview page** — a multi-ticker table (price, RSI, recommendation, last
   signal) so you can scan the whole list at a glance, not one ticker at a time.
5. **Richer indicators** — MACD and Bollinger Bands (compute + chart overlays + new alert
   rules); make the indicator set user-configurable.
6. **Portfolio tracking** — enter holdings and show P/L plus position-aware context in the
   analysis.
7. **Auth + deployment** — optional login and a Docker compose / one-box deploy so it can
   run as an always-on service (enabling true server-side scheduled jobs without the OS scheduler).
8. **Export** — download an analysis (chart + reasoning + news) as PDF/CSV.

## License & disclaimer

For personal/educational use. **Not financial advice.** Use at your own risk; verify
everything independently before making any investment decision.
