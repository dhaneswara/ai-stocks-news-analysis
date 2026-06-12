import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useWatchlistRunContext } from '../state/watchlistRunState';

/** A link only when it actually goes somewhere: on the chip's own target page it renders
 *  as a plain pill (default cursor), so the pointer never promises a no-op navigation. */
function Chip({ to, detail, children }: { to: string; detail: string; children: ReactNode }) {
  const { pathname } = useLocation();
  if (pathname === to) {
    return <span className="run-indicator" title={detail}>{children}</span>;
  }
  return (
    <Link className="run-indicator" to={to} title={`${detail} Click to open.`}>
      {children}
    </Link>
  );
}

/** Masthead chip for any in-flight watchlist-wide process — LLM batch, Discover rescan,
 *  or technical/network snapshot — visible from every page since they all live above the
 *  router. Hover for detail; click (from other pages) to open the page that owns the
 *  result. Hidden when nothing runs. */
export function RunIndicator() {
  const { run, snapshot, rescan } = useWatchlistRunContext();

  if (run.phase === 'running') {
    const done = Object.values(run.statuses).filter((t) => t.status !== 'running').length;
    const current = run.tickers.find((t) => run.statuses[t]?.status === 'running');
    const label = run.mode === 'deep' ? 'Deep batch' : 'Fast batch';
    return (
      <Chip
        to="/evaluation"
        detail={`${label} running in the background — ${done}/${run.total} done${current ? `, analyzing ${current}` : ''}.`}
      >
        <span className="run-indicator-pulse">●</span> {label} {done}/{run.total}
      </Chip>
    );
  }

  if (rescan.phase === 'running') {
    const label = rescan.total ? `Rescan ${rescan.scanned}/${rescan.total}` : 'Rescanning…';
    return (
      <Chip
        to="/discover"
        detail={`Discover rescan running in the background — ${rescan.scanned}/${rescan.total || '?'} scanned${rescan.ticker ? `, fetching ${rescan.ticker}` : ''}. The watchlist snapshot follows automatically.`}
      >
        <span className="run-indicator-pulse">●</span> {label}
      </Chip>
    );
  }

  if (snapshot.isPending) {
    return (
      <Chip to="/evaluation" detail="Recording the watchlist's technical/network calls.">
        <span className="run-indicator-pulse">●</span> Snapshotting…
      </Chip>
    );
  }

  return null;
}
