# Frontend (React + Vite + TS) Implementation Plan — AI Stocks & News Analysis

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React dashboard that consumes the backend API: pick a ticker, see an interactive candlestick chart with SMA overlays and LLM-drawn buy/sell markers, read the analysis reasoning and per-stock news, and configure the LLM provider on a Settings page.

**Architecture:** Vite + React + TypeScript SPA. TanStack Query owns server state (fetch/cache); a thin typed `api` client wraps the 6 backend endpoints; `lightweight-charts` (v4) renders the chart and markers. Two routes — Dashboard and Settings — under a small app shell. TypeScript types mirror the backend Pydantic schemas exactly.

**Tech Stack:** Vite, React 18, TypeScript, react-router-dom v6, @tanstack/react-query v5, lightweight-charts ~4.2, Vitest + Testing Library.

**Reference spec:** `docs/superpowers/specs/2026-06-02-ai-stocks-news-analysis-design.md`. **Backend** (already built, on `master`) runs at `http://localhost:8000`; CORS already allows the Vite dev origin `http://localhost:5173`.

**Backend contract notes (important):**
- Query param is `?period=` (e.g. `2y`), NOT `range`.
- `fundamentals.dividend_yield` is a fraction (e.g. 0.0054) — multiply ×100 for display.
- `GET/PUT /api/settings` mask api keys as `****`; sending `****` back preserves the stored key.

**Testing approach (read this):** Frontend logic is unit-tested with Vitest (the `api` client and the `signalsToMarkers` mapper). Visual/React components are verified by `tsc --noEmit` (type check) + `vite build` (compile) + a final live visual smoke (controller-run). We do NOT force red-green TDD on presentational components — that's low-value for JSX. Each task lists its exact gate.

---

## File Structure

All paths under `frontend/`.

| File | Responsibility |
|---|---|
| `package.json`, `vite.config.ts`, `tsconfig*.json`, `index.html` | Scaffold + Vitest config. |
| `.env.example` | Documents `VITE_API_BASE`. |
| `src/main.tsx` | Entry: QueryClientProvider + BrowserRouter. |
| `src/App.tsx` | Layout, nav, routes, disclaimer banner. |
| `src/types.ts` | TS types mirroring backend schemas. |
| `src/api/client.ts` | Typed fetch wrapper for the 6 endpoints. |
| `src/lib/markers.ts` | `signalsToMarkers` pure mapper (signals → chart markers). |
| `src/hooks/queries.ts` | TanStack Query hooks (stock, analyze, settings, providers). |
| `src/components/PriceChart.tsx` | Candlestick + SMA overlays + buy/sell markers. |
| `src/components/IndicatorBar.tsx` | Latest RSI / SMA / 52-wk distance / fundamentals readout. |
| `src/components/ReasoningPanel.tsx` | Summary, news take, recommendation, confidence, risks, selected-signal reasoning. |
| `src/components/NewsList.tsx` | Recent headlines with links. |
| `src/components/TickerBar.tsx` | Ticker input + watchlist quick-picks + Analyze button. |
| `src/pages/Dashboard.tsx` | Composes the above; owns ticker + analysis state. |
| `src/pages/Settings.tsx` | Provider/model/key form, test-connection, watchlist. |
| `src/styles.css` | Dark dashboard styling. |
| `src/test-setup.ts` | jest-dom matchers for Vitest. |
| `src/lib/markers.test.ts`, `src/api/client.test.ts` | Unit tests. |

---

## Task 1: Scaffold the Vite React-TS app

**Files:** create the `frontend/` project; modify `vite.config.ts`; add `src/test-setup.ts`, `.env.example`.

- [ ] **Step 1: Scaffold via create-vite (gets correct, current versions)**

Run from `D:\workspace\ai-stocks-news-analysis`:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: Install runtime + dev dependencies**

From `frontend/`:
```bash
npm install react-router-dom @tanstack/react-query "lightweight-charts@~4.2.0"
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom
```

- [ ] **Step 3: Replace `frontend/vite.config.ts`** (adds Vitest config)
```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
  },
});
```

- [ ] **Step 4: Create `frontend/src/test-setup.ts`**
```ts
import '@testing-library/jest-dom';
```

- [ ] **Step 5: Create `frontend/.env.example`**
```bash
# Base URL of the backend API. Defaults to http://localhost:8000/api if unset.
VITE_API_BASE=http://localhost:8000/api
```

- [ ] **Step 6: Add a trivial smoke test `frontend/src/smoke.test.ts`**
```ts
import { describe, expect, it } from 'vitest';

describe('toolchain', () => {
  it('runs vitest', () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 7: Verify toolchain**

From `frontend/`:
```bash
npx tsc --noEmit
npx vitest run
npm run build
```
Expected: tsc clean; 1 test passes; build succeeds (produces `dist/`). The default Vite template `App.tsx`/`App.css` may remain for now — later tasks replace them.

- [ ] **Step 8: Commit**
```bash
git add frontend
git commit -m "feat(frontend): scaffold Vite React-TS app with Vitest"
```
(Note: the repo-root `.gitignore` already ignores `node_modules/`, `dist/`, `*.local`.)

---

## Task 2: Types + API client

**Files:** Create `frontend/src/types.ts`, `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`.

- [ ] **Step 1: Create `frontend/src/types.ts`** (mirrors backend schemas exactly)
```ts
export interface Candle { time: string; open: number; high: number; low: number; close: number; volume: number; }
export interface IndicatorPoint { time: string; value: number; }
export interface Indicators {
  sma50: IndicatorPoint[];
  sma200: IndicatorPoint[];
  rsi14: IndicatorPoint[];
  dist_from_52wk_high_pct: number | null;
}
export interface Fundamentals {
  market_cap: number | null;
  pe_ratio: number | null;
  eps: number | null;
  dividend_yield: number | null;
  week52_high: number | null;
  week52_low: number | null;
}
export interface PriceSummary { current: number; change: number; change_pct: number; currency: string; }
export interface NewsItem { title: string; source: string; published_at: string; url: string; summary: string; }
export interface StockData {
  ticker: string;
  company_name: string;
  as_of: string;
  price: PriceSummary;
  candles: Candle[];
  fundamentals: Fundamentals;
  indicators: Indicators;
  news: NewsItem[];
}
export type Action = 'buy' | 'sell';
export interface Signal { date: string; action: Action; price: number; confidence: number; reasoning: string; }
export type Sentiment = 'bullish' | 'neutral' | 'bearish';
export type Recommendation = 'buy' | 'sell' | 'hold';
export interface AnalysisResult {
  ticker: string;
  provider: string;
  model: string;
  generated_at: string;
  overall_summary: string;
  news_analysis: string;
  sentiment: Sentiment;
  current_recommendation: Recommendation;
  confidence: number;
  signals: Signal[];
  risks: string[];
  disclaimer: string;
}
export interface ProviderConfig { model: string; api_key: string; base_url: string; }
export interface IndicatorParams { sma_windows: number[]; rsi_length: number; }
export type ProviderId = 'anthropic' | 'openai' | 'gemini' | 'ollama';
export interface Settings {
  active_provider: ProviderId;
  providers: Record<string, ProviderConfig>;
  watchlist: string[];
  indicator_params: IndicatorParams;
}
export interface ProviderInfo { id: string; label: string; configured: boolean; default_model: string; }
export interface TestResult { ok: boolean; message: string; }
```

- [ ] **Step 2: Create `frontend/src/api/client.ts`**
```ts
import type {
  AnalysisResult,
  ProviderInfo,
  Settings,
  StockData,
  TestResult,
} from '../types';

const BASE = (import.meta.env.VITE_API_BASE as string) || 'http://localhost:8000/api';

export async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  getStock: (ticker: string, period = '2y') =>
    http<StockData>(`/stock/${encodeURIComponent(ticker)}?period=${period}`),
  analyze: (ticker: string, period = '2y') =>
    http<AnalysisResult>(`/analyze/${encodeURIComponent(ticker)}?period=${period}`, {
      method: 'POST',
    }),
  getSettings: () => http<Settings>('/settings'),
  saveSettings: (s: Settings) =>
    http<Settings>('/settings', { method: 'PUT', body: JSON.stringify(s) }),
  listProviders: () => http<ProviderInfo[]>('/providers'),
  testProvider: (id: string) =>
    http<TestResult>(`/providers/${encodeURIComponent(id)}/test`, { method: 'POST' }),
};
```

- [ ] **Step 3: Write the test `frontend/src/api/client.test.ts`**
```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';

afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('GET stock parses JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ticker: 'AAPL' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const data = await api.getStock('AAPL');
    expect(data.ticker).toBe('AAPL');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/stock/AAPL?period=2y'),
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it('throws with backend detail on error response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, statusText: 'Bad', json: async () => ({ detail: 'No price history' }) }),
    );
    await expect(api.getStock('NOPE')).rejects.toThrow('No price history');
  });

  it('analyze POSTs', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticker: 'AAPL' }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.analyze('AAPL');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/analyze/AAPL'),
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
```

- [ ] **Step 4: Verify**

From `frontend/`: `npx vitest run src/api/client.test.ts` → 3 pass. Then `npx tsc --noEmit` → clean.

- [ ] **Step 5: Commit**
```bash
git add frontend/src/types.ts frontend/src/api
git commit -m "feat(frontend): add API types and typed fetch client"
```

---

## Task 3: Markers mapper + query hooks

**Files:** Create `frontend/src/lib/markers.ts`, `frontend/src/lib/markers.test.ts`, `frontend/src/hooks/queries.ts`.

- [ ] **Step 1: Write the failing test `frontend/src/lib/markers.test.ts`**
```ts
import { describe, expect, it } from 'vitest';
import { signalsToMarkers } from './markers';
import type { Signal } from '../types';

const signals: Signal[] = [
  { date: '2026-05-10', action: 'sell', price: 200, confidence: 0.6, reasoning: 'x' },
  { date: '2026-04-01', action: 'buy', price: 150, confidence: 0.7, reasoning: 'y' },
];

describe('signalsToMarkers', () => {
  it('sorts by date ascending', () => {
    const m = signalsToMarkers(signals);
    expect(m.map((x) => x.time)).toEqual(['2026-04-01', '2026-05-10']);
  });

  it('maps buy below-bar arrowUp and sell above-bar arrowDown', () => {
    const m = signalsToMarkers(signals);
    const buy = m.find((x) => x.time === '2026-04-01')!;
    const sell = m.find((x) => x.time === '2026-05-10')!;
    expect(buy.position).toBe('belowBar');
    expect(buy.shape).toBe('arrowUp');
    expect(sell.position).toBe('aboveBar');
    expect(sell.shape).toBe('arrowDown');
  });

  it('does not mutate the input array order', () => {
    const copy = [...signals];
    signalsToMarkers(signals);
    expect(signals).toEqual(copy);
  });
});
```

- [ ] **Step 2: Run, confirm it FAILS** (`Cannot find module './markers'`). From `frontend/`: `npx vitest run src/lib/markers.test.ts`.

- [ ] **Step 3: Create `frontend/src/lib/markers.ts`**
```ts
import type { Signal } from '../types';

export interface ChartMarker {
  time: string;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

// lightweight-charts requires markers sorted by time ascending.
export function signalsToMarkers(signals: Signal[]): ChartMarker[] {
  return [...signals]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((s) => ({
      time: s.date,
      position: s.action === 'buy' ? 'belowBar' : 'aboveBar',
      color: s.action === 'buy' ? '#26a69a' : '#ef5350',
      shape: s.action === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${s.action.toUpperCase()} @ ${s.price}`,
    }));
}
```

- [ ] **Step 4: Run, confirm 3 pass.**

- [ ] **Step 5: Create `frontend/src/hooks/queries.ts`**
```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Settings } from '../types';

export function useStock(ticker: string, period = '2y') {
  return useQuery({
    queryKey: ['stock', ticker, period],
    queryFn: () => api.getStock(ticker, period),
    enabled: ticker.length > 0,
    retry: false,
  });
}

export function useAnalyze(ticker: string, period = '2y') {
  return useMutation({ mutationFn: () => api.analyze(ticker, period) });
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: api.getSettings });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (s: Settings) => api.saveSettings(s),
    onSuccess: (data) => qc.setQueryData(['settings'], data),
  });
}

export function useProviders() {
  return useQuery({ queryKey: ['providers'], queryFn: api.listProviders });
}
```

- [ ] **Step 6: Verify** `npx tsc --noEmit` clean, then commit.
```bash
git add frontend/src/lib frontend/src/hooks
git commit -m "feat(frontend): add signalsToMarkers mapper and query hooks"
```

---

## Task 4: App shell (entry, layout, routing, styles)

**Files:** Replace `frontend/src/main.tsx`, `frontend/src/App.tsx`; create `frontend/src/styles.css`; delete the template `src/App.css` and `src/index.css` if present (fold needed resets into styles.css). Create placeholder `src/pages/Dashboard.tsx` and `src/pages/Settings.tsx` so routes resolve.

- [ ] **Step 1: Replace `frontend/src/main.tsx`**
```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 2: Replace `frontend/src/App.tsx`**
```tsx
import { NavLink, Route, Routes } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Settings from './pages/Settings';

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">📈 AI Stocks &amp; News</span>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <p className="disclaimer">
        Decision support only — not financial advice. LLM output can be wrong; historical markers are
        retrospective reasoning, not a backtested strategy.
      </p>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Create placeholder pages** so routing compiles (replaced in later tasks).

`frontend/src/pages/Dashboard.tsx`:
```tsx
export default function Dashboard() {
  return <div>Dashboard</div>;
}
```
`frontend/src/pages/Settings.tsx`:
```tsx
export default function Settings() {
  return <div>Settings</div>;
}
```

- [ ] **Step 4: Create `frontend/src/styles.css`**
```css
:root {
  --bg: #0b0d12;
  --panel: #141821;
  --panel-2: #1c212c;
  --border: #262c39;
  --text: #d8dce5;
  --muted: #8b93a7;
  --green: #26a69a;
  --red: #ef5350;
  --accent: #4c8dff;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
a { color: var(--accent); text-decoration: none; }
.app { max-width: 1200px; margin: 0 auto; padding: 0 16px 48px; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 16px 0; }
.brand { font-weight: 700; font-size: 18px; }
.topbar nav a { margin-left: 16px; color: var(--muted); padding: 6px 10px; border-radius: 6px; }
.topbar nav a.active { color: var(--text); background: var(--panel-2); }
.disclaimer { background: #2a2310; border: 1px solid #4a3d12; color: #e6c869; padding: 8px 12px; border-radius: 8px; font-size: 12px; margin: 0 0 16px; }
.content { display: flex; flex-direction: column; gap: 16px; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.row { display: flex; gap: 16px; flex-wrap: wrap; }
.row > * { flex: 1; min-width: 280px; }
.price-chart { width: 100%; height: 420px; }
input, select, button { font: inherit; }
input, select { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 8px 10px; }
button { background: var(--accent); color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
button.secondary { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.tickerbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.chip { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); padding: 4px 10px; border-radius: 999px; cursor: pointer; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.metric { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.metric .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
.metric .value { font-size: 16px; font-weight: 600; }
.badge { padding: 2px 8px; border-radius: 999px; font-weight: 700; font-size: 12px; }
.badge.buy, .badge.bullish { background: rgba(38,166,154,.15); color: var(--green); }
.badge.sell, .badge.bearish { background: rgba(239,83,80,.15); color: var(--red); }
.badge.hold, .badge.neutral { background: var(--panel-2); color: var(--muted); }
.news-item { padding: 8px 0; border-bottom: 1px solid var(--border); }
.news-item .meta { color: var(--muted); font-size: 12px; }
.muted { color: var(--muted); }
.error { color: var(--red); }
.field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
.field label { color: var(--muted); font-size: 12px; }
.signal-reason { border-left: 3px solid var(--accent); padding-left: 10px; margin-top: 8px; }
```

- [ ] **Step 5: Remove leftover template CSS imports.** If `src/App.css`/`src/index.css` exist and are imported, delete the files and remove their imports (only `styles.css` is imported, in `main.tsx`).

- [ ] **Step 6: Verify** `npx tsc --noEmit` clean and `npm run build` succeeds. (Optional: `npm run dev` and confirm the nav + two routes render.)

- [ ] **Step 7: Commit**
```bash
git add frontend/src
git commit -m "feat(frontend): app shell with routing, nav, disclaimer, styles"
```

---

## Task 5: Presentational components (IndicatorBar, NewsList, ReasoningPanel, TickerBar)

**Files:** Create `frontend/src/components/IndicatorBar.tsx`, `NewsList.tsx`, `ReasoningPanel.tsx`, `TickerBar.tsx`.

- [ ] **Step 1: Create `frontend/src/components/IndicatorBar.tsx`**
```tsx
import type { StockData } from '../types';

function fmt(n: number | null | undefined, digits = 2): string {
  return n === null || n === undefined ? '—' : n.toFixed(digits);
}
function money(n: number | null): string {
  if (n === null) return '—';
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  return `${n}`;
}
function lastValue(points: { value: number }[]): number | null {
  return points.length ? points[points.length - 1].value : null;
}

export function IndicatorBar({ data }: { data: StockData }) {
  const rsi = lastValue(data.indicators.rsi14);
  const sma50 = lastValue(data.indicators.sma50);
  const sma200 = lastValue(data.indicators.sma200);
  const div = data.fundamentals.dividend_yield;
  return (
    <div className="metrics">
      <div className="metric"><div className="label">Price</div><div className="value">{fmt(data.price.current)}</div></div>
      <div className="metric"><div className="label">Change %</div><div className="value">{fmt(data.price.change_pct)}%</div></div>
      <div className="metric"><div className="label">RSI(14)</div><div className="value">{fmt(rsi)}</div></div>
      <div className="metric"><div className="label">SMA50</div><div className="value">{fmt(sma50)}</div></div>
      <div className="metric"><div className="label">SMA200</div><div className="value">{fmt(sma200)}</div></div>
      <div className="metric"><div className="label">52wk dist</div><div className="value">{fmt(data.indicators.dist_from_52wk_high_pct)}%</div></div>
      <div className="metric"><div className="label">P/E</div><div className="value">{fmt(data.fundamentals.pe_ratio)}</div></div>
      <div className="metric"><div className="label">Mkt cap</div><div className="value">{money(data.fundamentals.market_cap)}</div></div>
      <div className="metric"><div className="label">Div yield</div><div className="value">{div === null ? '—' : `${(div * 100).toFixed(2)}%`}</div></div>
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/src/components/NewsList.tsx`**
```tsx
import type { NewsItem } from '../types';

export function NewsList({ news }: { news: NewsItem[] }) {
  if (!news.length) return <p className="muted">No recent headlines found.</p>;
  return (
    <div>
      {news.map((n, i) => (
        <div className="news-item" key={`${n.url}-${i}`}>
          <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
          <div className="meta">{[n.source, n.published_at].filter(Boolean).join(' · ')}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/ReasoningPanel.tsx`**
```tsx
import type { AnalysisResult, Signal } from '../types';

export function ReasoningPanel({
  result,
  selected,
}: {
  result: AnalysisResult;
  selected: Signal | null;
}) {
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <span className={`badge ${result.current_recommendation}`}>
          {result.current_recommendation.toUpperCase()}
        </span>
        <span className={`badge ${result.sentiment}`}>{result.sentiment}</span>
        <span className="muted">confidence {(result.confidence * 100).toFixed(0)}%</span>
        <span className="muted" style={{ marginLeft: 'auto' }}>{result.provider} · {result.model}</span>
      </div>
      <h4>Summary</h4>
      <p>{result.overall_summary}</p>
      <h4>News analysis</h4>
      <p>{result.news_analysis}</p>
      {result.risks.length > 0 && (
        <>
          <h4>Risks</h4>
          <ul>{result.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </>
      )}
      {selected && (
        <div className="signal-reason">
          <strong className={`badge ${selected.action}`}>{selected.action.toUpperCase()}</strong>{' '}
          {selected.date} @ {selected.price} (confidence {(selected.confidence * 100).toFixed(0)}%)
          <p>{selected.reasoning}</p>
        </div>
      )}
      <p className="muted" style={{ fontSize: 11, marginTop: 12 }}>{result.disclaimer}</p>
    </div>
  );
}
```

- [ ] **Step 4: Create `frontend/src/components/TickerBar.tsx`**
```tsx
import { useState } from 'react';

export function TickerBar({
  watchlist,
  onSelect,
  onAnalyze,
  analyzing,
  canAnalyze,
}: {
  watchlist: string[];
  onSelect: (ticker: string) => void;
  onAnalyze: () => void;
  analyzing: boolean;
  canAnalyze: boolean;
}) {
  const [input, setInput] = useState('');
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (t) onSelect(t);
  };
  return (
    <div className="tickerbar">
      <form onSubmit={submit} style={{ display: 'flex', gap: 8 }}>
        <input
          aria-label="ticker"
          placeholder="Ticker e.g. AAPL"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" className="secondary">Load</button>
      </form>
      {watchlist.map((t) => (
        <span className="chip" key={t} onClick={() => onSelect(t)}>{t}</span>
      ))}
      <button style={{ marginLeft: 'auto' }} onClick={onAnalyze} disabled={!canAnalyze || analyzing}>
        {analyzing ? 'Analyzing…' : 'Analyze with LLM'}
      </button>
    </div>
  );
}
```

- [ ] **Step 5: Verify** `npx tsc --noEmit` clean.

- [ ] **Step 6: Commit**
```bash
git add frontend/src/components
git commit -m "feat(frontend): add IndicatorBar, NewsList, ReasoningPanel, TickerBar"
```

---

## Task 6: PriceChart (candlestick + SMA overlays + markers)

**Files:** Create `frontend/src/components/PriceChart.tsx`.

- [ ] **Step 1: Create `frontend/src/components/PriceChart.tsx`**
```tsx
import { useEffect, useRef } from 'react';
import { ColorType, createChart, type IChartApi } from 'lightweight-charts';
import type { Signal, StockData } from '../types';
import { signalsToMarkers } from '../lib/markers';

export function PriceChart({
  data,
  signals,
  onSelectSignal,
}: {
  data: StockData;
  signals: Signal[];
  onSelectSignal?: (s: Signal) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart: IChartApi = createChart(el, {
      autoSize: true,
      height: 420,
      layout: { background: { type: ColorType.Solid, color: '#0b0d12' }, textColor: '#d8dce5' },
      grid: { vertLines: { color: '#1c212c' }, horzLines: { color: '#1c212c' } },
      rightPriceScale: { borderColor: '#262c39' },
      timeScale: { borderColor: '#262c39' },
    });

    const candles = chart.addCandlestickSeries({
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candles.setData(
      data.candles.map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })),
    );

    if (data.indicators.sma50.length) {
      const s = chart.addLineSeries({ color: '#f0b90b', lineWidth: 1, priceLineVisible: false });
      s.setData(data.indicators.sma50.map((p) => ({ time: p.time, value: p.value })));
    }
    if (data.indicators.sma200.length) {
      const s = chart.addLineSeries({ color: '#4c8dff', lineWidth: 1, priceLineVisible: false });
      s.setData(data.indicators.sma200.map((p) => ({ time: p.time, value: p.value })));
    }

    candles.setMarkers(
      signalsToMarkers(signals).map((m) => ({
        time: m.time,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text,
      })),
    );

    if (onSelectSignal) {
      chart.subscribeClick((param) => {
        const t = param.time as unknown as string | undefined;
        if (!t) return;
        const hit = signals.find((s) => s.date === t);
        if (hit) onSelectSignal(hit);
      });
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, signals, onSelectSignal]);

  return <div ref={containerRef} className="price-chart" />;
}
```

- [ ] **Step 2: Verify** `npx tsc --noEmit` clean and `npm run build` succeeds (this confirms the lightweight-charts v4 API calls type-check against the installed version). If the build reports that `addCandlestickSeries`/`setMarkers` don't exist, the installed major version is not v4 — STOP and report (do not silently rewrite to a different API).

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/PriceChart.tsx
git commit -m "feat(frontend): add PriceChart with SMA overlays and buy/sell markers"
```

---

## Task 7: Dashboard page (wire it together)

**Files:** Replace `frontend/src/pages/Dashboard.tsx`.

- [ ] **Step 1: Replace `frontend/src/pages/Dashboard.tsx`**
```tsx
import { useEffect, useState } from 'react';
import { PriceChart } from '../components/PriceChart';
import { IndicatorBar } from '../components/IndicatorBar';
import { NewsList } from '../components/NewsList';
import { ReasoningPanel } from '../components/ReasoningPanel';
import { TickerBar } from '../components/TickerBar';
import { useAnalyze, useSettings, useStock } from '../hooks/queries';
import type { AnalysisResult, Signal } from '../types';

export default function Dashboard() {
  const settings = useSettings();
  const watchlist = settings.data?.watchlist ?? [];
  const [ticker, setTicker] = useState('');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [selected, setSelected] = useState<Signal | null>(null);

  const stock = useStock(ticker);
  const analyze = useAnalyze(ticker);

  // Default to the first watchlist ticker once settings load.
  useEffect(() => {
    if (!ticker && watchlist.length) setTicker(watchlist[0]);
  }, [watchlist, ticker]);

  // Reset analysis when the ticker changes.
  useEffect(() => {
    setAnalysis(null);
    setSelected(null);
  }, [ticker]);

  const runAnalyze = () => {
    analyze.mutate(undefined, { onSuccess: (res) => setAnalysis(res) });
  };

  return (
    <>
      <div className="panel">
        <TickerBar
          watchlist={watchlist}
          onSelect={setTicker}
          onAnalyze={runAnalyze}
          analyzing={analyze.isPending}
          canAnalyze={!!stock.data}
        />
      </div>

      {!ticker && <p className="muted">Enter a ticker or pick one from your watchlist to begin.</p>}
      {stock.isLoading && <p className="muted">Loading {ticker}…</p>}
      {stock.isError && <p className="error">Could not load {ticker}: {(stock.error as Error).message}</p>}
      {analyze.isError && <p className="error">Analysis failed: {(analyze.error as Error).message}</p>}

      {stock.data && (
        <>
          <div className="panel">
            <h3 style={{ marginTop: 0 }}>{stock.data.company_name} ({stock.data.ticker})</h3>
            <IndicatorBar data={stock.data} />
          </div>

          <div className="panel">
            <PriceChart data={stock.data} signals={analysis?.signals ?? []} onSelectSignal={setSelected} />
            {analysis && <p className="muted" style={{ fontSize: 12 }}>Click a ▲/▼ marker to see its reasoning.</p>}
          </div>

          <div className="row">
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>Analysis</h3>
              {analysis ? (
                <ReasoningPanel result={analysis} selected={selected} />
              ) : (
                <p className="muted">Click “Analyze with LLM” to generate a reasoned recommendation and buy/sell signals.</p>
              )}
            </div>
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>News</h3>
              <NewsList news={stock.data.news} />
            </div>
          </div>
        </>
      )}
    </>
  );
}
```

- [ ] **Step 2: Verify** `npx tsc --noEmit` clean and `npm run build` succeeds.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): wire Dashboard (chart + analysis + news + indicators)"
```

---

## Task 8: Settings page

**Files:** Replace `frontend/src/pages/Settings.tsx`.

- [ ] **Step 1: Replace `frontend/src/pages/Settings.tsx`**
```tsx
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useProviders, useSaveSettings, useSettings } from '../hooks/queries';
import type { ProviderId, Settings as SettingsT, TestResult } from '../types';

export default function Settings() {
  const settingsQuery = useSettings();
  const providers = useProviders();
  const save = useSaveSettings();
  const [form, setForm] = useState<SettingsT | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settingsQuery.data) setForm(structuredClone(settingsQuery.data));
  }, [settingsQuery.data]);

  if (!form) return <p className="muted">Loading settings…</p>;

  const active = form.active_provider;
  const cfg = form.providers[active];
  const update = (next: Partial<SettingsT>) => { setForm({ ...form, ...next }); setSaved(false); };
  const updateCfg = (patch: Partial<typeof cfg>) =>
    update({ providers: { ...form.providers, [active]: { ...cfg, ...patch } } });

  const onSave = () => save.mutate(form, { onSuccess: () => setSaved(true) });
  const onTest = async () => {
    setTest(null);
    // Persist first so the backend tests the current form values.
    await save.mutateAsync(form);
    setTest(await api.testProvider(active));
  };

  return (
    <div className="panel" style={{ maxWidth: 640 }}>
      <h3 style={{ marginTop: 0 }}>Provider settings</h3>

      <div className="field">
        <label>Active provider</label>
        <select value={active} onChange={(e) => update({ active_provider: e.target.value as ProviderId })}>
          {(providers.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.label}{p.configured ? ' ✓' : ''}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Model</label>
        <input value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
      </div>

      {active === 'ollama' ? (
        <div className="field">
          <label>Base URL</label>
          <input value={cfg.base_url} onChange={(e) => updateCfg({ base_url: e.target.value })} placeholder="http://localhost:11434" />
        </div>
      ) : (
        <div className="field">
          <label>API key (leave as **** to keep the saved key)</label>
          <input type="password" value={cfg.api_key} onChange={(e) => updateCfg({ api_key: e.target.value })} placeholder="paste API key" />
        </div>
      )}

      <div className="field">
        <label>Watchlist (comma-separated)</label>
        <input
          value={form.watchlist.join(', ')}
          onChange={(e) => update({ watchlist: e.target.value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean) })}
        />
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={onSave} disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
        <button className="secondary" onClick={onTest} disabled={save.isPending}>Test connection</button>
        {saved && <span className="muted">Saved.</span>}
        {test && <span className={test.ok ? 'muted' : 'error'}>{test.ok ? '✓ ' : '✗ '}{test.message}</span>}
      </div>
      {save.isError && <p className="error">Save failed: {(save.error as Error).message}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Verify** `npx tsc --noEmit` clean and `npm run build` succeeds.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat(frontend): add Settings page (provider/model/key, test, watchlist)"
```

---

## Task 9: Frontend README + final verification (build, tests, live smoke)

**Files:** Create `frontend/README.md`.

- [ ] **Step 1: Create `frontend/README.md`**
```markdown
# Frontend — AI Stocks & News Analysis

React + Vite + TypeScript dashboard for the backend API.

## Setup

    cd frontend
    npm install

## Run (backend must be running on :8000)

    npm run dev      # http://localhost:5173

Set `VITE_API_BASE` (see `.env.example`) if the backend isn't at `http://localhost:8000/api`.

## Build / test / typecheck

    npm run build
    npx vitest run
    npx tsc --noEmit

## Pages

- **Dashboard** — pick a ticker, view the candlestick chart with SMA overlays; click **Analyze with LLM** to draw buy/sell markers and show reasoning + news.
- **Settings** — choose the LLM provider (Anthropic/OpenAI/Gemini/Ollama), set model + API key (or Ollama base URL), test the connection, and edit the watchlist.
```

- [ ] **Step 2: Full frontend verification**

From `frontend/`:
```bash
npx tsc --noEmit      # clean
npx vitest run        # all unit tests pass (client + markers + smoke)
npm run build         # succeeds
```

- [ ] **Step 3: Live end-to-end smoke (controller-run)**

Start the backend and frontend, then confirm the dashboard loads a ticker and renders the chart. (The controller will do this with the backend `uvicorn` + `npm run dev` and a browser screenshot; an implementer without a browser can stop after Step 2 and report.)

- [ ] **Step 4: Commit**
```bash
git add frontend/README.md
git commit -m "docs(frontend): add README and finalize"
```

---

## Done — frontend complete

The app is now end-to-end: backend API + React dashboard with an annotated chart, LLM reasoning, per-stock news, and a multi-provider Settings page. Run `uvicorn app.main:app --port 8000` (in `backend/`) and `npm run dev` (in `frontend/`) together to use it.
