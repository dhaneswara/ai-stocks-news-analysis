import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SignalsStrip } from './SignalsStrip';
import type { SignalsSummary, StockScore } from '../types';

function score(extra: Partial<StockScore> = {}): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0,
    score: 72, direction: 'buy', net: 0.3, reasons: ['RSI 28 (oversold)'], components: {}, as_of: 't',
    ...extra,
  };
}

function signals(extra: Partial<SignalsSummary> = {}): SignalsSummary {
  return {
    ticker: 'AAPL',
    sources: {
      technical: {
        latest: { call_date: '2026-06-09', recommendation: 'buy', confidence: 0.4 },
        track: { n_calls: 4, n_matured: 3, hit_rate: 66.7, avg_score: 61.2, grade: 'Mixed' },
      },
      llm_fast: {
        latest: { call_date: '2026-06-09', recommendation: 'sell', confidence: 0.7 },
        track: { n_calls: 2, n_matured: 0, hit_rate: null, avg_score: null, grade: null },
      },
    },
    agreement: { counted: 2, agreeing: 1, on: 'buy', conflict: true },
    winner: 'technical',
    ...extra,
  };
}

it('renders the score, one chip per source, and dashes for absent sources', () => {
  render(<SignalsStrip score={score()} signals={signals()} />);
  expect(screen.getByText('72')).toBeInTheDocument();
  expect(screen.getByText(/TECH/)).toBeInTheDocument();
  expect(screen.getByText('▲ BUY')).toBeInTheDocument();
  expect(screen.getByText('▼ SELL')).toBeInTheDocument();
  expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2); // NET + DEEP absent
});

it('crowns the winner and flags conflict', () => {
  render(<SignalsStrip score={score()} signals={signals()} />);
  expect(screen.getByText(/👑/)).toBeInTheDocument();
  expect(screen.getByText(/1\/2 lean BUY/)).toBeInTheDocument();
});

it('shows the 🔗 network badge only when the score has a network signal', () => {
  const { rerender } = render(<SignalsStrip score={score()} signals={signals()} />);
  expect(screen.queryByText('🔗')).not.toBeInTheDocument();
  rerender(<SignalsStrip
    score={score({ network: { ticker: 'AAPL', intensity: 0.5, signed: 0.3, influences: [], reasons: ['partner MSFT (bullish)'] } })}
    signals={signals()}
  />);
  expect(screen.getByText('🔗')).toBeInTheDocument();
});

it('renders without signals data (score only)', () => {
  render(<SignalsStrip score={score()} />);
  expect(screen.getByText('72')).toBeInTheDocument();
});

it('renders hold calls with a distinct glyph from absent sources', () => {
  render(<SignalsStrip score={score()} signals={signals({
    sources: {
      network: {
        latest: { call_date: '2026-06-09', recommendation: 'hold', confidence: 0.1 },
        track: { n_calls: 1, n_matured: 0, hit_rate: null, avg_score: null, grade: null },
      },
    },
  })} />);
  expect(screen.getByText('■ HOLD')).toBeInTheDocument();
  expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3); // TECH/FAST/DEEP absent
});
