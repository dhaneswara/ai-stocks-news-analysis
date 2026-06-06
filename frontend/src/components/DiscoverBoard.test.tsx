import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DiscoverBoard } from './DiscoverBoard';
import type { StockScore } from '../types';

function row(extra: Partial<StockScore>): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0,
    score: 50, direction: 'hold', net: 0, reasons: ['RSI 50'], components: {}, as_of: 't',
    ...extra,
  };
}

it('shows a network badge only when a network signal is present', () => {
  const withNet = row({
    network: { ticker: 'AAPL', intensity: 0.5, signed: -0.3,
      influences: [], reasons: ['supplier TSM (bearish)'] },
  });
  render(<MemoryRouter><DiscoverBoard items={[withNet]} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.getByTitle(/company-network influence/i)).toBeInTheDocument();
});
