# Backend — AI Stocks & News Analysis

FastAPI service: US-stock data + indicators + news + multi-provider LLM analysis.

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
- `POST /api/analyze/{ticker}?period=2y`
- `GET  /api/settings` · `PUT /api/settings`
- `GET  /api/providers` · `POST /api/providers/{id}/test`
- `GET  /api/truth/mood` — current Truth Social mood + post count

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

The fetcher is isolated (`app/truth_social.py`) so the data source can be swapped (e.g.
`truthbrush` or a paid API). The mood read mirrors the per-day analysis cache — real-time
reaction to a breaking post is out of scope for this version.

> *Decision support only — not financial advice.* This is one weighted input among many;
> it never auto-triggers a trade or creates historical buy/sell chart markers.

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
