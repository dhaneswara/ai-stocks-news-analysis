import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RunIndicator } from './RunIndicator';
import { WatchlistRunProvider, useWatchlistRunContext } from '../state/watchlistRunState';
import type { WatchlistStreamHandlers } from '../api/client';

const handlers: { current?: WatchlistStreamHandlers } = {};

vi.mock('../api/client', () => ({
  api: {
    rescan: vi.fn(),
    snapshotEvaluation: vi.fn(),
  },
  streamWatchlistRun: vi.fn((_mode: string, h: WatchlistStreamHandlers) => {
    handlers.current = h;
    return () => {};
  }),
}));

import { api } from '../api/client';

function StartProbe() {
  const { run, rescanAndSnapshot } = useWatchlistRunContext();
  return (
    <>
      <button onClick={() => run.start('fast')}>go</button>
      <button onClick={() => rescanAndSnapshot()}>go-rescan</button>
    </>
  );
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
  it('is hidden when no process is active', () => {
    renderIndicator();
    expect(screen.queryByText(/batch|rescanning|snapshotting/i)).not.toBeInTheDocument();
  });

  it('shows live batch progress, links to Evaluation, and hides on done', () => {
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

  it('shows the rescan chip and the app-level chain still fires the snapshot', async () => {
    let resolveRescan!: (v: unknown) => void;
    vi.mocked(api.rescan).mockReturnValue(new Promise((r) => { resolveRescan = r; }) as never);
    vi.mocked(api.snapshotEvaluation).mockResolvedValue({ recorded: 1, skipped: [] });

    renderIndicator();
    fireEvent.click(screen.getByText('go-rescan'));
    expect(await screen.findByText(/rescanning/i)).toBeInTheDocument();
    expect(screen.getByText(/rescanning/i).closest('a')).toHaveAttribute('href', '/discover');

    await act(async () => { resolveRescan({ items: [] }); });
    // The chained snapshot is registered in the provider, not a page — it must fire
    // even with no page-level component mounted.
    await waitFor(() => expect(api.snapshotEvaluation).toHaveBeenCalledTimes(1));
  });
});
