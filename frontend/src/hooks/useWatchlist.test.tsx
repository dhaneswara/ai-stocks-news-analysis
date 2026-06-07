import { beforeEach, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { Settings } from '../types';

vi.mock('../api/client', () => ({
  api: { getSettings: vi.fn(), saveSettings: vi.fn() },
}));
import { api } from '../api/client';
import { useWatchlist } from './queries';

const SETTINGS: Settings = {
  active_provider: 'anthropic', providers: {}, watchlist: ['AAPL', 'MSFT'],
  indicator_params: { sma_windows: [50, 200], rsi_length: 14 },
  alerts: { enabled: false, channel: 'log', telegram_bot_token: '', telegram_chat_id: '', rsi_low: 30, rsi_high: 70 },
  truth_signal: { enabled: true, source_url: '', lookback_hours: 48 },
  screener: { enabled: true, top_n: 25, default_sector: null, rsi_low: 30, rsi_high: 70, weights: {} },
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4, symmetric_types: ['competitor', 'partner', 'other'] },
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
};

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.saveSettings).mockImplementation(async (s) => s);
});

it('appends a ticker that is not already listed', async () => {
  const { result } = renderHook(() => useWatchlist(), { wrapper });
  await waitFor(() => expect(result.current.list).toEqual(['AAPL', 'MSFT']));
  await act(async () => { result.current.add('TSLA'); });
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(expect.objectContaining({ watchlist: ['AAPL', 'MSFT', 'TSLA'] })),
  );
});

it('does not append a duplicate', async () => {
  const { result } = renderHook(() => useWatchlist(), { wrapper });
  await waitFor(() => expect(result.current.list).toContain('AAPL'));
  act(() => result.current.add('AAPL'));
  expect(api.saveSettings).not.toHaveBeenCalled();
});

it('removes a ticker that is present', async () => {
  const { result } = renderHook(() => useWatchlist(), { wrapper });
  await waitFor(() => expect(result.current.list).toContain('AAPL'));
  await act(async () => { result.current.remove('AAPL'); });
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(expect.objectContaining({ watchlist: ['MSFT'] })),
  );
});
