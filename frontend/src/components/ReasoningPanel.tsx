import type { AnalysisResult, Signal } from '../types';

export function ReasoningPanel({
  result,
  selected,
}: {
  result: AnalysisResult;
  selected: Signal | null;
}) {
  const rec = result.current_recommendation;
  return (
    <div>
      <div className="verdict">
        <span className={`verdict-word ${rec}`}>{rec.toUpperCase()}</span>
        <span className={`badge ${result.sentiment}`}>{result.sentiment}</span>
        <span className="conf">confidence <b>{(result.confidence * 100).toFixed(0)}%</b></span>
        <span className="provider">{result.provider} · {result.model}</span>
      </div>

      <h4>Summary</h4>
      <p className="lead">{result.overall_summary}</p>

      <h4>News analysis</h4>
      <p>{result.news_analysis}</p>

      {result.risks.length > 0 && (
        <>
          <h4>Risks</h4>
          <ul className="risk-list">{result.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </>
      )}

      {selected && (
        <div className="signal-reason">
          <div className="sig-head">
            <span className={`badge ${selected.action}`}>{selected.action.toUpperCase()}</span>
            <span>{selected.date} @ {selected.price} · confidence {(selected.confidence * 100).toFixed(0)}%</span>
          </div>
          <p>{selected.reasoning}</p>
        </div>
      )}

      <p className="disclaimer-fine">{result.disclaimer}</p>
    </div>
  );
}
