import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { streamWatchlistRun } from '../api/client';
import type { Recommendation, TickerRunStatus } from '../types';

export type RunMode = 'fast' | 'deep';
export type RunPhase = 'idle' | 'running' | 'done' | 'error';

export interface TickerRunState {
  status: TickerRunStatus;
  recommendation?: Recommendation | '';
  fellBack?: boolean;
  error?: string;
}

export interface WatchlistRunState {
  phase: RunPhase;
  mode: RunMode | null;
  total: number;
  tickers: string[];
  statuses: Record<string, TickerRunState>;
  summary: { analyzed: number; skipped: number; failed: number } | null;
  stopped: boolean;
  message: string | null;
}

const IDLE: WatchlistRunState = {
  phase: 'idle', mode: null, total: 0, tickers: [], statuses: {}, summary: null,
  stopped: false, message: null,
};

/** Drive a watchlist-wide LLM batch run (mode=fast|deep) over SSE. One run at a time;
 *  every terminal transition (done / error / stop) refreshes the evaluation board. */
export function useWatchlistRun() {
  const qc = useQueryClient();
  const [state, setState] = useState<WatchlistRunState>(IDLE);
  const closeRef = useRef<(() => void) | null>(null);
  const runningRef = useRef(false);

  const finish = useCallback(
    () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
    [qc],
  );

  const start = useCallback((mode: RunMode) => {
    if (runningRef.current) return;
    runningRef.current = true;
    closeRef.current?.(); // a prior errored run may have left its stream open
    setState({ ...IDLE, phase: 'running', mode });
    closeRef.current = streamWatchlistRun(mode, {
      onEvent: (e) => {
        if (e.type === 'start') {
          setState((s) => ({ ...s, total: e.total ?? 0, tickers: e.tickers ?? [] }));
        } else if (e.type === 'ticker' && e.ticker) {
          setState((s) => ({
            ...s,
            statuses: {
              ...s.statuses,
              [e.ticker as string]: {
                status: e.status ?? 'running',
                recommendation: e.recommendation,
                fellBack: e.fell_back,
                error: e.error,
              },
            },
          }));
        } else if (e.type === 'done') {
          runningRef.current = false;
          setState((s) => ({
            ...s,
            phase: 'done',
            summary: {
              analyzed: e.analyzed ?? 0, skipped: e.skipped ?? 0, failed: e.failed ?? 0,
            },
          }));
          finish();
        } else if (e.type === 'error') {
          runningRef.current = false;
          setState((s) => ({ ...s, phase: 'error', message: e.message || 'Run error' }));
          finish();
        }
      },
      onError: (message) => {
        runningRef.current = false;
        setState((s) => ({ ...s, phase: 'error', message }));
        finish();
      },
    });
  }, [finish]);

  const stop = useCallback(() => {
    if (!runningRef.current) return;
    runningRef.current = false;
    closeRef.current?.();
    setState((s) => ({ ...s, phase: 'done', stopped: true }));
    finish();
  }, [finish]);

  /** Clear a finished/stopped run's chips and messages (no-op while running) — used when
   *  another process starts so the command bar shows one activity at a time. */
  const reset = useCallback(() => {
    if (runningRef.current) return;
    closeRef.current?.();
    setState(IDLE);
  }, []);

  useEffect(() => () => closeRef.current?.(), []); // close the stream on unmount

  return { ...state, start, stop, reset };
}
