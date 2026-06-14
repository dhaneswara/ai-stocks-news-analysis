import { useCallback, type ReactNode } from 'react';
import { useSnapshotEvaluation } from '../hooks/queries';
import { useRescanRun } from '../hooks/useRescanRun';
import { useWatchlistRun } from '../hooks/useWatchlistRun';
import { RunContext } from './watchlistRunContext';

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

  const rescanAndSnapshot = useCallback((scope?: string) => {
    runReset();
    snapshotReset();
    rescanStart(scope, () => snapshotMutate());
  }, [runReset, snapshotReset, rescanStart, snapshotMutate]);

  return (
    <RunContext.Provider
      value={{ run, snapshot, rescan, startRun, rescanAndSnapshot }}
    >
      {children}
    </RunContext.Provider>
  );
}
