import { act, renderHook } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import * as client from '../api/client';
import { useDeepAnalyze } from './useDeepAnalyze';

it('accumulates steps and captures the final result', () => {
  let handlers: client.DeepStreamHandlers | undefined;
  vi.spyOn(client, 'streamDeepAnalysis').mockImplementation((_t, _p, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useDeepAnalyze('AAPL', '1y'));

  act(() => result.current.start());
  expect(result.current.running).toBe(true);

  act(() => handlers!.onEvent({ type: 'step', step: { index: 0, thought: 't' } } as never));
  expect(result.current.steps).toHaveLength(1);

  act(() => handlers!.onEvent({ type: 'final', result: { current_recommendation: 'buy' }, trace: { fell_back: false } } as never));
  expect(result.current.running).toBe(false);
  expect(result.current.result?.current_recommendation).toBe('buy');
});

it('surfaces a transport error', () => {
  let handlers: client.DeepStreamHandlers | undefined;
  vi.spyOn(client, 'streamDeepAnalysis').mockImplementation((_t, _p, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useDeepAnalyze('AAPL', '1y'));
  act(() => result.current.start());
  act(() => handlers!.onError('Connection error'));
  expect(result.current.running).toBe(false);
  expect(result.current.error).toBe('Connection error');
});
