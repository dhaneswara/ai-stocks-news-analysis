# 📈 AI Stocks & News Analysis

A personal web app for **swing/long-term US-stock decision support**. It pulls price
data, fundamentals, and recent news for a stock, computes simple technical indicators,
and asks an **LLM (Anthropic / OpenAI / Gemini / local Ollama)** to produce a structured
analysis — a plain-language summary, a read on the news, and **buy/sell signals drawn
directly on an interactive chart** with the reasoning shown on the page. It can also send
**scheduled buy/sell alerts** to Telegram.

> ⚠️ **Decision support, not financial advice.** The LLM can be confidently wrong, and the
> on-chart/alert signals are mechanical heuristics + retrospective reasoning — **not** a
> backtested, validated strategy. This project does not execute trades.

---

## Features

- **Interactive dashboard** — candlestick chart (TradingView Lightweight Charts) with a
  **timeframe selector (1M / 3M / 6M / 1Y / 2Y / 5Y)**, SMA50/200 overlays, and LLM-drawn
  **buy ▲ / sell ▼ markers**. Click a marker — or a row in the dedicated **Signals** list — to
  read that signal's reasoning.
- **LLM analysis** — runs over the chart's **selected timeframe** and weighs the latest news
  *together with* the technicals/fundamentals. Returns a plain-language summary, news
  interpretation, sentiment, a current buy/sell/hold recommendation with confidence, the
  **key factors driving it** ("why now"), dated buy/sell signals (timed **buy-low / sell-high**,
  with a deterministic guard that drops incoherent ones), and risks.
- **Per-stock news** — recent headlines via Google News RSS.
- **Multi-provider, switchable in the UI** — Anthropic, OpenAI, Gemini, or local Ollama;
  API keys are stored locally and masked in the UI.
- **Scheduled alerts** — a CLI evaluates indicator rules (RSI 30/70 crossings, golden/death
  cross) on your watchlist and sends deduplicated Telegram alerts (with best-effort LLM
  reasoning), scheduled via the OS.
- **Free/minimal data** — `yfinance` for prices/fundamentals, Google News RSS for news.

## Architecture

```
┌─────────────────────────┐      REST/JSON      ┌──────────────────────────────┐
│ Frontend (React+Vite+TS) │  ───────────────▶  │ Backend (FastAPI, Python)      │
│  Dashboard + Settings    │  ◀───────────────  │  data · indicators · news      │
│  Lightweight Charts      │                    │  LLM providers · analyzer      │
└─────────────────────────┘                    │  settings/cache (SQLite)       │
                                                │  alerts (CLI + Telegram)       │
                                                └──────────────────────────────┘
```

- **Backend** (`backend/`) — FastAPI REST API + the `python -m app.alerts` CLI. See
  [backend/README.md](backend/README.md).
- **Frontend** (`frontend/`) — React dashboard. See [frontend/README.md](frontend/README.md).
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
   to draw buy/sell markers and show the reasoning + news.
4. **Alerts (optional):** in **Settings → Alerts**, enable alerts, paste a Telegram bot token
   (from [@BotFather](https://t.me/BotFather)) + your chat id, set RSI thresholds, and click
   **Send test alert**. Then schedule `python -m app.alerts` daily (see
   [backend/README.md](backend/README.md) for Windows Task Scheduler / cron steps).

## Testing

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q      # backend (82 tests)
cd frontend; npx vitest run                            # frontend unit tests
cd frontend; npm run build                             # type-check + bundle
```

## Project layout

```
ai-stocks-news-analysis/
  backend/      FastAPI service + alerts CLI (Python)
  frontend/     React + Vite + TypeScript dashboard
  docs/         design specs and implementation plans
  start.ps1     one-command launcher (Windows)
```

## Roadmap — recommended for the next release

Curated, high-value additions (roughly in priority order):

1. **More alert channels** — email (SMTP) and Slack/Discord webhooks alongside Telegram
   (the `Notifier` interface is already pluggable).
2. **Backtesting & signal performance** — replay the indicator rules (and/or LLM
   recommendations) over history and report hit-rate / return so signals can be judged,
   not just shown. This is the biggest credibility upgrade.
3. **Analysis history** — persist each `AnalysisResult` so you can see how the LLM's
   recommendation for a ticker changed over time (and diff against price moves).
4. **Watchlist overview page** — a multi-ticker table (price, RSI, recommendation, last
   signal) so you can scan the whole list at a glance, not one ticker at a time.
5. **Richer indicators** — MACD and Bollinger Bands (compute + chart overlays + new alert
   rules); make the indicator set user-configurable.
6. **Portfolio tracking** — enter holdings and show P/L plus position-aware context in the
   analysis.
7. **Auth + deployment** — optional login and a Docker compose / one-box deploy so it can
   run as an always-on service (enabling true server-side scheduled alerts without the OS scheduler).
8. **Export** — download an analysis (chart + reasoning + news) as PDF/CSV.

## License & disclaimer

For personal/educational use. **Not financial advice.** Use at your own risk; verify
everything independently before making any investment decision.
