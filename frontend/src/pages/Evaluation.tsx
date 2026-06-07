import { useState } from 'react';
import { EvaluationBoard } from '../components/EvaluationBoard';
import { useDeleteTracked, useEvaluation, useExplainPrediction } from '../hooks/queries';
import type { CompanyEvaluation, HorizonResult, PredictionRecord } from '../types';

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

function CompanyDetail({ company }: { company: CompanyEvaluation }) {
  const explain = useExplainPrediction();
  const remove = useDeleteTracked();
  const [openExplain, setOpenExplain] = useState<string | null>(null);
  const [text, setText] = useState<Record<string, string>>({});

  const runExplain = (callDate: string) => {
    setOpenExplain(callDate);
    explain.mutate(
      { ticker: company.rollup.ticker, callDate },
      { onSuccess: (d) => setText((t) => ({ ...t, [callDate]: d.explanation })) },
    );
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="section-label">{company.rollup.ticker} — calls</span>
        <button className="secondary" onClick={() => remove.mutate(company.rollup.ticker)} disabled={remove.isPending}>
          {remove.isPending ? 'Removing…' : 'Stop tracking'}
        </button>
      </div>
      {remove.isError && <p className="error">Couldn't remove: {(remove.error as Error).message}</p>}
      <div className="calls">
        {company.calls.map((call) => (
          <div className="call-row" key={call.call_date}>
            <span className="mono">{call.call_date}</span>
            <span className={`badge ${call.recommendation}`}>{call.recommendation.toUpperCase()}</span>
            <span className="muted">conf {(call.confidence * 100).toFixed(0)}%</span>
            <div className="outcomes">
              {call.results.map((r) => <OutcomeChip key={r.horizon} r={r} />)}
            </div>
            {hasMiss(call) && (
              <button className="secondary" onClick={() => runExplain(call.call_date)}
                      disabled={explain.isPending && openExplain === call.call_date}>
                {explain.isPending && openExplain === call.call_date ? 'Analyzing…' : 'Explain miss'}
              </button>
            )}
            {openExplain === call.call_date && explain.isError && (
              <p className="error">Couldn't explain: {(explain.error as Error).message}</p>
            )}
            {text[call.call_date] && <p className="explain-box">{text[call.call_date]}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Evaluation() {
  const board = useEvaluation();
  const [selected, setSelected] = useState<string | null>(null);

  const companies = board.data?.companies ?? [];
  const current = companies.find((c) => c.rollup.ticker === selected) ?? null;

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <span className="section-label">LLM call accuracy — click a company to see its calls</span>
          {board.data?.as_of && (
            <span className="muted board-asof">As of {new Date(board.data.as_of).toLocaleString()}</span>
          )}
        </div>
        {board.isLoading && <p className="muted">Loading evaluation…</p>}
        {board.isError && <p className="error">Could not load evaluation: {(board.error as Error).message}</p>}
        {board.data && <EvaluationBoard companies={companies} selected={selected} onSelect={setSelected} />}
      </section>
      {current && <CompanyDetail company={current} />}
    </>
  );
}
