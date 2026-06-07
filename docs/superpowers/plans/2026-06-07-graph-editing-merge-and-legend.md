# Editable Graph — Merge Imports, Manual Edit, Canvas Legend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a company graph a durable, editable artifact — merge import sets into the working/saved graph with a conflict-resolution + Discover-linking preview, add/delete nodes & relationships by right-click, and show an on-canvas legend.

**Architecture:** Backend change is tiny (add `"manual"` to two `Literal`s; one read-only route to fetch a single import set). All merge reconciliation and manual editing are **pure frontend functions** (`lib/graphMerge.ts`, additions to `lib/graphView.ts`) consumed by thin React components (`GraphLegend`, `GraphContextMenu`, `MergePreview`) and wired in `pages/Graph.tsx`. The Discover board (already loaded on the page, carries `name`) is the linking authority.

**Tech Stack:** Backend FastAPI + Pydantic v2 + pytest (run from `backend/`: `.venv/Scripts/python.exe -m pytest -q`). Frontend React + Vite + TypeScript + TanStack Query + Vitest/RTL (run from `frontend/`: `npx vitest run`; build/type-gate: `npm run build` = `tsc -b && vite build`). `react-force-graph-2d` for the canvas.

**Spec:** `docs/superpowers/specs/2026-06-07-graph-editing-merge-and-legend-design.md`

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/app/models/schemas.py` | add `"manual"` to `GraphEdge.origin` + `NodeMeta.source` | 1 |
| `frontend/src/types.ts` | mirror the two `"manual"` unions | 1 |
| `backend/app/network/store.py` | `load_import_graph(set_id, cache)` | 2 |
| `backend/app/api/routes.py` | `GET /api/graph/imports/{set_id}` | 2 |
| `frontend/src/api/client.ts` | `getImportSet(id)` | 3 |
| `frontend/src/lib/graphView.ts` | `normalizeName`, `slug`, `resolveManualTarget`, `addManualEdge`, `addManualNode`, `deleteNode`, `deleteEdge` | 4 |
| `frontend/src/lib/graphMerge.ts` (new) | `planMerge`, `applyMerge`, types | 5 |
| `frontend/src/components/GraphLegend.tsx` (new) | collapsible canvas legend | 6 |
| `frontend/src/components/GraphContextMenu.tsx` (new) | right-click menu | 7 |
| `frontend/src/components/MergePreview.tsx` (new) | merge link/conflict preview | 8 |
| `frontend/src/components/GraphCanvas.tsx` | mount legend, right-click handlers, manual dash | 9 |
| `frontend/src/components/GraphSidebar.tsx` | relationship form, merge button, target field | 10 |
| `frontend/src/pages/Graph.tsx` | wire merge/manual/dirty/prompt-target | 11 |
| `frontend/src/styles.css` | menu, legend, preview, form, unsaved hint | 12 |
| `README.md`, `frontend/README.md`, `backend/README.md` | document the feature | 13 |

---

## Task 1: Data model — add `"manual"` provenance

**Files:**
- Modify: `backend/app/models/schemas.py:110` (`NodeMeta.source`), `:123` (`GraphEdge.origin`)
- Modify: `frontend/src/types.ts:40` (`NodeMeta`), `:44` (`GraphEdge.origin`)
- Test: `backend/tests/test_schemas_manual.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_schemas_manual.py`:

```python
from app.models.schemas import GraphEdge, NodeMeta


def test_manual_origin_and_source_are_valid():
    e = GraphEdge(source="AAPL", target="man:ai-demand", type="other", origin="manual")
    assert e.origin == "manual"
    m = NodeMeta(label="AI demand", kind="concept", source="manual")
    assert m.source == "manual"


def test_existing_defaults_unchanged():
    assert GraphEdge(source="A", target="B", type="supplier").origin == "extracted"
    assert NodeMeta().source == "native"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_schemas_manual.py -q`
Expected: FAIL — `ValidationError` on `origin="manual"` / `source="manual"`.

- [ ] **Step 3: Widen the two Literals (backend)**

In `backend/app/models/schemas.py`, change `NodeMeta.source` (line ~110):

```python
    source: Literal["native", "imported", "manual"] = "native"
```

and `GraphEdge.origin` (line ~123):

```python
    origin: Literal["extracted", "imported", "manual"] = "extracted"
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_schemas_manual.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Mirror the unions in the frontend types**

In `frontend/src/types.ts`, change `NodeMeta` (line ~40):

```ts
export interface NodeMeta { label: string; kind: string; source: 'native' | 'imported' | 'manual'; }
```

and `GraphEdge.origin` (line ~44):

```ts
  origin?: 'extracted' | 'imported' | 'manual';
```

- [ ] **Step 6: Type-check the frontend**

Run: `cd frontend && npm run build`
Expected: PASS (build succeeds; no type errors).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_schemas_manual.py frontend/src/types.ts
git commit -m "feat(graph): add \"manual\" provenance to GraphEdge.origin and NodeMeta.source"
```

---

## Task 2: Backend — fetch a single import set

**Files:**
- Modify: `backend/app/network/store.py` (add `load_import_graph` near `_load_import_set`, ~line 168)
- Modify: `backend/app/api/routes.py` (new route + import; near the other `/graph/imports` routes ~line 314)
- Test: `backend/tests/test_api_graph.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api_graph.py`:

```python
def test_get_single_import_set(client, monkeypatch):
    tc, _ = client
    _stub_universe(monkeypatch)
    tc.post("/api/graph/import", json={"name": "d", "payload": {"edges": [
        {"source": "AAPL", "target": "MSFT", "type": "partner"}]}})
    sid = tc.get("/api/graph/imports").json()[0]["id"]
    r = tc.get(f"/api/graph/imports/{sid}")
    assert r.status_code == 200
    g = r.json()
    assert g["scope"] == "imported"
    assert any(e["source"] == "AAPL" and e["origin"] == "imported" for e in g["edges"])


def test_get_unknown_import_set_404(client):
    tc, _ = client
    assert tc.get("/api/graph/imports/nope").status_code == 404
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_graph.py -q -k import_set`
Expected: FAIL — 404 for the valid set (route missing), or NameError.

- [ ] **Step 3: Add the store helper**

In `backend/app/network/store.py`, after `_load_import_set` (~line 179) add:

```python
def load_import_graph(set_id: str, cache: Cache) -> KnowledgeGraph | None:
    """The graph of one import set, for merging into a working graph; None if unknown."""
    loaded = _load_import_set(set_id, cache)
    return loaded[1] if loaded else None
```

- [ ] **Step 4: Add the route**

In `backend/app/api/routes.py`, add `load_import_graph` to the `from app.network.store import (...)` block (~line 32), then add the route next to `list_imports` (~line 314):

```python
@router.get("/graph/imports/{set_id}", response_model=KnowledgeGraph)
def get_import_set(set_id: str, cache: Cache = Depends(get_cache)) -> KnowledgeGraph:
    """One import set's graph, for the merge-into-graph preview."""
    graph = load_import_graph(set_id, cache)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No import set '{set_id}'")
    return graph
```

- [ ] **Step 5: Run it to confirm it passes**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_graph.py -q`
Expected: PASS (all graph route tests, incl. the 2 new ones).

- [ ] **Step 6: Commit**

```bash
git add backend/app/network/store.py backend/app/api/routes.py backend/tests/test_api_graph.py
git commit -m "feat(graph): GET /api/graph/imports/{id} to fetch one import set"
```

---

## Task 3: Client — `getImportSet`

**Files:**
- Modify: `frontend/src/api/client.ts:88` (after `getOverlay`)
- Test: `frontend/src/api/client.test.ts` (append before the closing `});`)

- [ ] **Step 1: Write the failing test**

Append inside the `describe('api client', …)` block in `frontend/src/api/client.test.ts`:

```ts
  it('getImportSet GETs /graph/imports/{id} with the id encoded', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ scope: 'imported', edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getImportSet('2026-06-07T00:00:00+00:00');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/graph/imports/');
    expect(url).toContain('%3A'); // colon encoded
  });
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `api.getImportSet is not a function`.

- [ ] **Step 3: Add the client method**

In `frontend/src/api/client.ts`, after the `getOverlay` line (~88):

```ts
  getImportSet: (id: string) => http<KnowledgeGraph>(`/graph/imports/${encodeURIComponent(id)}`),
```

(`KnowledgeGraph` is already imported.)

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(graph): client getImportSet(id)"
```

---

## Task 4: Pure manual-edit helpers + `normalizeName`

**Files:**
- Modify: `frontend/src/lib/graphView.ts` (append helpers; import `StockScore`)
- Test: `frontend/src/lib/graphView.test.ts` (append)

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/graphView.test.ts`:

```ts
import {
  addManualEdge, addManualNode, deleteEdge, deleteNode, normalizeName, resolveManualTarget,
} from './graphView';
import type { GraphEdge } from '../types';

const EMPTY = (): KnowledgeGraph => ({ as_of: '', scope: 'x', built: 0, skipped: 0, nodes: [], edges: [], node_meta: {} });

describe('normalizeName', () => {
  it('strips suffixes and punctuation', () => {
    expect(normalizeName('NVIDIA Corporation')).toBe('nvidia');
    expect(normalizeName('Alphabet Inc. (Class A)')).toBe('alphabet a'); // "class" stripped, "a" kept
    expect(normalizeName('Apple')).toBe('apple');
  });
});

describe('resolveManualTarget', () => {
  const board = BOARD.items; // AAPL/Apple, TSM/Taiwan Semi
  it('reuses an existing node by id (case-insensitive)', () => {
    const g = { ...EMPTY(), nodes: ['AAPL'] };
    expect(resolveManualTarget('aapl', g, board)).toMatchObject({ id: 'AAPL', isNew: false });
  });
  it('links a Discover company by name', () => {
    expect(resolveManualTarget('Taiwan Semi', EMPTY(), board)).toMatchObject({ id: 'TSM', external: false, isNew: true });
  });
  it('links a Discover company by symbol', () => {
    expect(resolveManualTarget('TSM', EMPTY(), board)).toMatchObject({ id: 'TSM', external: false });
  });
  it('makes a ticker node for an unknown ALL-CAPS symbol', () => {
    expect(resolveManualTarget('ASML', EMPTY(), board)).toMatchObject({ id: 'ASML', external: false, isNew: true });
  });
  it('makes a concept node for free text', () => {
    expect(resolveManualTarget('AI chip demand', EMPTY(), board)).toMatchObject({ id: 'man:ai-chip-demand', external: true });
  });
});

describe('manual graph mutations', () => {
  const edge = (s: string, t: string, type: RelationType = 'partner'): GraphEdge => ({
    source: s, target: t, type, sentiment: 'positive', weight: 0.5, confidence: 0.9, evidence: '', url: '', as_of: '', origin: 'manual',
  });
  it('addManualEdge appends and creates missing endpoints', () => {
    const out = addManualEdge({ ...EMPTY(), nodes: ['AAPL'] }, edge('AAPL', 'man:x'));
    expect(out.nodes).toContain('man:x');
    expect(out.edges[0].origin).toBe('manual');
    expect(out.node_meta?.['man:x']?.source).toBe('manual');
  });
  it('addManualEdge de-dupes by source|target|type', () => {
    let g = addManualEdge({ ...EMPTY(), nodes: ['AAPL', 'TSM'] }, edge('AAPL', 'TSM'));
    g = addManualEdge(g, edge('AAPL', 'TSM'));
    expect(g.edges).toHaveLength(1);
  });
  it('addManualNode adds a man: concept with meta', () => {
    const out = addManualNode(EMPTY(), { id: 'man:x', label: 'X thing' });
    expect(out.node_meta?.['man:x']).toMatchObject({ label: 'X thing', source: 'manual' });
  });
  it('deleteNode removes the node, its meta, and incident edges', () => {
    let g = addManualEdge({ ...EMPTY(), nodes: ['AAPL'] }, edge('AAPL', 'man:x'));
    g = deleteNode(g, 'man:x');
    expect(g.nodes).not.toContain('man:x');
    expect(g.edges).toHaveLength(0);
    expect(g.node_meta?.['man:x']).toBeUndefined();
  });
  it('deleteEdge removes only the matching edge', () => {
    let g = addManualEdge({ ...EMPTY(), nodes: ['AAPL', 'TSM'] }, edge('AAPL', 'TSM', 'partner'));
    g = addManualEdge(g, edge('AAPL', 'TSM', 'supplier'));
    g = deleteEdge(g, { source: 'AAPL', target: 'TSM', type: 'partner' });
    expect(g.edges).toHaveLength(1);
    expect(g.edges[0].type).toBe('supplier');
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/lib/graphView.test.ts`
Expected: FAIL — helpers not exported.

- [ ] **Step 3: Implement the helpers**

In `frontend/src/lib/graphView.ts`, add `StockScore` to the type import on line 1:

```ts
import type { GraphEdge, KnowledgeGraph, NetworkSignal, RelationType, ScreenBoard, StockScore } from '../types';
```

Append at the end of the file:

```ts
const _SUFFIX = /\b(inc|corp|corporation|co|ltd|plc|company|companies|holdings|group|the|class [abc])\b\.?/gi;

/** Normalise a company name for matching (modelled on the backend TickerResolver). */
export function normalizeName(s: string): string {
  return (s || '').toLowerCase().replace(_SUFFIX, '').replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim();
}

function slug(s: string): string {
  return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

export interface ResolvedTarget { id: string; label: string; external: boolean; isNew: boolean }

/** Map a free-typed target to an existing node, a Discover ticker, a new ticker node, or a concept. */
export function resolveManualTarget(input: string, graph: KnowledgeGraph, board: StockScore[]): ResolvedTarget {
  const raw = input.trim();
  const meta = graph.node_meta ?? {};
  const has = (id: string) => graph.nodes.includes(id);

  const byId = graph.nodes.find((n) => n.toLowerCase() === raw.toLowerCase());
  if (byId) return { id: byId, label: meta[byId]?.label || byId, external: byId.startsWith('ext:') || byId.startsWith('man:'), isNew: false };

  const byLabel = graph.nodes.find((n) => normalizeName(meta[n]?.label || n) === normalizeName(raw));
  if (byLabel) return { id: byLabel, label: meta[byLabel]?.label || byLabel, external: byLabel.startsWith('ext:') || byLabel.startsWith('man:'), isNew: false };

  const sym = board.find((s) => s.ticker.toUpperCase() === raw.toUpperCase());
  if (sym) return { id: sym.ticker, label: sym.ticker, external: false, isNew: !has(sym.ticker) };
  const named = board.find((s) => normalizeName(s.name) === normalizeName(raw));
  if (named) return { id: named.ticker, label: named.ticker, external: false, isNew: !has(named.ticker) };

  if (raw.length <= 10 && raw === raw.toUpperCase() && /^[A-Z0-9.\-]+$/.test(raw) && /[A-Z]/.test(raw)) {
    return { id: raw, label: raw, external: false, isNew: !has(raw) };
  }
  const id = `man:${slug(raw)}`;
  return { id, label: raw, external: true, isNew: !has(id) };
}

/** Add a node; concept/external ids (`man:`/`ext:`) get a `manual`/existing meta entry. No-op if present. */
export function addManualNode(graph: KnowledgeGraph, meta: { id: string; label: string; kind?: string }): KnowledgeGraph {
  if (graph.nodes.includes(meta.id)) return graph;
  const node_meta = { ...(graph.node_meta ?? {}) };
  if (meta.id.startsWith('man:') || meta.id.startsWith('ext:')) {
    node_meta[meta.id] = { label: meta.label || meta.id, kind: meta.kind || 'concept', source: 'manual' };
  }
  return { ...graph, nodes: [...graph.nodes, meta.id], node_meta };
}

/** Append a manual edge, creating any missing endpoint nodes; de-dupes by source|target|type. */
export function addManualEdge(graph: KnowledgeGraph, edge: GraphEdge): KnowledgeGraph {
  let g = graph;
  for (const ep of [edge.source, edge.target]) {
    if (!g.nodes.includes(ep)) g = addManualNode(g, { id: ep, label: ep });
  }
  const key = `${edge.source}|${edge.target}|${edge.type}`;
  if (g.edges.some((e) => `${e.source}|${e.target}|${e.type}` === key)) return g;
  return { ...g, edges: [...g.edges, edge] };
}

export function deleteNode(graph: KnowledgeGraph, id: string): KnowledgeGraph {
  const node_meta = { ...(graph.node_meta ?? {}) };
  delete node_meta[id];
  return {
    ...graph,
    nodes: graph.nodes.filter((n) => n !== id),
    edges: graph.edges.filter((e) => e.source !== id && e.target !== id),
    node_meta,
  };
}

export function deleteEdge(graph: KnowledgeGraph, ref: { source: string; target: string; type: RelationType }): KnowledgeGraph {
  return {
    ...graph,
    edges: graph.edges.filter((e) => !(e.source === ref.source && e.target === ref.target && e.type === ref.type)),
  };
}
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/lib/graphView.test.ts`
Expected: PASS (existing + new describes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/graphView.ts frontend/src/lib/graphView.test.ts
git commit -m "feat(graph): pure manual-edit helpers + normalizeName"
```

---

## Task 5: Merge reconciliation (`lib/graphMerge.ts`)

**Files:**
- Create: `frontend/src/lib/graphMerge.ts`
- Test: `frontend/src/lib/graphMerge.test.ts` (create)

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/graphMerge.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { applyMerge, planMerge } from './graphMerge';
import type { KnowledgeGraph, StockScore } from '../types';

const board: StockScore[] = [
  { ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0, score: 80, direction: 'buy', reasons: [], components: {}, as_of: '', net: 0 },
  { ticker: 'NVDA', name: 'NVIDIA Corporation', sector: 'Tech', price: 1, change_pct: 0, score: 70, direction: 'buy', reasons: [], components: {}, as_of: '', net: 0 },
];

const working: KnowledgeGraph = {
  as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0,
  nodes: ['AAPL', 'NVDA'],
  node_meta: {},
  edges: [{ source: 'AAPL', target: 'NVDA', type: 'partner', sentiment: 'positive', weight: 1, confidence: 1, evidence: 'news', url: '', as_of: '', origin: 'extracted' }],
};

// import has NVDA as an unresolved external node + a new edge + a duplicate edge with different sentiment
const importSet: KnowledgeGraph = {
  as_of: 't', scope: 'imported', built: 1, skipped: 0,
  nodes: ['AAPL', 'ext:nvidia', 'ext:foundry'],
  node_meta: {
    'ext:nvidia': { label: 'Nvidia', kind: 'company', source: 'imported' },
    'ext:foundry': { label: 'Foundry Co', kind: 'private_company', source: 'imported' },
  },
  edges: [
    { source: 'AAPL', target: 'ext:nvidia', type: 'partner', sentiment: 'negative', weight: 1, confidence: 1, evidence: 'imp', url: '', as_of: '', origin: 'imported' },
    { source: 'ext:nvidia', target: 'ext:foundry', type: 'supplier', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' },
  ],
};

describe('planMerge', () => {
  it('suggests a Discover ticker for a name-matched external node', () => {
    const { links } = planMerge(working, importSet, board);
    const nv = links.find((l) => l.importId === 'ext:nvidia')!;
    expect(nv.suggestion).toBe('NVDA');
    expect(nv.resolved).toBe('NVDA');
    const fo = links.find((l) => l.importId === 'ext:foundry')!;
    expect(fo.suggestion).toBeNull();
    expect(fo.resolved).toBe('ext:foundry');
  });
  it('emits no row for a node that is already a ticker', () => {
    const { links } = planMerge(working, importSet, board);
    expect(links.some((l) => l.importId === 'AAPL')).toBe(false);
  });
});

describe('applyMerge', () => {
  it('links ext:nvidia -> NVDA, collapsing onto the existing node', () => {
    const { graph, summary } = applyMerge(working, importSet, { 'ext:nvidia': 'NVDA', 'ext:foundry': 'ext:foundry' }, { dupPolicy: 'keep' });
    expect(graph.nodes).not.toContain('ext:nvidia');
    expect(graph.nodes).toContain('ext:foundry');
    expect(graph.node_meta?.['ext:nvidia']).toBeUndefined(); // ticker adopts board identity
    expect(summary.linked).toBe(1);
    // NVDA->foundry edge added (re-pointed from ext:nvidia); AAPL->NVDA partner is a duplicate
    expect(graph.edges.some((e) => e.source === 'NVDA' && e.target === 'ext:foundry')).toBe(true);
    expect(summary.duplicates).toBe(1);
  });
  it('keeps the existing edge by default on a duplicate', () => {
    const { graph } = applyMerge(working, importSet, { 'ext:nvidia': 'NVDA' }, { dupPolicy: 'keep' });
    const dup = graph.edges.find((e) => e.source === 'AAPL' && e.target === 'NVDA' && e.type === 'partner')!;
    expect(dup.sentiment).toBe('positive'); // mine kept (not the imported 'negative')
    expect(dup.evidence).toBe('news');
  });
  it('uses the imported edge when dupPolicy=import', () => {
    const { graph } = applyMerge(working, importSet, { 'ext:nvidia': 'NVDA' }, { dupPolicy: 'import' });
    const dup = graph.edges.find((e) => e.source === 'AAPL' && e.target === 'NVDA' && e.type === 'partner')!;
    expect(dup.sentiment).toBe('negative');
  });
  it('keeps native node_meta on a same-id ticker merge (no downgrade)', () => {
    const w2: KnowledgeGraph = { ...working, node_meta: { NVDA: { label: 'NVDA', kind: '', source: 'native' } } };
    const imp2: KnowledgeGraph = { ...importSet, nodes: ['NVDA'], node_meta: { NVDA: { label: 'Nvidia', kind: 'company', source: 'imported' } }, edges: [] };
    const { graph } = applyMerge(w2, imp2, {}, { dupPolicy: 'keep' });
    expect(graph.node_meta?.['NVDA']?.source).toBe('native');
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/lib/graphMerge.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `graphMerge.ts`**

Create `frontend/src/lib/graphMerge.ts`:

```ts
import type { GraphEdge, KnowledgeGraph, NodeMeta, RelationType, StockScore } from '../types';
import { normalizeName } from './graphView';

export interface MergeLinkRow {
  importId: string;          // import-set node id, e.g. 'ext:nvidia' or 'NVDA'
  label: string;             // display label
  external: boolean;         // ext:/man: or has imported node_meta
  suggestion: string | null; // suggested ticker (Discover/working match) or null
  resolved: string;          // default choice: a ticker id, or importId to keep-as-is
}

export interface MergeSummary {
  addedNodes: number;
  addedEdges: number;
  duplicates: number; // (source,target,type) present in both
  linked: number;     // import nodes re-pointed to a ticker
  merged: number;     // import tickers already present in working
}

export type DupPolicy = 'keep' | 'import';

const isExt = (id: string) => id.startsWith('ext:') || id.startsWith('man:');

/** Build the editable link rows: one per external import node, with a suggested Discover ticker. */
export function planMerge(working: KnowledgeGraph, importSet: KnowledgeGraph, board: StockScore[]): { links: MergeLinkRow[] } {
  const byTicker = new Set(board.map((s) => s.ticker.toUpperCase()));
  const byName = new Map(board.map((s) => [normalizeName(s.name), s.ticker]));
  const wmeta = working.node_meta ?? {};
  const workingByName = new Map(working.nodes.map((id) => [normalizeName(wmeta[id]?.label || id), id]));
  const meta = importSet.node_meta ?? {};

  const links: MergeLinkRow[] = [];
  for (const id of importSet.nodes) {
    if (!(isExt(id) || meta[id])) continue; // already a ticker -> merges/adds directly
    const label = meta[id]?.label || id;
    const norm = normalizeName(label);
    let suggestion: string | null = null;
    if (byName.has(norm)) suggestion = byName.get(norm)!;
    else if (byTicker.has(label.toUpperCase())) suggestion = label.toUpperCase();
    else if (workingByName.has(norm)) suggestion = workingByName.get(norm)!;
    links.push({ importId: id, label, external: true, suggestion, resolved: suggestion ?? id });
  }
  return { links };
}

/** Apply the resolved link choices + duplicate policy; pure, used for live counts and the final commit. */
export function applyMerge(
  working: KnowledgeGraph, importSet: KnowledgeGraph,
  resolved: Record<string, string>, opts: { dupPolicy: DupPolicy },
): { graph: KnowledgeGraph; summary: MergeSummary } {
  const map = (id: string) => resolved[id] ?? id;

  // 1) rewrite import nodes / meta / edges through the link map
  const importNodes = new Set<string>(importSet.nodes.map(map));
  const importMeta: Record<string, NodeMeta> = {};
  for (const [k, v] of Object.entries(importSet.node_meta ?? {})) {
    const nk = map(k);
    if (isExt(nk)) importMeta[nk] = v; // keep meta only for nodes that stay external
  }
  const rewritten: GraphEdge[] = [];
  const seen = new Set<string>();
  for (const e of importSet.edges) {
    const s = map(e.source); const t = map(e.target);
    if (s === t) continue;
    const key = `${s}|${t}|${e.type}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rewritten.push({ ...e, source: s, target: t });
  }

  // 2) union into working
  const nodeSet = new Set(working.nodes);
  const nodes = [...working.nodes];
  let addedNodes = 0;
  for (const n of importNodes) if (!nodeSet.has(n)) { nodes.push(n); nodeSet.add(n); addedNodes++; }

  const node_meta = { ...importMeta, ...(working.node_meta ?? {}) }; // working wins -> ticker keeps identity

  const idx = new Map<string, number>();
  working.edges.forEach((e, i) => idx.set(`${e.source}|${e.target}|${e.type}`, i));
  const edges = [...working.edges];
  let addedEdges = 0; let duplicates = 0;
  for (const e of rewritten) {
    const key = `${e.source}|${e.target}|${e.type}`;
    if (idx.has(key)) {
      duplicates++;
      if (opts.dupPolicy === 'import') edges[idx.get(key)!] = e;
    } else {
      idx.set(key, edges.length);
      edges.push(e);
      addedEdges++;
    }
  }

  let linked = 0; let merged = 0;
  for (const id of importSet.nodes) {
    const r = map(id);
    if (r !== id && !isExt(r)) linked++;
    else if (r === id && !isExt(id) && working.nodes.includes(id)) merged++;
  }

  return { graph: { ...working, nodes, edges, node_meta }, summary: { addedNodes, addedEdges, duplicates, linked, merged } };
}
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/lib/graphMerge.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/graphMerge.ts frontend/src/lib/graphMerge.test.ts
git commit -m "feat(graph): merge reconciliation — planMerge/applyMerge with Discover linking"
```

---

## Task 6: `GraphLegend` component

**Files:**
- Create: `frontend/src/components/GraphLegend.tsx`
- Test: `frontend/src/components/GraphLegend.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/GraphLegend.test.tsx`:

```tsx
import { expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { GraphLegend } from './GraphLegend';

it('renders the colour keys and collapses', () => {
  render(<GraphLegend />);
  expect(screen.getByText('buy')).toBeInTheDocument();
  expect(screen.getByText('imported')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /legend/i }));
  expect(screen.queryByText('buy')).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/components/GraphLegend.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/GraphLegend.tsx`:

```tsx
import { useState } from 'react';

/** Collapsible legend overlaid in a corner of the graph canvas. */
export function GraphLegend() {
  const [open, setOpen] = useState(true);
  return (
    <div className="graph-legend-overlay">
      <button type="button" className="graph-legend-toggle" onClick={() => setOpen((o) => !o)}>
        Legend {open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="graph-legend-body">
          <div className="legend-group">
            <span className="legend-title">Company</span>
            <span><i className="dot" style={{ background: '#3fb950' }} />buy</span>
            <span><i className="dot" style={{ background: '#f85149' }} />sell</span>
            <span><i className="dot" style={{ background: '#8b949e' }} />hold</span>
            <span><i className="dot" style={{ background: '#484f58' }} />unknown</span>
            <span><i className="dot" style={{ background: '#6e7681' }} />external</span>
            <span className="legend-note">size = score</span>
          </div>
          <div className="legend-group">
            <span className="legend-title">News effect</span>
            <span><i className="bar" style={{ background: '#3fb950' }} />positive</span>
            <span><i className="bar" style={{ background: '#f85149' }} />negative</span>
            <span><i className="bar" style={{ background: '#6e7681' }} />neutral</span>
          </div>
          <div className="legend-group">
            <span className="legend-title">Source</span>
            <span><i className="line solid" />news</span>
            <span><i className="line dashed" />imported</span>
            <span><i className="line dotted" />manual</span>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/components/GraphLegend.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GraphLegend.tsx frontend/src/components/GraphLegend.test.tsx
git commit -m "feat(graph): collapsible canvas legend component"
```

---

## Task 7: `GraphContextMenu` component

**Files:**
- Create: `frontend/src/components/GraphContextMenu.tsx`
- Test: `frontend/src/components/GraphContextMenu.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/GraphContextMenu.test.tsx`:

```tsx
import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { GraphContextMenu } from './GraphContextMenu';

it('renders items, fires onClick then onClose', () => {
  const onClose = vi.fn(); const onClick = vi.fn();
  render(<GraphContextMenu x={10} y={20} onClose={onClose} items={[{ label: 'Delete node', danger: true, onClick }]} />);
  fireEvent.click(screen.getByRole('menuitem', { name: /delete node/i }));
  expect(onClick).toHaveBeenCalled();
  expect(onClose).toHaveBeenCalled();
});

it('closes on Escape', () => {
  const onClose = vi.fn();
  render(<GraphContextMenu x={0} y={0} onClose={onClose} items={[{ label: 'X', onClick: vi.fn() }]} />);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/components/GraphContextMenu.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/GraphContextMenu.tsx`:

```tsx
import { useEffect, useRef } from 'react';

export interface MenuItem { label: string; onClick: () => void; danger?: boolean }
export interface GraphContextMenuProps { items: MenuItem[]; x: number; y: number; onClose: () => void }

/** A small right-click menu positioned at (x, y) inside the canvas; closes on outside-click / Escape. */
export function GraphContextMenu({ items, x, y, onClose }: GraphContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [onClose]);

  return (
    <div ref={ref} className="graph-ctx-menu" style={{ left: x, top: y }} role="menu">
      {items.map((it) => (
        <button
          key={it.label} type="button" role="menuitem"
          className={`graph-ctx-item${it.danger ? ' danger' : ''}`}
          onClick={() => { it.onClick(); onClose(); }}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/components/GraphContextMenu.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GraphContextMenu.tsx frontend/src/components/GraphContextMenu.test.tsx
git commit -m "feat(graph): right-click context-menu component"
```

---

## Task 8: `MergePreview` component

**Files:**
- Create: `frontend/src/components/MergePreview.tsx`
- Test: `frontend/src/components/MergePreview.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/MergePreview.test.tsx`:

```tsx
import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MergePreview } from './MergePreview';
import type { KnowledgeGraph, StockScore } from '../types';

const board: StockScore[] = [
  { ticker: 'NVDA', name: 'NVIDIA Corporation', sector: 'Tech', price: 1, change_pct: 0, score: 70, direction: 'buy', reasons: [], components: {}, as_of: '', net: 0 },
];
const working: KnowledgeGraph = { as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0, nodes: ['AAPL'], node_meta: {}, edges: [] };
const importSet: KnowledgeGraph = {
  as_of: 't', scope: 'imported', built: 1, skipped: 0, nodes: ['AAPL', 'ext:nvidia'],
  node_meta: { 'ext:nvidia': { label: 'Nvidia', kind: 'company', source: 'imported' } },
  edges: [{ source: 'AAPL', target: 'ext:nvidia', type: 'partner', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' }],
};

it('applies with the suggested Discover link by default', () => {
  const onApply = vi.fn();
  render(<MergePreview working={working} importSet={importSet} board={board} onApply={onApply} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: /apply merge/i }));
  const merged = onApply.mock.calls[0][0] as KnowledgeGraph;
  expect(merged.nodes).toContain('NVDA');
  expect(merged.nodes).not.toContain('ext:nvidia');
});

it('keeps it external when the dropdown is set to keep', () => {
  const onApply = vi.fn();
  render(<MergePreview working={working} importSet={importSet} board={board} onApply={onApply} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByDisplayValue(/NVDA/), { target: { value: 'ext:nvidia' } });
  fireEvent.click(screen.getByRole('button', { name: /apply merge/i }));
  const merged = onApply.mock.calls[0][0] as KnowledgeGraph;
  expect(merged.nodes).toContain('ext:nvidia');
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/components/MergePreview.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/MergePreview.tsx`:

```tsx
import { useMemo, useState } from 'react';
import type { KnowledgeGraph, StockScore } from '../types';
import { applyMerge, planMerge, type DupPolicy } from '../lib/graphMerge';

export interface MergePreviewProps {
  working: KnowledgeGraph;
  importSet: KnowledgeGraph;
  board: StockScore[];
  onApply: (merged: KnowledgeGraph) => void;
  onCancel: () => void;
}

/** Preview the merge of one import set: link externals to Discover tickers, resolve duplicates. */
export function MergePreview({ working, importSet, board, onApply, onCancel }: MergePreviewProps) {
  const plan = useMemo(() => planMerge(working, importSet, board), [working, importSet, board]);
  const [resolved, setResolved] = useState<Record<string, string>>(
    () => Object.fromEntries(plan.links.map((l) => [l.importId, l.resolved])),
  );
  const [dupPolicy, setDupPolicy] = useState<DupPolicy>('keep');
  const tickers = useMemo(() => [...board].sort((a, b) => a.ticker.localeCompare(b.ticker)), [board]);

  const { graph, summary } = useMemo(
    () => applyMerge(working, importSet, resolved, { dupPolicy }),
    [working, importSet, resolved, dupPolicy],
  );

  return (
    <div className="merge-preview">
      <h4>Merge into graph</h4>
      {plan.links.length > 0 ? (
        <div className="merge-links">
          <span className="label">Link imported companies</span>
          {plan.links.map((l) => (
            <label key={l.importId} className="merge-link-row">
              <span className="merge-link-label">{l.label}</span>
              <select value={resolved[l.importId]} onChange={(e) => setResolved((r) => ({ ...r, [l.importId]: e.target.value }))}>
                <option value={l.importId}>keep as external</option>
                {tickers.map((s) => (
                  <option key={s.ticker} value={s.ticker}>{s.ticker} — {s.name}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      ) : (
        <p className="muted">No external companies to link.</p>
      )}

      <label className="merge-duppolicy">
        Duplicate relationships:{' '}
        <select value={dupPolicy} onChange={(e) => setDupPolicy(e.target.value as DupPolicy)}>
          <option value="keep">keep mine</option>
          <option value="import">use imported</option>
        </select>
      </label>

      <p className="muted merge-summary">
        +{summary.addedNodes} nodes, +{summary.addedEdges} edges · {summary.linked} linked ·{' '}
        {summary.merged} already in graph · {summary.duplicates} duplicate{summary.duplicates === 1 ? '' : 's'}
      </p>

      <div className="graph-actions">
        <button onClick={() => onApply(graph)}>Apply merge</button>
        <button className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/components/MergePreview.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MergePreview.tsx frontend/src/components/MergePreview.test.tsx
git commit -m "feat(graph): merge preview component (link + dedupe)"
```

---

## Task 9: `GraphCanvas` — legend, right-click, manual dash

**Files:**
- Modify: `frontend/src/components/GraphCanvas.tsx` (whole file rewritten below)

No new unit test (the `ForceGraph2D` canvas can't render in jsdom — the existing repo has no `GraphCanvas.test`). Verified via `tsc -b` here and the `Graph.test.tsx` mock + smoke in later tasks.

- [ ] **Step 1: Rewrite the component**

Replace the entire contents of `frontend/src/components/GraphCanvas.tsx` with:

```tsx
import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { directionColor, nodeRadius, sentimentColor, type ViewLink, type ViewNode } from '../lib/graphView';
import { GraphLegend } from './GraphLegend';
import { GraphContextMenu, type MenuItem } from './GraphContextMenu';
import type { RelationType } from '../types';

export interface GraphCanvasProps {
  nodes: ViewNode[];
  links: ViewLink[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAddRelationship: (sourceId: string) => void;
  onDeleteNode: (id: string) => void;
  onDeleteEdge: (ref: { source: string; target: string; type: RelationType }) => void;
}

interface Menu { x: number; y: number; items: MenuItem[] }

export function GraphCanvas({
  nodes, links, selectedId, onSelect, onAddRelationship, onDeleteNode, onDeleteEdge,
}: GraphCanvasProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 600, height: 480 });
  const [menu, setMenu] = useState<Menu | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setDims({ width: entry.contentRect.width, height: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

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
  const endpointId = (v: unknown): string => (typeof v === 'object' && v ? (v as { id: string }).id : (v as string));
  const localXY = (e: MouseEvent) => {
    const r = wrap.current?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) };
  };

  return (
    <div ref={wrap} className="graph-canvas" onContextMenu={(e) => e.preventDefault()}>
      <ForceGraph2D
        width={dims.width}
        height={dims.height}
        graphData={data}
        nodeRelSize={1}
        nodeVal={(n: any) => nodeRadius(n.score) ** 2}
        nodeColor={(n: any) => (isDim(n.id) ? '#30363d' : n.external ? '#6e7681' : directionColor(n.direction))}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(n: any, ctx: CanvasRenderingContext2D, scale: number) => {
          ctx.fillStyle = isDim(n.id) ? '#6e7681' : '#e6edf3';
          ctx.font = `${10 / scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(n.label, n.x, n.y - nodeRadius(n.score) - 2 / scale);
        }}
        linkColor={(l: any) => sentimentColor(l.sentiment)}
        linkWidth={(l: any) => 0.5 + l.weight * l.confidence * 2}
        linkLineDash={(l: any) => (l.origin === 'imported' ? [4, 2] : l.origin === 'manual' ? [1, 3] : [])}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel={(l: any) => `${l.type} · ${l.sentiment}${l.evidence ? ` · ${l.evidence}` : ''}`}
        onNodeClick={(n: any) => onSelect(n.id)}
        onNodeRightClick={(n: any, e: MouseEvent) => {
          e.preventDefault();
          setMenu({
            ...localXY(e),
            items: [
              { label: 'Add relationship', onClick: () => onAddRelationship(n.id) },
              { label: 'Delete node', danger: true, onClick: () => onDeleteNode(n.id) },
            ],
          });
        }}
        onLinkRightClick={(l: any, e: MouseEvent) => {
          e.preventDefault();
          const ref = { source: endpointId(l.source), target: endpointId(l.target), type: l.type as RelationType };
          setMenu({ ...localXY(e), items: [{ label: 'Delete relationship', danger: true, onClick: () => onDeleteEdge(ref) }] });
        }}
      />
      <GraphLegend />
      {menu && <GraphContextMenu items={menu.items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npm run build`
Expected: FAIL — `pages/Graph.tsx` does not yet pass the three new props (`onAddRelationship`/`onDeleteNode`/`onDeleteEdge`). That is expected; Task 11 wires them. To verify *this file* in isolation, instead run `cd frontend && npx vitest run src/components/GraphLegend.test.tsx src/components/GraphContextMenu.test.tsx` (both PASS) and proceed — `npm run build` goes green at the end of Task 11.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphCanvas.tsx
git commit -m "feat(graph): canvas legend + right-click add/delete + manual dash"
```

---

## Task 10: `GraphSidebar` — relationship form, merge button, target field

**Files:**
- Modify: `frontend/src/components/GraphSidebar.tsx`
- Test: `frontend/src/components/GraphSidebar.test.tsx` (extend `base()` + add cases)

- [ ] **Step 1: Extend the test `base()` and add failing cases**

In `frontend/src/components/GraphSidebar.test.tsx`, add the new props to `base()` (inside the returned object, before `promptDefault`):

```ts
    addingFrom: null as string | null,
    onSubmitRelationship: vi.fn(),
    onCancelRelationship: vi.fn(),
    onMergeImport: vi.fn(),
    board: [] as import('../types').StockScore[],
```

Then add these cases at the end of the file:

```ts
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx`
Expected: FAIL — new props/UI not present.

- [ ] **Step 3: Extend the props interface**

In `frontend/src/components/GraphSidebar.tsx`, update the imports (line ~3) and the `GraphSidebarProps` interface. Change the type import line to:

```ts
import type { EdgeSentiment, ImportReport, ImportSetSummary, RelationType, SavedGraphSummary, StockScore } from '../types';
```

(If `EdgeSentiment` isn't exported from `types.ts`, add `export type EdgeSentiment = 'positive' | 'negative' | 'neutral';` near the top of `types.ts`.) Then add to `GraphSidebarProps`:

```ts
  addingFrom: string | null;
  onSubmitRelationship: (data: { target: string; type: RelationType; sentiment: EdgeSentiment; note: string }) => void;
  onCancelRelationship: () => void;
  onMergeImport: (id: string) => void;
  board: StockScore[];
```

and destructure them in the component body (add to the `const { … } = props;` list):

```ts
    addingFrom, onSubmitRelationship, onCancelRelationship, onMergeImport, board,
```

- [ ] **Step 4: Add local form state + the relationship form**

Add state near the other `useState`s (~line 45):

```ts
  const [relTarget, setRelTarget] = useState('');
  const [relType, setRelType] = useState<RelationType>('supplier');
  const [relEffect, setRelEffect] = useState<EdgeSentiment>('positive');
  const [relNote, setRelNote] = useState('');

  const submitRel = () => {
    if (!relTarget.trim()) return;
    onSubmitRelationship({ target: relTarget.trim(), type: relType, sentiment: relEffect, note: relNote.trim() });
    setRelTarget(''); setRelType('supplier'); setRelEffect('positive'); setRelNote('');
  };
```

Then, inside the `{tab === 'explore' && (...)}` block, render the form at the top of the `<div className="graph-tab">` (just after the opening tag) so it appears when adding:

```tsx
          {addingFrom && (
            <div className="graph-section rel-form">
              <span className="label">Add relationship from <b>{addingFrom}</b></span>
              <input
                placeholder="Target (ticker or company)"
                value={relTarget}
                onChange={(e) => setRelTarget(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') submitRel(); }}
              />
              <select value={relType} onChange={(e) => setRelType(e.target.value as RelationType)} aria-label="relationship type">
                {EDGE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <select value={relEffect} onChange={(e) => setRelEffect(e.target.value as EdgeSentiment)} aria-label="effect on source">
                <option value="positive">helps</option>
                <option value="negative">hurts</option>
                <option value="neutral">neutral</option>
              </select>
              <input placeholder="Note (optional)" value={relNote} onChange={(e) => setRelNote(e.target.value)} />
              <div className="graph-actions">
                <button onClick={submitRel}>Add</button>
                <button className="secondary" onClick={onCancelRelationship}>Cancel</button>
              </div>
            </div>
          )}
```

(`board` is available for the page to resolve targets; the sidebar passes raw text up via `onSubmitRelationship`, so it needs no board lookup itself. The `board` prop is wired for symmetry/future use and consumed by `pages/Graph.tsx`.)

- [ ] **Step 5: Remove the duplicate legend colour line**

In the `selected ? (...) : (...)` block, replace the empty-state legend (the `<div className="graph-legend">…</div>` containing the colour `<p className="label">…buy…sell…hold…</p>`) with just the hint:

```tsx
          ) : (
            <div className="graph-legend">
              <p className="muted">Click a node for its detail, then Expand to grow the graph. Right-click a node or edge to add or delete.</p>
            </div>
          )}
```

- [ ] **Step 6: Add the Merge button to each import-set row**

In the `{tab === 'import' && (...)}` block, find the import-set row and add a Merge button before the delete `✕`:

```tsx
                  <div key={s.id} className="graph-save-row">
                    <span>{s.name || '(unnamed)'} · {s.edge_count} edges</span>
                    <button className="linklike" aria-label={`merge ${s.name || s.id}`} onClick={() => onMergeImport(s.id)}>Merge into graph</button>
                    <button className="icon-btn" aria-label={`delete ${s.name || s.id}`} onClick={() => onDeleteImport(s.id)}>✕</button>
                  </div>
```

- [ ] **Step 7: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx`
Expected: PASS (existing + 2 new).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphSidebar.test.tsx frontend/src/types.ts
git commit -m "feat(graph): sidebar relationship form + merge button + target field"
```

---

## Task 11: `pages/Graph.tsx` — wire merge, manual edit, dirty, prompt target

**Files:**
- Modify: `frontend/src/pages/Graph.tsx`
- Test: `frontend/src/pages/Graph.test.tsx` (update the `GraphCanvas` mock + add cases)

- [ ] **Step 1: Update the canvas mock + add failing cases**

In `frontend/src/pages/Graph.test.tsx`, replace the `vi.mock('../components/GraphCanvas', …)` block (lines ~9-15) so the mock exposes the new callbacks:

```tsx
vi.mock('../components/GraphCanvas', () => ({
  GraphCanvas: ({ nodes, onSelect, onDeleteNode, onAddRelationship }: {
    nodes: { id: string }[]; onSelect: (id: string) => void;
    onDeleteNode: (id: string) => void; onAddRelationship: (id: string) => void;
  }) => (
    <div data-testid="graph-canvas">
      {nodes.map((n) => <button key={n.id} onClick={() => onSelect(n.id)}>{`sel-${n.id}`}</button>)}
      {nodes.map((n) => <button key={`del-${n.id}`} onClick={() => onDeleteNode(n.id)}>{`del-${n.id}`}</button>)}
      {nodes.map((n) => <button key={`add-${n.id}`} onClick={() => onAddRelationship(n.id)}>{`add-${n.id}`}</button>)}
    </div>
  ),
}));
```

Add `getImportSet: vi.fn()` to the mocked `api` object (in the `vi.mock('../api/client', …)` block). Then add these cases at the end:

```tsx
it('deletes a node from the working graph', async () => {
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npx vitest run src/pages/Graph.test.tsx`
Expected: FAIL — delete/add not wired; counts unchanged.

- [ ] **Step 3: Wire the page**

In `frontend/src/pages/Graph.tsx`:

(a) Update imports — extend the `graphView` import and add `graphMerge` + `MergePreview` + `client`:

```ts
import {
  addManualEdge, addManualNode, applyFilters, deleteEdge, deleteNode, mergeGraph, mergeNodes,
  resolveManualTarget, toLinks, type ViewNode,
} from '../lib/graphView';
import { MergePreview } from '../components/MergePreview';
import { api } from '../api/client';
import type { EdgeSentiment, GraphEdge, ImportReport, KnowledgeGraph, RelationType } from '../types';
```

(`ImportReport` is already imported in the existing file — keep a single import; this list shows the full set the file needs.)

(b) Add state (after the existing `notice` state, ~line 55):

```ts
  const [addingFrom, setAddingFrom] = useState<string | null>(null);
  const [mergeImport, setMergeImport] = useState<KnowledgeGraph | null>(null);
  const [dirty, setDirty] = useState(false);
```

(c) Add handlers (after `toggleType`, ~line 119):

```ts
  const startMerge = async (id: string) => {
    setNotice(null);
    try {
      const set = await api.getImportSet(id);
      setMergeImport(set); setTab('import');
    } catch { setNotice('Could not load that import set.'); }
  };
  const applyMergeResult = (merged: KnowledgeGraph) => {
    setWorking(merged); setMergeImport(null); setDirty(true);
  };
  const addRelationship = (data: { target: string; type: RelationType; sentiment: EdgeSentiment; note: string }) => {
    if (!working || !addingFrom) return;
    const t = resolveManualTarget(data.target, working, board.data?.items ?? []);
    const edge: GraphEdge = {
      source: addingFrom, target: t.id, type: data.type, sentiment: data.sentiment,
      weight: 0.5, confidence: 0.9, evidence: data.note, url: '', as_of: new Date().toISOString(), origin: 'manual',
    };
    // For a brand-new concept/external target, create it with its human label first (so it isn't
    // labelled by its id); addManualEdge then attaches the edge (no-op node-create for existing ids).
    const base = t.external && t.isNew ? addManualNode(working, { id: t.id, label: t.label }) : working;
    setWorking(addManualEdge(base, edge)); setDirty(true); setAddingFrom(null);
  };
  const removeNode = (id: string) => {
    if (!working) return;
    const hasEdges = working.edges.some((e) => e.source === id || e.target === id);
    if (hasEdges && !window.confirm(`Delete ${id} and its relationships?`)) return;
    setWorking(deleteNode(working, id));
    if (selectedId === id) setSelectedId(null);
    setDirty(true);
  };
  const removeEdge = (ref: { source: string; target: string; type: RelationType }) => {
    if (!working) return;
    setWorking(deleteEdge(working, ref)); setDirty(true);
  };
```

(d) Reset `dirty` in the lifecycle handlers — add `setDirty(false);` to `loadRoot` (after `setTab('explore')`), `doLoadSaved` (after setting working), `clearGraph`, and after a successful `doSave` (in the `try` after `saveGraph.mutateAsync`).

(e) Pass new props to `GraphCanvas` (replace the existing `<GraphCanvas … />`):

```tsx
          <GraphCanvas
            nodes={view.nodes} links={view.links} selectedId={selectedId} onSelect={selectNode}
            onAddRelationship={(id) => { setAddingFrom(id); setTab('explore'); }}
            onDeleteNode={removeNode}
            onDeleteEdge={removeEdge}
          />
```

(f) Pass new props to `GraphSidebar` (add to the existing element), and change `promptDefault` to prefer the selected node:

```tsx
        addingFrom={addingFrom}
        onSubmitRelationship={addRelationship}
        onCancelRelationship={() => setAddingFrom(null)}
        onMergeImport={startMerge}
        board={board.data?.items ?? []}
        promptDefault={selectedId || root || ''}
```

(g) Render the `MergePreview` — when `mergeImport` is set and the Import tab is active, show it. Add it inside the `graph-main` panel just below the canvas, or pass through the sidebar. Simplest: render above the sidebar's Import tab content by placing it in `graph-main`. Add after the `<GraphCanvas …/>`/empty block, inside `graph-main`:

```tsx
        {mergeImport && working && (
          <MergePreview
            working={working} importSet={mergeImport} board={board.data?.items ?? []}
            onApply={applyMergeResult} onCancel={() => setMergeImport(null)}
          />
        )}
```

(h) Surface the unsaved hint near the node/edge counts is handled in the sidebar via `canSave`; add a minimal hint in `graph-main`:

```tsx
        {dirty && <p className="muted unsaved-hint">Unsaved changes — click Save to keep them.</p>}
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `cd frontend && npx vitest run src/pages/Graph.test.tsx`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Full type-check + whole suite**

Run: `cd frontend && npm run build && npx vitest run`
Expected: PASS — build green (Task 9's props now satisfied), all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Graph.tsx frontend/src/pages/Graph.test.tsx
git commit -m "feat(graph): wire merge preview, manual add/delete, dirty hint, prompt target"
```

---

## Task 12: Styles

**Files:**
- Modify: `frontend/src/styles.css` (append a graph-editing block)

No test (visual). Verified in the Task 14 smoke.

- [ ] **Step 1: Append styles**

Append to `frontend/src/styles.css`:

```css
/* graph editing: context menu, legend overlay, merge preview, relationship form */
.graph-canvas { position: relative; }
.graph-ctx-menu {
  position: absolute; z-index: 20; min-width: 150px; padding: 4px;
  background: #161b22; border: 1px solid #30363d; border-radius: 6px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.5); display: flex; flex-direction: column;
}
.graph-ctx-item {
  text-align: left; background: none; border: 0; color: #e6edf3;
  padding: 6px 10px; border-radius: 4px; cursor: pointer; font-size: 13px;
}
.graph-ctx-item:hover { background: #21262d; }
.graph-ctx-item.danger { color: #f85149; }

.graph-legend-overlay {
  position: absolute; left: 10px; bottom: 10px; z-index: 10;
  background: rgba(13, 17, 23, 0.85); border: 1px solid #30363d; border-radius: 6px;
  padding: 6px 8px; font-size: 11px; color: #8b949e; max-width: 230px;
}
.graph-legend-toggle { background: none; border: 0; color: #8b949e; cursor: pointer; font-size: 11px; padding: 0 0 4px; }
.graph-legend-body { display: flex; flex-direction: column; gap: 6px; }
.legend-group { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
.legend-title { color: #6e7681; width: 100%; text-transform: uppercase; letter-spacing: 0.04em; font-size: 9px; }
.legend-group .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; vertical-align: middle; }
.legend-group .bar { display: inline-block; width: 12px; height: 3px; margin-right: 3px; vertical-align: middle; }
.legend-group .line { display: inline-block; width: 16px; height: 0; margin-right: 3px; vertical-align: middle; border-top: 2px solid #8b949e; }
.legend-group .line.dashed { border-top-style: dashed; }
.legend-group .line.dotted { border-top-style: dotted; }
.legend-note { color: #6e7681; font-style: italic; }

.merge-preview { border: 1px solid #30363d; border-radius: 8px; padding: 12px; margin-top: 12px; background: #0d1117; }
.merge-preview h4 { margin: 0 0 8px; }
.merge-links { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
.merge-link-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.merge-link-label { font-weight: 600; }
.merge-duppolicy { display: block; margin: 8px 0; }
.merge-summary { margin: 8px 0; }

.rel-form { display: flex; flex-direction: column; gap: 6px; }
.unsaved-hint { color: #e8c87e; }
```

- [ ] **Step 2: Build to confirm CSS is valid**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles.css
git commit -m "style(graph): context menu, legend overlay, merge preview, relationship form"
```

---

## Task 13: Documentation

**Files:**
- Modify: `README.md`, `frontend/README.md`, `backend/README.md`

No test. Keep it factual and short.

- [ ] **Step 1: Update `frontend/README.md`**

In the **Graph** bullet (line ~25), append after the Import-tab sentence:

```
Each imported set can be **merged into the current graph** with a conflict-resolution preview (links imported companies to the Discover list, collapses clashing nodes, dedupes relationships) so Save keeps them permanently. **Right-click** a node to add a relationship or delete it, or an edge to delete it; a collapsible **legend** on the canvas explains node/edge colours and styles.
```

- [ ] **Step 2: Update `backend/README.md`**

In the graph endpoints list, add the new route:

```
- `GET /api/graph/imports/{id}` — one import set's graph (for the merge-into-graph preview).
```

- [ ] **Step 3: Update the root `README.md`**

In the knowledge-graph feature bullet, append: "merge imported sets into a saved company graph (with conflict resolution + Discover linking), edit nodes/relationships by right-click, and an on-canvas legend."

- [ ] **Step 4: Commit**

```bash
git add README.md frontend/README.md backend/README.md
git commit -m "docs(graph): document merge-into-graph, manual edit, and legend"
```

---

## Task 14: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Backend tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS (full suite green).

- [ ] **Step 2: Frontend build + tests**

Run: `cd frontend && npm run build && npx vitest run`
Expected: PASS (`tsc -b` clean; all vitest suites green).

- [ ] **Step 3: Live browser smoke (isolated cache)**

Back up `backend/data/app.db` (copy aside), start the backend with a temp `DATA_DIR` and the Vite dev server, then in the preview: explore a company (e.g. `AAPL`), import a small model via the Import tab, click **Merge into graph**, confirm the preview links an external company to its Discover ticker, **Apply**, then **Save**; right-click a node → **Add relationship** (target a ticker and a free-text concept), right-click the new edge → **Delete relationship**; confirm the **legend** toggles. Restore the backed-up `app.db` afterward (same protocol as prior graph phases). Check `preview_console_logs` for errors. (Note: `preview_screenshot` may time out on the chart-heavy Dashboard but the Graph page is fine; if it stalls, verify via `preview_snapshot` + geometry instead.)

- [ ] **Step 4: Commit any smoke fixes, then finish**

Use **superpowers:finishing-a-development-branch** to complete (merge to master locally, per the project convention).

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:
- §1 data model → Task 1. §2 merge + reconciliation → Tasks 2,3,5,8,10,11. §2b iterative prompt target → Task 11 (`promptDefault={selectedId || root}`). §3 manual add/delete → Tasks 4,7,9,10,11. §4 legend → Task 6,9. §5 persistence/dirty → Task 11. §6 files → all. API → Task 2. Testing → per-task tests + Task 14.

**2. Placeholder scan** — no "TBD"/"handle edge cases"/"similar to". Every code step shows code; every test step shows assertions; commands have expected output. The one judgement call (`addNodeWithLabel` helper to preserve concept labels) is spelled out with code.

**3. Type consistency** — names match across tasks: `resolveManualTarget`/`addManualEdge`/`addManualNode`/`deleteNode`/`deleteEdge` (Task 4) used in Task 11; `planMerge`/`applyMerge`/`MergeLinkRow`/`MergeSummary`/`DupPolicy` (Task 5) used in Tasks 8,11; `normalizeName` lives in `graphView.ts` (Task 4) and is imported by `graphMerge.ts` (Task 5) — ordering is correct (Task 4 precedes Task 5). `getImportSet` (Task 3) used in Task 11. `GraphContextMenu`/`MenuItem` (Task 7) used in Task 9. `onAddRelationship`/`onDeleteNode`/`onDeleteEdge` props consistent between Task 9 (canvas) and Task 11 (page). `onSubmitRelationship`/`onMergeImport`/`addingFrom`/`board` props consistent between Task 10 (sidebar) and Task 11 (page). `EdgeSentiment` ensured exported in Task 10.

**Note on build ordering:** Task 9 leaves `npm run build` red (canvas needs props the page passes in Task 11); this is called out explicitly in Task 9 Step 2 and goes green in Task 11 Step 5. Per-file vitest suites stay green throughout.
