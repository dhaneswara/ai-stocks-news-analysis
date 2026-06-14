import type { Signal } from '../types';

export interface ChartMarker {
  time: string;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

// lightweight-charts requires markers sorted by time ascending.
export function signalsToMarkers(signals: Signal[]): ChartMarker[] {
  return [...signals]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((s) => ({
      time: s.date,
      position: s.action === 'buy' ? 'belowBar' : 'aboveBar',
      // Vivid neon marker colors that stand apart from the muted candle
      // bodies (up #27c98b / down #e0517a) so buys aren't camouflaged.
      color: s.action === 'buy' ? '#2bff9e' : '#ff3b6b',
      shape: s.action === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${s.action.toUpperCase()} @ ${s.price}`,
    }));
}
