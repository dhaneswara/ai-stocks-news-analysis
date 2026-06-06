import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { TickerBar } from './TickerBar';

function setup(over: { watchlist?: string[]; current?: string } = {}) {
  const onSelect = vi.fn();
  const onAdd = vi.fn();
  const onRemove = vi.fn();
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
    />,
  );
  return { onSelect, onAdd, onRemove };
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

it('removes a chip via its × without also selecting it', () => {
  const { onRemove, onSelect } = setup({ watchlist: ['AAPL', 'MSFT'], current: '' });
  fireEvent.click(screen.getByRole('button', { name: /remove MSFT/i }));
  expect(onRemove).toHaveBeenCalledWith('MSFT');
  expect(onSelect).not.toHaveBeenCalled();
});

it('selects a ticker when its chip body is clicked', () => {
  const { onSelect } = setup({ watchlist: ['AAPL', 'MSFT'], current: '' });
  fireEvent.click(screen.getByText('MSFT'));
  expect(onSelect).toHaveBeenCalledWith('MSFT');
});

it('shows no star when no ticker is loaded', () => {
  setup({ current: '' });
  expect(screen.queryByRole('button', { name: /watchlist/i })).not.toBeInTheDocument();
});
