import { createContext, useCallback, useContext, type ReactNode } from 'react';
import { useSnapshotEvaluation } from '../hooks/queries';
import { useRescanRun } from '../hooks/useRescanRun';
import { useWatchlistRun } from '../hooks/useWatchlistRun';

interface ProcessesValue {
  /** The fast/deep LLM batch stream. */
  run: ReturnType<typeof useWatchlistRun>;
  /** The watchlist technical/network snapshot mutation. */
  snapshot: ReturnType<typeof useSnapshotEvaluation>;
  /** The Discover board rescan stream (live per-ticker progress). */
  rescan: ReturnType<typeof useRescanRun>;
  /** Start a fast/deep batch, clearing the other processes' leftover status first. */
  startRun: (mode: 'fast' | 'deep') => void;
  /** Snapshot now, clearing the other processes' leftover status first. */
  snapshotNow: () => void;
  /** Rescan with the watchlist snapshot chained — the chain lives HERE so it survives
   *  page navigation (a call-site onSuccess dies with the page that registered it). */
  rescanAndSnapshot: (sector?: string) => void;
}

const RunContext = createContext<ProcessesValue | null>(null);

/** Hosts every watchlist-wide evaluation process ABOVE the page router, so in-flight
 *  work survives navigating between pages: the fast/deep batch SSE stream (previously
 *  the Evaluation page owned it and unmounting stopped the run server-side), the
 *  snapshot mutation and the rescan SSE stream (their pending state, result lines and —
 *  critically — the rescan→snapshot chain used to die with the page), all shared by the Evaluation
 *  command bar, the Discover bar and the masthead RunIndicator. A browser refresh /
 *  tab close still ends an LLM batch after the in-flight ticker; skip-already-done
 *  makes the next click resume from the gap. */
export function WatchlistRunProvider({ children }: { children: ReactNode }) {
  const run = useWatchlistRun();
  const snapshot = useSnapshotEvaluation();
  const rescan = useRescanRun();
  const { start: rescanStart, reset: rescanReset } = rescan;
  const { mutate: snapshotMutate, reset: snapshotReset } = snapshot;
  const { start: runStart, reset: runReset } = run;

  // Each action clears the OTHER processes' leftover chips/result lines first, so the
  // command bar's status zone always describes a single (the latest) activity.
  const startRun = useCallback((mode: 'fast' | 'deep') => {
    snapshotReset();
    rescanReset();
    runStart(mode);
  }, [snapshotReset, rescanReset, runStart]);

  const snapshotNow = useCallback(() => {
    runReset();
    rescanReset();
    snapshotMutate();
  }, [runReset, rescanReset, snapshotMutate]);

  const rescanAndSnapshot = useCallback((sector?: string) => {
    runReset();
    snapshotReset();
    rescanStart(sector, () => snapshotMutate());
  }, [runReset, snapshotReset, rescanStart, snapshotMutate]);

  return (
    <RunContext.Provider
      value={{ run, snapshot, rescan, startRun, snapshotNow, rescanAndSnapshot }}
    >
      {children}
    </RunContext.Provider>
  );
}

export function useWatchlistRunContext(): ProcessesValue {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error('useWatchlistRunContext must be used within WatchlistRunProvider');
  return ctx;
}
