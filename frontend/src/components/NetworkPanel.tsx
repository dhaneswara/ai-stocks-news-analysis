import type { NetworkSignal } from '../types';

export function NetworkPanel({ network }: { network?: NetworkSignal | null }) {
  if (!network || network.influences.length === 0) return null;
  return (
    <>
      <h4>Network influence 🔗</h4>
      <ul className="factor-list">
        {network.influences.map((inf, i) => {
          const lean = inf.signed > 0 ? 'bullish' : inf.signed < 0 ? 'bearish' : 'neutral';
          return (
            <li key={i}>
              <b>{inf.type} {inf.neighbour}</b>{inf.name ? ` (${inf.name})` : ''} — neighbour {inf.neighbour_direction},
              {' '}news {inf.edge_sentiment} → <span className={`badge ${lean === 'bullish' ? 'buy' : lean === 'bearish' ? 'sell' : 'hold'}`}>{lean}</span>
            </li>
          );
        })}
      </ul>
    </>
  );
}
