import { expect, it } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ScoreBoard } from './ScoreBoard';
import type { StockScore } from '../types';

function row(extra: Partial<StockScore>): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
    price: 1, change_pct: 0, score: 50, direction: 'hold', net: 0,
    reasons: ['RSI 50'], components: {}, as_of: 't', ...extra,
  };
}

it('renders exchange and an S&P/Custom membership badge', () => {
  const items = [row({}), row({ ticker: 'PRIV', name: 'Private Co', in_sp500: false, exchange: 'NYSE' })];
  render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.getByText('NASDAQ')).toBeInTheDocument();
  expect(screen.getByTitle(/S&P 500 member/i)).toBeInTheDocument();
  expect(screen.getByTitle(/not in the s&p 500/i)).toBeInTheDocument();
});

it('filters rows by the search box (ticker or company name)', () => {
  const items = [row({}), row({ ticker: 'TSLA', name: 'Tesla' })];
  render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} /></MemoryRouter>);
  fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'tesla' } });
  expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
  expect(screen.getByText('TSLA')).toBeInTheDocument();
});

it('shows the network badge only when a network signal is present', () => {
  const withNet = row({ network: { ticker: 'AAPL', intensity: 0.5, signed: -0.3, influences: [], reasons: ['x'] } });
  render(<MemoryRouter><ScoreBoard items={[withNet]} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.getByTitle(/company-network influence/i)).toBeInTheDocument();
});

it('renders a remove (×) button only for custom rows when onRemove is given', () => {
  const items = [row({}), row({ ticker: 'PRIV', in_sp500: false })];
  render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} onRemove={() => {}} /></MemoryRouter>);
  expect(screen.getAllByTitle(/remove this custom company/i)).toHaveLength(1);
});
