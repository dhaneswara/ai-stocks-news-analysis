import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ScoreChip } from './ScoreChip';
import type { StockScore } from '../types';

function s(extra: Partial<StockScore> = {}): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0,
    score: 72, direction: 'buy', net: 0.3, reasons: ['RSI 28 (oversold)'], components: {}, as_of: 't',
    ...extra,
  };
}

it('renders score, call, and reasons', () => {
  render(<ScoreChip score={s()} />);
  expect(screen.getByText('72')).toBeInTheDocument();
  expect(screen.getByText('BUY')).toBeInTheDocument();
  expect(screen.getByText(/RSI 28/)).toBeInTheDocument();
});

it('shows the 🔗 network badge only when a network signal is present', () => {
  const { rerender } = render(<ScoreChip score={s()} />);
  expect(screen.queryByText('🔗')).not.toBeInTheDocument();
  rerender(<ScoreChip score={s({
    network: { ticker: 'AAPL', intensity: 0.5, signed: 0.3, influences: [], reasons: ['partner MSFT (bullish)'] },
  })} />);
  expect(screen.getByText('🔗')).toBeInTheDocument();
});
