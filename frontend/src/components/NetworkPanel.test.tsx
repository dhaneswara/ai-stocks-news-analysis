import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NetworkPanel } from './NetworkPanel';
import type { NetworkSignal } from '../types';

const NET: NetworkSignal = {
  ticker: 'AAPL', intensity: 0.5, signed: -0.4,
  influences: [{ neighbour: 'TSM', name: 'Taiwan Semi', type: 'supplier',
    edge_sentiment: 'negative', neighbour_direction: 'sell', signed: -0.4, reason: 'supplier TSM (bearish)' }],
  reasons: ['supplier TSM (bearish)'],
};

it('renders nothing without a signal', () => {
  const { container } = render(<NetworkPanel network={null} />);
  expect(container).toBeEmptyDOMElement();
});

it('lists neighbour influences', () => {
  render(<NetworkPanel network={NET} />);
  expect(screen.getByText(/Network influence/i)).toBeInTheDocument();
  expect(screen.getByText(/TSM/)).toBeInTheDocument();
});
