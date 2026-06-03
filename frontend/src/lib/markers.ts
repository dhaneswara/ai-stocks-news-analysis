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
      // Vivid, high-contrast marker colors that stand apart from the muted
      // candle bodies (up #5fd39b / down #f0817c) so buys aren't camouflaged.
      color: s.action === 'buy' ? '#00e676' : '#ff5252',
      shape: s.action === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${s.action.toUpperCase()} @ ${s.price}`,
    }));
}
