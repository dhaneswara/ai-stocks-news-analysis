import { useState } from 'react';
import { DiscoverBoard } from '../components/DiscoverBoard';
import { MarketHint } from '../components/MarketHint';
import { useRefreshUniverse, useScreen, useSectors, useWatchlist } from '../hooks/queries';
import { useWatchlistRunContext } from '../state/watchlistRunState';

export default function Discover() {
  const [sector, setSector] = useState('');
  const [direction, setDirection] = useState('');
  const [show, setShow] = useState(25);
  const sectors = useSectors();
  const board = useScreen(sector || undefined, direction || undefined, show);
  // Shared app-level rescan/snapshot — the chained snapshot survives page navigation.
  const { snapshot, rescan, rescanAndSnapshot } = useWatchlistRunContext();
  const refreshList = useRefreshUniverse();
  const watch = useWatchlist();

  const data = board.data;
  const empty = data && data.items.length === 0 && data.as_of === '';

  return (
    <>
      <div className="panel commandbar">
        <div className="board-controls">
          <label>Sector
            <select value={sector} onChange={(e) => setSector(e.target.value)}>
              <option value="">All sectors</option>
              {(sectors.data ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Call
            <select value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="">Any</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
              <option value="hold">Hold</option>
            </select>
          </label>
          <label>Show
            <select value={show} onChange={(e) => setShow(Number(e.target.value))}>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={0}>All</option>
            </select>
          </label>
          <span className="spacer" />
          {data && (
            <span className="muted board-asof">
              {data.as_of ? `As of ${new Date(data.as_of).toLocaleString()}` : 'No scan yet'}
              {data.scanned ? ` · ${data.scanned} scanned` : ''}
              {data.skipped ? `, ${data.skipped} skipped` : ''}
            </span>
          )}
          <button className="secondary" onClick={() => refreshList.mutate()} disabled={refreshList.isPending}>
            {refreshList.isPending ? 'Updating…' : 'Update S&P 500 list'}
          </button>
          <button onClick={() => rescanAndSnapshot(sector || undefined)} disabled={rescan.isPending}>
            {rescan.isPending ? 'Scanning…' : sector ? `Rescan ${sector}` : 'Rescan all'}
          </button>
        </div>
        <MarketHint />
      </div>

      {board.isLoading && <p className="muted">Loading board…</p>}
      {board.isError && <p className="error">Could not load the board: {(board.error as Error).message}</p>}
      {rescan.isError && <p className="error">Rescan failed: {(rescan.error as Error).message}</p>}
      {snapshot.data && (
        <p className="muted">
          ✓ Recorded {snapshot.data.recorded} watchlist signal{snapshot.data.recorded === 1 ? '' : 's'} for
          evaluation{snapshot.data.skipped.length ? ` (${snapshot.data.skipped.length} skipped)` : ''}.
        </p>
      )}
      {refreshList.isSuccess && (
        <p className="muted">S&amp;P 500 list updated — {refreshList.data.count} names. Hit Rescan to rebuild the board.</p>
      )}
      {refreshList.isError && <p className="error">Update failed: {(refreshList.error as Error).message}</p>}
      {empty && (
        <p className="muted">
          No snapshot yet — hit <b>Rescan all</b> to build today's board (scans the S&amp;P 500; a
          few minutes cold, near-instant once cached).
        </p>
      )}

      <section className="panel">
        <div className="panel-head">
          <span className="section-label">Opportunity board — click a row to deep-dive</span>
        </div>
        {data && <DiscoverBoard items={data.items} onAdd={watch.add} />}
      </section>
    </>
  );
}
