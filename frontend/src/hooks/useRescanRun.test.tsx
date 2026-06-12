import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import * as client from '../api/client';
import { useRescanRun } from './useRescanRun';

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, 'invalidateQueries');
  const closer = vi.fn();
  const handlers: { current?: client.RescanStreamHandlers } = {};
  const stream = vi.spyOn(client, 'streamRescan').mockImplementation((_s, h) => {
    handlers.current = h;
    return closer;
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useRescanRun(), { wrapper });
  return { hook, handlers, closer, invalidate, stream };
}

it('tracks tick progress, then summarizes, refreshes the board and fires onDone', () => {
  const { hook, handlers, invalidate } = setup();
  const onDone = vi.fn();
  act(() => hook.result.current.start(undefined, onDone));
  expect(hook.result.current.phase).toBe('running');

  act(() => handlers.current!.onEvent({ type: 'tick', ticker: 'AAPL', scanned: 0, total: 3, skipped: 0 }));
  expect(hook.result.current).toMatchObject({ ticker: 'AAPL', scanned: 0, total: 3 });

  act(() => handlers.current!.onEvent({ type: 'tick', ticker: 'MSFT', scanned: 2, total: 3, skipped: 1 }));
  expect(hook.result.current).toMatchObject({ ticker: 'MSFT', scanned: 2, skipped: 1 });
  expect(onDone).not.toHaveBeenCalled();

  act(() => handlers.current!.onEvent({ type: 'done', scanned: 3, skipped: 1 }));
  expect(hook.result.current.phase).toBe('done');
  expect(hook.result.current.summary).toEqual({ scanned: 3, skipped: 1 });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['screen'] });
  expect(onDone).toHaveBeenCalledTimes(1);
});

it('passes the sector through to the stream and ignores start() while running', () => {
  const { hook, stream } = setup();
  act(() => hook.result.current.start('Energy'));
  act(() => hook.result.current.start());
  expect(stream).toHaveBeenCalledTimes(1);
  expect(stream).toHaveBeenCalledWith('Energy', expect.anything());
});

it('surfaces a scan error without refreshing the board (nothing was saved)', () => {
  const { hook, handlers, invalidate } = setup();
  act(() => hook.result.current.start());
  act(() => handlers.current!.onEvent({ type: 'error', message: 'universe file corrupt' }));
  expect(hook.result.current.phase).toBe('error');
  expect(hook.result.current.message).toBe('universe file corrupt');
  expect(invalidate).not.toHaveBeenCalled();
});

it('surfaces a transport error', () => {
  const { hook, handlers } = setup();
  act(() => hook.result.current.start());
  act(() => handlers.current!.onError('Connection error'));
  expect(hook.result.current.phase).toBe('error');
  expect(hook.result.current.message).toBe('Connection error');
});

it('stop() closes the stream, marks the scan stopped and skips onDone', () => {
  const { hook, closer } = setup();
  const onDone = vi.fn();
  act(() => hook.result.current.start(undefined, onDone));
  act(() => hook.result.current.stop());
  expect(closer).toHaveBeenCalled();
  expect(hook.result.current.phase).toBe('done');
  expect(hook.result.current.stopped).toBe(true);
  expect(onDone).not.toHaveBeenCalled();
});

it('reset() is a no-op while running, clears state once finished', () => {
  const { hook, handlers } = setup();
  act(() => hook.result.current.start());
  act(() => handlers.current!.onEvent({ type: 'tick', ticker: 'AAPL', scanned: 0, total: 3, skipped: 0 }));
  act(() => hook.result.current.reset());
  expect(hook.result.current.phase).toBe('running'); // still going

  act(() => handlers.current!.onEvent({ type: 'done', scanned: 3, skipped: 0 }));
  act(() => hook.result.current.reset());
  expect(hook.result.current.phase).toBe('idle');
  expect(hook.result.current.summary).toBeNull();
});

it('closes the stream on unmount', () => {
  const { hook, closer } = setup();
  act(() => hook.result.current.start());
  hook.unmount();
  expect(closer).toHaveBeenCalled();
});

it('allows a second scan after done and resets per-scan state', () => {
  const { hook, handlers, stream } = setup();
  act(() => hook.result.current.start());
  act(() => handlers.current!.onEvent({ type: 'done', scanned: 1, skipped: 0 }));
  expect(hook.result.current.phase).toBe('done');

  act(() => hook.result.current.start());
  expect(stream).toHaveBeenCalledTimes(2);
  expect(hook.result.current.phase).toBe('running');
  expect(hook.result.current.summary).toBeNull();
});
