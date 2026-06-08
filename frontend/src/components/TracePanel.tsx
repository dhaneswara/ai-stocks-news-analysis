import { useEffect, useRef, useState } from 'react';
import type { AgentStep } from '../types';

export function TracePanel({
  steps, running, fellBack = false, maxSteps = 6,
}: { steps: AgentStep[]; running: boolean; fellBack?: boolean; maxSteps?: number }) {
  const [open, setOpen] = useState(true);
  const wasRunning = useRef(running);
  // Show the live trace while the agent runs, then tuck it away once the result is in — the
  // reasoning is for tracing the chain of thought, not the headline answer. (Manual toggle still
  // works, and a static/already-finished trace stays open so it isn't hidden on first paint.)
  useEffect(() => {
    if (wasRunning.current && !running) setOpen(false);
    wasRunning.current = running;
  }, [running]);

  const count = steps.length;
  return (
    <div className="trace">
      <button
        type="button"
        className="trace-head"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="trace-caret">{open ? '▾' : '▸'}</span>
        <span className="section-label">Agent trace — what the LLM is doing</span>
        {running && <span className="trace-progress">step {count} / {maxSteps}…</span>}
        {!running && count > 0 && <span className="trace-count">{count} step{count > 1 ? 's' : ''}</span>}
        {fellBack && <span className="badge bearish">fell back to single-shot</span>}
      </button>
      {open && (
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
                <pre className="trace-raw">{s.raw}</pre>
              )}
              {s.is_final && <p className="trace-final-label">→ final answer</p>}
            </li>
          ))}
          {running && <li className="trace-step pending muted">…thinking</li>}
        </ol>
      )}
    </div>
  );
}
