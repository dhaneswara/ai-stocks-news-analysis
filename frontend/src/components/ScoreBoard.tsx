import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { StockScore } from '../types';
import { ScoreBar } from './ScoreBar';

interface Props {
  items: StockScore[];
  onAdd: (t: string) => void;
  /** Tickers currently in the watchlist; matching rows render a filled ★ (case-insensitive). */
  watched?: string[];
  /** Remove from the watchlist — the ★ action. Omit to render watched rows as a non-acting ★. */
  onUnwatch?: (t: string) => void;
  /** When given, custom rows (`in_sp500 === false`) get a × remove button. */
  onRemove?: (t: string) => void;
  /** Re-score a single row. Omit to hide the per-row ⟳ button. */
  onRescan?: (t: string) => void;
  /** Ticker currently being rescanned — that row's ⟳ spins and is disabled. */
  rescanning?: string | null;
}

export function ScoreBoard({ items, onAdd, watched, onUnwatch, onRemove, onRescan, rescanning }: Props) {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const shown = needle
    ? items.filter((s) => s.ticker.toLowerCase().includes(needle) || s.name.toLowerCase().includes(needle))
    : items;
  const watchedSet = new Set((watched ?? []).map((t) => t.toUpperCase()));

  return (
    <div className="board-wrap">
      <div className="board-search">
        <input
          type="search"
          placeholder="Search ticker or company…"
          title="Filter the rows below by ticker or company name"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {shown.length === 0 ? (
        <p className="muted">No matches. Try a different search, sector, or hit Rescan.</p>
      ) : (
        <table className="board">
          <thead>
            <tr>
              <th>#</th><th>Ticker</th><th>Company</th><th>Exchange</th><th>Sector</th>
              <th>Price</th><th>S&amp;P</th><th>Score</th><th>Call</th><th>Why</th><th></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s, i) => {
              const saved = watchedSet.has(s.ticker.toUpperCase());
              const isRescanning = rescanning?.toUpperCase() === s.ticker.toUpperCase();
              return (
                <tr key={s.ticker} className="board-row"
                    onClick={() => navigate(`/?ticker=${encodeURIComponent(s.ticker)}`)}>
                  <td className="muted">{i + 1}</td>
                  <td className="mono">{s.ticker}</td>
                  <td>{s.name}</td>
                  <td className="muted">{s.exchange || '—'}</td>
                  <td className="muted">{s.sector || '—'}</td>
                  <td className="mono">{s.price.toFixed(2)}</td>
                  <td>
                    {s.in_sp500
                      ? <span className="badge sp" title="S&P 500 member">S&amp;P 500</span>
                      : <span className="badge custom" title="Not in the S&P 500 (custom company)">Custom</span>}
                  </td>
                  <td>
                    <div className="score-cell"><ScoreBar score={s.score} /><span>{s.score.toFixed(0)}</span></div>
                  </td>
                  <td><span className={`badge ${s.direction}`}>{s.direction.toUpperCase()}</span></td>
                  <td>
                    <div className="reasons">
                      {s.network && s.network.reasons.length > 0 && (
                        <span className="reason-chip net" title="company-network influence">🔗</span>
                      )}
                      {s.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
                    </div>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="star-btn"
                      aria-label={saved ? 'Remove from watchlist' : 'Add to watchlist'}
                      title={saved ? `Remove ${s.ticker} from watchlist` : `Add ${s.ticker} to watchlist`}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (saved) onUnwatch?.(s.ticker);
                        else onAdd(s.ticker);
                      }}
                    >
                      {saved ? '★' : '☆'}
                    </button>
                    {onRescan && (
                      <button
                        type="button"
                        className={`rescan-btn${isRescanning ? ' spinning' : ''}`}
                        disabled={isRescanning}
                        aria-label={isRescanning ? `Rescanning ${s.ticker}` : `Rescan ${s.ticker}`}
                        title={isRescanning ? `Rescanning ${s.ticker}…` : `Rescan ${s.ticker} — re-score this one company`}
                        onClick={(e) => { e.stopPropagation(); onRescan(s.ticker); }}
                      >
                        ⟳
                      </button>
                    )}
                    {onRemove && !s.in_sp500 && (
                      <button className="secondary" title="Remove this custom company"
                              onClick={(e) => { e.stopPropagation(); onRemove(s.ticker); }}>
                        ×
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
