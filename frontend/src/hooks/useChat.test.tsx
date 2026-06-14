import { act, renderHook } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import * as client from '../api/client';
import { useChat } from './useChat';

it('appends a user turn and fills the assistant turn from the stream', () => {
  let handlers: client.ChatStreamHandlers | undefined;
  vi.spyOn(client, 'streamChat').mockImplementation((_m, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useChat());

  act(() => result.current.send('What about NVDA?'));
  // user turn + empty assistant turn
  expect(result.current.turns).toHaveLength(2);
  expect(result.current.turns[0]).toMatchObject({ role: 'user', content: 'What about NVDA?' });
  expect(result.current.running).toBe(true);

  act(() => handlers!.onEvent({ type: 'step', step: { index: 0, thought: 't' } } as never));
  expect(result.current.turns[1].steps).toHaveLength(1);

  act(() => handlers!.onEvent({ type: 'final', answer: '**Buy**' } as never));
  expect(result.current.running).toBe(false);
  expect(result.current.turns[1].content).toBe('**Buy**');
});

it('sends prior turns as history on a follow-up', () => {
  const calls: client.ChatStreamHandlers[] = [];
  const sent: unknown[][] = [];
  vi.spyOn(client, 'streamChat').mockImplementation((m, h) => { sent.push(m); calls.push(h); return () => {}; });
  const { result } = renderHook(() => useChat());

  act(() => result.current.send('first'));
  act(() => calls[0].onEvent({ type: 'final', answer: 'a1' } as never));
  act(() => result.current.send('second'));

  // The second call's history includes the first Q + answer + the new question.
  expect(sent[1]).toEqual([
    { role: 'user', content: 'first' },
    { role: 'assistant', content: 'a1' },
    { role: 'user', content: 'second' },
  ]);
});

it('records a per-turn error', () => {
  let handlers: client.ChatStreamHandlers | undefined;
  vi.spyOn(client, 'streamChat').mockImplementation((_m, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useChat());
  act(() => result.current.send('x'));
  act(() => handlers!.onError('Connection error'));
  expect(result.current.running).toBe(false);
  expect(result.current.turns[1].error).toBe('Connection error');
});

it('stop aborts the stream and discards the empty in-flight turn', () => {
  const close = vi.fn();
  vi.spyOn(client, 'streamChat').mockImplementation(() => close);
  const { result } = renderHook(() => useChat());

  act(() => result.current.send('hello'));
  expect(result.current.turns).toHaveLength(2); // user + empty assistant
  expect(result.current.running).toBe(true);

  act(() => result.current.stop());
  expect(close).toHaveBeenCalledTimes(1);          // stream closer invoked (abort)
  expect(result.current.running).toBe(false);
  expect(result.current.turns).toHaveLength(1);     // empty assistant turn discarded
  expect(result.current.turns[0]).toMatchObject({ role: 'user', content: 'hello' });
});
