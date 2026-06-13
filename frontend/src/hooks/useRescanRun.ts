import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { streamRescan } from '../api/client';

export type RescanPhase = 'idle' | 'running' | 'done' | 'error';

export interface RescanRunState {
  phase: RescanPhase;
  /** In-flight ticker from the latest tick — names the culprit when a fetch stalls. */
  ticker: string;
  scanned: number;
  total: number;
  skipped: number;
  summary: { scanned: number; skipped: number } | null;
  stopped: boolean;
  message: string | null;
}

const IDLE: RescanRunState = {
  phase: 'idle', ticker: '', scanned: 0, total: 0, skipped: 0,
  summary: null, stopped: false, message: null,
};

/** Drive a Discover board rescan over SSE (one `tick` per ticker, terminal `done`). One scan
 *  at a time; the board query refreshes only on `done` — a stopped or failed scan saved
 *  nothing server-side. `onDone` (registered at start) carries the rescan→snapshot chain. */
export function useRescanRun() {
  const qc = useQueryClient();
  const [state, setState] = useState<RescanRunState>(IDLE);
  const closeRef = useRef<(() => void) | null>(null);
  const runningRef = useRef(false);
  const onDoneRef = useRef<(() => void) | undefined>(undefined);

  const start = useCallback((scope?: string, onDone?: () => void) => {
    if (runningRef.current) return;
    runningRef.current = true;
    onDoneRef.current = onDone;
    closeRef.current?.(); // a prior errored run may have left its stream open
    setState({ ...IDLE, phase: 'running' });
    closeRef.current = streamRescan(scope, {
      onEvent: (e) => {
        if (e.type === 'tick') {
          setState((s) => ({
            ...s, ticker: e.ticker ?? '', scanned: e.scanned ?? 0,
            total: e.total ?? 0, skipped: e.skipped ?? 0,
          }));
        } else if (e.type === 'done') {
          runningRef.current = false;
          const summary = { scanned: e.scanned ?? 0, skipped: e.skipped ?? 0 };
          setState((s) => ({ ...s, phase: 'done', ticker: '', summary, ...summary }));
          qc.invalidateQueries({ queryKey: ['screen'] });
          onDoneRef.current?.();
        } else if (e.type === 'error') {
          runningRef.current = false;
          setState((s) => ({ ...s, phase: 'error', message: e.message || 'Rescan error' }));
        }
      },
      onError: (message) => {
        runningRef.current = false;
        setState((s) => ({ ...s, phase: 'error', message }));
      },
    });
  }, [qc]);

  const stop = useCallback(() => {
    if (!runningRef.current) return;
    runningRef.current = false;
    closeRef.current?.(); // closing aborts the scan server-side at its next tick
    setState((s) => ({ ...s, phase: 'done', stopped: true }));
  }, []);

  /** Clear a finished/stopped scan's status lines (no-op while running) — used when another
   *  process starts so the command bar shows one activity at a time. */
  const reset = useCallback(() => {
    if (runningRef.current) return;
    closeRef.current?.();
    setState(IDLE);
  }, []);

  useEffect(() => () => closeRef.current?.(), []); // close the stream on unmount

  return { ...state, start, stop, reset };
}
