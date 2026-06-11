import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RunIndicator } from './RunIndicator';
import { WatchlistRunProvider, useWatchlistRunContext } from '../state/watchlistRunState';
import type { WatchlistStreamHandlers } from '../api/client';

const handlers: { current?: WatchlistStreamHandlers } = {};

vi.mock('../api/client', () => ({
  streamWatchlistRun: vi.fn((_mode: string, h: WatchlistStreamHandlers) => {
    handlers.current = h;
    return () => {};
  }),
}));

function StartProbe() {
  const run = useWatchlistRunContext();
  return <button onClick={() => run.start('fast')}>go</button>;
}

function renderIndicator() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WatchlistRunProvider>
          <RunIndicator />
          <StartProbe />
        </WatchlistRunProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  handlers.current = undefined;
});

describe('RunIndicator', () => {
  it('is hidden when no run is active', () => {
    renderIndicator();
    expect(screen.queryByText(/batch/i)).not.toBeInTheDocument();
  });

  it('shows live progress while a run streams, links to Evaluation, and hides on done', () => {
    renderIndicator();
    fireEvent.click(screen.getByText('go'));
    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
    act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'AAPL', status: 'running' }));

    const chip = screen.getByText(/fast batch 0\/2/i).closest('a');
    expect(chip).toHaveAttribute('href', '/evaluation');
    expect(chip).toHaveAttribute('title', expect.stringContaining('analyzing AAPL'));

    act(() => handlers.current!.onEvent({
      type: 'ticker', ticker: 'AAPL', status: 'done', recommendation: 'buy',
    }));
    expect(screen.getByText(/fast batch 1\/2/i)).toBeInTheDocument();

    act(() => handlers.current!.onEvent({ type: 'done', analyzed: 2, skipped: 0, failed: 0 }));
    expect(screen.queryByText(/fast batch/i)).not.toBeInTheDocument();
  });
});
