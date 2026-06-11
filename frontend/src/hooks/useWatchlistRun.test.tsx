import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import * as client from '../api/client';
import { useWatchlistRun } from './useWatchlistRun';

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, 'invalidateQueries');
  const closer = vi.fn();
  const handlers: { current?: client.WatchlistStreamHandlers } = {};
  vi.spyOn(client, 'streamWatchlistRun').mockImplementation((_m, h) => {
    handlers.current = h;
    return closer;
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useWatchlistRun(), { wrapper });
  return { hook, handlers, closer, invalidate };
}

it('tracks ticker statuses through a full run and invalidates on done', () => {
  const { hook, handlers, invalidate } = setup();
  act(() => hook.result.current.start('fast'));
  expect(hook.result.current.phase).toBe('running');
  expect(hook.result.current.mode).toBe('fast');

  act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
  expect(hook.result.current.tickers).toEqual(['AAPL', 'MSFT']);

  act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'AAPL', status: 'running' }));
  act(() => handlers.current!.onEvent({
    type: 'ticker', ticker: 'AAPL', status: 'done', recommendation: 'buy',
  }));
  act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'MSFT', status: 'skipped' }));
  expect(hook.result.current.statuses['AAPL']).toMatchObject({ status: 'done', recommendation: 'buy' });
  expect(hook.result.current.statuses['MSFT'].status).toBe('skipped');

  act(() => handlers.current!.onEvent({ type: 'done', analyzed: 1, skipped: 1, failed: 0 }));
  expect(hook.result.current.phase).toBe('done');
  expect(hook.result.current.summary).toEqual({ analyzed: 1, skipped: 1, failed: 0 });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['evaluation'] });
});

it('ignores start() while already running', () => {
  const { hook } = setup();
  act(() => hook.result.current.start('fast'));
  act(() => hook.result.current.start('deep'));
  expect(client.streamWatchlistRun).toHaveBeenCalledTimes(1);
  expect(hook.result.current.mode).toBe('fast');
});

it('surfaces a run-level error event', () => {
  const { hook, handlers } = setup();
  act(() => hook.result.current.start('deep'));
  act(() => handlers.current!.onEvent({ type: 'error', message: 'disabled' }));
  expect(hook.result.current.phase).toBe('error');
  expect(hook.result.current.message).toBe('disabled');
});

it('surfaces a transport error', () => {
  const { hook, handlers } = setup();
  act(() => hook.result.current.start('fast'));
  act(() => handlers.current!.onError('Connection error'));
  expect(hook.result.current.phase).toBe('error');
  expect(hook.result.current.message).toBe('Connection error');
});

it('stop() closes the stream, marks the run stopped and invalidates', () => {
  const { hook, closer, invalidate } = setup();
  act(() => hook.result.current.start('fast'));
  act(() => hook.result.current.stop());
  expect(closer).toHaveBeenCalled();
  expect(hook.result.current.phase).toBe('done');
  expect(hook.result.current.stopped).toBe(true);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['evaluation'] });
});

it('closes the stream on unmount', () => {
  const { hook, closer } = setup();
  act(() => hook.result.current.start('fast'));
  hook.unmount();
  expect(closer).toHaveBeenCalled();
});
