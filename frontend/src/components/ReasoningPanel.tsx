import type { AnalysisResult } from '../types';
import { NetworkPanel } from './NetworkPanel';

export function ReasoningPanel({ result }: { result: AnalysisResult }) {
  const rec = result.current_recommendation;
  return (
    <div>
      <div className="verdict">
        <span className={`verdict-word ${rec}`}>{rec.toUpperCase()}</span>
        <span className={`badge ${result.sentiment}`}>{result.sentiment}</span>
        <span className="conf">confidence <b>{(result.confidence * 100).toFixed(0)}%</b></span>
        <span className="provider">{result.provider} · {result.model}</span>
      </div>

      {result.market_mood && result.market_mood.post_count > 0 && (
        <p className="note muted">
          Policy / market mood: <b>{result.market_mood.lean.replace('_', ' ')}</b>
          {result.market_mood.summary ? ` — ${result.market_mood.summary}` : ''}
        </p>
      )}

      <NetworkPanel network={result.network} />

      {result.key_factors?.length ? (
        <>
          <h4>Why now — key factors</h4>
          <ul className="factor-list">{result.key_factors.map((f, i) => <li key={i}>{f}</li>)}</ul>
        </>
      ) : null}

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

      <p className="disclaimer-fine">{result.disclaimer}</p>
    </div>
  );
}
