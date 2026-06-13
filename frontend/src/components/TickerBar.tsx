import { useState } from 'react';
import { WatchlistMenu } from './WatchlistMenu';

export function TickerBar({
  watchlist,
  current,
  onSelect,
  onAdd,
  onRemove,
  onAnalyze,
  analyzing,
  canAnalyze,
  onDeepAnalyze,
  deepAnalyzing,
}: {
  watchlist: string[];
  current: string;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => void;
  onRemove: (ticker: string) => void;
  onAnalyze: () => void;
  analyzing: boolean;
  canAnalyze: boolean;
  onDeepAnalyze: () => void;
  deepAnalyzing: boolean;
}) {
  const [input, setInput] = useState('');
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (t) onSelect(t);
  };
  const saved = !!current && watchlist.includes(current);
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
      {current && (
        <button
          type="button"
          className="star-btn"
          aria-label={saved ? 'Remove from watchlist' : 'Add to watchlist'}
          title={saved ? `Remove ${current} from watchlist` : `Add ${current} to watchlist`}
          onClick={() => (saved ? onRemove(current) : onAdd(current))}
        >
          {saved ? '★' : '☆'}
        </button>
      )}
      {watchlist.length > 0 && (
        <WatchlistMenu
          watchlist={watchlist}
          current={current}
          onSelect={onSelect}
          onRemove={onRemove}
        />
      )}
      <span className="spacer" />
      <button type="button" onClick={onAnalyze} disabled={!canAnalyze || analyzing}>
        {analyzing ? 'Analyzing…' : 'Analyze with LLM'}
      </button>
      <button
        type="button"
        onClick={onDeepAnalyze}
        disabled={!canAnalyze || deepAnalyzing}
        title="Agentic analysis — the LLM pulls data step-by-step; slower, streamed live"
      >
        {deepAnalyzing ? 'Deep analyzing…' : 'Deep Analysis'}
      </button>
    </div>
  );
}
