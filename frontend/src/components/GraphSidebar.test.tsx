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
    root: '', onLoadRoot: vi.fn(), onExpand: vi.fn(), onLoadFocus: vi.fn(),
    onRebuild: vi.fn(), rebuilding: false, loading: false,
    canSave: true, onSave: vi.fn(), saving: false,
    saved: [], onLoadSaved: vi.fn(), onDeleteSaved: vi.fn(),
    nodeCount: 2, linkCount: 1,
    sectors: ['Tech'], sector: '', onSector: vi.fn(),
    enabledTypes: new Set<RelationType>(['supplier']), onToggleType: vi.fn(),
  };
}

function wrap(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

it('starts a root from the input', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/ticker/i), { target: { value: 'tsla' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  expect(props.onLoadRoot).toHaveBeenCalledWith('tsla');
});

it('shows the legend hint when nothing is selected', () => {
  wrap(<GraphSidebar {...base()} selected={null} />);
  expect(screen.getByText(/click a node/i)).toBeInTheDocument();
});

it('expands the selected node', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={SELECTED} />);
  fireEvent.click(screen.getByRole('button', { name: /expand neighbours/i }));
  expect(props.onExpand).toHaveBeenCalledWith('AAPL');
});

it('shows the selected node detail and a Dashboard link', () => {
  wrap(<GraphSidebar {...base()} selected={SELECTED} />);
  expect(screen.getByText(/supplier TSM/i)).toBeInTheDocument();
  const link = screen.getByRole('link', { name: /open in dashboard/i });
  expect(link).toHaveAttribute('href', expect.stringContaining('ticker=AAPL'));
});

it('fires save / load-focus', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /save graph/i }));
  fireEvent.click(screen.getByRole('button', { name: /load focus set/i }));
  expect(props.onSave).toHaveBeenCalled();
  expect(props.onLoadFocus).toHaveBeenCalled();
});

it('lists saved graphs and fires load / delete', () => {
  const props = { ...base(), saved: [{ root: 'AAPL', versions: ['t2', 't1'] }] };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^load AAPL$/i }));
  expect(props.onLoadSaved).toHaveBeenCalledWith('AAPL', undefined);
  fireEvent.click(screen.getByRole('button', { name: /delete AAPL/i }));
  expect(props.onDeleteSaved).toHaveBeenCalledWith('AAPL', undefined);
});

it('toggling an edge-type fires onToggleType', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /competitor/i }));
  expect(props.onToggleType).toHaveBeenCalledWith('competitor');
});
