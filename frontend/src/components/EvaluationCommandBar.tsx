import { useRescan, useSettings, useSnapshotEvaluation, useWatchlist } from '../hooks/queries';
import { useWatchlistRun } from '../hooks/useWatchlistRun';
import type { TickerRunStatus } from '../types';

const CHIP_ICON: Record<TickerRunStatus, string> = {
  running: '⏳', done: '✓', skipped: '−', failed: '✗',
};

/** One button per watchlist-wide process, ordered as a left-to-right pipeline: full
 *  Discover rescan (refreshes the board the network call blends against, then chains the
 *  snapshot itself), snapshot technical/network calls (the cheap alternative when the
 *  board is fresh), and the fast/deep LLM batches (live per-ticker progress + Stop). One
 *  process at a time. */
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

  // Until settings load, the bar would render a misleading frame — "(0 tickers)", the
  // add-tickers hint, disabled buttons — that snaps to real data a beat later.
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
        <span className="section-label">
          Run on your watchlist ({watch.list.length} ticker{watch.list.length === 1 ? '' : 's'})
        </span>
        <span className="spacer" />
        <button
          className="secondary" disabled={disabled}
          title="Rebuilds the S&P 500 board (fresh neighbour data for the network call), then snapshots the watchlist — no separate Snapshot click needed."
          onClick={() => rescan.mutate(undefined, { onSuccess: () => snapshot.mutate() })}
        >
          {rescan.isPending ? 'Scanning…' : 'Full Discover rescan'}
        </button>
        <button
          className="secondary" disabled={disabled}
          title="Records today's technical/network calls from the latest board data — rescan first if the board is stale."
          onClick={() => snapshot.mutate()}
        >
          {snapshot.isPending ? 'Snapshotting…' : 'Snapshot technical/network'}
        </button>
        <button className="secondary" disabled={disabled} onClick={() => run.start('fast')}>
          {running && run.mode === 'fast' ? 'Analyzing…' : 'Fast LLM analysis'}
        </button>
        <button className="secondary" disabled={disabled} onClick={() => run.start('deep')}>
          {running && run.mode === 'deep' ? 'Deep analyzing…' : 'Deep LLM analysis (slow)'}
        </button>
        {running && <button onClick={run.stop}>Stop</button>}
      </div>

      {watch.list.length === 0 && (
        <p className="muted">Add tickers to your watchlist first (★ on the Dashboard).</p>
      )}

      {run.tickers.length > 0 && run.phase !== 'idle' && (
        <div className="run-strip">
          {running && <span className="muted mono">{progressed}/{run.total}</span>}
          {run.tickers.map((t) => {
            const st = run.statuses[t];
            return (
              <span key={t} className={`run-chip ${st?.status ?? 'pending'}`} title={st?.error || undefined}>
                {st ? CHIP_ICON[st.status] : '·'} {t}
                {st?.status === 'done' && st.recommendation
                  ? ` ${st.recommendation.toUpperCase()}` : ''}
                {st?.status === 'done' && st.fellBack ? ' (fell back)' : ''}
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
