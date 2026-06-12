import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EvaluationCommandBar } from './EvaluationCommandBar';
import { WatchlistRunProvider } from '../state/watchlistRunState';
import type { RescanStreamHandlers, WatchlistStreamHandlers } from '../api/client';

const handlers: { current?: WatchlistStreamHandlers } = {};
const rescanHandlers: { current?: RescanStreamHandlers } = {};
const closer = vi.fn();
const rescanCloser = vi.fn();

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
    snapshotEvaluation: vi.fn(),
  },
  streamWatchlistRun: vi.fn((_mode: string, h: WatchlistStreamHandlers) => {
    handlers.current = h;
    return closer;
  }),
  streamRescan: vi.fn((_sector: string | undefined, h: RescanStreamHandlers) => {
    rescanHandlers.current = h;
    return rescanCloser;
  }),
}));

import { api, streamRescan, streamWatchlistRun } from '../api/client';

function renderBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WatchlistRunProvider>
        <EvaluationCommandBar />
      </WatchlistRunProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  handlers.current = undefined;
  rescanHandlers.current = undefined;
  vi.mocked(api.getSettings).mockResolvedValue({ watchlist: ['AAPL', 'MSFT'] } as never);
  vi.mocked(api.snapshotEvaluation).mockResolvedValue({ recorded: 2, skipped: [] });
});

describe('EvaluationCommandBar', () => {
  it('renders the four process buttons once the watchlist loads', async () => {
    renderBar();
    expect(await screen.findByText(/run on your watchlist \(2 tickers\)/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /fast llm analysis/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /deep llm analysis/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /full discover rescan/i })).toBeEnabled();
    // Pipeline order: the rescan (which chains the snapshot) leads, as the freshest first step.
    const names = screen.getAllByRole('button').map((b) => b.textContent);
    expect(names.slice(0, 4)).toEqual([
      'Full Discover rescan', 'Snapshot technical/network', 'Fast LLM analysis', 'Deep LLM analysis (slow)',
    ]);
    // The when-to-run hint renders with live clock data (either market state is valid here).
    expect(screen.getByText(/US market is (open|closed)/)).toBeInTheDocument();
  });

  it('disables everything and hints when the watchlist is empty', async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ watchlist: [] } as never);
    renderBar();
    expect(await screen.findByText(/add tickers to your watchlist first/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /fast llm analysis/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeDisabled();
  });

  it('snapshot button records and reports', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /snapshot technical\/network/i }));
    expect(await screen.findByText(/recorded 2 watchlist signals/i)).toBeInTheDocument();
    expect(api.snapshotEvaluation).toHaveBeenCalledTimes(1);
  });

  it('rescan shows live tick progress, then chains a snapshot on done', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /full discover rescan/i }));
    expect(vi.mocked(streamRescan)).toHaveBeenCalledWith(undefined, expect.anything());

    act(() => rescanHandlers.current!.onEvent({ type: 'tick', ticker: 'AAPL', scanned: 0, total: 3, skipped: 0 }));
    expect(screen.getByRole('button', { name: /scanning… 0\/3/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /fast llm analysis/i })).toBeDisabled();

    act(() => rescanHandlers.current!.onEvent({ type: 'tick', ticker: 'MSFT', scanned: 2, total: 3, skipped: 1 }));
    expect(screen.getByText(/2\/3 scanned \(1 skipped\) · fetching MSFT/)).toBeInTheDocument();
    expect(api.snapshotEvaluation).not.toHaveBeenCalled();

    act(() => rescanHandlers.current!.onEvent({ type: 'done', scanned: 3, skipped: 1 }));
    expect(screen.getByText(/✓ board rescanned — 3 scanned, 1 skipped/i)).toBeInTheDocument();
    await waitFor(() => expect(api.snapshotEvaluation).toHaveBeenCalledTimes(1));
  });

  it('rescan can be stopped — stream closed, nothing-saved note, no snapshot', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /full discover rescan/i }));
    act(() => rescanHandlers.current!.onEvent({ type: 'tick', ticker: 'AAPL', scanned: 0, total: 3, skipped: 0 }));
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(rescanCloser).toHaveBeenCalled();
    expect(screen.getByText(/rescan stopped — nothing saved/i)).toBeInTheDocument();
    expect(api.snapshotEvaluation).not.toHaveBeenCalled();
  });

  it('shows a rescan error line', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /full discover rescan/i }));
    act(() => rescanHandlers.current!.onEvent({ type: 'error', message: 'universe file corrupt' }));
    expect(screen.getByText(/rescan failed: universe file corrupt/i)).toBeInTheDocument();
  });

  it('runs a fast batch with live chips, disabling the other buttons', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /fast llm analysis/i }));
    expect(vi.mocked(streamWatchlistRun)).toHaveBeenCalledWith('fast', expect.anything());

    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
    act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'AAPL', status: 'running' }));
    expect(screen.getByText(/⏳ AAPL/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument();

    act(() => handlers.current!.onEvent({
      type: 'ticker', ticker: 'AAPL', status: 'done', recommendation: 'buy',
    }));
    act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'MSFT', status: 'skipped' }));
    expect(screen.getByText(/✓ AAPL BUY/)).toBeInTheDocument();
    expect(screen.getByText(/− MSFT/)).toBeInTheDocument();

    act(() => handlers.current!.onEvent({ type: 'done', analyzed: 1, skipped: 1, failed: 0 }));
    expect(screen.getByText(/analyzed 1 · skipped 1 · failed 0/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeEnabled();
  });

  it('renders failed and fell-back chips', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /deep llm analysis/i }));
    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
    act(() => handlers.current!.onEvent({
      type: 'ticker', ticker: 'AAPL', status: 'failed', error: 'boom',
    }));
    act(() => handlers.current!.onEvent({
      type: 'ticker', ticker: 'MSFT', status: 'done', recommendation: 'hold', fell_back: true,
    }));
    expect(screen.getByText(/✗ AAPL/)).toBeInTheDocument();
    expect(screen.getByText(/✗ AAPL/)).toHaveAttribute('title', 'boom');
    expect(screen.getByText(/✓ MSFT HOLD \(fell back\)/)).toBeInTheDocument();
  });

  it('stop closes the stream and notes the run was stopped', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /deep llm analysis/i }));
    expect(vi.mocked(streamWatchlistRun)).toHaveBeenCalledWith('deep', expect.anything());
    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(closer).toHaveBeenCalled();
    expect(screen.getByText(/stopped — run again to resume/i)).toBeInTheDocument();
  });

  it('starting a new process clears the previous status — one story at a time', async () => {
    renderBar();
    // Start a deep batch, then stop it mid-run — chips + stopped note shown.
    fireEvent.click(await screen.findByRole('button', { name: /deep llm analysis/i }));
    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(screen.getByText(/stopped — run again/i)).toBeInTheDocument();
    expect(screen.getByText(/· AAPL/)).toBeInTheDocument();

    // Snapshot next: the stopped run's residue vanishes; only the snapshot result shows.
    fireEvent.click(screen.getByRole('button', { name: /snapshot technical\/network/i }));
    expect(await screen.findByText(/recorded 2 watchlist signals/i)).toBeInTheDocument();
    expect(screen.queryByText(/stopped — run again/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/· AAPL/)).not.toBeInTheDocument();
  });

  it('shows a run-level error line', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /fast llm analysis/i }));
    act(() => handlers.current!.onEvent({ type: 'error', message: 'Evaluation recording is disabled' }));
    expect(screen.getByText(/run failed: evaluation recording is disabled/i)).toBeInTheDocument();
  });
});
