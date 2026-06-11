import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EvaluationCommandBar } from './EvaluationCommandBar';
import type { WatchlistStreamHandlers } from '../api/client';

const handlers: { current?: WatchlistStreamHandlers } = {};
const closer = vi.fn();

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
    snapshotEvaluation: vi.fn(),
    rescan: vi.fn(),
  },
  streamWatchlistRun: vi.fn((_mode: string, h: WatchlistStreamHandlers) => {
    handlers.current = h;
    return closer;
  }),
}));

import { api, streamWatchlistRun } from '../api/client';

function renderBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EvaluationCommandBar />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  handlers.current = undefined;
  vi.mocked(api.getSettings).mockResolvedValue({ watchlist: ['AAPL', 'MSFT'] } as never);
  vi.mocked(api.snapshotEvaluation).mockResolvedValue({ recorded: 2, skipped: [] });
  vi.mocked(api.rescan).mockResolvedValue({ items: [] } as never);
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

  it('rescan chains a snapshot on success', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /full discover rescan/i }));
    await waitFor(() => expect(api.rescan).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.snapshotEvaluation).toHaveBeenCalledTimes(1));
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

  it('shows a run-level error line', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /fast llm analysis/i }));
    act(() => handlers.current!.onEvent({ type: 'error', message: 'Evaluation recording is disabled' }));
    expect(screen.getByText(/run failed: evaluation recording is disabled/i)).toBeInTheDocument();
  });
});
