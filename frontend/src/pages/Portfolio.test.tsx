import { expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('../hooks/queries', () => ({
  useScreen: vi.fn(),
  usePortfolioTickers: vi.fn(),
  useWatchlist: vi.fn(),
}));
vi.mock('../state/watchlistRunState', () => ({
  useWatchlistRunContext: () => ({
    rescan: { phase: 'idle', scanned: 0, total: 0, skipped: 0, summary: null, stopped: false, stop: vi.fn() },
    snapshot: { data: null },
    rescanAndSnapshot: vi.fn(),
  }),
}));
vi.mock('../components/MarketHint', () => ({ MarketHint: () => null }));

import { useScreen, usePortfolioTickers, useWatchlist } from '../hooks/queries';
import Portfolio from './Portfolio';

function wrap(ui: ReactNode) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: [] } as never);
});

it('prompts to build a portfolio when empty', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [], as_of: '' } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: [] } } as never);
  wrap(<Portfolio />);
  expect(screen.getByText(/add to your watchlist or activate an ontology/i)).toBeInTheDocument();
});

it('renders the board when the portfolio has scored rows', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
      price: 1, change_pct: 0, score: 80, direction: 'buy', net: 0.5, reasons: [], components: {}, as_of: 't' },
  ], as_of: '2026-06-13T00:00:00Z', scanned: 1 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['AAPL'] } } as never);
  wrap(<Portfolio />);
  expect(screen.getByText('AAPL')).toBeInTheDocument();
});

it('splits scored rows into Watchlist and Extended boards', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
      price: 1, change_pct: 0, score: 80, direction: 'buy', net: 0, reasons: [], components: {}, as_of: 't' },
    { ticker: 'TSM', name: 'TSMC', sector: 'Tech', exchange: 'NYSE', in_sp500: true,
      price: 1, change_pct: 0, score: 70, direction: 'hold', net: 0, reasons: [], components: {}, as_of: 't' },
  ], as_of: 't', scanned: 2 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['AAPL', 'TSM'] } } as never);
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: ['AAPL'] } as never);
  wrap(<Portfolio />);
  expect(screen.getByText(/Watchlist \(1\)/i)).toBeInTheDocument();
  expect(screen.getByText(/Extended via ontology \(1\)/i)).toBeInTheDocument();
  expect(screen.getByText('AAPL')).toBeInTheDocument();
  expect(screen.getByText('TSM')).toBeInTheDocument();
});

it('hides the Extended board when every scored ticker is in the watchlist', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
      price: 1, change_pct: 0, score: 80, direction: 'buy', net: 0, reasons: [], components: {}, as_of: 't' },
  ], as_of: 't', scanned: 1 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['AAPL'] } } as never);
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: ['AAPL'] } as never);
  wrap(<Portfolio />);
  expect(screen.getByText(/Watchlist \(1\)/i)).toBeInTheDocument();
  expect(screen.queryByText(/Extended via ontology/i)).not.toBeInTheDocument();
});

it('hides the Watchlist board when no scored ticker is in the watchlist', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'TSM', name: 'TSMC', sector: 'Tech', exchange: 'NYSE', in_sp500: true,
      price: 1, change_pct: 0, score: 70, direction: 'hold', net: 0, reasons: [], components: {}, as_of: 't' },
  ], as_of: 't', scanned: 1 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['TSM'] } } as never);
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: [] } as never);
  wrap(<Portfolio />);
  expect(screen.queryByText(/Watchlist \(/i)).not.toBeInTheDocument();
  expect(screen.getByText(/Extended via ontology \(1\)/i)).toBeInTheDocument();
});
