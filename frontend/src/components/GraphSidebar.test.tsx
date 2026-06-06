import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphSidebar } from './GraphSidebar';
import type { ViewNode } from '../lib/graphView';
import type { RelationType } from '../types';

const SELECTED: ViewNode = {
  id: 'AAPL', label: 'AAPL', direction: 'sell', score: 80, sector: 'Tech', onBoard: true,
  network: { ticker: 'AAPL', intensity: 0.5, signed: -0.4, reasons: ['supplier TSM (bearish)'],
    influences: [{ neighbour: 'TSM', name: 'Taiwan Semi', type: 'supplier', edge_sentiment: 'negative',
      neighbour_direction: 'sell', signed: -0.4, reason: 'supplier TSM (bearish)' }] },
};

function base() {
  return {
    asOf: '2026-06-06', built: 1, skipped: 0, nodeCount: 2, linkCount: 1,
    sectors: ['Tech'], sector: '', onSector: vi.fn(),
    enabledTypes: new Set<RelationType>(['supplier']), onToggleType: vi.fn(),
    onRebuild: vi.fn(), rebuilding: false,
  };
}

function wrap(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

it('shows the legend hint when nothing is selected', () => {
  wrap(<GraphSidebar {...base()} selected={null} />);
  expect(screen.getByText(/click a node/i)).toBeInTheDocument();
});

it('shows the selected node detail and a Dashboard link', () => {
  wrap(<GraphSidebar {...base()} selected={SELECTED} />);
  expect(screen.getByText('AAPL')).toBeInTheDocument();
  expect(screen.getByText(/supplier TSM/i)).toBeInTheDocument();
  const link = screen.getByRole('link', { name: /open in dashboard/i });
  expect(link).toHaveAttribute('href', expect.stringContaining('ticker=AAPL'));
});

it('fires rebuild', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /rebuild graph/i }));
  expect(props.onRebuild).toHaveBeenCalled();
});

it('toggling an edge-type fires onToggleType', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /competitor/i }));
  expect(props.onToggleType).toHaveBeenCalledWith('competitor');
});
