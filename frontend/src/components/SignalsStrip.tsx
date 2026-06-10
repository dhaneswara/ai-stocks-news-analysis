import type { Recommendation, SignalsSummary, Source, StockScore } from '../types';
import { ScoreBar } from './ScoreBar';

const ORDER: [Source, string][] = [
  ['technical', 'TECH'], ['network', 'NET'], ['llm_fast', 'FAST'], ['llm_deep', 'DEEP'],
];
const ARROW: Record<Recommendation, string> = { buy: '▲', sell: '▼', hold: '—' };

/** Every CALL source for the loaded ticker side by side: latest call per source, hit-rate
 * tooltips, a crown on the historically best source, and an agree/conflict badge. Replaces
 * the old ScoreChip — the score bar + reason chips live on. */
export function SignalsStrip({ score, signals }: { score?: StockScore; signals?: SignalsSummary }) {
  const a = signals?.agreement;
  return (
    <div className="signals-strip">
      <div className="signals-row">
        <span className="section-label">Signals</span>
        {score && (
          <div className="score-cell"><ScoreBar score={score.score} /><span>{score.score.toFixed(0)}</span></div>
        )}
        {ORDER.map(([key, label]) => {
          const s = signals?.sources?.[key];
          const crowned = signals?.winner === key;
          const title = s
            ? `${label}: ${s.latest.recommendation.toUpperCase()} on ${s.latest.call_date}` +
              (s.track.hit_rate != null
                ? ` · ${s.track.hit_rate}% hit rate over ${s.track.n_matured} scored`
                : ' · collecting data')
            : `${label}: no call recorded yet`;
          return (
            <span key={key} className={`signal-chip${crowned ? ' winner' : ''}`} title={title}>
              <span className="signal-src">{crowned ? '👑 ' : ''}{label}</span>
              {s ? (
                <span className={`badge ${s.latest.recommendation}`}>
                  {ARROW[s.latest.recommendation]} {s.latest.recommendation.toUpperCase()}
                </span>
              ) : (
                <span className="muted">—</span>
              )}
            </span>
          );
        })}
        {a && a.counted >= 2 && (
          <span className={`agree-badge${a.conflict ? ' conflict' : ''}`}>
            {a.conflict
              ? `${a.agreeing}/${a.counted} lean ${a.on?.toUpperCase() ?? ''}`
              : `${a.counted}/${a.counted} agree on ${a.on?.toUpperCase() ?? ''}`}
          </span>
        )}
      </div>
      {score && (
        <div className="reasons">
          {score.network && score.network.reasons.length > 0 && (
            <span className="reason-chip net" title={score.network.reasons.join(' · ')}>🔗</span>
          )}
          {score.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
        </div>
      )}
    </div>
  );
}
