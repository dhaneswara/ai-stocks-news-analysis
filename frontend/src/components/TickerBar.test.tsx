import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { TickerBar } from './TickerBar';

function setup(over: { watchlist?: string[]; current?: string } = {}) {
  const onSelect = vi.fn();
  const onAdd = vi.fn();
  const onRemove = vi.fn();
  const onDeepAnalyze = vi.fn();
  render(
    <TickerBar
      watchlist={over.watchlist ?? ['AAPL', 'MSFT']}
      current={over.current ?? 'AAPL'}
      onSelect={onSelect}
      onAdd={onAdd}
      onRemove={onRemove}
      onAnalyze={vi.fn()}
      analyzing={false}
      canAnalyze
      onDeepAnalyze={onDeepAnalyze}
      deepAnalyzing={false}
    />,
  );
  return { onSelect, onAdd, onRemove, onDeepAnalyze };
}

it('adds the current ticker when it is not yet in the watchlist', () => {
  const { onAdd } = setup({ current: 'TSLA', watchlist: ['AAPL'] });
  fireEvent.click(screen.getByRole('button', { name: /add to watchlist/i }));
  expect(onAdd).toHaveBeenCalledWith('TSLA');
});

it('removes the current ticker when it is already in the watchlist', () => {
  const { onRemove } = setup({ current: 'AAPL', watchlist: ['AAPL'] });
  fireEvent.click(screen.getByRole('button', { name: /remove from watchlist/i }));
  expect(onRemove).toHaveBeenCalledWith('AAPL');
});

it('shows no star when no ticker is loaded', () => {
  setup({ current: '' });
  expect(
    screen.queryByRole('button', { name: /add to watchlist|remove from watchlist/i }),
  ).not.toBeInTheDocument();
});

it('renders the collapsible watchlist toggle with a count', () => {
  setup({ watchlist: ['AAPL', 'MSFT'], current: 'AAPL' });
  expect(screen.getByRole('button', { name: /watchlist \(2\)/i })).toBeInTheDocument();
});

it('fires onDeepAnalyze when the Deep Analysis button is clicked', () => {
  const onDeepAnalyze = vi.fn();
  render(
    <TickerBar
      watchlist={['AAPL']} current="AAPL"
      onSelect={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()}
      onAnalyze={vi.fn()} analyzing={false} canAnalyze
      onDeepAnalyze={onDeepAnalyze} deepAnalyzing={false}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: /deep analysis/i }));
  expect(onDeepAnalyze).toHaveBeenCalled();
});

it('renders the Deep Analysis button as a solid-gold (non-secondary) button', () => {
  setup();
  const deep = screen.getByRole('button', { name: /deep analysis/i });
  expect(deep).not.toHaveClass('secondary');
});
