import { Link } from 'react-router-dom';
import { useWatchlistRunContext } from '../state/watchlistRunState';

/** Masthead chip for a live watchlist batch run — visible from every page since the
 *  stream survives navigation. Hover for the current position; click to open the
 *  Evaluation page with the full per-ticker progress. Hidden when nothing runs. */
export function RunIndicator() {
  const run = useWatchlistRunContext();
  if (run.phase !== 'running') return null;
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
