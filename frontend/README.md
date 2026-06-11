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

- **Dashboard** — pick a ticker and a chart timeframe (1M–5Y) and view the candlestick chart with SMA overlays. Edit your watchlist inline (★ toggle on the loaded ticker, × on each chip). A **Signals strip** loads with the ticker: the instant **no-LLM opportunity score** (score / reason chips / 🔗 network — same as the Discover board) plus the latest recorded call from each source — **TECH / NET / FAST / DEEP** — with an agree/conflict badge and a 👑 on the per-ticker historically-best source. Click **Analyze with LLM** (scoped to the selected timeframe) to draw buy/sell markers, list the signals (click one for its reasoning), and show the reasoning + key factors + news — or **Deep Analysis** to stream an agentic ReAct run live (collapsible Thought → Action → Observation trace panel); its result renders through the same chart/reasoning path.
- **Discover** — an opportunity board ranking the S&P 500 (or a sector) by a 0–100 no-LLM score; filter by sector/direction, choose how many rows to show, **Rescan** (which also snapshots your watchlist's technical/network calls into the Evaluation scoreboard), **Update S&P 500 list**, and click a row to deep-dive on the Dashboard.
- **Graph** — the company knowledge graph: explore from any company (one-hop ego graph + on-demand neighbour expansion) and save/load explored subgraphs per company. An **Import** tab enriches the graph with an external ontology model — paste/upload JSON (with a built-in **Copy ChatGPT prompt** button) and manage the imported overlay sets; imported entities render distinctly (grey external nodes, dashed edges). Lazy-loaded so the graph library stays out of the main bundle. Each imported set can be **merged into the current graph** with a conflict-resolution preview (links imported companies to the Discover list, collapses clashing nodes, dedupes relationships) so Save keeps them permanently. **Right-click** a node to add a relationship or delete it, or an edge to delete it; a collapsible **legend** on the canvas explains node/edge colours and styles.
- **Evaluation** — tracks how accurate past calls turned out to be across **all four signal sources** (Technical / Network / LLM fast / LLM deep): per-source scoreboard cards (calls / scored / hit-rate / grade) and a per-company board (hit-rate, 0–100 score, Strong/Mixed/Weak grade, overconfidence flag) that expands to each call's 1d/5d/20d ✓/✗ outcomes with a source badge per row and a source filter for the call list, plus an on-demand source-aware **Explain miss** LLM post-mortem, a confirm-guarded **Clear all results** reset (start the experiment over after a period of testing), plus an **action bar** that runs any process watchlist-wide — snapshot technical/network calls, batch fast/deep LLM analyses (live per-ticker chips + Stop; already-recorded tickers are skipped; all four processes live at app level so they survive page navigation — including the rescan's chained snapshot — with a pulsing masthead chip showing progress from any page), or a full Discover rescan — with a live **when-to-run hint** showing whether the US market is open and the next close in the user's local timezone (run after the close so daily prices are final; the same hint sits on the Discover bar, and the Dashboard shows it only while the market is open).
- **Settings** — choose the LLM provider (Anthropic/OpenAI/Gemini/DeepSeek/Ollama), set model + API key (or Ollama base URL), test the connection, edit the watchlist, and toggle the Truth Social / screener / network signals.

## Notes

- Built on the Vite 5 toolchain (vitest 2, lightweight-charts 4, react-force-graph-2d 1) for Node 20 compatibility.
- The backend API uses the `period` query param. `dividend_yield` from yfinance is already a percentage value (e.g. 0.35 = 0.35%), shown as-is.
