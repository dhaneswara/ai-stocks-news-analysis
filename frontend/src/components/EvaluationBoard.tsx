import { Fragment, type ReactNode } from 'react';
import type { CompanyEvaluation, Grade } from '../types';

const GRADE_CLASS: Record<Grade, string> = { Strong: 'buy', Mixed: 'hold', Weak: 'sell' };

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="score-bar" title={`${score.toFixed(0)} / 100`}>
      <span style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
    </div>
  );
}

export function EvaluationBoard({
  companies,
  selected,
  onSelect,
  renderDetail,
}: {
  companies: CompanyEvaluation[];
  selected: string | null;
  onSelect: (ticker: string) => void;
  /** Rendered as an accordion row directly under the selected company. */
  renderDetail?: (company: CompanyEvaluation) => ReactNode;
}) {
  if (!companies.length) {
    return <p className="muted">No tracked calls yet — analyze a company on the Dashboard to start.</p>;
  }
  return (
    <div className="board-wrap">
      <table className="board">
        <thead>
          <tr>
            <th>Ticker</th><th>Calls</th><th>Scored</th><th>Hit rate</th>
            <th>Avg score</th><th>Grade</th><th>Latest</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((c) => {
            const r = c.rollup;
            return (
              <Fragment key={r.ticker}>
                <tr
                  className={`board-row${selected === r.ticker ? ' selected' : ''}`}
                  onClick={() => onSelect(r.ticker)}
                >
                  <td className="mono">{r.ticker}</td>
                  <td className="muted">{r.n_calls}</td>
                  <td className="muted">{r.n_matured}</td>
                  <td className="mono">{r.hit_rate == null ? '—' : `${r.hit_rate.toFixed(1)}%`}</td>
                  <td>
                    {r.avg_score == null ? (
                      <span className="muted">—</span>
                    ) : (
                      <div className="score-cell"><ScoreBar score={r.avg_score} /><span>{r.avg_score.toFixed(0)}</span></div>
                    )}
                  </td>
                  <td>
                    {r.grade ? (
                      <span className={`badge ${GRADE_CLASS[r.grade]}`}>{r.grade}</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                    {r.overconfident && <span className="overconf" title="Missed calls were as confident as correct ones"> ⚠ overconfident</span>}
                  </td>
                  <td>
                    {r.latest_recommendation && (
                      <span className={`badge ${r.latest_recommendation}`}>{r.latest_recommendation.toUpperCase()}</span>
                    )}
                  </td>
                </tr>
                {selected === r.ticker && renderDetail && (
                  <tr className="board-detail-row">
                    <td colSpan={7}>{renderDetail(c)}</td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
