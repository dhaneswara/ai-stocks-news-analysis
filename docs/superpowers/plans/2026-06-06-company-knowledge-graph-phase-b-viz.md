# Company Knowledge Graph — Phase B (Interactive Graph Page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only interactive Knowledge Graph page (nodes = companies coloured by call/sized by score, edges = relationships coloured by news sentiment) on top of the existing Phase A API.

**Architecture:** Frontend-only. `pages/Graph.tsx` fetches the graph + board, derives a view-model via pure helpers in `lib/graphView.ts`, and renders `GraphCanvas` (a thin `react-force-graph-2d` wrapper) beside a fixed `GraphSidebar` (controls + selected-node detail). The Graph route is lazy-loaded so the heavy graph lib code-splits and never enters the app-level test's module graph.

**Tech Stack:** React 18 + TS 5.6, Vite 5, vitest 2 + @testing-library/react, react-router v7, @tanstack/react-query v5, `react-force-graph-2d` (new dep, Node 20). All commands run from `frontend/`.

**Spec:** `docs/superpowers/specs/2026-06-06-company-knowledge-graph-phase-b-viz-design.md`

**Conventions:** Conventional Commits, **no `Co-Authored-By` trailer**. Branch `feat/company-knowledge-graph-viz` (already checked out). Run tests with `npx vitest run <file>`; typecheck/build with `npm run build`.

---

## File structure

**Create:**
- `frontend/src/lib/graphView.ts` — pure view-model: types `ViewNode`/`ViewLink`, `mergeNodes`, `toLinks`, `applyFilters`, `directionColor`, `sentimentColor`, `nodeRadius`.
- `frontend/src/lib/graphView.test.ts`
- `frontend/src/components/GraphSidebar.tsx` + `frontend/src/components/GraphSidebar.test.tsx`
- `frontend/src/components/GraphCanvas.tsx` (force-graph wrapper; mocked in tests)
- `frontend/src/pages/Graph.tsx` + `frontend/src/pages/Graph.test.tsx`

**Modify:**
- `frontend/package.json` (+ lockfile) — add `react-force-graph-2d`
- `frontend/src/api/client.ts` (+ `client.test.ts`) — `getGraph`, `rebuildGraph`
- `frontend/src/hooks/queries.ts` — `useGraph`, `useRebuildGraph`
- `frontend/src/App.tsx` — lazy Graph route + nav link
- `frontend/src/styles.css` — minimal `.graph-*` layout classes

---

## Task 1: Add the graph library

**Files:** Modify `frontend/package.json` (+ `package-lock.json`)

- [ ] **Step 1: Install** — from `frontend/`:

```
npm install react-force-graph-2d@^1.27.4
```

(`react-force-graph-2d` is the 2D-only build — HTML canvas via `force-graph`, no three.js. Peer dep React ≥16.8 satisfied by React 18.3. If `^1.27.4` is unavailable, install the latest `1.x`: `npm install react-force-graph-2d@1`.)

- [ ] **Step 2: Verify it builds and the existing suite is unaffected** — from `frontend/`:

Run: `npm run build`  → Expected: `tsc -b && vite build` succeeds, no errors.
Run: `npx vitest run` → Expected: all existing tests pass (the dep isn't imported by any test yet).

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "build(frontend): add react-force-graph-2d for the knowledge graph page"
```

---

## Task 2: Pure view-model helpers (`lib/graphView.ts`)

**Files:**
- Create: `frontend/src/lib/graphView.ts`
- Test: `frontend/src/lib/graphView.test.ts`

- [ ] **Step 1: Write the failing test** — create `frontend/src/lib/graphView.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { applyFilters, directionColor, mergeNodes, nodeRadius, sentimentColor, toLinks } from './graphView';
import type { KnowledgeGraph, ScreenBoard, RelationType } from '../types';

const GRAPH: KnowledgeGraph = {
  as_of: 't', scope: 'focus', built: 1, skipped: 0,
  nodes: ['AAPL', 'TSM', 'XYZ'],
  edges: [
    { source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: 'e', url: '', as_of: '' },
    { source: 'AAPL', target: 'XYZ', type: 'competitor', sentiment: 'positive', weight: 0.5, confidence: 0.8, evidence: '', url: '', as_of: '' },
  ],
};
const BOARD: ScreenBoard = {
  as_of: 't', scope: 'all', scanned: 2, skipped: 0,
  items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0, score: 80, direction: 'sell', reasons: [], components: {}, as_of: '', net: -0.3 },
    { ticker: 'TSM', name: 'Taiwan Semi', sector: 'Tech', price: 1, change_pct: 0, score: 40, direction: 'sell', reasons: [], components: {}, as_of: '', net: -0.9 },
  ],
};

describe('mergeNodes', () => {
  it('joins board scores and marks off-board nodes unknown', () => {
    const nodes = mergeNodes(GRAPH, BOARD);
    const aapl = nodes.find((n) => n.id === 'AAPL')!;
    expect(aapl.direction).toBe('sell');
    expect(aapl.score).toBe(80);
    expect(aapl.onBoard).toBe(true);
    const xyz = nodes.find((n) => n.id === 'XYZ')!;
    expect(xyz.direction).toBe('unknown');
    expect(xyz.onBoard).toBe(false);
    expect(xyz.score).toBe(0);
  });
  it('handles a missing board', () => {
    expect(mergeNodes(GRAPH, null).every((n) => !n.onBoard)).toBe(true);
  });
});

describe('applyFilters', () => {
  it('filters by sector and drops orphaned links', () => {
    const nodes = mergeNodes(GRAPH, BOARD);
    const links = toLinks(GRAPH);
    const all: Set<RelationType> = new Set(['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary']);
    const out = applyFilters(nodes, links, 'Tech', all);
    expect(out.nodes.map((n) => n.id).sort()).toEqual(['AAPL', 'TSM']); // XYZ has no sector
    expect(out.links).toHaveLength(1); // AAPL->XYZ dropped (XYZ filtered out)
    expect(out.links[0].target).toBe('TSM');
  });
  it('filters by edge type', () => {
    const nodes = mergeNodes(GRAPH, BOARD);
    const links = toLinks(GRAPH);
    const out = applyFilters(nodes, links, null, new Set(['competitor'] as RelationType[]));
    expect(out.links.map((l) => l.type)).toEqual(['competitor']);
  });
});

describe('encoders', () => {
  it('maps colours and radius', () => {
    expect(directionColor('buy')).toBe('#3fb950');
    expect(directionColor('unknown')).toBe('#484f58');
    expect(sentimentColor('negative')).toBe('#f85149');
    expect(nodeRadius(0)).toBeLessThan(nodeRadius(100));
  });
});
```

- [ ] **Step 2: Run it — expect failure** — `npx vitest run src/lib/graphView.test.ts` → FAIL (module missing).

- [ ] **Step 3: Implement — create `frontend/src/lib/graphView.ts`:**

```ts
import type { GraphEdge, KnowledgeGraph, NetworkSignal, RelationType, ScreenBoard } from '../types';

export type NodeDirection = 'buy' | 'sell' | 'hold' | 'unknown';

export interface ViewNode {
  id: string;            // ticker
  label: string;         // ticker
  direction: NodeDirection;
  score: number;         // 0..100 (0 when off-board)
  sector: string;        // '' when off-board
  onBoard: boolean;
  network?: NetworkSignal | null;
}

export interface ViewLink {
  source: string;
  target: string;
  type: RelationType;
  sentiment: GraphEdge['sentiment'];
  weight: number;
  confidence: number;
  evidence: string;
  url: string;
}

export function mergeNodes(graph: KnowledgeGraph, board?: ScreenBoard | null): ViewNode[] {
  const byTicker = new Map(board?.items.map((s) => [s.ticker, s]) ?? []);
  return graph.nodes.map((ticker) => {
    const s = byTicker.get(ticker);
    return {
      id: ticker,
      label: ticker,
      direction: (s?.direction ?? 'unknown') as NodeDirection,
      score: s?.score ?? 0,
      sector: s?.sector ?? '',
      onBoard: !!s,
      network: s?.network ?? null,
    };
  });
}

export function toLinks(graph: KnowledgeGraph): ViewLink[] {
  return graph.edges.map((e) => ({
    source: e.source, target: e.target, type: e.type, sentiment: e.sentiment,
    weight: e.weight, confidence: e.confidence, evidence: e.evidence, url: e.url,
  }));
}

export function applyFilters(
  nodes: ViewNode[],
  links: ViewLink[],
  sector: string | null,
  enabledTypes: Set<RelationType>,
): { nodes: ViewNode[]; links: ViewLink[] } {
  const ns = sector ? nodes.filter((n) => n.sector === sector) : nodes;
  const keep = new Set(ns.map((n) => n.id));
  const ls = links.filter((l) => enabledTypes.has(l.type) && keep.has(l.source) && keep.has(l.target));
  return { nodes: ns, links: ls };
}

export function directionColor(d: NodeDirection): string {
  return d === 'buy' ? '#3fb950' : d === 'sell' ? '#f85149' : d === 'hold' ? '#8b949e' : '#484f58';
}

export function sentimentColor(s: ViewLink['sentiment']): string {
  return s === 'positive' ? '#3fb950' : s === 'negative' ? '#f85149' : '#6e7681';
}

export function nodeRadius(score: number): number {
  return 4 + (Math.max(0, Math.min(100, score)) / 100) * 8; // 4..12
}
```

- [ ] **Step 4: Run it — expect pass** — `npx vitest run src/lib/graphView.test.ts` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/graphView.ts frontend/src/lib/graphView.test.ts
git commit -m "feat(frontend): pure view-model helpers for the knowledge graph"
```

---

## Task 3: API client + hooks (`getGraph` / `rebuildGraph`)

**Files:**
- Modify: `frontend/src/api/client.ts` (+ `frontend/src/api/client.test.ts`)
- Modify: `frontend/src/hooks/queries.ts`

- [ ] **Step 1: Write the failing test** — append to `frontend/src/api/client.test.ts` (inside the existing `describe('api client', ...)` block, before its closing `});`):

```ts
  it('getGraph GETs /graph with scope', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ nodes: [], edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getGraph('focus');
    expect(fetchMock.mock.calls[0][0] as string).toContain('/graph?scope=focus');
  });

  it('rebuildGraph POSTs /graph/rebuild', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ nodes: [], edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.rebuildGraph();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/rebuild');
    expect((init as RequestInit).method).toBe('POST');
  });
```

- [ ] **Step 2: Run it — expect failure** — `npx vitest run src/api/client.test.ts` → FAIL (`api.getGraph` is not a function).

- [ ] **Step 3a: Implement client** — in `frontend/src/api/client.ts`, add `KnowledgeGraph` to the type import block, then add two methods to the `api` object (e.g. after `getSectors`):

```ts
  getGraph: (scope = 'focus') =>
    http<KnowledgeGraph>(`/graph?scope=${encodeURIComponent(scope)}`),
  rebuildGraph: () => http<KnowledgeGraph>('/graph/rebuild', { method: 'POST' }),
```

The import block at the top becomes:

```ts
import type {
  AnalysisResult,
  KnowledgeGraph,
  MarketMood,
  ProviderInfo,
  ScreenBoard,
  Settings,
  StockData,
  TestResult,
} from '../types';
```

- [ ] **Step 3b: Implement hooks** — append to `frontend/src/hooks/queries.ts`:

```ts
export function useGraph(scope = 'focus') {
  return useQuery({ queryKey: ['graph', scope], queryFn: () => api.getGraph(scope) });
}

export function useRebuildGraph() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.rebuildGraph(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['graph'] });
      qc.invalidateQueries({ queryKey: ['screen'] }); // rebuild bakes network into the board too
    },
  });
}
```

- [ ] **Step 4: Run it — expect pass** — `npx vitest run src/api/client.test.ts` → PASS. Then `npm run build` → succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/hooks/queries.ts
git commit -m "feat(frontend): graph API client methods and query hooks"
```

---

## Task 4: Sidebar (`components/GraphSidebar.tsx`)

**Files:**
- Create: `frontend/src/components/GraphSidebar.tsx`
- Test: `frontend/src/components/GraphSidebar.test.tsx`

- [ ] **Step 1: Write the failing test** — create `frontend/src/components/GraphSidebar.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphSidebar } from './GraphSidebar';
import type { ViewNode } from '../lib/graphView';

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
    enabledTypes: new Set(['supplier'] as const), onToggleType: vi.fn(),
    onRebuild: vi.fn(), rebuilding: false,
  };
}

function wrap(ui: React.ReactNode) {
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
```

- [ ] **Step 2: Run it — expect failure** — `npx vitest run src/components/GraphSidebar.test.tsx` → FAIL (module missing).

- [ ] **Step 3: Implement — create `frontend/src/components/GraphSidebar.tsx`:**

```tsx
import { Link } from 'react-router-dom';
import type { RelationType } from '../types';
import type { ViewNode } from '../lib/graphView';

const EDGE_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];

export interface GraphSidebarProps {
  asOf: string;
  built: number;
  skipped: number;
  nodeCount: number;
  linkCount: number;
  sectors: string[];
  sector: string;
  onSector: (s: string) => void;
  enabledTypes: Set<RelationType>;
  onToggleType: (t: RelationType) => void;
  selected: ViewNode | null;
  onRebuild: () => void;
  rebuilding: boolean;
}

export function GraphSidebar(props: GraphSidebarProps) {
  const { asOf, built, skipped, nodeCount, linkCount, sectors, sector, onSector,
    enabledTypes, onToggleType, selected, onRebuild, rebuilding } = props;
  return (
    <aside className="graph-sidebar panel">
      <div className="panel-head"><span className="section-label">Knowledge graph</span></div>

      <button onClick={onRebuild} disabled={rebuilding}>
        {rebuilding ? 'Rebuilding… (LLM)' : 'Rebuild graph'}
      </button>
      <p className="muted">
        {asOf ? `As of ${new Date(asOf).toLocaleString()}` : 'Not built yet'}
        {built ? ` · ${built} built` : ''}{skipped ? `, ${skipped} skipped` : ''}
      </p>
      <p className="muted">{nodeCount} nodes · {linkCount} edges shown</p>

      <label>Sector
        <select value={sector} onChange={(e) => onSector(e.target.value)}>
          <option value="">All sectors</option>
          {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>

      <div className="graph-types">
        {EDGE_TYPES.map((t) => (
          <label key={t} className="chip-toggle">
            <input type="checkbox" checked={enabledTypes.has(t)} onChange={() => onToggleType(t)} /> {t}
          </label>
        ))}
      </div>

      {selected ? (
        <div className="graph-detail">
          <h4>{selected.label}{' '}
            <span className={`badge ${selected.direction === 'unknown' ? 'hold' : selected.direction}`}>
              {selected.direction.toUpperCase()}
            </span>
          </h4>
          {selected.onBoard && <p className="muted">score {selected.score.toFixed(0)}</p>}
          {selected.network && selected.network.influences.length > 0 ? (
            <ul className="factor-list">
              {selected.network.influences.map((inf, i) => {
                const lean = inf.signed > 0 ? 'bullish' : inf.signed < 0 ? 'bearish' : 'neutral';
                return (
                  <li key={i}>
                    <b>{inf.type} {inf.neighbour}</b> — news {inf.edge_sentiment} ({lean})
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="muted">No outgoing network edges.</p>
          )}
          <Link to={`/?ticker=${encodeURIComponent(selected.id)}`}>Open in Dashboard →</Link>
        </div>
      ) : (
        <div className="graph-legend">
          <p className="muted">Click a node for its network detail.</p>
          <p className="label">
            <span style={{ color: '#3fb950' }}>●</span> buy{' '}
            <span style={{ color: '#f85149' }}>●</span> sell{' '}
            <span style={{ color: '#8b949e' }}>●</span> hold · edge colour = news effect
          </p>
        </div>
      )}
    </aside>
  );
}
```

- [ ] **Step 4: Run it — expect pass** — `npx vitest run src/components/GraphSidebar.test.tsx` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphSidebar.test.tsx
git commit -m "feat(frontend): knowledge graph sidebar (controls + node detail)"
```

---

## Task 5: Canvas wrapper (`components/GraphCanvas.tsx`)

**Files:** Create `frontend/src/components/GraphCanvas.tsx`

No unit test for this file — it is the mocked boundary (canvas can't render in jsdom; same convention as `PriceChart`). It is exercised at build time (tsc) and at runtime in the browser smoke check (Task 7).

- [ ] **Step 1: Implement — create `frontend/src/components/GraphCanvas.tsx`:**

```tsx
import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { directionColor, nodeRadius, sentimentColor, type ViewLink, type ViewNode } from '../lib/graphView';

export interface GraphCanvasProps {
  nodes: ViewNode[];
  links: ViewLink[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function GraphCanvas({ nodes, links, selectedId, onSelect }: GraphCanvasProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 600, height: 480 });

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setDims({ width: entry.contentRect.width, height: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Stable graphData (keyed on nodes/links, NOT selection) so selecting a node
  // recolours without restarting the force simulation.
  const data = useMemo(
    () => ({ nodes: nodes.map((n) => ({ ...n })), links: links.map((l) => ({ ...l })) }),
    [nodes, links],
  );

  const neighbours = useMemo(() => {
    const set = new Set<string>();
    if (selectedId) {
      for (const l of links) {
        if (l.source === selectedId) set.add(l.target);
        if (l.target === selectedId) set.add(l.source);
      }
    }
    return set;
  }, [links, selectedId]);

  const isDim = (id: string) => !!selectedId && id !== selectedId && !neighbours.has(id);

  return (
    <div ref={wrap} className="graph-canvas">
      <ForceGraph2D
        width={dims.width}
        height={dims.height}
        graphData={data}
        nodeRelSize={1}
        nodeVal={(n: any) => nodeRadius(n.score) ** 2}
        nodeColor={(n: any) => (isDim(n.id) ? '#30363d' : directionColor(n.direction))}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(n: any, ctx: CanvasRenderingContext2D, scale: number) => {
          ctx.fillStyle = isDim(n.id) ? '#6e7681' : '#e6edf3';
          ctx.font = `${10 / scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(n.label, n.x, n.y - nodeRadius(n.score) - 2 / scale);
        }}
        linkColor={(l: any) => sentimentColor(l.sentiment)}
        linkWidth={(l: any) => 0.5 + l.weight * l.confidence * 2}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel={(l: any) => `${l.type} · ${l.sentiment}${l.evidence ? ` · ${l.evidence}` : ''}`}
        onNodeClick={(n: any) => onSelect(n.id)}
      />
    </div>
  );
}
```

(The `any` in the `react-force-graph-2d` accessor callbacks is intentional — its generics are awkward and `npm run build` runs `tsc` only, not eslint, so explicit `any` is accepted. Keep them local to these callbacks.)

- [ ] **Step 2: Verify it typechecks** — from `frontend/`: `npm run build` → succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphCanvas.tsx
git commit -m "feat(frontend): react-force-graph-2d canvas wrapper"
```

---

## Task 6: The Graph page (`pages/Graph.tsx`)

**Files:**
- Create: `frontend/src/pages/Graph.tsx`
- Test: `frontend/src/pages/Graph.test.tsx`

- [ ] **Step 1: Write the failing test** — create `frontend/src/pages/Graph.test.tsx`:

```tsx
import { beforeEach, expect, it, vi, waitFor } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
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
```

- [ ] **Step 2: Run it — expect failure** — `npx vitest run src/pages/Graph.test.tsx` → FAIL (module missing).

- [ ] **Step 3: Implement — create `frontend/src/pages/Graph.tsx`:**

```tsx
import { useMemo, useState } from 'react';
import { GraphCanvas } from '../components/GraphCanvas';
import { GraphSidebar } from '../components/GraphSidebar';
import { useGraph, useRebuildGraph, useScreen, useSectors } from '../hooks/queries';
import { applyFilters, mergeNodes, toLinks, type ViewNode } from '../lib/graphView';
import type { RelationType } from '../types';

const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];

export default function Graph() {
  const graph = useGraph();
  const board = useScreen(undefined, undefined, 0); // full uncapped board for node colour/size
  const sectors = useSectors();
  const rebuild = useRebuildGraph();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sector, setSector] = useState('');
  const [enabledTypes, setEnabledTypes] = useState<Set<RelationType>>(new Set(ALL_TYPES));

  const view = useMemo(() => {
    if (!graph.data) return { nodes: [] as ViewNode[], links: [] };
    return applyFilters(mergeNodes(graph.data, board.data), toLinks(graph.data), sector || null, enabledTypes);
  }, [graph.data, board.data, sector, enabledTypes]);

  const selected = useMemo(
    () => view.nodes.find((n) => n.id === selectedId) ?? null,
    [view.nodes, selectedId],
  );

  const toggleType = (t: RelationType) =>
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });

  const g = graph.data;
  const empty = !!g && g.nodes.length === 0;

  return (
    <div className="graph-page">
      <div className="graph-main panel">
        {graph.isLoading && <p className="muted">Loading graph…</p>}
        {graph.isError && <p className="error">Could not load the graph: {(graph.error as Error).message}</p>}
        {empty && (
          <div className="graph-empty">
            <p className="muted">
              No graph yet — hit <b>Rebuild graph</b> to extract relationships (runs the LLM over your focus set).
            </p>
          </div>
        )}
        {!empty && g && (
          <GraphCanvas nodes={view.nodes} links={view.links} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </div>

      <GraphSidebar
        asOf={g?.as_of ?? ''}
        built={g?.built ?? 0}
        skipped={g?.skipped ?? 0}
        nodeCount={view.nodes.length}
        linkCount={view.links.length}
        sectors={sectors.data ?? []}
        sector={sector}
        onSector={setSector}
        enabledTypes={enabledTypes}
        onToggleType={toggleType}
        selected={selected}
        onRebuild={() => rebuild.mutate()}
        rebuilding={rebuild.isPending}
      />
    </div>
  );
}
```

- [ ] **Step 4: Run it — expect pass** — `npx vitest run src/pages/Graph.test.tsx` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Graph.tsx frontend/src/pages/Graph.test.tsx
git commit -m "feat(frontend): knowledge graph page composing canvas + sidebar"
```

---

## Task 7: Route + nav + styles

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add the lazy route + nav link in `frontend/src/App.tsx`.**

Change the imports at the top to add `lazy` and `Suspense`, and lazy-import the Graph page (keeps `react-force-graph-2d` out of the eager bundle and out of `Dashboard.test.tsx`'s module graph):

```tsx
import { lazy, Suspense } from 'react';
import { Link, NavLink, Route, Routes } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Discover from './pages/Discover';
import Settings from './pages/Settings';
import { DashboardStateProvider } from './state/dashboardState';

const Graph = lazy(() => import('./pages/Graph'));
```

Add the nav link after the Discover link:

```tsx
            <NavLink to="/discover" className={navClass}>Discover</NavLink>
            <NavLink to="/graph" className={navClass}>Graph</NavLink>
            <NavLink to="/settings" className={navClass}>Settings</NavLink>
```

Add the route (wrapped in Suspense) inside `<Routes>`:

```tsx
            <Route path="/discover" element={<Discover />} />
            <Route path="/graph" element={<Suspense fallback={<p className="muted">Loading graph…</p>}><Graph /></Suspense>} />
            <Route path="/settings" element={<Settings />} />
```

- [ ] **Step 2: Add layout styles** — append to `frontend/src/styles.css`:

```css
/* --- Knowledge graph page --- */
.graph-page { display: flex; gap: 16px; align-items: stretch; min-height: 520px; height: calc(100vh - 170px); }
.graph-main { flex: 1 1 auto; position: relative; padding: 0; overflow: hidden; }
.graph-canvas { position: absolute; inset: 0; }
.graph-empty { display: flex; align-items: center; justify-content: center; height: 100%; padding: 24px; text-align: center; }
.graph-sidebar { flex: 0 0 320px; display: flex; flex-direction: column; gap: 10px; overflow: auto; }
.graph-types { display: flex; flex-wrap: wrap; gap: 6px; }
.chip-toggle { font-size: 12px; display: inline-flex; align-items: center; gap: 4px; }
.graph-detail .factor-list { margin: 6px 0; }
```

- [ ] **Step 3: Verify the whole suite + build** — from `frontend/`:

Run: `npx vitest run` → Expected: all pass, **including the existing `Dashboard.test.tsx`** (which renders `<App/>`; the lazy Graph route means `react-force-graph-2d` is never imported there).
Run: `npm run build` → Expected: succeeds (tsc + vite), Graph chunk code-split.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat(frontend): Graph nav link, lazy route, and layout styles"
```

---

## Task 8: Live browser smoke check

**Files:** none (verification only)

- [ ] **Step 1: Start backend + frontend.** Backend: from `backend/`, `.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000`. Frontend: from `frontend/`, `npm run dev` (serves on :5173). Ensure a board snapshot exists (run a Discover **Rescan all** once if needed) and provider keys are set.

- [ ] **Step 2: Verify the page** using the preview tooling (preview_start/preview_eval/preview_snapshot/preview_screenshot — never ask the user to check manually):
  - Navigate to `/graph`. With no graph snapshot, confirm the **empty state** + Rebuild button render.
  - Click **Rebuild graph**; confirm it calls `POST /api/graph/rebuild` (network panel) and the canvas then shows nodes/edges (coloured), no console errors.
  - Click a node; confirm the sidebar shows its call badge + influences + the "Open in Dashboard →" link, and that link routes to `/?ticker=…`.
  - Toggle a sector and an edge-type filter; confirm node/edge counts change.
  - Capture a `preview_screenshot` as proof.

- [ ] **Step 3: No commit** (verification only). If issues are found, fix in the relevant source file, re-run `npx vitest run` + `npm run build`, and commit the fix with a `fix(frontend): …` message.

---

## Self-review notes (author check vs. spec)

- **Spec coverage:** layout A (graph + fixed sidebar) → Task 6/7 · sentiment-coloured edges + call-coloured/score-sized nodes → `GraphCanvas` + `graphView` (Tasks 2/5) · click-to-select + highlight neighbours → `GraphCanvas` (Task 5) · sector + edge-type filters (hide) → `applyFilters` + sidebar (Tasks 2/4/6) · Rebuild + status → sidebar/page (Tasks 3/4/6) · empty/loading/error/off-board states → Task 6 + `mergeNodes` · `react-force-graph-2d` pinned + Node 20 → Task 1 · nav/route → Task 7 · no backend changes → confirmed (only `getGraph`/`rebuildGraph` clients hit existing endpoints).
- **Type consistency:** `ViewNode`/`ViewLink` defined in Task 2 are imported unchanged by Tasks 4/5/6. `getGraph(scope)`/`rebuildGraph()` and `useGraph`/`useRebuildGraph` consistent across Tasks 3/6. `GraphSidebarProps`/`GraphCanvasProps` match the page's usage in Task 6.
- **Test isolation:** no test imports `react-force-graph-2d` — `GraphCanvas` is mocked in `Graph.test.tsx`, and the Graph route is `lazy` so `Dashboard.test.tsx` (renders `<App/>`) never loads it.
- **Deferred / out of scope:** clustering/virtualization for very large graphs; pixel/canvas rendering tests; any backend change.
