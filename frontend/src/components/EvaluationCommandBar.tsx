import { useRescan, useSettings, useSnapshotEvaluation, useWatchlist } from '../hooks/queries';
import { useWatchlistRun } from '../hooks/useWatchlistRun';
import type { TickerRunStatus } from '../types';

const CHIP_ICON: Record<TickerRunStatus, string> = {
  running: '⏳', done: '✓', skipped: '−', failed: '✗',
};

/** One button per watchlist-wide process: snapshot technical/network calls, fast/deep LLM
 *  batches (live per-ticker progress + Stop), and a full Discover rescan. One process at
 *  a time. */
export function EvaluationCommandBar() {
  const settings = useSettings();
  const watch = useWatchlist();
  const snapshot = useSnapshotEvaluation();
  const rescan = useRescan();
  const run = useWatchlistRun();

  const running = run.phase === 'running';
  const busy = snapshot.isPending || rescan.isPending || running;
  const disabled = busy || watch.list.length === 0;
  const progressed = Object.values(run.statuses).filter((t) => t.status !== 'running').length;

  // Don't render the action buttons until settings have loaded — this lets tests
  // use findByRole to wait for the watchlist to be available before clicking.
  if (settings.isPending) {
    return (
      <div className="panel commandbar">
        <div className="board-controls">
          <span className="section-label muted">Loading…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="panel commandbar">
      <div className="board-controls">
        <span className="section-label">Run on your watchlist ({watch.list.length} tickers)</span>
        <span className="spacer" />
        <button className="secondary" disabled={disabled} onClick={() => snapshot.mutate()}>
          {snapshot.isPending ? 'Snapshotting…' : 'Snapshot technical/network'}
        </button>
        <button className="secondary" disabled={disabled} onClick={() => run.start('fast')}>
          {running && run.mode === 'fast' ? 'Analyzing…' : 'Fast LLM analysis'}
        </button>
        <button className="secondary" disabled={disabled} onClick={() => run.start('deep')}>
          {running && run.mode === 'deep' ? 'Deep analyzing…' : 'Deep LLM analysis (slow)'}
        </button>
        <button
          className="secondary" disabled={disabled}
          onClick={() => rescan.mutate(undefined, { onSuccess: () => snapshot.mutate() })}
        >
          {rescan.isPending ? 'Scanning…' : 'Full Discover rescan'}
        </button>
        {running && <button onClick={run.stop}>Stop</button>}
      </div>

      {watch.list.length === 0 && (
        <p className="muted">Add tickers to your watchlist first (★ on the Dashboard).</p>
      )}

      {run.tickers.length > 0 && (running || run.summary || run.stopped) && (
        <div className="run-strip">
          {running && <span className="muted mono">{progressed}/{run.total}</span>}
          {run.tickers.map((t) => {
            const st = run.statuses[t];
            return (
              <span key={t} className={`run-chip ${st?.status ?? 'pending'}`} title={st?.error ?? ''}>
                {st ? CHIP_ICON[st.status] : '·'} {t}
                {st?.status === 'done' && st.recommendation
                  ? ` ${st.recommendation.toUpperCase()}` : ''}
              </span>
            );
          })}
        </div>
      )}

      {run.summary && (
        <p className="muted">
          Analyzed {run.summary.analyzed} · skipped {run.summary.skipped} · failed {run.summary.failed}.
        </p>
      )}
      {run.stopped && <p className="muted">Stopped — run again to resume the rest.</p>}
      {run.phase === 'error' && run.message && <p className="error">Run failed: {run.message}</p>}
      {snapshot.data && (
        <p className="muted">
          ✓ Recorded {snapshot.data.recorded} watchlist signal{snapshot.data.recorded === 1 ? '' : 's'} for
          evaluation{snapshot.data.skipped.length ? ` (${snapshot.data.skipped.length} skipped)` : ''}.
        </p>
      )}
      {snapshot.isError && <p className="error">Snapshot failed: {(snapshot.error as Error).message}</p>}
      {rescan.isError && <p className="error">Rescan failed: {(rescan.error as Error).message}</p>}
    </div>
  );
}
