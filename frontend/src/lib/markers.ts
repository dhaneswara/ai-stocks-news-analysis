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
      color: s.action === 'buy' ? '#5fd39b' : '#f0817c',
      shape: s.action === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${s.action.toUpperCase()} @ ${s.price}`,
    }));
}
