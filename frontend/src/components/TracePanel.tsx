import type { AgentStep } from '../types';

export function TracePanel({
  steps, running, fellBack = false, maxSteps = 6,
}: { steps: AgentStep[]; running: boolean; fellBack?: boolean; maxSteps?: number }) {
  return (
    <div className="trace">
      <div className="trace-head">
        <span className="section-label">Agent trace — what the LLM is doing</span>
        {running && <span className="trace-progress">step {steps.length} / {maxSteps}…</span>}
        {fellBack && <span className="badge bearish">fell back to single-shot</span>}
      </div>
      <ol className="trace-steps">
        {steps.map((s, i) => (
          <li key={i} className={`trace-step${s.is_final ? ' final' : ''}`}>
            {s.thought && <p className="trace-thought">{s.thought}</p>}
            {s.action && (
              <p className="trace-action">
                <b>{s.action}</b>(<code>{JSON.stringify(s.action_args)}</code>)
              </p>
            )}
            {s.observation && <pre className="trace-obs">{s.observation}</pre>}
            {!s.thought && !s.action && !s.is_final && s.raw && (
              <pre className="trace-raw muted">{s.raw}</pre>
            )}
            {s.is_final && <p className="trace-final-label">→ final answer</p>}
          </li>
        ))}
        {running && <li className="trace-step pending muted">…thinking</li>}
      </ol>
    </div>
  );
}
