import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WatchlistMenu } from './WatchlistMenu';

function setup(over: { watchlist?: string[]; current?: string } = {}) {
  const onSelect = vi.fn();
  const onRemove = vi.fn();
  render(
    <WatchlistMenu
      watchlist={over.watchlist ?? ['AAPL', 'MSFT', 'NVDA']}
      current={over.current ?? 'AAPL'}
      onSelect={onSelect}
      onRemove={onRemove}
    />,
  );
  return { onSelect, onRemove };
}

const toggle = () => screen.getByRole('button', { name: /watchlist \(/i });

it('shows the count and is closed by default', () => {
  setup();
  expect(toggle()).toHaveTextContent('Watchlist (3)');
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it('opens, filters, and selects a ticker (closing the menu)', () => {
  const { onSelect } = setup();
  fireEvent.click(toggle());
  fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: 'nv' } });
  expect(screen.queryByRole('option', { name: /AAPL/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('option', { name: /NVDA/ }));
  expect(onSelect).toHaveBeenCalledWith('NVDA');
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it('removes a ticker via × without selecting or closing', () => {
  const { onSelect, onRemove } = setup();
  fireEvent.click(toggle());
  fireEvent.click(screen.getByRole('button', { name: /remove MSFT/i }));
  expect(onRemove).toHaveBeenCalledWith('MSFT');
  expect(onSelect).not.toHaveBeenCalled();
  expect(screen.getByRole('listbox')).toBeInTheDocument();
});

it('closes on Escape', () => {
  setup();
  fireEvent.click(toggle());
  expect(screen.getByRole('listbox')).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it('disables the toggle when the watchlist is empty', () => {
  setup({ watchlist: [] });
  expect(screen.getByRole('button', { name: /watchlist \(0\)/i })).toBeDisabled();
});
