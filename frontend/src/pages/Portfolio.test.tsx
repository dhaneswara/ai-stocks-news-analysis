import { expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('../hooks/queries', () => ({
  useScreen: vi.fn(),
  usePortfolioTickers: vi.fn(),
  useWatchlist: () => ({ add: vi.fn(), remove: vi.fn(), list: [] }),
}));
vi.mock('../state/watchlistRunState', () => ({
  useWatchlistRunContext: () => ({
    rescan: { phase: 'idle', scanned: 0, total: 0, skipped: 0, summary: null, stopped: false, stop: vi.fn() },
    snapshot: { data: null },
    rescanAndSnapshot: vi.fn(),
  }),
}));
vi.mock('../components/MarketHint', () => ({ MarketHint: () => null }));

import { useScreen, usePortfolioTickers } from '../hooks/queries';
import Portfolio from './Portfolio';

function wrap(ui: ReactNode) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => vi.clearAllMocks());

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
