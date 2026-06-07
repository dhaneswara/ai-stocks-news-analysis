# Frontend — MarketCortex

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

- **Dashboard** — pick a ticker and a chart timeframe (1M–5Y) and view the candlestick chart with SMA overlays. Edit your watchlist inline (★ toggle on the loaded ticker, × on each chip). A compact **Signal** chip shows the instant **no-LLM opportunity score** (score / call / reason chips / 🔗 network) — the same as the Discover board — as soon as the ticker loads. Click **Analyze with LLM** (analysis is scoped to the selected timeframe) to draw buy/sell markers, list the signals (click one for its reasoning), and show the reasoning + key factors + news.
- **Discover** — an opportunity board ranking the S&P 500 (or a sector) by a 0–100 no-LLM score; filter by sector/direction, choose how many rows to show, **Rescan**, **Update S&P 500 list**, and click a row to deep-dive on the Dashboard.
- **Graph** — the company knowledge graph: explore from any company (one-hop ego graph + on-demand neighbour expansion) and save/load explored subgraphs per company. An **Import** tab enriches the graph with an external ontology model — paste/upload JSON (with a built-in **Copy ChatGPT prompt** button) and manage the imported overlay sets; imported entities render distinctly (grey external nodes, dashed edges). Lazy-loaded so the graph library stays out of the main bundle.
- **Evaluation** — tracks how accurate past **Analyze with LLM** calls turned out to be: a per-company board (hit-rate, 0–100 score, Strong/Mixed/Weak grade, overconfidence flag) that expands to each call's 1d/5d/20d ✓/✗ outcomes, with an on-demand **Explain miss** LLM post-mortem.
- **Settings** — choose the LLM provider (Anthropic/OpenAI/Gemini/Ollama), set model + API key (or Ollama base URL), test the connection, edit the watchlist, and toggle the Truth Social / screener / network signals.

## Notes

- Built on the Vite 5 toolchain (vitest 2, lightweight-charts 4, react-force-graph-2d 1) for Node 20 compatibility.
- The backend API uses the `period` query param. `dividend_yield` from yfinance is already a percentage value (e.g. 0.35 = 0.35%), shown as-is.
