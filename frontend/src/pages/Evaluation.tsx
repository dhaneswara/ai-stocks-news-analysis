import { useState } from 'react';
import { EvaluationBoard } from '../components/EvaluationBoard';
import { EvaluationCommandBar } from '../components/EvaluationCommandBar';
import { ScoreBar } from '../components/ScoreBar';
import { useClearEvaluation, useDeleteTracked, useEvaluation, useExplainPrediction } from '../hooks/queries';
import type {
  CompanyEvaluation, HorizonResult, PredictionRecord, Source, SourceTrack,
} from '../types';

const SOURCE_ORDER: Source[] = ['technical', 'network', 'llm_fast', 'llm_deep'];
const SOURCE_LABEL: Record<Source, string> = {
  technical: 'Technical', network: 'Network', llm_fast: 'LLM fast', llm_deep: 'LLM deep',
};
const GRADE_CLASS: Record<string, string> = { Strong: 'buy', Mixed: 'hold', Weak: 'sell' };

function OutcomeChip({ r }: { r: HorizonResult }) {
  if (r.status !== 'final') return <span className="outcome pending">{r.horizon}d · pending</span>;
  const pct = r.return_pct ?? 0;
  const sign = pct >= 0 ? '+' : '';
  return (
    <span className={`outcome ${r.hit ? 'hit' : 'miss'}`}>
      {r.horizon}d {r.hit ? '✓' : '✗'} {sign}{pct.toFixed(1)}%
    </span>
  );
}

function hasMiss(call: PredictionRecord): boolean {
  return call.results.some((r) => r.status === 'final' && r.hit === false);
}

function SourceScoreboard({ sources }: { sources: Partial<Record<Source, SourceTrack>> }) {
  const entries = SOURCE_ORDER.filter((k) => sources[k]);
  if (!entries.length) return null;
  return (
    <div className="source-cards">
      {entries.map((k) => {
        const t = sources[k]!;
        return (
          <div className="source-card" key={k}>
            <span className="section-label">{SOURCE_LABEL[k]}</span>
            <span className="muted">{t.n_calls} calls · {t.n_matured} scored</span>
            <span className="mono">{t.hit_rate == null ? '— hit rate' : `${t.hit_rate.toFixed(1)}% hit rate`}</span>
            {t.avg_score != null ? (
              <div className="score-cell"><ScoreBar score={t.avg_score} /><span>{t.avg_score.toFixed(0)}</span></div>
            ) : (
              <span className="muted">no scored calls yet</span>
            )}
            {t.grade && <span className={`badge ${GRADE_CLASS[t.grade]}`}>{t.grade}</span>}
          </div>
        );
      })}
    </div>
  );
}

function CompanyDetail({ company, srcFilter, onFilter }: {
  company: CompanyEvaluation;
  srcFilter: Source | null;
  onFilter: (src: Source | null) => void;
}) {
  const explain = useExplainPrediction();
  const remove = useDeleteTracked();
  const [openExplain, setOpenExplain] = useState<string | null>(null);
  const [text, setText] = useState<Record<string, string>>({});

  const runExplain = (call: PredictionRecord) => {
    const key = `${call.call_date}:${call.source}`;
    setOpenExplain(key);
    explain.mutate(
      { ticker: company.rollup.ticker, callDate: call.call_date, source: call.source },
      { onSuccess: (d) => setText((t) => ({ ...t, [key]: d.explanation })) },
    );
  };

  const calls = company.calls.filter((c) => !srcFilter || c.source === srcFilter);

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="section-label">{company.rollup.ticker} — calls</span>
        <button className="secondary" onClick={() => remove.mutate(company.rollup.ticker)} disabled={remove.isPending}>
          {remove.isPending ? 'Removing…' : 'Stop tracking'}
        </button>
      </div>
      <div className="src-filter">
        {SOURCE_ORDER.filter((k) => company.by_source[k]).map((k) => {
          const t = company.by_source[k]!;
          return (
            <span key={k} className="reason-chip">
              {SOURCE_LABEL[k]}: {t.hit_rate == null ? '—' : `${t.hit_rate.toFixed(0)}%`} over {t.n_matured}
            </span>
          );
        })}
      </div>
      {remove.isError && <p className="error">Couldn't remove: {(remove.error as Error).message}</p>}
      <div className="src-filter">
        <span className="muted">Filter calls:</span>
        <button className={srcFilter == null ? 'secondary active' : 'secondary'} onClick={() => onFilter(null)}>All</button>
        {SOURCE_ORDER.map((k) => (
          <button key={k} className={srcFilter === k ? 'secondary active' : 'secondary'} onClick={() => onFilter(k)}>
            {SOURCE_LABEL[k]}
          </button>
        ))}
      </div>
      {!calls.length && <p className="muted">No calls from this source yet.</p>}
      <div className="calls">
        {calls.map((call) => {
          const key = `${call.call_date}:${call.source}`;
          return (
            <div className="call-row" key={key}>
              <span className="mono">{call.call_date}</span>
              <span className="reason-chip">{SOURCE_LABEL[call.source]}</span>
              <span className={`badge ${call.recommendation}`}>{call.recommendation.toUpperCase()}</span>
              <span className="muted">conf {(call.confidence * 100).toFixed(0)}%</span>
              <div className="outcomes">
                {call.results.map((r) => <OutcomeChip key={r.horizon} r={r} />)}
              </div>
              {hasMiss(call) && (
                <button className="secondary" onClick={() => runExplain(call)}
                        disabled={explain.isPending && openExplain === key}>
                  {explain.isPending && openExplain === key ? 'Analyzing…' : 'Explain miss'}
                </button>
              )}
              {openExplain === key && explain.isError && (
                <p className="error">Couldn't explain: {(explain.error as Error).message}</p>
              )}
              {text[key] && <p className="explain-box">{text[key]}</p>}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function Evaluation() {
  const board = useEvaluation();
  const clearAll = useClearEvaluation();
  const [selected, setSelected] = useState<string | null>(null);
  const [srcFilter, setSrcFilter] = useState<Source | null>(null);

  const companies = board.data?.companies ?? [];
  const current = companies.find((c) => c.rollup.ticker === selected) ?? null;

  const startOver = () => {
    if (window.confirm('Delete ALL recorded calls and scores for every tracked ticker? This cannot be undone.')) {
      clearAll.mutate();
    }
  };

  return (
    <>
      <EvaluationCommandBar />
      <section className="panel">
        <div className="panel-head">
          <span className="section-label">Call accuracy by source — click a company to see its calls</span>
          {board.data?.as_of && (
            <span className="muted board-asof">As of {new Date(board.data.as_of).toLocaleString()}</span>
          )}
          <button
            className="secondary"
            disabled={clearAll.isPending || companies.length === 0}
            title="Start over: wipe every recorded call and score, for all tickers — e.g. after testing, so old junk doesn't pollute the track record."
            onClick={startOver}
          >
            {clearAll.isPending ? 'Clearing…' : 'Clear all results'}
          </button>
        </div>
        {clearAll.isError && <p className="error">Couldn't clear: {(clearAll.error as Error).message}</p>}
        {clearAll.data && (
          <p className="muted">
            ✓ Cleared {clearAll.data.predictions} call{clearAll.data.predictions === 1 ? '' : 's'} and{' '}
            {clearAll.data.evals} scored outcome{clearAll.data.evals === 1 ? '' : 's'} — a fresh start.
          </p>
        )}
        {board.isLoading && <p className="muted">Loading evaluation…</p>}
        {board.isError && <p className="error">Could not load evaluation: {(board.error as Error).message}</p>}
        {board.data && (
          <>
            <SourceScoreboard sources={board.data.sources ?? {}} />
            <EvaluationBoard companies={companies} selected={selected} onSelect={setSelected} />
          </>
        )}
      </section>
      {current && <CompanyDetail company={current} srcFilter={srcFilter} onFilter={setSrcFilter} />}
    </>
  );
}
