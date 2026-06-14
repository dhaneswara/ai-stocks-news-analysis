import type { Signal } from '../types';

export interface ChartMarker {
  time: string;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

// lightweight-charts requires markers sorted by time ascending.
export function signalsToMarkers(
  signals: Signal[],
  colors: { buy: string; sell: string } = { buy: '#2bff9e', sell: '#ff3b6b' },
): ChartMarker[] {
  return [...signals]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((s) => ({
      time: s.date,
      position: s.action === 'buy' ? 'belowBar' : 'aboveBar',
      // Vivid markers stand apart from the muted candle bodies so buys aren't camouflaged.
      color: s.action === 'buy' ? colors.buy : colors.sell,
      shape: s.action === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${s.action.toUpperCase()} @ ${s.price}`,
    }));
}
