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
