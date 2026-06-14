import { expect, it, vi } from 'vitest';
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

it('shows a filled ★ for watched rows and a hollow ☆ otherwise (case-insensitive)', () => {
  const items = [row({ ticker: 'AAPL' }), row({ ticker: 'TSLA', name: 'Tesla' })];
  render(
    <MemoryRouter>
      <ScoreBoard items={items} onAdd={() => {}} watched={['aapl']} onUnwatch={() => {}} />
    </MemoryRouter>,
  );
  expect(screen.getByTitle(/remove AAPL from watchlist/i)).toHaveTextContent('★');
  expect(screen.getByTitle(/add TSLA to watchlist/i)).toHaveTextContent('☆');
});

it('routes a ☆ click to onAdd and a ★ click to onUnwatch', () => {
  const onAdd = vi.fn();
  const onUnwatch = vi.fn();
  const items = [row({ ticker: 'AAPL' }), row({ ticker: 'TSLA', name: 'Tesla' })];
  render(
    <MemoryRouter>
      <ScoreBoard items={items} onAdd={onAdd} watched={['AAPL']} onUnwatch={onUnwatch} />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByTitle(/add TSLA to watchlist/i));
  fireEvent.click(screen.getByTitle(/remove AAPL from watchlist/i));
  expect(onAdd).toHaveBeenCalledWith('TSLA');
  expect(onUnwatch).toHaveBeenCalledWith('AAPL');
});

it('renders a ⟳ rescan button per row only when onRescan is given', () => {
  const items = [row({})];
  const { rerender } = render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.queryByTitle(/rescan AAPL/i)).not.toBeInTheDocument();
  rerender(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} onRescan={() => {}} /></MemoryRouter>);
  expect(screen.getByTitle(/rescan AAPL/i)).toBeInTheDocument();
});

it('calls onRescan with the ticker when ⟳ is clicked', () => {
  const onRescan = vi.fn();
  render(<MemoryRouter><ScoreBoard items={[row({})]} onAdd={() => {}} onRescan={onRescan} /></MemoryRouter>);
  fireEvent.click(screen.getByTitle(/rescan AAPL/i));
  expect(onRescan).toHaveBeenCalledWith('AAPL');
});

it('disables the ⟳ for the row currently being rescanned', () => {
  render(
    <MemoryRouter>
      <ScoreBoard items={[row({})]} onAdd={() => {}} onRescan={() => {}} rescanning="AAPL" />
    </MemoryRouter>,
  );
  expect(screen.getByTitle(/rescanning AAPL/i)).toBeDisabled();
});
