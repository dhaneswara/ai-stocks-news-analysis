import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { GraphSearch } from './GraphSearch';
import type { ViewNode } from '../lib/graphView';

const vn = (id: string, label = id): ViewNode => ({
  id, label, direction: 'unknown', score: 0, sector: '', onBoard: false, external: false, kind: '',
});
const NODES = [vn('AAPL', 'Apple'), vn('TSM', 'TSMC'), vn('ext:openai', 'OpenAI')];

it('lists matches by ticker or name and picks on click', () => {
  const onPick = vi.fn();
  render(<GraphSearch nodes={NODES} onPick={onPick} />);
  const input = screen.getByLabelText('find node');
  fireEvent.change(input, { target: { value: 'open' } });
  fireEvent.click(screen.getByRole('button', { name: /openai/i }));
  expect(onPick).toHaveBeenCalledWith('ext:openai');
  expect(input).toHaveValue('');   // cleared after a pick
});

it('Enter picks the top match; Escape clears the query', () => {
  const onPick = vi.fn();
  render(<GraphSearch nodes={NODES} onPick={onPick} />);
  const input = screen.getByLabelText('find node');
  fireEvent.change(input, { target: { value: 'aapl' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(onPick).toHaveBeenCalledWith('AAPL');
  fireEvent.change(input, { target: { value: 'tsm' } });
  fireEvent.keyDown(input, { key: 'Escape' });
  expect(input).toHaveValue('');
});

it('shows a no-matches note', () => {
  render(<GraphSearch nodes={NODES} onPick={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('find node'), { target: { value: 'zzz' } });
  expect(screen.getByText(/no matches/i)).toBeInTheDocument();
});
