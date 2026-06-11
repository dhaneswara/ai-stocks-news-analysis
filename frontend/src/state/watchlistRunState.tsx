import { createContext, useContext, type ReactNode } from 'react';
import { useWatchlistRun } from '../hooks/useWatchlistRun';

type RunContextValue = ReturnType<typeof useWatchlistRun>;

const RunContext = createContext<RunContextValue | null>(null);

/** Hosts the watchlist batch-run stream ABOVE the page router, so an in-flight fast/deep
 *  run keeps streaming while the user navigates between pages — previously the stream
 *  belonged to the Evaluation page and unmounting it stopped the run server-side. The
 *  Evaluation command bar and the masthead RunIndicator read the same live state. A
 *  browser refresh / tab close still ends the run after the in-flight ticker;
 *  skip-already-done makes the next click resume from the gap. */
export function WatchlistRunProvider({ children }: { children: ReactNode }) {
  const run = useWatchlistRun();
  return <RunContext.Provider value={run}>{children}</RunContext.Provider>;
}

export function useWatchlistRunContext(): RunContextValue {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error('useWatchlistRunContext must be used within WatchlistRunProvider');
  return ctx;
}
