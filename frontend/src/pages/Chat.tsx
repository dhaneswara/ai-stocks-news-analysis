import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useChatContext } from '../state/chatState';
import { TracePanel } from '../components/TracePanel';
import { Markdown } from '../components/Markdown';

const SUGGESTIONS = [
  'How does geopolitics affect NVDA right now?',
  'Compare AMD vs NVDA using the ontology graph.',
  "What's the strongest opportunity in my watchlist?",
];

export default function Chat() {
  const { turns, running, send, stop } = useChatContext();
  const [input, setInput] = useState('');
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [turns, running]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = input.trim();
    if (!q || running) return;
    send(q);
    setInput('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <section className="panel chat">
      <div className="chat-log">
        {turns.length === 0 && (
          <div className="chat-empty">
            <p className="muted">
              Ask about any stock — prices, news, geopolitics, the ontology graph, or your
              portfolio. The assistant reasons step by step using the app's own data.
            </p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="chip" disabled={running}
                        onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t, i) => (
          <div key={i} className={`chat-turn ${t.role}`}>
            {t.role === 'user' ? (
              <div className="chat-bubble user">{t.content}</div>
            ) : (
              <div className="chat-bubble assistant">
                {t.steps && t.steps.length > 0 && (
                  <TracePanel steps={t.steps} running={running && i === turns.length - 1}
                              maxSteps={10} />
                )}
                {t.content && <Markdown text={t.content} />}
                {!t.content && !t.error && running && i === turns.length - 1 && (
                  <p className="muted">…thinking</p>
                )}
                {t.error && <p className="error">{t.error}</p>}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form className="chat-composer" onSubmit={submit}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about a stock, a sector, geopolitics, the ontology…"
          rows={2}
          disabled={running}
        />
        {running ? (
          <button type="button" className="secondary" onClick={stop}>Stop</button>
        ) : (
          <button type="submit" disabled={!input.trim()}>Send</button>
        )}
      </form>
    </section>
  );
}
