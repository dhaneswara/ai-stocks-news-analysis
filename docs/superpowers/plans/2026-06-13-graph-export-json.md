# Export working graph to JSON — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Export" button to the Graph page that downloads the current working canvas as a `.json` file in the import-model shape the existing Import tab already accepts.

**Architecture:** Frontend-only. A pure transform (`toImportModel`) maps the working `KnowledgeGraph` into the import-model object; a tiny DOM helper (`downloadText`) saves it as a file. The Graph page wires a button to those. The file round-trips through the existing `POST /api/graph/import` via the Import tab's file upload — no backend changes.

**Tech Stack:** TypeScript, React, Vitest, @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-06-13-graph-export-json-design.md`

**Conventions:** Conventional Commits, **no `Co-Authored-By` trailer**. All commands run from `frontend/`. Single-file test run: `npx vitest run <path>`.

---

## File Structure

- **Create** `frontend/src/lib/graphExport.ts` — pure: `toImportModel`, `exportFilename`, and the `ImportModel` type. No I/O.
- **Create** `frontend/src/lib/graphExport.test.ts` — unit tests for the above.
- **Create** `frontend/src/lib/download.ts` — `downloadText(filename, text, mime?)` Blob+anchor helper (the only DOM side-effect).
- **Create** `frontend/src/lib/download.test.ts` — unit test for the helper.
- **Modify** `frontend/src/pages/Graph.tsx` — import the two libs, add a `doExport` handler, add the Export button to `.ontology-bar`.
- **Modify** `frontend/src/pages/Graph.test.tsx` — a test that clicking Export calls `downloadText` with the right filename and content.

---

## Task 1: Pure export transform (`graphExport.ts`)

**Files:**
- Create: `frontend/src/lib/graphExport.ts`
- Test: `frontend/src/lib/graphExport.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/graphExport.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { exportFilename, toImportModel } from './graphExport';
import type { KnowledgeGraph } from '../types';

const GRAPH: KnowledgeGraph = {
  as_of: '2026-06-13', scope: 'active', built: 1, skipped: 0,
  nodes: ['NVDA', 'ext:acme', 'man:project-x'],
  edges: [
    {
      source: 'NVDA', target: 'ext:acme', type: 'supplier', sentiment: 'positive',
      weight: 0.8, confidence: 0.7, evidence: 'deal', url: 'http://x', as_of: '2026-06-01',
      origin: 'manual',
    },
  ],
  node_meta: {
    'ext:acme': { label: 'Acme Corp', kind: 'private_company', source: 'imported' },
    'man:project-x': { label: 'Project X', kind: 'product', source: 'manual' },
  },
};

describe('toImportModel', () => {
  it('maps node label/kind from node_meta, falling back to the id', () => {
    const m = toImportModel(GRAPH, 'Tech');
    expect(m.nodes).toContainEqual({ id: 'NVDA', label: 'NVDA', kind: '' });
    expect(m.nodes).toContainEqual({ id: 'ext:acme', label: 'Acme Corp', kind: 'private_company' });
    expect(m.nodes).toContainEqual({ id: 'man:project-x', label: 'Project X', kind: 'product' });
  });

  it('projects edges to the import shape, dropping origin and per-edge as_of', () => {
    const m = toImportModel(GRAPH, 'Tech');
    expect(m.edges).toEqual([
      {
        source: 'NVDA', target: 'ext:acme', type: 'supplier', sentiment: 'positive',
        weight: 0.8, confidence: 0.7, evidence: 'deal', url: 'http://x',
      },
    ]);
    expect(m.edges[0]).not.toHaveProperty('origin');
    expect(m.edges[0]).not.toHaveProperty('as_of');
  });

  it('passes name through and takes as_of from the graph', () => {
    const m = toImportModel(GRAPH, 'Tech');
    expect(m.name).toBe('Tech');
    expect(m.as_of).toBe('2026-06-13');
  });

  it('handles a graph with no node_meta and an empty graph', () => {
    const bare: KnowledgeGraph = {
      as_of: '', scope: 'active', built: 0, skipped: 0, nodes: ['AAPL'], edges: [],
    };
    expect(toImportModel(bare, '').nodes).toEqual([{ id: 'AAPL', label: 'AAPL', kind: '' }]);
    const empty: KnowledgeGraph = { as_of: '', scope: 'active', built: 0, skipped: 0, nodes: [], edges: [] };
    const m = toImportModel(empty, '');
    expect(m.nodes).toEqual([]);
    expect(m.edges).toEqual([]);
    expect(m.as_of).toBe('');
  });
});

describe('exportFilename', () => {
  it('slugs the name and appends .json', () => {
    expect(exportFilename('My Tech Graph!')).toBe('my-tech-graph.json');
  });
  it('falls back to graph.json for empty or punctuation-only names', () => {
    expect(exportFilename('')).toBe('graph.json');
    expect(exportFilename('  ---  ')).toBe('graph.json');
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/lib/graphExport.test.ts`
Expected: FAIL — `Failed to resolve import "./graphExport"` (module does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/graphExport.ts`:

```ts
/** Serialize the working graph into the import-model JSON shape `normalize_import` accepts.
 *  Lossy by design (see the spec): origin and per-edge as_of are dropped; tickers are
 *  re-resolved on import. The file round-trips through the existing Import tab's file upload. */
import type { KnowledgeGraph } from '../types';

export interface ImportModelNode {
  id: string;
  label: string;
  kind: string;
}

export interface ImportModelEdge {
  source: string;
  target: string;
  type: string;
  sentiment: string;
  weight: number;
  confidence: number;
  evidence: string;
  url: string;
}

export interface ImportModel {
  name: string;
  as_of: string;
  nodes: ImportModelNode[];
  edges: ImportModelEdge[];
}

export function toImportModel(graph: KnowledgeGraph, name: string): ImportModel {
  const meta = graph.node_meta ?? {};
  return {
    name,
    as_of: graph.as_of ?? '',
    nodes: graph.nodes.map((id) => ({
      id,
      label: meta[id]?.label || id, // empty/missing label -> the id is the useful display value
      kind: meta[id]?.kind || '',
    })),
    edges: graph.edges.map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
      sentiment: e.sentiment,
      weight: e.weight,
      confidence: e.confidence,
      evidence: e.evidence,
      url: e.url,
    })),
  };
}

export function exportFilename(name: string): string {
  const slug = (name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return `${slug || 'graph'}.json`;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/lib/graphExport.test.ts`
Expected: PASS (all cases in both `describe` blocks).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/graphExport.ts frontend/src/lib/graphExport.test.ts
git commit -m "feat(frontend): pure toImportModel/exportFilename graph-export transform"
```

---

## Task 2: Download helper (`download.ts`)

**Files:**
- Create: `frontend/src/lib/download.ts`
- Test: `frontend/src/lib/download.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/download.test.ts`:

```ts
import { afterEach, expect, it, vi } from 'vitest';
import { downloadText } from './download';

const origCreate = URL.createObjectURL;
const origRevoke = URL.revokeObjectURL;
afterEach(() => {
  URL.createObjectURL = origCreate;
  URL.revokeObjectURL = origRevoke;
  vi.restoreAllMocks();
});

it('creates an object URL, clicks an anchor with the filename, and revokes the URL', () => {
  URL.createObjectURL = vi.fn(() => 'blob:abc');
  URL.revokeObjectURL = vi.fn();
  let downloadAttr = '';
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    downloadAttr = this.download;
  });

  downloadText('graph.json', '{"a":1}');

  expect(URL.createObjectURL).toHaveBeenCalledOnce();
  expect(click).toHaveBeenCalledOnce();
  expect(downloadAttr).toBe('graph.json');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:abc');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/lib/download.test.ts`
Expected: FAIL — `Failed to resolve import "./download"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/download.ts`:

```ts
/** Trigger a browser download of `text` as a file named `filename`. */
export function downloadText(filename: string, text: string, mime = 'application/json'): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/lib/download.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/download.ts frontend/src/lib/download.test.ts
git commit -m "feat(frontend): downloadText blob helper"
```

---

## Task 3: Wire the Export button into the Graph page

**Files:**
- Modify: `frontend/src/pages/Graph.tsx` (imports near top; `doExport` handler near `doSaveAs` ~line 105; button in `.ontology-bar` after the "New" button ~line 275)
- Test: `frontend/src/pages/Graph.test.tsx`

- [ ] **Step 1: Write the failing test**

Add the `download` mock to the existing mocks near the top of `frontend/src/pages/Graph.test.tsx` (after the `vi.mock('../api/client', …)` block, ~line 41), then add the import line and the test.

Add the mock + import (top of file, alongside the other `vi.mock`/`import` lines):

```ts
vi.mock('../lib/download', () => ({ downloadText: vi.fn() }));
import { downloadText } from '../lib/download';
```

Add this test (e.g. after the "saves the working graph as a named ontology" test, ~line 122). It reuses the existing `renderGraph()` and `addCompany()` helpers:

```ts
it('exports the working graph as JSON via the Export button', async () => {
  renderGraph();
  await addCompany('AAPL');
  fireEvent.change(screen.getByRole('textbox', { name: /ontology name/i }), { target: { value: 'Tech' } });
  fireEvent.click(screen.getByRole('button', { name: /^export$/i }));
  expect(downloadText).toHaveBeenCalledWith('tech.json', expect.stringContaining('"AAPL"'));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/pages/Graph.test.tsx -t "exports the working graph"`
Expected: FAIL — no button matches `/^export$/i` (button not added yet).

- [ ] **Step 3: Add the imports to `Graph.tsx`**

At the top of `frontend/src/pages/Graph.tsx`, after the existing `import { api } from '../api/client';` line (~line 13), add:

```ts
import { exportFilename, toImportModel } from '../lib/graphExport';
import { downloadText } from '../lib/download';
```

- [ ] **Step 4: Add the `doExport` handler**

In `frontend/src/pages/Graph.tsx`, immediately after the `doSaveAs` function (the block ending ~line 118, before `doNew`), add:

```ts
  const doExport = () => {
    if (!working) return;
    downloadText(exportFilename(ontologyName), JSON.stringify(toImportModel(working, ontologyName), null, 2));
  };
```

- [ ] **Step 5: Add the Export button to the toolbar**

In `frontend/src/pages/Graph.tsx`, in the `.ontology-bar` block, after the `<button className="secondary" onClick={doNew}>New</button>` line (~line 275), add:

```tsx
          <button
            className="secondary" disabled={!working || working.nodes.length === 0}
            title="Download this graph as JSON to import on another machine"
            onClick={doExport}
          >
            Export
          </button>
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `npx vitest run src/pages/Graph.test.tsx -t "exports the working graph"`
Expected: PASS.

- [ ] **Step 7: Run the full Graph + lib suites to confirm no regressions**

Run: `npx vitest run src/pages/Graph.test.tsx src/lib/graphExport.test.ts src/lib/download.test.ts`
Expected: PASS (all tests).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/Graph.tsx frontend/src/pages/Graph.test.tsx
git commit -m "feat(frontend): Export button downloads the working graph as import JSON"
```

---

## Task 4: Full frontend verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole frontend test suite**

Run (from `frontend/`): `npm test`
Expected: PASS — all existing tests plus the 3 new ones (graphExport, download, Graph export button).

- [ ] **Step 2: Typecheck / build**

Run (from `frontend/`): `npx tsc -b`
Expected: no type errors.

- [ ] **Step 3: Lint the new/changed files**

Run (from `frontend/`): `npx eslint src/lib/graphExport.ts src/lib/download.ts src/pages/Graph.tsx`
Expected: no errors.

---

## Manual verification (optional, after automated checks pass)

The user's dev server runs with HMR, so edits are already live. To sanity-check end to end:
1. On the Graph page, load or build an ontology with a couple of nodes.
2. Click **Export** → a `<name>.json` file downloads.
3. Open the file: confirm it has `name`, `as_of`, `nodes` (`{id,label,kind}`), `edges` (`{source,target,type,sentiment,weight,confidence,evidence,url}` — no `origin`/`as_of`).
4. Go to the **Import** tab → upload that same file → confirm it imports as a set (the ImportReport shows nodes/edges added), then Merge into graph works as today.
