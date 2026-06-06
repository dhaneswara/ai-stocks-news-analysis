import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import Graph from './Graph';
import type { KnowledgeGraph, ScreenBoard } from '../types';

// Canvas can't render in jsdom — mock the wrapper (keeps react-force-graph-2d out of the test).
vi.mock('../components/GraphCanvas', () => ({ GraphCanvas: () => <div data-testid="graph-canvas" /> }));
vi.mock('../api/client', () => ({
  api: { getGraph: vi.fn(), getScreen: vi.fn(), getSectors: vi.fn(), rebuildGraph: vi.fn() },
}));
import { api } from '../api/client';

const EMPTY: KnowledgeGraph = { as_of: '', scope: 'focus', nodes: [], edges: [], built: 0, skipped: 0 };
const GRAPH: KnowledgeGraph = {
  as_of: '2026-06-06', scope: 'focus', built: 1, skipped: 0, nodes: ['AAPL', 'TSM'],
  edges: [{ source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: 'x', url: '', as_of: '' }],
};
const BOARD: ScreenBoard = { as_of: '2026-06-06', scope: 'all', scanned: 2, skipped: 0, items: [] };

function renderGraph() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Graph /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.getScreen).mockResolvedValue(BOARD);
  vi.mocked(api.getSectors).mockResolvedValue([]);
  vi.mocked(api.rebuildGraph).mockResolvedValue(GRAPH);
});

it('shows the empty state when there is no graph', async () => {
  vi.mocked(api.getGraph).mockResolvedValue(EMPTY);
  renderGraph();
  expect(await screen.findByText(/no graph yet/i)).toBeInTheDocument();
});

it('renders the canvas when the graph has nodes', async () => {
  vi.mocked(api.getGraph).mockResolvedValue(GRAPH);
  renderGraph();
  expect(await screen.findByTestId('graph-canvas')).toBeInTheDocument();
});

it('rebuild button calls the API', async () => {
  vi.mocked(api.getGraph).mockResolvedValue(EMPTY);
  renderGraph();
  fireEvent.click(await screen.findByRole('button', { name: /rebuild graph/i }));
  await waitFor(() => expect(api.rebuildGraph).toHaveBeenCalled());
});
