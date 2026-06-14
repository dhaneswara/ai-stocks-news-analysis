import { beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { GraphCanvas, type GraphCanvasProps } from './GraphCanvas';
import type { ViewLink, ViewNode } from '../lib/graphView';

// Mock the force-graph: it can't render in jsdom (canvas), and we drive its callbacks/ref
// directly. `mock.props` exposes the latest props so tests can fire onEngineStop / clicks;
// `mock.api` is the imperative handle the component calls (d3Force/zoomToFit/…).
const mock = vi.hoisted(() => {
  const chain: Record<string, () => unknown> = {};
  chain.strength = () => chain; chain.distanceMax = () => chain; chain.distance = () => chain;
  return {
    props: { current: null as Record<string, (...a: unknown[]) => unknown> | null },
    api: {
      d3Force: vi.fn(() => chain),
      d3ReheatSimulation: vi.fn(),
      zoomToFit: vi.fn(),
      zoom: vi.fn(() => 1),
      centerAt: vi.fn(),
    },
  };
});

vi.mock('react-force-graph-2d', async () => {
  const React = await import('react');
  return {
    default: React.forwardRef((props: Record<string, (...a: unknown[]) => unknown>, ref: React.Ref<unknown>) => {
      mock.props.current = props;
      React.useImperativeHandle(ref, () => mock.api);
      return null;
    }),
  };
});

beforeAll(() => {
  // jsdom lacks ResizeObserver, which the canvas wrapper observes on mount.
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});

beforeEach(() => { vi.clearAllMocks(); mock.props.current = null; });

const node = (id: string, score = 50): ViewNode => ({
  id, label: id, direction: 'buy', score, sector: 'Tech', onBoard: true, external: false, kind: '',
});
const NODES = [node('AAPL', 80), node('TSM', 20)];
const LINKS: ViewLink[] = [
  { source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: '', url: '', origin: 'extracted' },
];

function props(over: Partial<GraphCanvasProps> = {}): GraphCanvasProps {
  return {
    nodes: NODES, links: LINKS, selectedId: null,
    onSelect: vi.fn(), onBackgroundClick: vi.fn(), onAddRelationship: vi.fn(), onAddCompany: vi.fn(),
    onRenameNode: vi.fn(), onDeleteNode: vi.fn(), onDeleteEdge: vi.fn(),
    watchlist: [], onToggleWatch: vi.fn(), focus: null, ...over,
  };
}

const evt = () => ({ preventDefault() {}, clientX: 5, clientY: 5 }) as unknown as MouseEvent;

// Bug: d3-zoom stops propagation of the canvas mousedown, so the menu's own outside-click
// listener never sees on-canvas clicks. The fix closes the menu from the force-graph's
// click callbacks instead.
it('closes the right-click menu when empty canvas space is left-clicked', () => {
  render(<GraphCanvas {...props()} />);
  act(() => { mock.props.current!.onBackgroundRightClick(evt()); });
  expect(screen.getByRole('menu')).toBeInTheDocument();
  act(() => { mock.props.current!.onBackgroundClick(); });
  expect(screen.queryByRole('menu')).not.toBeInTheDocument();
});

it('closes the right-click menu when a node is left-clicked', () => {
  render(<GraphCanvas {...props()} />);
  act(() => { mock.props.current!.onNodeRightClick({ id: 'AAPL' }, evt()); });
  expect(screen.getByRole('menu')).toBeInTheDocument();
  act(() => { mock.props.current!.onNodeClick({ id: 'AAPL' }); });
  expect(screen.queryByRole('menu')).not.toBeInTheDocument();
});

// Bug: a background board refetch hands the canvas new nodes/links arrays with identical
// shape (only scores differ). The old code re-fit the view every time, throwing away the
// user's zoom. The fix re-fits only when the graph's shape actually changes.
it('fits on first layout and on topology change, but not on a score-only update', () => {
  const { rerender } = render(<GraphCanvas {...props()} />);
  act(() => { mock.props.current!.onEngineStop(); });
  expect(mock.api.zoomToFit).toHaveBeenCalledTimes(1);   // initial fit

  // Same ids + edges, different scores (a board refetch) → must NOT re-fit.
  rerender(<GraphCanvas {...props({ nodes: [node('AAPL', 90), node('TSM', 10)] })} />);
  act(() => { mock.props.current!.onEngineStop(); });
  expect(mock.api.zoomToFit).toHaveBeenCalledTimes(1);

  // A real shape change (new node) → re-fit.
  rerender(<GraphCanvas {...props({ nodes: [...NODES, node('NVDA', 60)] })} />);
  act(() => { mock.props.current!.onEngineStop(); });
  expect(mock.api.zoomToFit).toHaveBeenCalledTimes(2);
});
