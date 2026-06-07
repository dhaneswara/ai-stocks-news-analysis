import { useNavigate } from 'react-router-dom';
import type { StockScore } from '../types';
import { ScoreBar } from './ScoreBar';

export function DiscoverBoard({ items, onAdd }: { items: StockScore[]; onAdd: (t: string) => void }) {
  const navigate = useNavigate();
  if (!items.length) return <p className="muted">No matches. Try a different sector, or hit Rescan.</p>;
  return (
    <div className="board-wrap">
      <table className="board">
        <thead>
          <tr>
            <th>#</th><th>Ticker</th><th>Company</th><th>Sector</th><th>Price</th>
            <th>Score</th><th>Call</th><th>Why</th><th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((s, i) => (
            <tr key={s.ticker} className="board-row"
                onClick={() => navigate(`/?ticker=${encodeURIComponent(s.ticker)}`)}>
              <td className="muted">{i + 1}</td>
              <td className="mono">{s.ticker}</td>
              <td>{s.name}</td>
              <td className="muted">{s.sector}</td>
              <td className="mono">{s.price.toFixed(2)}</td>
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
                <button className="secondary" onClick={(e) => { e.stopPropagation(); onAdd(s.ticker); }}>
                  + Watch
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
