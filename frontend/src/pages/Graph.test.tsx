import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import Graph from './Graph';
import type { KnowledgeGraph, ScreenBoard } from '../types';

// Canvas can't render in jsdom — mock it; render a select button per node so tests can select.
vi.mock('../components/GraphCanvas', () => ({
  GraphCanvas: ({ nodes, onSelect }: { nodes: { id: string }[]; onSelect: (id: string) => void }) => (
    <div data-testid="graph-canvas">
      {nodes.map((n) => <button key={n.id} onClick={() => onSelect(n.id)}>{`sel-${n.id}`}</button>)}
    </div>
  ),
}));
vi.mock('../api/client', () => ({
  api: {
    getScreen: vi.fn(),
    getCompanyGraph: vi.fn(), listSavedGraphs: vi.fn(), saveGraph: vi.fn(),
    loadSavedGraph: vi.fn(), deleteSavedGraph: vi.fn(),
    listImports: vi.fn(), getOverlay: vi.fn(), importGraph: vi.fn(), deleteImport: vi.fn(),
  },
}));
import { api } from '../api/client';

const BOARD: ScreenBoard = { as_of: 't', scope: 'all', scanned: 0, skipped: 0, items: [] };
const EMPTY_OVERLAY: KnowledgeGraph = { as_of: '', scope: 'imported', built: 0, skipped: 0, nodes: [], edges: [], node_meta: {} };
const OVERLAY: KnowledgeGraph = {
  as_of: 't', scope: 'imported', built: 1, skipped: 0,
  nodes: ['AAPL', 'ext:openai'],
  node_meta: { 'ext:openai': { label: 'OpenAI', kind: 'private_company', source: 'imported' } },
  edges: [{ source: 'AAPL', target: 'ext:openai', type: 'other', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' }],
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
  vi.mocked(api.listSavedGraphs).mockResolvedValue([]);
  vi.mocked(api.listImports).mockResolvedValue([]);
  vi.mocked(api.getOverlay).mockResolvedValue(EMPTY_OVERLAY);
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

it('saves the working graph', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  vi.mocked(api.saveGraph).mockResolvedValue({ root: 'AAPL', saved_at: 't', expanded: [], graph: AAPL_GRAPH });
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
  await waitFor(() => expect(api.saveGraph).toHaveBeenCalled());
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
  fireEvent.click(screen.getByRole('button', { name: /^saved/i })); // go to Saved tab
  expect(screen.queryByRole('button', { name: /expand neighbours/i })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'sel-AAPL' })); // select a node on the canvas
  expect(await screen.findByRole('button', { name: /expand neighbours/i })).toBeInTheDocument();
});

it('unions an imported overlay edge incident to a working node', async () => {
  vi.mocked(api.getCompanyGraph).mockResolvedValue(AAPL_GRAPH);
  vi.mocked(api.getOverlay).mockResolvedValue(OVERLAY);
  renderGraph();
  fireEvent.change(await screen.findByPlaceholderText(/ticker/i), { target: { value: 'AAPL' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  await screen.findByTestId('graph-canvas');
  // AAPL + TSM (working) + ext:openai (overlay, incident to AAPL) = 3 nodes
  await waitFor(() => expect(screen.getByText(/3 nodes/)).toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'sel-ext:openai' })).toBeInTheDocument();
});
