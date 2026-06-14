import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RunIndicator } from './RunIndicator';
import { WatchlistRunProvider } from '../state/watchlistRunState';
import { useWatchlistRunContext } from '../state/watchlistRunContext';
import type { RescanStreamHandlers, WatchlistStreamHandlers } from '../api/client';

const handlers: { current?: WatchlistStreamHandlers } = {};
const rescanHandlers: { current?: RescanStreamHandlers } = {};

vi.mock('../api/client', () => ({
  api: {
    snapshotEvaluation: vi.fn(),
  },
  streamWatchlistRun: vi.fn((_mode: string, h: WatchlistStreamHandlers) => {
    handlers.current = h;
    return () => {};
  }),
  streamRescan: vi.fn((_sector: string | undefined, h: RescanStreamHandlers) => {
    rescanHandlers.current = h;
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

function renderIndicator(initialPath = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
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
  rescanHandlers.current = undefined;
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

  it('is a plain pill (no link) when already on the target page', () => {
    renderIndicator('/evaluation');
    fireEvent.click(screen.getByText('go'));
    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));

    const chip = screen.getByText(/fast batch 0\/2/i);
    expect(chip.closest('a')).toBeNull(); // no pointer affordance for a no-op navigation
    expect(chip.closest('.run-indicator')).toHaveAttribute('title', expect.not.stringContaining('Click'));
  });

  it('shows live rescan progress and the app-level chain still fires the snapshot', async () => {
    vi.mocked(api.snapshotEvaluation).mockResolvedValue({ recorded: 1, skipped: [] });

    renderIndicator();
    fireEvent.click(screen.getByText('go-rescan'));
    expect(await screen.findByText(/rescanning/i)).toBeInTheDocument(); // before the first tick

    act(() => rescanHandlers.current!.onEvent({ type: 'tick', ticker: 'AAPL', scanned: 0, total: 3, skipped: 0 }));
    const chip = screen.getByText(/rescan 0\/3/i).closest('a');
    expect(chip).toHaveAttribute('href', '/discover');
    expect(chip).toHaveAttribute('title', expect.stringContaining('fetching AAPL'));

    act(() => rescanHandlers.current!.onEvent({ type: 'tick', ticker: 'MSFT', scanned: 2, total: 3, skipped: 0 }));
    expect(screen.getByText(/rescan 2\/3/i)).toBeInTheDocument();

    act(() => rescanHandlers.current!.onEvent({ type: 'done', scanned: 3, skipped: 0 }));
    expect(screen.queryByText(/rescan \d+\/\d+/i)).not.toBeInTheDocument(); // chip gone
    // The chained snapshot is registered in the provider, not a page — it must fire
    // even with no page-level component mounted.
    await waitFor(() => expect(api.snapshotEvaluation).toHaveBeenCalledTimes(1));
  });
});
