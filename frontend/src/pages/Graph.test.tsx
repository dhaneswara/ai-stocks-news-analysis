import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import Graph from './Graph';
import type { KnowledgeGraph, ScreenBoard, Settings } from '../types';

// Canvas can't render in jsdom — mock it; render a select button per node so tests can select.
vi.mock('../components/GraphCanvas', () => ({
  GraphCanvas: ({ nodes, onSelect, onDeleteNode, onAddRelationship, onAddCompany }: {
    nodes: { id: string; score?: number }[]; onSelect: (id: string) => void;
    onDeleteNode: (id: string) => void; onAddRelationship: (id: string) => void;
    onAddCompany: () => void;
    watchlist: string[]; onToggleWatch: (id: string) => void;
  }) => (
    <div data-testid="graph-canvas">
      {nodes.map((n) => <button key={n.id} data-score={n.score} onClick={() => onSelect(n.id)}>{`sel-${n.id}`}</button>)}
      {nodes.map((n) => <button key={`del-${n.id}`} onClick={() => onDeleteNode(n.id)}>{`del-${n.id}`}</button>)}
      {nodes.map((n) => <button key={`add-${n.id}`} onClick={() => onAddRelationship(n.id)}>{`add-${n.id}`}</button>)}
      <button onClick={onAddCompany}>canvas-add-company</button>
    </div>
  ),
}));
vi.mock('../api/client', () => ({
  api: {
    getScreen: vi.fn(),
    getCompanyGraph: vi.fn(),
    listImports: vi.fn(),
    importGraph: vi.fn(),
    deleteImport: vi.fn(),
    getImportSet: vi.fn(),
    listOntologies: vi.fn(),
    saveOntology: vi.fn(),
    loadOntology: vi.fn(),
    deleteOntology: vi.fn(),
    getActiveOntology: vi.fn(),
    setActiveOntology: vi.fn(),
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
  },
}));
import { api } from '../api/client';
vi.mock('../lib/download', () => ({ downloadText: vi.fn() }));
import { downloadText } from '../lib/download';

const BOARD: ScreenBoard = { as_of: 't', scope: 'all', scanned: 0, skipped: 0, items: [] };
const SETTINGS: Settings = {
  active_provider: 'anthropic', providers: {}, watchlist: [],
  indicator_params: { sma_windows: [50, 200], rsi_length: 14 },
  alerts: { enabled: false, channel: 'log', telegram_bot_token: '', telegram_chat_id: '', rsi_low: 30, rsi_high: 70 },
  truth_signal: { enabled: true, source_url: '', lookback_hours: 48 },
  screener: { enabled: true, top_n: 25, default_sector: null, rsi_low: 30, rsi_high: 70, weights: {} },
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4, symmetric_types: ['competitor', 'partner', 'other'] },
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
};
const AAPL_GRAPH: KnowledgeGraph = {
  as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0, nodes: ['AAPL', 'TSM'],
  edges: [{ source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' }],
};
const TSM_GRAPH: KnowledgeGraph = {
  as_of: 't', scope: 'company:TSM', built: 1, skipped: 0, nodes: ['TSM', 'FOO'],
  edges: [{ source: 'TSM', target: 'FOO', type: 'customer', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' }],
};

function renderGraph() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Graph /></MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Seed the canvas the way users do now: the add-company form (sidebar button works canvas or no canvas). */
async function addCompany(ticker: string) {
  fireEvent.click(await screen.findByRole('button', { name: /^add company…$/i }));
  fireEvent.change(screen.getByPlaceholderText(/ticker.*tsm/i), { target: { value: ticker } });
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
  await screen.findByTestId('graph-canvas');
}

beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(api.getScreen).mockResolvedValue(BOARD);
  vi.mocked(api.listImports).mockResolvedValue([]);
  vi.mocked(api.listOntologies).mockResolvedValue([]);
  vi.mocked(api.getActiveOntology).mockResolvedValue({ name: null });
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS as never);
  vi.mocked(api.saveSettings).mockImplementation(async (s) => s as never);
});

it('shows the empty-state CTA and opens the add-company form', async () => {
  renderGraph();
  fireEvent.click(await screen.findByRole('button', { name: /add a company/i }));
  expect(screen.getByPlaceholderText(/ticker.*tsm/i)).toBeInTheDocument();
});

it('adds the first company and renders the canvas', async () => {
  renderGraph();
  await addCompany('AAPL');
  expect(screen.getByTestId('graph-canvas')).toBeInTheDocument();
  expect(screen.getByText(/1 nodes/)).toBeInTheDocument();
});

it('expands a selected node and grows the graph', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValueOnce(AAPL_GRAPH).mockResolvedValueOnce(TSM_GRAPH);
  renderGraph();
  await addCompany('AAPL');
  // the new node is auto-selected — Expand neighbours runs the news extraction
  fireEvent.click(await screen.findByRole('button', { name: /expand neighbours/i }));
  await waitFor(() => expect(screen.getByText(/2 nodes/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'sel-TSM' }));
  fireEvent.click(screen.getByRole('button', { name: /expand neighbours/i }));
  await waitFor(() => expect(screen.getByText(/3 nodes/)).toBeInTheDocument());
});

it('saves the working graph as a named ontology', async () => {
  vi.mocked(api.saveOntology).mockResolvedValue({ name: 'Tech', saved_at: 't', expanded: [], graph: AAPL_GRAPH });
  renderGraph();
  await addCompany('AAPL');
  fireEvent.change(screen.getByRole('textbox', { name: /ontology name/i }), { target: { value: 'Tech' } });
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
  await waitFor(() => expect(api.saveOntology).toHaveBeenCalledWith(expect.objectContaining({ name: 'Tech' })));
});

it('exports the working graph as JSON via the Export button', async () => {
  renderGraph();
  await addCompany('AAPL');
  fireEvent.change(screen.getByRole('textbox', { name: /ontology name/i }), { target: { value: 'Tech' } });
  fireEvent.click(screen.getByRole('button', { name: /^export$/i }));
  expect(downloadText).toHaveBeenCalledWith('tech.json', expect.stringContaining('"AAPL"'));
});

it('surfaces a load error when extraction fails', async () => {
  vi.mocked(api.getCompanyGraph).mockRejectedValue(new Error('boom'));
  renderGraph();
  await addCompany('AAPL');
  fireEvent.click(await screen.findByRole('button', { name: /expand neighbours/i }));
  expect(await screen.findByText(/couldn't load: boom/i)).toBeInTheDocument();
});

it('restores the explored graph after remount (persistence)', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  const first = renderGraph();
  await addCompany('AAPL');
  fireEvent.click(await screen.findByRole('button', { name: /expand neighbours/i }));
  await waitFor(() => expect(screen.getByText(/2 nodes/)).toBeInTheDocument());
  first.unmount();
  vi.mocked(api.getCompanyGraph).mockClear();
  renderGraph();
  expect(await screen.findByTestId('graph-canvas')).toBeInTheDocument();
  expect(screen.getByText(/2 nodes/)).toBeInTheDocument();
  expect(api.getCompanyGraph).not.toHaveBeenCalled(); // restored from storage, no refetch
});

it('switches back to the Explore tab when a node is selected', async () => {
  renderGraph();
  await addCompany('AAPL');
  fireEvent.click(screen.getByRole('button', { name: /^ontologies/i })); // go to Ontologies tab
  expect(screen.queryByRole('button', { name: /expand neighbours/i })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'sel-AAPL' })); // select a node on the canvas
  expect(await screen.findByRole('button', { name: /expand neighbours/i })).toBeInTheDocument();
});

it('deletes a node from the working graph', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  await addCompany('AAPL');
  fireEvent.click(await screen.findByRole('button', { name: /expand neighbours/i }));
  await waitFor(() => expect(screen.getByText(/2 nodes/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'del-TSM' }));
  await waitFor(() => expect(screen.getByText(/1 nodes/)).toBeInTheDocument());
});

it('adds a manual relationship via the form', async () => {
  renderGraph();
  await addCompany('AAPL');
  fireEvent.click(screen.getByRole('button', { name: 'add-AAPL' }));
  fireEvent.change(await screen.findByPlaceholderText(/ticker or company/i), { target: { value: 'BIDU' } });
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
  await waitFor(() => expect(screen.getByText(/2 nodes/)).toBeInTheDocument());
});

it('boots into the active ontology when nothing restored', async () => {
  vi.mocked(api.getActiveOntology).mockResolvedValue({ name: 'Tech' });
  vi.mocked(api.loadOntology).mockResolvedValue({ name: 'Tech', saved_at: 't', expanded: [], graph: AAPL_GRAPH });
  renderGraph();
  expect(await screen.findByDisplayValue('Tech')).toBeInTheDocument();
  expect(api.loadOntology).toHaveBeenCalledWith('Tech', undefined);
});

it('hint names the active ontology when canvas is empty and no active set', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  // active is null (default), no graph loaded — hint should say "no network signal"
  expect(await screen.findByText(/analysis currently uses no network signal/i)).toBeInTheDocument();
});

it('empty-name Save shows the notice and does not call saveOntology', async () => {
  renderGraph();
  await addCompany('AAPL');
  // Explicitly clear the ontology name input so the test is not sensitive to sessionStorage
  // residue from a prior test run in the same environment.
  const nameInput = screen.getByRole('textbox', { name: /ontology name/i });
  fireEvent.change(nameInput, { target: { value: '' } });
  expect(nameInput).toHaveValue('');
  vi.mocked(api.saveOntology).mockClear();
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
  expect(await screen.findByText(/name the ontology first/i)).toBeInTheDocument();
  expect(api.saveOntology).not.toHaveBeenCalled();
});

it('adds a company node via the sidebar Add company… button', async () => {
  vi.mocked(api.saveOntology).mockResolvedValue({ name: 'test', saved_at: 't', expanded: [], graph: AAPL_GRAPH });
  renderGraph();
  // Click the standing sidebar button (no canvas needed — empty canvas)
  fireEvent.click(await screen.findByRole('button', { name: /^add company…$/i }));
  // Company form appears
  fireEvent.change(screen.getByPlaceholderText(/ticker.*tsm/i), { target: { value: 'tsm' } });
  fireEvent.change(screen.getByPlaceholderText(/name.*optional/i), { target: { value: 'TSMC' } });
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
  // Node is selected → detail panel shows label
  expect(await screen.findByText('TSMC')).toBeInTheDocument();
  // Save to assert the graph payload contains the node
  fireEvent.change(screen.getByRole('textbox', { name: /ontology name/i }), { target: { value: 'co-test' } });
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
  await waitFor(() =>
    expect(api.saveOntology).toHaveBeenCalledWith(
      expect.objectContaining({ graph: expect.objectContaining({ nodes: expect.arrayContaining(['TSM']) }) }),
    ),
  );
});

it('rejects a bad ticker from the company form and shows a notice', async () => {
  renderGraph();
  fireEvent.click(await screen.findByRole('button', { name: /^add company…$/i }));
  fireEvent.change(screen.getByPlaceholderText(/ticker.*tsm/i), { target: { value: 'not a ticker!!' } });
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
  expect(await screen.findByText(/ticker must be/i)).toBeInTheDocument();
  // form stays open, canvas still empty
  expect(screen.queryByTestId('graph-canvas')).not.toBeInTheDocument();
});

it('loading an old version marks the canvas dirty so the hint is visible', async () => {
  vi.mocked(api.listOntologies).mockResolvedValue([
    { name: 'Tech', versions: ['t2', 't1'], node_count: 2, edge_count: 1, active: true },
  ]);
  vi.mocked(api.getActiveOntology).mockResolvedValue({ name: 'Tech' });
  // boot load (latest, version=undefined) → resolves Tech graph; the test then drives a 't1' load.
  vi.mocked(api.loadOntology).mockResolvedValue({ name: 'Tech', saved_at: 't2', expanded: [], graph: AAPL_GRAPH });
  renderGraph();
  // Wait for the boot load to finish (dirty=false at this point).
  await screen.findByDisplayValue('Tech');
  // Switch to Ontologies tab so the version select is visible.
  fireEvent.click(screen.getByRole('button', { name: /^ontologies/i }));
  // The select only renders when versions.length > 1 — it is present now.
  const versionSelect = await screen.findByDisplayValue(/latest/i);
  // Mock the 't1' load response before triggering it.
  vi.mocked(api.loadOntology).mockResolvedValue({ name: 'Tech', saved_at: 't1', expanded: [], graph: AAPL_GRAPH });
  fireEvent.change(versionSelect, { target: { value: 't1' } });
  // dirty=true because 't1' !== 't2' (latest) → hint must show "unsaved changes here".
  expect(await screen.findByText(/unsaved changes here/i)).toBeInTheDocument();
});

it('adding a company over a loaded ontology keeps the name and marks it dirty', async () => {
  vi.mocked(api.getActiveOntology).mockResolvedValue({ name: 'Tech' });
  vi.mocked(api.loadOntology).mockResolvedValue({ name: 'Tech', saved_at: 't', expanded: [], graph: AAPL_GRAPH });
  renderGraph();
  // Wait for boot load to complete — ontology name should be 'Tech'
  await screen.findByDisplayValue('Tech');
  await addCompany('NVDA');
  // The canvas is now an unsaved edit of Tech: the name stays and the hint flags the divergence.
  expect(screen.getByLabelText('ontology name')).toHaveValue('Tech');
  expect(await screen.findByText(/unsaved changes here/i)).toBeInTheDocument();
});

it('renames the selected node and re-selects it under the new ticker', async () => {
  renderGraph();
  await addCompany('AAPL');
  // AAPL is auto-selected — open the rename form from the detail panel
  fireEvent.click(screen.getByRole('button', { name: /rename…/i }));
  fireEvent.change(screen.getByLabelText('rename ticker'), { target: { value: 'MSFT' } });
  fireEvent.click(screen.getByRole('button', { name: /^rename$/i }));
  expect(await screen.findByRole('button', { name: 'sel-MSFT' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'sel-AAPL' })).not.toBeInTheDocument();
});

it('rejects a rename onto an existing node with a notice', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  await addCompany('AAPL');
  fireEvent.click(await screen.findByRole('button', { name: /expand neighbours/i }));
  await waitFor(() => expect(screen.getByText(/2 nodes/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'sel-TSM' }));
  fireEvent.click(screen.getByRole('button', { name: /rename…/i }));
  fireEvent.change(screen.getByLabelText('rename ticker'), { target: { value: 'aapl' } });
  fireEvent.click(screen.getByRole('button', { name: /^rename$/i }));
  expect(await screen.findByText(/already on the canvas/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'sel-TSM' })).toBeInTheDocument(); // unchanged
});

it('finds a node from the toolbar search and selects it', async () => {
  renderGraph();
  await addCompany('AAPL');
  await addCompany('MSFT');           // MSFT is now the selected node
  const find = screen.getByLabelText('find node');
  fireEvent.change(find, { target: { value: 'aapl' } });
  fireEvent.keyDown(find, { key: 'Enter' });
  expect(await screen.findByRole('heading', { name: /aapl/i })).toBeInTheDocument();
  expect(find).toHaveValue('');       // box clears after the pick
});

it('adds AAPL to watchlist via the sidebar detail panel watchlist button', async () => {
  renderGraph();
  await addCompany('AAPL');
  // The new node is auto-selected — the sidebar detail panel shows the watchlist button
  const addBtn = await screen.findByRole('button', { name: /☆ Add to watchlist/i });
  fireEvent.click(addBtn);
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ watchlist: expect.arrayContaining(['AAPL']) }),
    ),
  );
});

it('node colour prefers portfolio board over all board for the same ticker', async () => {
  const pfAapl = {
    ticker: 'AAPL', score: 90, direction: 'buy' as const, in_sp500: true,
    name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', price: 1, change_pct: 0, net: 0.6,
    reasons: [], components: {}, as_of: 't',
  };
  const allAapl = {
    ticker: 'AAPL', score: 10, direction: 'sell' as const, in_sp500: true,
    name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', price: 1, change_pct: 0, net: -0.6,
    reasons: [], components: {}, as_of: 't',
  };
  vi.mocked(api.getScreen).mockImplementation((_s, _d, _l, scope) =>
    scope === 'portfolio'
      ? Promise.resolve({ as_of: 't', scope: 'portfolio', scanned: 1, skipped: 0, items: [pfAapl] })
      : Promise.resolve({ as_of: 't', scope: 'all', scanned: 1, skipped: 0, items: [allAapl] }),
  );
  renderGraph();
  await addCompany('AAPL');
  const aaplBtn = await screen.findByRole('button', { name: 'sel-AAPL' });
  // Portfolio board (score 90) must win over all-board (score 10)
  expect(aaplBtn).toHaveAttribute('data-score', '90');
});
