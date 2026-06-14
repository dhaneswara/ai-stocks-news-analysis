import { useCallback, useEffect, useRef, useState } from 'react';
import { streamChat } from '../api/client';
import type { AgentStep, ChatEvent, ChatMessage, ChatTurn } from '../types';

/** Conversation state + per-turn streaming. History lives here (frontend-owned, ephemeral):
 *  each send POSTs the prior turns + the new question and fills the assistant turn as events
 *  arrive. A turnsRef mirrors state so building history and updating the in-flight turn never
 *  rely on a stale closure. */
export function useChat() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [running, setRunning] = useState(false);
  const turnsRef = useRef<ChatTurn[]>([]);
  const closeRef = useRef<(() => void) | null>(null);

  const commit = useCallback((next: ChatTurn[]) => {
    turnsRef.current = next;
    setTurns(next);
  }, []);

  const patchAssistant = useCallback((fn: (a: ChatTurn) => ChatTurn) => {
    const cur = turnsRef.current;
    const i = cur.length - 1;
    if (i < 0 || cur[i].role !== 'assistant') return;
    const copy = cur.slice();
    copy[i] = fn(copy[i]);
    commit(copy);
  }, [commit]);

  const send = useCallback((text: string) => {
    const q = text.trim();
    if (!q || running) return;
    closeRef.current?.();

    const history: ChatMessage[] = turnsRef.current
      .filter((t) => t.role === 'user' || t.content)
      .map((t) => ({ role: t.role, content: t.content }));
    const messages: ChatMessage[] = [...history, { role: 'user', content: q }];
    commit([
      ...turnsRef.current,
      { role: 'user', content: q },
      { role: 'assistant', content: '', steps: [] },
    ]);
    setRunning(true);

    let steps: AgentStep[] = [];
    closeRef.current = streamChat(messages, {
      onEvent: (e: ChatEvent) => {
        if (e.type === 'step' && e.step) {
          steps = [...steps, e.step];
          patchAssistant((a) => ({ ...a, steps }));
        } else if (e.type === 'final') {
          setRunning(false);
          patchAssistant((a) => ({ ...a, content: e.answer ?? '', steps }));
        } else if (e.type === 'error') {
          setRunning(false);
          patchAssistant((a) => ({ ...a, error: e.message || 'Error' }));
        }
      },
      onError: (message) => {
        setRunning(false);
        patchAssistant((a) => ({ ...a, error: message }));
      },
    });
  }, [running, commit, patchAssistant]);

  const stop = useCallback(() => {
    closeRef.current?.();
    setRunning(false);
    // Discard the in-flight assistant turn if it never produced an answer.
    const cur = turnsRef.current;
    const i = cur.length - 1;
    if (i >= 0 && cur[i].role === 'assistant' && !cur[i].content) {
      commit(cur.slice(0, i));
    }
  }, [commit]);

  useEffect(() => () => closeRef.current?.(), []);

  return { turns, running, send, stop };
}
