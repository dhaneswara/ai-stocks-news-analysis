# AI Stocks & News Analysis — Design

- **Date:** 2026-06-02
- **Status:** Approved (v1 scope)
- **Owner:** giri.dhaneswara@gmail.com

## Overview

A personal web app for **swing / long-term US-stock** decision support. It pulls
price data, fundamentals, and recent news for a stock, computes simple technical
indicators, and asks an LLM to produce a structured analysis: a plain-language
summary, a read on the news, and a set of **buy/sell signals** that are drawn
directly on an interactive price chart with their reasoning shown on the page.

The LLM provider is user-selectable (Anthropic, OpenAI, Gemini, or local Ollama)
via a Settings page in the UI.

This is **decision support, not financial advice, and not an autopilot.** The app
never executes trades.

## Locked decisions

| Decision | Choice |
|---|---|
| Primary goal | Both: news/fundamentals digest **and** buy/sell flags with reasoning |
| Time horizon | Long-term / swing (daily data; no intraday/real-time) |
| Assets | US stocks |
| Delivery | Web dashboard |
| Web stack | **FastAPI** backend + **React (Vite + TypeScript)** frontend |
| Charting | **TradingView Lightweight Charts** (`setMarkers()` for buy/sell) |
| LLM providers | **Anthropic, OpenAI, Gemini, Ollama** — switchable in Settings |
| Analysis style | Single **structured analysis call** (typed, validated output) |
| Signal basis | News/fundamentals + simple indicators (SMA, RSI, 52-wk distance) |
| Budget | Free / minimal |
| Market data | `yfinance` (free) |
| Storage | **SQLite** for settings + cache |

## Non-goals (explicitly out of scope for v1)

- Scheduled digests and email/Telegram/Slack notifications
- True backtesting or validated performance metrics
- Portfolio / position tracking
- Intraday or real-time streaming data
- Authentication / multi-user
- Automated trade execution (never)

## Architecture

Two tiers communicating only via typed JSON. Pydantic models on the backend
mirror TypeScript types on the frontend, so each side is understandable and
testable in isolation.

```
┌─────────────────────────┐         REST/JSON          ┌──────────────────────────┐
│  React + Vite + TS       │  ───────────────────────▶  │  FastAPI (Python)          │
│  - Dashboard (chart,     │                            │  - data (yfinance, news)   │
│    reasoning, news)      │  ◀───────────────────────  │  - indicators (pure fns)   │
│  - Settings page         │                            │  - LLM provider layer      │
│  - Lightweight Charts    │                            │  - analyzer ("agent")      │
└─────────────────────────┘                            │  - settings + cache (SQLite)│
                                                        └──────────────────────────┘
```

## Backend components

Each unit has one purpose and a small, testable interface.

1. **Market data** — `data/market.py`
   Wraps `yfinance`. Returns daily OHLCV history (default ~1–2 years), current
   price, and fundamentals (market cap, P/E, EPS, dividend yield, 52-wk high/low).
   Sits behind the cache layer to respect free rate limits.

2. **News** — `data/news.py`
   Recent headlines per ticker: `{title, source, published_at, url, summary}`.
   Source: yfinance news, optionally augmented with Google News RSS. Deduplicated,
   newest N kept.

3. **Indicators** — `analysis/indicators.py`
   Pure functions over OHLCV: SMA(50/200), RSI(14), MACD, distance-from-52-wk-high,
   volume trend. No I/O — directly unit-testable.

4. **LLM provider layer** — `llm/`
   - `base.py` — `LLMProvider` protocol: `analyze(input: AnalysisInput) -> AnalysisResult`.
   - `anthropic_provider.py`, `openai_provider.py`, `gemini_provider.py`, `ollama_provider.py`
     — each uses its SDK's native structured/JSON output to return data matching the schema.
   - `factory.py` — builds the active provider from saved settings.

5. **Analyzer / "agent"** — `analysis/analyzer.py`
   Assembles the prompt payload `{ticker, price summary, indicators, fundamentals,
   recent news}`, calls the active provider, and validates the result against the
   Pydantic schema (one retry + repair prompt on invalid JSON).

6. **Settings store** — `config/settings_store.py`
   Persists provider config, API keys, watchlist, and indicator params in SQLite.
   Keys are stored locally (gitignored data dir; env-var fallback) and **masked**
   when returned to the UI.

7. **Cache** — `config/cache.py`
   SQLite-backed TTL cache. Stock data: short TTL (e.g. 15–60 min). Analysis:
   keyed by `ticker + provider + model + date` so revisiting a stock doesn't
   re-pay for an LLM call.

8. **API** — `api/routes.py` (FastAPI)
   - `GET  /api/stock/{ticker}?range=1y` → `StockData`
   - `POST /api/analyze/{ticker}` → `AnalysisResult` (cached)
   - `GET  /api/settings` → `Settings` (keys masked)
   - `PUT  /api/settings` → update settings
   - `GET  /api/providers` → `[{id, label, configured}]`
   - `POST /api/providers/{id}/test` → `{ok, message}` (connection test)

## Data model (contract)

```jsonc
// StockData
{
  "ticker": "AAPL",
  "company_name": "Apple Inc.",
  "as_of": "2026-06-02T00:00:00Z",
  "price": { "current": 0, "change": 0, "change_pct": 0, "currency": "USD" },
  "candles": [{ "time": "2026-05-30", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0 }],
  "fundamentals": { "market_cap": 0, "pe_ratio": 0, "eps": 0, "dividend_yield": 0, "week52_high": 0, "week52_low": 0 },
  "indicators": {
    "sma50": [{ "time": "2026-05-30", "value": 0 }],
    "sma200": [{ "time": "2026-05-30", "value": 0 }],
    "rsi14": [{ "time": "2026-05-30", "value": 0 }],
    "dist_from_52wk_high_pct": 0
  },
  "news": [{ "title": "", "source": "", "published_at": "", "url": "", "summary": "" }]
}

// AnalysisResult
{
  "ticker": "AAPL",
  "provider": "anthropic",
  "model": "claude-...",
  "generated_at": "2026-06-02T00:00:00Z",
  "overall_summary": "",
  "news_analysis": "",
  "sentiment": "bullish | neutral | bearish",
  "current_recommendation": "buy | sell | hold",
  "confidence": 0.0,
  "signals": [{ "date": "2026-04-15", "action": "buy | sell", "price": 0, "confidence": 0.0, "reasoning": "" }],
  "risks": [""],
  "disclaimer": "Not financial advice."
}

// Settings  (api keys write-only; returned masked)
{
  "active_provider": "anthropic | openai | gemini | ollama",
  "providers": {
    "anthropic": { "model": "", "api_key": "****" },
    "openai":    { "model": "", "api_key": "****" },
    "gemini":    { "model": "", "api_key": "****" },
    "ollama":    { "model": "", "base_url": "http://localhost:11434" }
  },
  "watchlist": ["AAPL", "MSFT"],
  "indicator_params": { "sma_windows": [50, 200], "rsi_length": 14 }
}
```

## Data flow

1. **Open dashboard** → `GET /api/stock/{ticker}` → backend fetches/caches price +
   fundamentals + news, computes indicators → chart and readouts render.
2. **Click Analyze** → `POST /api/analyze/{ticker}` → backend builds payload, calls
   the provider from settings, validates the typed result → frontend draws buy/sell
   markers, the reasoning panel, and the news analysis.
3. **Edit Settings** → `PUT /api/settings` persists provider/keys/watchlist →
   subsequent analyze calls use the new provider/model.

## Frontend components

- **Dashboard** (`pages/Dashboard.tsx`)
  - `components/PriceChart.tsx` — candlestick + SMA overlays; buy ▲ / sell ▼ markers
    from `signals` via `setMarkers()`; clicking a marker reveals that signal's reasoning.
  - `components/ReasoningPanel.tsx` — overall summary, news take, current recommendation
    + confidence, risks; disclaimer banner.
  - `components/NewsList.tsx` — recent headlines with source/date/links.
  - `components/IndicatorBar.tsx` — RSI, SMA50/200 relationship, distance from 52-wk high.
  - Ticker picker (watchlist + free input) and an "Analyze" button showing provider/model used.
- **Settings** (`pages/Settings.tsx`) — pick active provider; set model + API key (or
  Ollama base URL); **Test connection**; manage watchlist; tune indicator params.
- **Plumbing** — `api/client.ts` (typed fetch), TanStack Query for fetch/cache,
  `lightweight-charts` for the chart, shared `types.ts`.

## Configuration & secrets

- API keys entered in the Settings UI are stored in SQLite under a **gitignored**
  data directory; environment variables are a fallback for headless use.
- Keys are **never** returned in full to the frontend (masked as `****`).
- `.gitignore` covers the data dir, `.env`, `node_modules`, `__pycache__`, build output.

## Error handling

- Invalid ticker / data rate limit → clear API error; serve cached data if present.
- LLM bad key / timeout / malformed JSON → retry once with a repair prompt, validate
  against the schema, then surface a readable error. The page never crashes.
- Selected provider missing its key → Settings flags it; Analyze is disabled with a hint.
- Signal dates outside the chart window → clamped or dropped (logged).

## Testing strategy

- **Indicators** — known-input/expected-output unit tests (pytest).
- **Providers** — mocked SDK responses; a schema-conformance test per provider.
- **Analyzer** — prompt assembly + parsing/validation of a sample response (LLM mocked).
- **API** — FastAPI `TestClient` per route, with data and LLM mocked.
- **Frontend** — light Vitest/RTL: "given N signals, chart renders N markers"; settings form round-trip.
- **Manual** — run both tiers; analyze a couple of real tickers; eyeball markers/reasoning.

## Project structure

```
ai-stocks-news-analysis/
  backend/
    app/
      main.py                 # FastAPI app + CORS
      api/routes.py
      models/schemas.py       # StockData, AnalysisResult, Settings, Signal, AnalysisInput
      data/market.py
      data/news.py
      analysis/indicators.py
      analysis/analyzer.py
      llm/base.py
      llm/factory.py
      llm/anthropic_provider.py
      llm/openai_provider.py
      llm/gemini_provider.py
      llm/ollama_provider.py
      config/settings_store.py
      config/cache.py
    tests/
    pyproject.toml            # or requirements.txt
    .env.example
  frontend/
    src/
      pages/Dashboard.tsx
      pages/Settings.tsx
      components/PriceChart.tsx
      components/ReasoningPanel.tsx
      components/NewsList.tsx
      components/IndicatorBar.tsx
      api/client.ts
      types.ts
    package.json
    vite.config.ts
  docs/superpowers/specs/
  README.md
  .gitignore
```

## Build order (to be expanded by the implementation plan)

1. Backend skeleton: FastAPI app, schemas, yfinance market data + indicators, `GET /api/stock`. Tests.
2. LLM layer base + Anthropic adapter + analyzer + `POST /api/analyze`. Tests (mocked LLM).
3. Remaining providers (OpenAI, Gemini, Ollama) + factory + settings store + `GET/PUT /api/settings` + `/api/providers`.
4. Frontend scaffold (Vite/React/TS) + API client + Dashboard chart and data readouts.
5. Buy/sell markers + reasoning panel + news list wired to `/api/analyze`.
6. Settings page (provider/keys/watchlist/test connection).
7. Caching, error-handling polish, disclaimers, README.

## Risks & caveats

- **Not financial advice.** The LLM can be confidently wrong; output is decision support only. A disclaimer is shown in the UI and included in every `AnalysisResult`.
- **Historical markers are retrospective reasoning, not a backtested edge.** The actionable output is the *current recommendation*; historical signals exist for explanation/learning. Real backtesting is a later phase.
- **Free data is fragile.** `yfinance` is unofficial and can rate-limit or break. The cache mitigates this, and the data layer is behind an interface so a paid source (Alpha Vantage / Finnhub free tier) can be swapped in later.
- **Free-tier news is limited.** yfinance news is shallow; Google News RSS can augment it.
- **LLM cost.** Per-ticker/day analysis caching plus the option of cheap models or free local Ollama keeps cost near zero.
