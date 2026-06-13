import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphSidebar } from './GraphSidebar';
import type { ViewNode } from '../lib/graphView';
import type { ImportSetSummary, OntologySummary, RelationType } from '../types';

const SELECTED: ViewNode = {
  id: 'AAPL', label: 'AAPL', direction: 'sell', score: 80, sector: 'Tech', onBoard: true, external: false, kind: '',
  network: { ticker: 'AAPL', intensity: 0.5, signed: -0.4, reasons: ['supplier TSM (bearish)'],
    influences: [{ neighbour: 'TSM', name: 'Taiwan Semi', type: 'supplier', edge_sentiment: 'negative',
      neighbour_direction: 'sell', signed: -0.4, reason: 'supplier TSM (bearish)' }] },
};

function base() {
  return {
    tab: 'explore' as const, onTab: vi.fn(),
    onExpand: vi.fn(), loading: false,
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
    addingCompany: false,
    onSubmitCompany: vi.fn(),
    onCancelCompany: vi.fn(),
    onStartAddCompany: vi.fn(),
    renaming: null as { id: string; label: string } | null,
    onSubmitRename: vi.fn(),
    onCancelRename: vi.fn(),
    onStartRename: vi.fn(),
    onMergeImport: vi.fn(),
    promptDefault: 'AAPL',
    ontologies: [] as OntologySummary[],
    activeName: null as string | null,
    onLoadOntology: vi.fn(),
    onDeleteOntology: vi.fn(),
    onActivate: vi.fn(),
    watchlist: [] as string[],
    onToggleWatch: vi.fn(),
  };
}

function wrap(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

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

it('rename form prefills from the node and submits ticker + name', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} renaming={{ id: 'ext:tsmc', label: 'TSMC' }} />);
  expect(screen.getByLabelText('rename ticker')).toHaveValue('');     // ext: id → no ticker prefill
  expect(screen.getByLabelText('rename name')).toHaveValue('TSMC');
  fireEvent.change(screen.getByLabelText('rename ticker'), { target: { value: 'TSM' } });
  fireEvent.click(screen.getByRole('button', { name: /^rename$/i }));
  expect(props.onSubmitRename).toHaveBeenCalledWith({ ticker: 'TSM', label: 'TSMC' });
});

it('the standing Rename… starts a rename for the selected node, disabled without one', () => {
  const props = base();
  const view = wrap(<GraphSidebar {...props} selected={null} />);
  expect(screen.getByRole('button', { name: /rename…/i })).toBeDisabled();
  view.unmount();
  wrap(<GraphSidebar {...props} selected={SELECTED} />);
  fireEvent.click(screen.getByRole('button', { name: /rename…/i }));
  expect(props.onStartRename).toHaveBeenCalledWith('AAPL');
});

it('shows the selected node detail and a Dashboard link', () => {
  wrap(<GraphSidebar {...base()} selected={SELECTED} />);
  expect(screen.getByText(/supplier TSM/i)).toBeInTheDocument();
  const link = screen.getByRole('link', { name: /open in dashboard/i });
  expect(link).toHaveAttribute('href', expect.stringContaining('ticker=AAPL'));
});

it('switches to the Ontologies tab', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^ontologies/i }));
  expect(props.onTab).toHaveBeenCalledWith('saved');
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

it('the Import tab copy button reads "Copy LLM prompt"', () => {
  const props = { ...base(), tab: 'import' as const };
  wrap(<GraphSidebar {...props} selected={null} />);
  expect(screen.getByRole('button', { name: /copy llm prompt/i })).toBeInTheDocument();
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

it('the standing Add company… button fires onStartAddCompany', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^add company…$/i }));
  expect(props.onStartAddCompany).toHaveBeenCalled();
});

it('renders the company form when addingCompany=true, submits and cancels', () => {
  const props = { ...base(), addingCompany: true };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/ticker.*tsm/i), { target: { value: 'tsm' } });
  fireEvent.change(screen.getByPlaceholderText(/name.*optional/i), { target: { value: 'TSMC' } });
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
  expect(props.onSubmitCompany).toHaveBeenCalledWith({ ticker: 'tsm', label: 'TSMC' });

  // reset and test Cancel
  fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
  expect(props.onCancelCompany).toHaveBeenCalled();
});

it('Ontologies tab: lists ontologies, active badge, Set active, load, delete', () => {
  const ontos: OntologySummary[] = [
    { name: 'A', versions: ['t1'], node_count: 3, edge_count: 2, active: false },
    { name: 'B', versions: ['t1', 't2'], node_count: 1, edge_count: 0, active: true },
  ];
  const props = { ...base(), tab: 'saved' as const, ontologies: ontos, activeName: 'B' };
  wrap(<GraphSidebar {...props} selected={null} />);

  // Row A: stats, Set active, load, delete
  expect(screen.getByText('3n · 2e')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /^load A$/i }));
  expect(props.onLoadOntology).toHaveBeenCalledWith('A');

  fireEvent.click(screen.getByRole('button', { name: /delete A/i }));
  expect(props.onDeleteOntology).toHaveBeenCalledWith('A');

  // Row A has Set active (not ACTIVE badge); click it
  // The "None" row also has Set active (activeName='B'), so collect all and find A's row button
  // None row comes first, then A row, then B row (ACTIVE badge).
  // getAllByRole returns them in DOM order: None's "Set active" first, then A's "Set active".
  const setActiveButtons = screen.getAllByRole('button', { name: /^set active$/i });
  // index 0 = None row, index 1 = row A
  fireEvent.click(setActiveButtons[1]);
  expect(props.onActivate).toHaveBeenCalledWith('A');

  // Row B: ACTIVE badge, no Set active for B
  expect(screen.getByText('ACTIVE')).toBeInTheDocument();

  // None row: activeName is 'B' (not null), so "None" row shows "Set active" not ACTIVE
  fireEvent.click(setActiveButtons[0]);
  expect(props.onActivate).toHaveBeenCalledWith(null);
});

it('shows ☆ Add to watchlist when company node selected and not in watchlist', () => {
  const props = { ...base(), watchlist: [] as string[], onToggleWatch: vi.fn() };
  wrap(<GraphSidebar {...props} selected={SELECTED} />);
  const btn = screen.getByRole('button', { name: /☆ Add to watchlist/i });
  expect(btn).toBeInTheDocument();
  fireEvent.click(btn);
  expect(props.onToggleWatch).toHaveBeenCalledWith('AAPL');
});

it('shows ★ Remove from watchlist when company node is already in watchlist', () => {
  const props = { ...base(), watchlist: ['AAPL'], onToggleWatch: vi.fn() };
  wrap(<GraphSidebar {...props} selected={SELECTED} />);
  const btn = screen.getByRole('button', { name: /★ Remove from watchlist/i });
  expect(btn).toBeInTheDocument();
  fireEvent.click(btn);
  expect(props.onToggleWatch).toHaveBeenCalledWith('AAPL');
});

it('shows no watchlist button when a concept node (man: prefix) is selected', () => {
  const conceptNode: ViewNode = {
    ...SELECTED, id: 'man:ai-chip', label: 'AI Chip',
  };
  const props = { ...base(), watchlist: [] as string[], onToggleWatch: vi.fn() };
  wrap(<GraphSidebar {...props} selected={conceptNode} />);
  expect(screen.queryByText(/watchlist/i)).not.toBeInTheDocument();
});
