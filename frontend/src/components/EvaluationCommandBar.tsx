import { usePortfolioTickers, useSettings } from '../hooks/queries';
import { useWatchlistRunContext } from '../state/watchlistRunContext';
import { MarketHint } from './MarketHint';
import type { TickerRunStatus } from '../types';

const CHIP_ICON: Record<TickerRunStatus, string> = {
  running: '⏳', done: '✓', skipped: '−', failed: '✗',
};

/** One button per portfolio-wide process, ordered as a left-to-right pipeline: the
 *  portfolio rescan (re-scores watchlist + ontology, then chains the technical/network
 *  snapshot itself — so no separate snapshot button is needed now the scan is fast), and
 *  the fast/deep LLM batches (live per-ticker progress + Stop). One process at a time. */
export function EvaluationCommandBar() {
  const settings = useSettings();
  const portfolio = usePortfolioTickers();
  const count = portfolio.data?.tickers.length ?? 0;
  // All four processes live at app level — they survive page navigation, and each
  // wrapped action clears the previous process's status so the bar tells one story.
  const { run, snapshot, rescan, startRun, rescanAndSnapshot } = useWatchlistRunContext();

  const running = run.phase === 'running';
  const scanning = rescan.phase === 'running';
  const busy = snapshot.isPending || scanning || running;
  const disabled = busy || count === 0;
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
          Run on your portfolio ({count} ticker{count === 1 ? '' : 's'}: watchlist + active ontology)
        </span>
        <span className="spacer" />
        {/* All four wear the default gold (user's choice) — the watchlist-wide processes
            are this page's headline actions, not auxiliaries. */}
        <button
          disabled={disabled}
          title="Re-score your portfolio (watchlist + active ontology) — fast, only these names — then snapshot the technical/network calls."
          onClick={() => rescanAndSnapshot('portfolio')}
        >
          {scanning
            ? rescan.total ? `Scanning… ${rescan.scanned}/${rescan.total}` : 'Scanning…'
            : 'Rescan portfolio'}
        </button>
        <button
          disabled={disabled}
          title="Runs the single-shot LLM analysis for each watchlist ticker (one provider call apiece, costs tokens) — tickers already recorded for the latest trading day are skipped, so re-running only fills gaps."
          onClick={() => startRun('fast')}
        >
          {running && run.mode === 'fast' ? 'Analyzing…' : 'Fast LLM analysis'}
        </button>
        <button
          disabled={disabled}
          title="Runs the agentic deep analysis for each watchlist ticker (several LLM calls + data tools apiece — slow, costs more tokens). Already-recorded tickers are skipped; a run that falls back to the fast path is recorded as fast."
          onClick={() => startRun('deep')}
        >
          {running && run.mode === 'deep' ? 'Deep analyzing…' : 'Deep LLM analysis (slow)'}
        </button>
        {running && <button onClick={run.stop}>Stop</button>}
        {scanning && <button onClick={rescan.stop}>Stop</button>}
      </div>

      {count === 0 && (
        <p className="muted">Your portfolio is empty — add to your watchlist (★ on the Dashboard) or activate an ontology.</p>
      )}

      <MarketHint />

      {/* One process at a time renders here — starting a new process clears the rest
          (CSS hides the zone entirely when empty). */}
      <div className="commandbar-status">
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
            ✓ Recorded {snapshot.data.recorded} portfolio signal{snapshot.data.recorded === 1 ? '' : 's'} for
            evaluation{snapshot.data.skipped.length ? ` (${snapshot.data.skipped.length} skipped)` : ''}.
          </p>
        )}
        {snapshot.isError && <p className="error">Snapshot failed: {(snapshot.error as Error).message}</p>}
        {scanning && (
          <p className="muted mono">
            ⏳ {rescan.scanned}/{rescan.total || '?'} scanned
            {rescan.skipped ? ` (${rescan.skipped} skipped)` : ''}
            {rescan.ticker ? ` · fetching ${rescan.ticker}` : ''}
          </p>
        )}
        {rescan.summary && !rescan.stopped && (
          <p className="muted">
            ✓ Board rescanned — {rescan.summary.scanned} scanned, {rescan.summary.skipped} skipped.
          </p>
        )}
        {rescan.stopped && (
          <p className="muted">Rescan stopped — nothing saved. Run again to redo (cached tickers go fast).</p>
        )}
        {rescan.phase === 'error' && rescan.message && (
          <p className="error">Rescan failed: {rescan.message}</p>
        )}
      </div>
    </div>
  );
}
