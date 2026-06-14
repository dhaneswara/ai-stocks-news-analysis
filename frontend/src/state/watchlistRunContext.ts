import { createContext, useContext } from 'react';
import type { useSnapshotEvaluation } from '../hooks/queries';
import type { useRescanRun } from '../hooks/useRescanRun';
import type { useWatchlistRun } from '../hooks/useWatchlistRun';

export interface ProcessesValue {
  /** The fast/deep LLM batch stream. */
  run: ReturnType<typeof useWatchlistRun>;
  /** The watchlist technical/network snapshot mutation. */
  snapshot: ReturnType<typeof useSnapshotEvaluation>;
  /** The Discover board rescan stream (live per-ticker progress). */
  rescan: ReturnType<typeof useRescanRun>;
  /** Start a fast/deep batch, clearing the other processes' leftover status first. */
  startRun: (mode: 'fast' | 'deep') => void;
  /** Rescan with the snapshot chained — the chain lives HERE so it survives
   *  page navigation (a call-site onSuccess dies with the page that registered it). */
  rescanAndSnapshot: (scope?: string) => void;
}

export const RunContext = createContext<ProcessesValue | null>(null);

export function useWatchlistRunContext(): ProcessesValue {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error('useWatchlistRunContext must be used within WatchlistRunProvider');
  return ctx;
}
