import { expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { ScreenBoard, StockScore } from '../types';

vi.mock('../api/client', () => ({ api: { rescanTicker: vi.fn() } }));
import { api } from '../api/client';
import { useRescanTicker } from './queries';

function row(ticker: string, score: number): StockScore {
  return {
    ticker, name: ticker, sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
    price: 1, change_pct: 0, score, direction: 'hold', net: 0,
    reasons: [], components: {}, as_of: 't',
  };
}

const KEY = ['screen', '', '', '', ''];

it('replaces the matching row in the screen cache and re-sorts by score', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData<ScreenBoard>(KEY, {
    as_of: 't', scope: 'all', scanned: 2, skipped: 0, items: [row('AAA', 90), row('BBB', 80)],
  });
  vi.mocked(api.rescanTicker).mockResolvedValue(row('BBB', 99));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useRescanTicker(), { wrapper });
  await act(async () => { await result.current.mutateAsync('BBB'); });

  const board = qc.getQueryData<ScreenBoard>(KEY)!;
  expect(board.items.map((i) => i.ticker)).toEqual(['BBB', 'AAA']);   // re-sorted
  expect(board.items[0].score).toBe(99);                              // patched
});

it('passes the scope through to the API', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(api.rescanTicker).mockResolvedValue(row('BBB', 99));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useRescanTicker('portfolio'), { wrapper });
  await act(async () => { await result.current.mutateAsync('BBB'); });
  await waitFor(() => expect(api.rescanTicker).toHaveBeenCalledWith('BBB', 'portfolio'));
});
