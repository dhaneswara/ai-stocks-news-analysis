import { ScoreBoard } from '../components/ScoreBoard';
import { MarketHint } from '../components/MarketHint';
import { usePortfolioTickers, useScreen, useWatchlist, useRescanTicker } from '../hooks/queries';
import { useWatchlistRunContext } from '../state/watchlistRunState';

export default function Portfolio() {
  const board = useScreen(undefined, undefined, 0, 'portfolio'); // uncapped, the focused set
  const tickers = usePortfolioTickers();
  const { rescan, snapshot, rescanAndSnapshot } = useWatchlistRunContext();
  const watch = useWatchlist();
  const rescanOne = useRescanTicker('portfolio');
  const rescanning = rescanOne.isPending ? rescanOne.variables ?? null : null;

  const data = board.data;
  const items = data?.items ?? [];
  const watchSet = new Set(watch.list.map((t) => t.toUpperCase()));
  const mine = items.filter((s) => watchSet.has(s.ticker.toUpperCase()));
  const extended = items.filter((s) => !watchSet.has(s.ticker.toUpperCase()));
  const scanning = rescan.phase === 'running';
  const empty = (tickers.data?.tickers.length ?? 0) === 0;

  return (
    <>
      <div className="panel commandbar">
        <div className="board-controls">
          <span className="section-label">
            Portfolio — watchlist + active ontology
            {tickers.data ? ` (${tickers.data.tickers.length})` : ''}
          </span>
          <span className="spacer" />
          {data && (
            <span className="muted board-asof">
              {data.as_of ? `As of ${new Date(data.as_of).toLocaleString()}` : 'No scan yet'}
              {data.scanned ? ` · ${data.scanned} scanned` : ''}
            </span>
          )}
          <button
            disabled={scanning || empty}
            title="Re-score your portfolio (watchlist + active ontology) — fast, only these names — and record today's technical/network snapshot."
            onClick={() => rescanAndSnapshot('portfolio')}
          >
            {scanning
              ? rescan.total ? `Scanning… ${rescan.scanned}/${rescan.total}` : 'Scanning…'
              : 'Rescan portfolio'}
          </button>
          {scanning && <button title="Stop the scan — nothing is saved." onClick={rescan.stop}>Stop</button>}
        </div>
        <MarketHint />
      </div>

      {board.isLoading && <p className="muted">Loading portfolio…</p>}
      {scanning && (
        <p className="muted mono">
          ⏳ {rescan.scanned}/{rescan.total || '?'} scanned
          {rescan.ticker ? ` · fetching ${rescan.ticker}` : ''}
        </p>
      )}
      {snapshot.data && (
        <p className="muted">
          ✓ Recorded {snapshot.data.recorded} portfolio signal{snapshot.data.recorded === 1 ? '' : 's'} for evaluation.
        </p>
      )}
      {empty && (
        <p className="muted">
          Your portfolio is empty — add to your watchlist or activate an ontology, then hit <b>Rescan portfolio</b>.
        </p>
      )}

      {mine.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <span className="section-label">Watchlist ({mine.length}) — click a row to deep-dive</span>
          </div>
          <ScoreBoard items={mine} onAdd={watch.add} watched={watch.list} onUnwatch={watch.remove} onRescan={(t) => rescanOne.mutate(t)} rescanning={rescanning} />
        </section>
      )}
      {extended.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <span className="section-label">
              Extended via ontology ({extended.length}) — related companies pulled in by your active graph
            </span>
          </div>
          <ScoreBoard items={extended} onAdd={watch.add} watched={watch.list} onUnwatch={watch.remove} onRescan={(t) => rescanOne.mutate(t)} rescanning={rescanning} />
        </section>
      )}
    </>
  );
}
