import type { StockScore } from '../types';
import { ScoreBar } from './ScoreBar';

/** Compact no-LLM opportunity score for the Dashboard summary — mirrors a Discover row's cells. */
export function ScoreChip({ score }: { score: StockScore }) {
  const net = score.network;
  return (
    <div className="score-chip">
      <span className="section-label">Signal</span>
      <div className="score-cell"><ScoreBar score={score.score} /><span>{score.score.toFixed(0)}</span></div>
      <span className={`badge ${score.direction}`}>{score.direction.toUpperCase()}</span>
      <div className="reasons">
        {net && net.reasons.length > 0 && (
          <span className="reason-chip net" title={net.reasons.join(' · ')}>🔗</span>
        )}
        {score.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
      </div>
    </div>
  );
}
