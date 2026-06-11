import { Link } from 'react-router-dom';
import { useWatchlistRunContext } from '../state/watchlistRunState';

/** Masthead chip for any in-flight watchlist-wide process — LLM batch, Discover rescan,
 *  or technical/network snapshot — visible from every page since they all live above the
 *  router. Hover for detail; click to open the page that owns the result. Hidden when
 *  nothing runs. */
export function RunIndicator() {
  const { run, snapshot, rescan } = useWatchlistRunContext();

  if (run.phase === 'running') {
    const done = Object.values(run.statuses).filter((t) => t.status !== 'running').length;
    const current = run.tickers.find((t) => run.statuses[t]?.status === 'running');
    const label = run.mode === 'deep' ? 'Deep batch' : 'Fast batch';
    return (
      <Link
        className="run-indicator"
        to="/evaluation"
        title={`${label} running in the background — ${done}/${run.total} done${current ? `, analyzing ${current}` : ''}. Click for details.`}
      >
        <span className="run-indicator-pulse">●</span> {label} {done}/{run.total}
      </Link>
    );
  }

  if (rescan.isPending) {
    return (
      <Link
        className="run-indicator"
        to="/discover"
        title="Discover rescan running in the background — the watchlist snapshot follows automatically. Click to open Discover."
      >
        <span className="run-indicator-pulse">●</span> Rescanning…
      </Link>
    );
  }

  if (snapshot.isPending) {
    return (
      <Link
        className="run-indicator"
        to="/evaluation"
        title="Recording the watchlist's technical/network calls. Click to open Evaluation."
      >
        <span className="run-indicator-pulse">●</span> Snapshotting…
      </Link>
    );
  }

  return null;
}
