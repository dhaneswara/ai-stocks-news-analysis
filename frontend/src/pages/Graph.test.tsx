import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import Graph from './Graph';
import type { KnowledgeGraph, ScreenBoard, Settings } from '../types';

// Canvas can't render in jsdom — mock it; render a select button per node so tests can select.
vi.mock('../components/GraphCanvas', () => ({
  GraphCanvas: ({ nodes, onSelect, onDeleteNode, onAddRelationship, onAddCompany }: {
    nodes: { id: string }[]; onSelect: (id: string) => void;
    onDeleteNode: (id: string) => void; onAddRelationship: (id: string) => void;
    onAddCompany: () => void;
    watchlist: string[]; onToggleWatch: (id: string) => void;
  }) => (
    <div data-testid="graph-canvas">
      {nodes.map((n) => <button key={n.id} onClick={() => onSelect(n.id)}>{`sel-${n.id}`}</button>)}
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

beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(api.getScreen).mockResolvedValue(BOARD);
  vi.mocked(api.listImports).mockResolvedValue([]);
  vi.mocked(api.listOntologies).mockResolvedValue([]);
  vi.mocked(api.getActiveOntology).mockResolvedValue({ name: null });
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS as never);
  vi.mocked(api.saveSettings).mockImplementation(async (s) => s as never);
});

it('shows the empty prompt before anything is loaded', async () => {
  renderGraph();
  expect(await screen.findByText(/type a company ticker/i)).toBeInTheDocument();
});

it('loads a root and renders the canvas', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  expect(await screen.findByTestId('graph-canvas')).toBeInTheDocument();
  expect(screen.getByText(/2 nodes/)).toBeInTheDocument();
});

it('expands a selected node and grows the graph', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValueOnce(AAPL_GRAPH).mockResolvedValueOnce(TSM_GRAPH);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  fireEvent.click(await screen.findByRole('button', { name: 'sel-TSM' }));
  fireEvent.click(screen.getByRole('button', { name: /expand neighbours/i }));
  await waitFor(() => expect(screen.getByText(/3 nodes/)).toBeInTheDocument());
});

it('saves the working graph as a named ontology', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  vi.mocked(api.saveOntology).mockResolvedValue({ name: 'Tech', saved_at: 't', expanded: [], graph: AAPL_GRAPH });
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  fireEvent.change(screen.getByRole('textbox', { name: /ontology name/i }), { target: { value: 'Tech' } });
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
  await waitFor(() => expect(api.saveOntology).toHaveBeenCalledWith(expect.objectContaining({ name: 'Tech' })));
});

it('surfaces a load error when extraction fails', async () => {
  vi.mocked(api.getCompanyGraph).mockRejectedValue(new Error('boom'));
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  expect(await screen.findByText(/couldn't load: boom/i)).toBeInTheDocument();
});

it('restores the explored graph after remount (persistence)', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  const first = renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  await waitFor(() => expect(screen.getByText(/2 nodes/)).toBeInTheDocument());
  first.unmount();
  vi.mocked(api.getCompanyGraph).mockClear();
  renderGraph();
  expect(await screen.findByTestId('graph-canvas')).toBeInTheDocument();
  expect(screen.getByText(/2 nodes/)).toBeInTheDocument();
  expect(api.getCompanyGraph).not.toHaveBeenCalled(); // restored from storage, no refetch
});

it('switches back to the Explore tab when a node is selected', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  fireEvent.click(screen.getByRole('button', { name: /^ontologies/i })); // go to Ontologies tab
  expect(screen.queryByRole('button', { name: /expand neighbours/i })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'sel-AAPL' })); // select a node on the canvas
  expect(await screen.findByRole('button', { name: /expand neighbours/i })).toBeInTheDocument();
});

it('deletes a node from the working graph', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  await waitFor(() => expect(screen.getByText(/2 nodes/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: 'del-TSM' }));
  await waitFor(() => expect(screen.getByText(/1 nodes/)).toBeInTheDocument());
});

it('adds a manual relationship via the form', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  fireEvent.click(screen.getByRole('button', { name: 'add-AAPL' }));
  fireEvent.change(await screen.findByPlaceholderText(/ticker or company/i), { target: { value: 'BIDU' } });
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
  await waitFor(() => expect(screen.getByText(/3 nodes/)).toBeInTheDocument());
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
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
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

it('adds AAPL to watchlist via the sidebar detail panel watchlist button', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  // Select the AAPL node via the canvas mock button
  fireEvent.click(screen.getByRole('button', { name: 'sel-AAPL' }));
  // The sidebar detail panel should show the watchlist button
  const addBtn = await screen.findByRole('button', { name: /☆ Add to watchlist/i });
  fireEvent.click(addBtn);
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ watchlist: expect.arrayContaining(['AAPL']) }),
    ),
  );
});
