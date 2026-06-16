import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import App from '../App';
import type { AnalysisResult, ScreenBoard, Settings, SignalsSummary, StockData, StockScore } from '../types';

// lightweight-charts can't render in jsdom; the chart isn't what we're testing.
vi.mock('../components/PriceChart', () => ({ PriceChart: () => null }));

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    getStock: vi.fn(),
    analyze: vi.fn(),
    getSectors: vi.fn(),
    getScreen: vi.fn(),
    saveSettings: vi.fn(),
    listProviders: vi.fn(),
    getMood: vi.fn(),
    refreshUniverse: vi.fn(),
    getScore: vi.fn(),
    getSignals: vi.fn(),
    getLastAnalysis: vi.fn(),
  },
  streamWatchlistRun: vi.fn(() => () => {}),
  streamRescan: vi.fn(() => () => {}),
}));

import { api } from '../api/client';

const SETTINGS: Settings = {
  active_provider: 'anthropic',
  providers: {},
  watchlist: ['AAPL'],
  indicator_params: { sma_windows: [50, 200], rsi_length: 14 },
  alerts: { enabled: false, channel: 'log', telegram_bot_token: '', telegram_chat_id: '', rsi_low: 30, rsi_high: 70 },
  truth_signal: { enabled: true, source_url: '', lookback_hours: 48 },
  screener: { enabled: true, top_n: 25, default_sector: null, rsi_low: 30, rsi_high: 70, weights: {} },
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4, symmetric_types: ['competitor', 'partner', 'other'] },
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
};

const STOCK: StockData = {
  ticker: 'AAPL',
  company_name: 'Apple Inc.',
  as_of: '2026-06-06',
  price: { current: 200, change: 1, change_pct: 0.5, currency: 'USD' },
  candles: [{ time: '2026-06-05', open: 1, high: 1, low: 1, close: 1, volume: 1 }],
  fundamentals: { market_cap: null, pe_ratio: null, eps: null, dividend_yield: null, week52_high: null, week52_low: null },
  indicators: { sma50: [], sma200: [], rsi14: [], dist_from_52wk_high_pct: null },
  news: [],
};

const ANALYSIS: AnalysisResult = {
  ticker: 'AAPL',
  provider: 'anthropic',
  model: 'claude-opus',
  generated_at: '2026-06-06',
  overall_summary: 'PERSIST-ME-SUMMARY',
  news_analysis: 'news',
  sentiment: 'bullish',
  current_recommendation: 'buy',
  confidence: 0.8,
  key_factors: ['some factor'],
  signals: [],
  risks: [],
  disclaimer: 'Not financial advice',
};

const BOARD: ScreenBoard = { as_of: '2026-06-06', scope: 'all', scanned: 0, skipped: 0, items: [] };

const SCORE: StockScore = {
  ticker: 'AAPL', name: 'Apple Inc.', sector: 'Tech', price: 200, change_pct: 0.5,
  score: 72, direction: 'buy', net: 0.3, reasons: ['RSI 28 (oversold)'], components: {}, as_of: '2026-06-06',
};

const SIGNALS: SignalsSummary = {
  ticker: 'AAPL',
  sources: {
    technical: {
      latest: { call_date: '2026-06-06', recommendation: 'buy', confidence: 0.6 },
      track: { n_calls: 2, n_matured: 1, hit_rate: 100, avg_score: 80, grade: 'Strong' },
    },
  },
  agreement: { counted: 1, agreeing: 1, on: 'buy', conflict: false },
  winner: 'technical',
};

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.getStock).mockResolvedValue(STOCK);
  vi.mocked(api.analyze).mockResolvedValue(ANALYSIS);
  vi.mocked(api.getSectors).mockResolvedValue([]);
  vi.mocked(api.getScreen).mockResolvedValue(BOARD);
  vi.mocked(api.getScore).mockResolvedValue(SCORE);
  vi.mocked(api.getSignals).mockResolvedValue(SIGNALS);
  vi.mocked(api.getLastAnalysis).mockResolvedValue(null);
});

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Dashboard analysis persistence', () => {
  it('keeps the LLM analysis after navigating to Discover and back', async () => {
    renderApp();

    // Wait for the default watchlist ticker to load and enable the Analyze button.
    const analyzeBtn = await screen.findByRole('button', { name: /analyze with llm/i });
    await waitFor(() => expect(analyzeBtn).toBeEnabled());

    fireEvent.click(analyzeBtn);
    expect(await screen.findByText('PERSIST-ME-SUMMARY')).toBeInTheDocument();

    // Toggle to Discover, then back to the Dashboard via the nav links.
    fireEvent.click(screen.getByRole('link', { name: 'Discover' }));
    await screen.findByText(/opportunity board/i);

    fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }));

    // The analysis must survive the round-trip.
    expect(await screen.findByText('PERSIST-ME-SUMMARY')).toBeInTheDocument();
  });
});

describe('Dashboard chart range', () => {
  it('defaults the chart range to 1Y', async () => {
    renderApp();
    const oneY = await screen.findByRole('button', { name: '1Y' });
    expect(oneY).toHaveClass('active');
    expect(screen.getByRole('button', { name: '2Y' })).not.toHaveClass('active');
  });
});

describe('Dashboard watchlist editing', () => {
  it('shows an error line when saving the watchlist fails', async () => {
    vi.mocked(api.saveSettings).mockRejectedValue(new Error('save boom'));
    renderApp();
    // AAPL is the default watchlist ticker, so its star is the "remove" toggle.
    const star = await screen.findByRole('button', { name: /remove from watchlist/i });
    fireEvent.click(star);
    expect(await screen.findByText(/couldn't update watchlist/i)).toBeInTheDocument();
  });
});

describe('Dashboard no-LLM score', () => {
  it('shows the opportunity score chip on ticker load', async () => {
    renderApp();
    const reason = await screen.findByText(/RSI 28 \(oversold\)/);
    const strip = reason.closest('.signals-strip');
    expect(strip).not.toBeNull();
    expect(within(strip as HTMLElement).getByText('72')).toBeInTheDocument();
    // SIGNALS fixture has a technical source — its chip label should appear in the strip.
    expect(within(strip as HTMLElement).getByText(/TECH/)).toBeInTheDocument();
  });
});

describe('Dashboard staleness badge', () => {
  beforeEach(() => {
    // Tue 2026-06-16 → latest completed trading day is Mon 2026-06-15.
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-06-16T18:00:00Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('flags a ticker whose latest price bar is behind the last trading day', async () => {
    vi.mocked(api.getStock).mockResolvedValue({
      ...STOCK,
      candles: [{ time: '2026-06-12', open: 1, high: 1, low: 1, close: 1, volume: 1 }],
    });
    renderApp();
    expect(await screen.findByText(/data lagging/i)).toBeInTheDocument();
  });

  it('shows no badge when the latest bar is current', async () => {
    vi.mocked(api.getStock).mockResolvedValue({
      ...STOCK,
      candles: [{ time: '2026-06-15', open: 1, high: 1, low: 1, close: 1, volume: 1 }],
    });
    renderApp();
    // The summary header (and its as_of line) renders…
    await screen.findByText(/Apple Inc\./);
    // …but no staleness pill.
    expect(screen.queryByText(/data lagging/i)).not.toBeInTheDocument();
  });
});

describe('Dashboard analysis restore', () => {
  it('restores the last saved analysis on load without clicking Analyze', async () => {
    vi.mocked(api.getLastAnalysis).mockResolvedValue({
      result: ANALYSIS, source: 'llm_fast', call_date: '2026-06-05', created_at: 1,
    });
    renderApp();
    // The persisted summary shows with no Analyze click.
    expect(await screen.findByText('PERSIST-ME-SUMMARY')).toBeInTheDocument();
    expect(screen.getByText(/as of 2026-06-05/i)).toBeInTheDocument();
  });
});
