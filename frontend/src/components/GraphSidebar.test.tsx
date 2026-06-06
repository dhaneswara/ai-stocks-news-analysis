import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphSidebar } from './GraphSidebar';
import type { ViewNode } from '../lib/graphView';
import type { RelationType, SavedGraphSummary } from '../types';

const SELECTED: ViewNode = {
  id: 'AAPL', label: 'AAPL', direction: 'sell', score: 80, sector: 'Tech', onBoard: true,
  network: { ticker: 'AAPL', intensity: 0.5, signed: -0.4, reasons: ['supplier TSM (bearish)'],
    influences: [{ neighbour: 'TSM', name: 'Taiwan Semi', type: 'supplier', edge_sentiment: 'negative',
      neighbour_direction: 'sell', signed: -0.4, reason: 'supplier TSM (bearish)' }] },
};

function base() {
  return {
    tab: 'explore' as const, onTab: vi.fn(),
    onLoadRoot: vi.fn(), onExpand: vi.fn(), onSave: vi.fn(), onClear: vi.fn(),
    canSave: true, saving: false, loading: false,
    saved: [] as SavedGraphSummary[], onLoadSaved: vi.fn(), onDeleteSaved: vi.fn(),
    nodeCount: 2, linkCount: 1,
    enabledTypes: new Set<RelationType>(['supplier']), onToggleType: vi.fn(),
  };
}

function wrap(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

it('starts a root from the input (Explore tab)', () => {
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

it('fires save and clear', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
  fireEvent.click(screen.getByRole('button', { name: /^clear$/i }));
  expect(props.onSave).toHaveBeenCalled();
  expect(props.onClear).toHaveBeenCalled();
});

it('switches to the Saved tab', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^saved/i }));
  expect(props.onTab).toHaveBeenCalledWith('saved');
});

it('lists saved graphs and fires load / delete (Saved tab)', () => {
  const props = { ...base(), tab: 'saved' as const, saved: [{ root: 'AAPL', versions: ['t2', 't1'] }] };
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
