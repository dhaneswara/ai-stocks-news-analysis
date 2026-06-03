import { useState } from 'react';

export function TickerBar({
  watchlist,
  onSelect,
  onAnalyze,
  analyzing,
  canAnalyze,
}: {
  watchlist: string[];
  onSelect: (ticker: string) => void;
  onAnalyze: () => void;
  analyzing: boolean;
  canAnalyze: boolean;
}) {
  const [input, setInput] = useState('');
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (t) onSelect(t);
  };
  return (
    <div className="tickerbar">
      <form onSubmit={submit}>
        <input
          aria-label="ticker"
          placeholder="Ticker · e.g. AAPL"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" className="secondary">Load</button>
      </form>
      {watchlist.length > 0 && (
        <div className="watch">
          <span className="watch-label">Watchlist</span>
          {watchlist.map((t) => (
            <span className="chip" key={t} onClick={() => onSelect(t)}>{t}</span>
          ))}
        </div>
      )}
      <span className="spacer" />
      <button onClick={onAnalyze} disabled={!canAnalyze || analyzing}>
        {analyzing ? 'Analyzing…' : 'Analyze with LLM'}
      </button>
    </div>
  );
}
