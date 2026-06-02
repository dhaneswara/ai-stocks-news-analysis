import type { AnalysisResult, Signal } from '../types';

export function ReasoningPanel({
  result,
  selected,
}: {
  result: AnalysisResult;
  selected: Signal | null;
}) {
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <span className={`badge ${result.current_recommendation}`}>
          {result.current_recommendation.toUpperCase()}
        </span>
        <span className={`badge ${result.sentiment}`}>{result.sentiment}</span>
        <span className="muted">confidence {(result.confidence * 100).toFixed(0)}%</span>
        <span className="muted" style={{ marginLeft: 'auto' }}>{result.provider} · {result.model}</span>
      </div>
      <h4>Summary</h4>
      <p>{result.overall_summary}</p>
      <h4>News analysis</h4>
      <p>{result.news_analysis}</p>
      {result.risks.length > 0 && (
        <>
          <h4>Risks</h4>
          <ul>{result.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </>
      )}
      {selected && (
        <div className="signal-reason">
          <strong className={`badge ${selected.action}`}>{selected.action.toUpperCase()}</strong>{' '}
          {selected.date} @ {selected.price} (confidence {(selected.confidence * 100).toFixed(0)}%)
          <p>{selected.reasoning}</p>
        </div>
      )}
      <p className="muted" style={{ fontSize: 11, marginTop: 12 }}>{result.disclaimer}</p>
    </div>
  );
}
