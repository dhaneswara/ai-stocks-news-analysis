import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphSidebar } from './GraphSidebar';
import type { ViewNode } from '../lib/graphView';
import type { ImportSetSummary, RelationType, SavedGraphSummary } from '../types';

const SELECTED: ViewNode = {
  id: 'AAPL', label: 'AAPL', direction: 'sell', score: 80, sector: 'Tech', onBoard: true, external: false, kind: '',
  network: { ticker: 'AAPL', intensity: 0.5, signed: -0.4, reasons: ['supplier TSM (bearish)'],
    influences: [{ neighbour: 'TSM', name: 'Taiwan Semi', type: 'supplier', edge_sentiment: 'negative',
      neighbour_direction: 'sell', signed: -0.4, reason: 'supplier TSM (bearish)' }] },
};

function base() {
  return {
    tab: 'explore' as const, onTab: vi.fn(),
    onLoadRoot: vi.fn(), onExpand: vi.fn(), onSave: vi.fn(), onClear: vi.fn(),
    canSave: true, saveAs: 'AAPL', saving: false, loading: false,
    saved: [] as SavedGraphSummary[], onLoadSaved: vi.fn(), onDeleteSaved: vi.fn(),
    nodeCount: 2, linkCount: 1,
    enabledTypes: new Set<RelationType>(['supplier']), onToggleType: vi.fn(),
    imports: [] as ImportSetSummary[],
    onImport: vi.fn(),
    onDeleteImport: vi.fn(),
    importing: false,
    importReport: null,
    importError: null,
    addingFrom: null as string | null,
    onSubmitRelationship: vi.fn(),
    onCancelRelationship: vi.fn(),
    onMergeImport: vi.fn(),
    promptDefault: 'AAPL',
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
  fireEvent.click(screen.getByRole('button', { name: /save as aapl/i }));
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

it('switches to the Import tab', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^import$/i }));
  expect(props.onTab).toHaveBeenCalledWith('import');
});

it('imports valid pasted JSON', () => {
  const props = { ...base(), tab: 'import' as const };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/paste.*json/i), {
    target: { value: '{"edges":[{"source":"AAPL","target":"NVDA","type":"partner"}]}' },
  });
  fireEvent.click(screen.getByRole('button', { name: /^import model$/i }));
  expect(props.onImport).toHaveBeenCalledWith(
    '', { edges: [{ source: 'AAPL', target: 'NVDA', type: 'partner' }] },
  );
});

it('shows an inline error for malformed JSON and does not call onImport', () => {
  const props = { ...base(), tab: 'import' as const };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/paste.*json/i), { target: { value: '{not json' } });
  fireEvent.click(screen.getByRole('button', { name: /^import model$/i }));
  expect(props.onImport).not.toHaveBeenCalled();
  expect(screen.getByText(/invalid json/i)).toBeInTheDocument();
});

it('lists import sets and fires delete', () => {
  const props = {
    ...base(), tab: 'import' as const,
    imports: [{ id: 't1', name: 'demo', as_of: '', created_at: 't1', node_count: 2, edge_count: 1 }],
  };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /delete demo/i }));
  expect(props.onDeleteImport).toHaveBeenCalledWith('t1');
});

it('submits an add-relationship form', () => {
  const props = { ...base(), addingFrom: 'AAPL' as string | null };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/ticker or company/i), { target: { value: 'NVDA' } });
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
  expect(props.onSubmitRelationship).toHaveBeenCalledWith(
    expect.objectContaining({ target: 'NVDA', type: 'supplier', sentiment: 'positive' }),
  );
});

it('fires merge for an import set (Import tab)', () => {
  const props = {
    ...base(), tab: 'import' as const,
    imports: [{ id: 't1', name: 'demo', as_of: '', created_at: 't1', node_count: 2, edge_count: 1 }],
  };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /merge demo/i }));
  expect(props.onMergeImport).toHaveBeenCalledWith('t1');
});
