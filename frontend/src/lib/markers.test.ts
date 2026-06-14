import { describe, expect, it } from 'vitest';
import { signalsToMarkers } from './markers';
import type { Signal } from '../types';

const signals: Signal[] = [
  { date: '2026-05-10', action: 'sell', price: 200, confidence: 0.6, reasoning: 'x' },
  { date: '2026-04-01', action: 'buy', price: 150, confidence: 0.7, reasoning: 'y' },
];

describe('signalsToMarkers', () => {
  it('sorts by date ascending', () => {
    const m = signalsToMarkers(signals);
    expect(m.map((x) => x.time)).toEqual(['2026-04-01', '2026-05-10']);
  });

  it('maps buy below-bar arrowUp and sell above-bar arrowDown', () => {
    const m = signalsToMarkers(signals);
    const buy = m.find((x) => x.time === '2026-04-01')!;
    const sell = m.find((x) => x.time === '2026-05-10')!;
    expect(buy.position).toBe('belowBar');
    expect(buy.shape).toBe('arrowUp');
    expect(sell.position).toBe('aboveBar');
    expect(sell.shape).toBe('arrowDown');
  });

  it('does not mutate the input array order', () => {
    const copy = [...signals];
    signalsToMarkers(signals);
    expect(signals).toEqual(copy);
  });

  it('uses provided colors for buy/sell markers', () => {
    const signals = [
      { date: '2024-01-02', action: 'buy', price: 10, reason: 'x' },
      { date: '2024-01-03', action: 'sell', price: 11, reason: 'y' },
    ] as unknown as Parameters<typeof signalsToMarkers>[0];
    const markers = signalsToMarkers(signals, { buy: '#111111', sell: '#222222' });
    expect(markers.find((m) => m.text.startsWith('BUY'))?.color).toBe('#111111');
    expect(markers.find((m) => m.text.startsWith('SELL'))?.color).toBe('#222222');
  });
});
