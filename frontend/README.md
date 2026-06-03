# Frontend — AI Stocks & News Analysis

React + Vite + TypeScript dashboard for the backend API.

## Setup

    cd frontend
    npm install

## Run (backend must be running on :8000)

    npm run dev      # http://localhost:5173

Set `VITE_API_BASE` (see `.env.example`) if the backend isn't at `http://localhost:8000/api`.

## Build / test / typecheck

    npm run build    # tsc -b && vite build (type-check + bundle)
    npx vitest run   # unit tests

## Pages

- **Dashboard** — pick a ticker and a chart timeframe (1M–5Y), and view the candlestick chart with SMA overlays. Click **Analyze with LLM** (analysis is scoped to the selected timeframe) to draw buy/sell markers, list the signals (click one for its reasoning), and show the reasoning + key factors + news.
- **Settings** — choose the LLM provider (Anthropic/OpenAI/Gemini/Ollama), set model + API key (or Ollama base URL), test the connection, and edit the watchlist.

## Notes

- Built on the Vite 5 toolchain (vitest 2, lightweight-charts 4) for Node 20 compatibility.
- The backend API uses the `period` query param. `dividend_yield` from yfinance is already a percentage value (e.g. 0.35 = 0.35%), shown as-is.
