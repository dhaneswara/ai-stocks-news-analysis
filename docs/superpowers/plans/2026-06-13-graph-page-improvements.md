# Graph Page Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four Graph-page improvements — a dated/year-anchored LLM import prompt, a renamed "Copy LLM prompt" button, "Open in Dashboard" moved under the ticker score, and a new "Revalidate relationships" node action that force-refreshes a company's extracted edges.

**Architecture:** Frontend-heavy. The import prompt and graph mutations stay pure functions in `frontend/src/lib/`. "Revalidate" reuses the existing `GET /graph/company/{ticker}` extraction path with a new `refresh` flag that bypasses the 24h relationship cache, and a pure `revalidateGraph` helper that replaces a company's `extracted`-origin edges while preserving manual/imported edges and keeping orphan nodes.

**Tech Stack:** React + TypeScript + vitest (frontend), FastAPI + pytest (backend).

**Spec:** `docs/superpowers/specs/2026-06-13-graph-page-improvements-design.md`

**Conventions (this repo):**
- Frontend tests: from `frontend/`, `npm test` (vitest run) or a single file `npx vitest run <path>`.
- Backend tests: from `backend/`, `.venv/Scripts/python.exe -m pytest -q` (or target a file).
- Commits: Conventional Commits, one per task. **No `Co-Authored-By: Claude` trailer.**

---

## Task 0: Feature branch

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/graph-page-improvements
```

---

## Task 1: Dated, year-anchored LLM prompt + rename `chatGptPrompt` → `llmPrompt`

Covers spec §1 (dates) and §2 (rename). Renaming the exported symbol and its importer happen together so the tree stays green.

**Files:**
- Modify: `frontend/src/lib/importPrompt.ts`
- Test: `frontend/src/lib/importPrompt.test.ts`
- Modify: `frontend/src/components/GraphSidebar.tsx` (import + call site + button label)
- Test: `frontend/src/components/GraphSidebar.test.tsx` (button name)

- [ ] **Step 1: Rewrite the prompt test for `llmPrompt`**

Replace the entire contents of `frontend/src/lib/importPrompt.test.ts` with:

```ts
import { describe, expect, it } from 'vitest';
import { llmPrompt } from './importPrompt';

describe('llmPrompt', () => {
  const NOW = new Date('2026-06-13T00:00:00Z');

  it('injects the company and keeps the JSON contract', () => {
    const p = llmPrompt('NVDA', { now: NOW });
    expect(p).toContain('NVDA');
    expect(p).toContain('"nodes"');
    expect(p).toContain('"edges"');
    expect(p).toContain('supplier|customer|partner|competitor|owner|subsidiary|other');
  });

  it('states today (with year) and a window derived from recencyDays', () => {
    const p = llmPrompt('NVDA', { now: NOW, recencyDays: 30 });
    expect(p).toContain('2026-06-13');   // today, includes the current year
    expect(p).toContain('2026-05-14');   // 30 days earlier
    expect(p).toContain('30 days');
    expect(p).toContain('"as_of": "2026-06-13"');
  });

  it('defaults to a 90-day window', () => {
    const p = llmPrompt('NVDA', { now: NOW });
    expect(p).toContain('2026-03-15');   // 90 days before 2026-06-13
    expect(p).toContain('90 days');
  });

  it('falls back to a placeholder when empty', () => {
    expect(llmPrompt('', { now: NOW })).toContain('[COMPANY]');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/importPrompt.test.ts`
Expected: FAIL — `llmPrompt` is not exported (import error).

- [ ] **Step 3: Rewrite `importPrompt.ts`**

Replace the entire contents of `frontend/src/lib/importPrompt.ts` with:

```ts
/** The copy-paste research prompt shown in the Import tab. `[COMPANY]` is filled with the
 *  current root. The news window is derived from the app's news-recency setting so the LLM
 *  gets concrete dates (and the current year) instead of a vague "recent" — works with any
 *  LLM (ChatGPT, Gemini, Claude, …). */
export function llmPrompt(
  company: string,
  opts: { recencyDays?: number; now?: Date } = {},
): string {
  const c = company || '[COMPANY]';
  const recencyDays = opts.recencyDays ?? 90;
  const now = opts.now ?? new Date();
  const today = now.toISOString().slice(0, 10);
  const from = new Date(now.getTime() - recencyDays * 86_400_000).toISOString().slice(0, 10);
  return `Research ${c} and its business relationships with other companies, based on real news published between ${from} and ${today} (about the last ${recencyDays} days). Today is ${today}. Output ONLY a single JSON object — no prose, no code fences — in exactly this shape:

{
  "name": "<short label>",
  "as_of": "${today}",
  "nodes": [
    { "id": "<ticker if public, else short name>", "label": "<display name>",
      "kind": "company|private_company|product|person|sector" }
  ],
  "edges": [
    { "source": "<node id>", "target": "<node id>",
      "type": "supplier|customer|partner|competitor|owner|subsidiary|other",
      "sentiment": "positive|negative|neutral", "weight": 0.0, "confidence": 0.0,
      "evidence": "<short fact or quote>", "url": "<source url>" }
  ]
}

Rules:
- Use the official stock ticker as "id" for any public company (e.g. NVDA, AAPL); a short readable id otherwise.
- "type" is the target's role relative to the source. Use "other" if none of the six fit.
- "sentiment" = the event's likely effect on the source company.
- "weight" = how material the relationship is (0-1); "confidence" = how sure you are it is real and current (0-1).
- Include only relationships supported by real information dated on or after ${from}; add a source "url" where possible.`;
}
```

- [ ] **Step 4: Update the importer in `GraphSidebar.tsx`**

In `frontend/src/components/GraphSidebar.tsx`, change the import (line 5):

```ts
import { llmPrompt } from '../lib/importPrompt';
```

Change `copyPrompt` (around line 127-129) to:

```ts
  const copyPrompt = () => {
    navigator.clipboard?.writeText(llmPrompt(promptDefault)).catch(() => {});
  };
```

Change the button label (around line 276) from `Copy ChatGPT prompt` to:

```tsx
          <button type="button" className="secondary" onClick={copyPrompt}>Copy LLM prompt</button>
```

- [ ] **Step 5: Add a button-name test**

In `frontend/src/components/GraphSidebar.test.tsx`, add after the existing `'switches to the Import tab'` test (around line 113):

```ts
it('the Import tab copy button reads "Copy LLM prompt"', () => {
  const props = { ...base(), tab: 'import' as const };
  wrap(<GraphSidebar {...props} selected={null} />);
  expect(screen.getByRole('button', { name: /copy llm prompt/i })).toBeInTheDocument();
});
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/importPrompt.test.ts src/components/GraphSidebar.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/importPrompt.ts frontend/src/lib/importPrompt.test.ts frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphSidebar.test.tsx
git commit -m "feat(frontend): date-anchor the LLM import prompt and rename the copy button"
```

---

## Task 2: Thread `news_recency_days` from settings into the prompt

The prompt now defaults to 90 days; this feeds the user's actual setting in.

**Files:**
- Modify: `frontend/src/components/GraphSidebar.tsx` (new `recencyDays` prop, pass to `llmPrompt`)
- Modify: `frontend/src/pages/Graph.tsx` (`useSettings`, pass prop)
- Test: `frontend/src/components/GraphSidebar.test.tsx` (add `recencyDays` to `base()`)

- [ ] **Step 1: Add the prop to `GraphSidebar`**

In `frontend/src/components/GraphSidebar.tsx`, add to `GraphSidebarProps` (near `promptDefault: string;`, line 64):

```ts
  promptDefault: string;
  recencyDays: number;
```

Add `recencyDays` to the destructured props (in the `const { … } = props;` block, near `promptDefault,`):

```ts
    promptDefault,
    recencyDays,
```

Update `copyPrompt` to pass it:

```ts
  const copyPrompt = () => {
    navigator.clipboard?.writeText(llmPrompt(promptDefault, { recencyDays })).catch(() => {});
  };
```

- [ ] **Step 2: Add `recencyDays` to the test `base()` so types stay valid**

In `frontend/src/components/GraphSidebar.test.tsx`, inside `base()` (after `promptDefault: 'AAPL',`, line 40):

```ts
    promptDefault: 'AAPL',
    recencyDays: 90,
```

- [ ] **Step 3: Wire settings in `Graph.tsx`**

In `frontend/src/pages/Graph.tsx`, add `useSettings` to the hooks import (lines 6-9):

```ts
import {
  useActiveOntology, useDeleteImport, useDeleteOntology, useEgoGraph, useImportGraph, useImports,
  useLoadOntology, useOntologies, useSaveOntology, useScreen, useSetActiveOntology, useSettings, useWatchlist,
} from '../hooks/queries';
```

Add the hook call near the other hooks (after `const ego = useEgoGraph();`, line 29):

```ts
  const settings = useSettings();
```

Pass the prop to `<GraphSidebar>` (next to `promptDefault={selectedId ?? ''}`, line 356). Note: `news` is an OPTIONAL field on `Settings`, so chain through it:

```tsx
        promptDefault={selectedId ?? ''}
        recencyDays={settings.data?.news?.news_recency_days ?? 90}
```

- [ ] **Step 4: Run the affected tests**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx src/pages/Graph.test.tsx`
Expected: PASS (Graph.test.tsx's `SETTINGS` mock has no `news`, so the chain falls back to 90 — no crash).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphSidebar.test.tsx frontend/src/pages/Graph.tsx
git commit -m "feat(frontend): feed the news-recency setting into the LLM prompt window"
```

---

## Task 3: Move "Open in Dashboard" under the ticker score

Spec §3.

**Files:**
- Modify: `frontend/src/components/GraphSidebar.tsx` (reorder the detail block)
- Test: `frontend/src/components/GraphSidebar.test.tsx` (DOM-order assertion)

- [ ] **Step 1: Add an order assertion test**

In `frontend/src/components/GraphSidebar.test.tsx`, add after the existing `'shows the selected node detail and a Dashboard link'` test (around line 92):

```ts
it('places the Dashboard link before the Expand button', () => {
  wrap(<GraphSidebar {...base()} selected={SELECTED} />);
  const link = screen.getByRole('link', { name: /open in dashboard/i });
  const expand = screen.getByRole('button', { name: /expand neighbours/i });
  // expand must FOLLOW the link in DOM order (4 = Node.DOCUMENT_POSITION_FOLLOWING)
  expect(link.compareDocumentPosition(expand) & 4).toBeTruthy();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx -t "before the Expand"`
Expected: FAIL — the link currently comes after Expand (and after the network list).

- [ ] **Step 3: Reorder the detail block**

In `frontend/src/components/GraphSidebar.tsx`, the `selected` detail block currently renders (lines ~224-236): score `<p>`, then the Expand `<button>`, then the network `<ul>`/`<p>`, then the `<Link>`. Move the `<Link>` to sit immediately after the score line. The block should read:

```tsx
              {selected.onBoard && <p className="muted">score {selected.score.toFixed(0)}</p>}
              <Link to={`/?ticker=${encodeURIComponent(selected.id)}`}>Open in Dashboard →</Link>
              <button disabled={loading} onClick={() => onExpand(selected.id)}>Expand neighbours</button>
              {selected.network && selected.network.influences.length > 0 ? (
                <ul className="factor-list">
                  {selected.network.influences.map((inf, i) => {
                    const lean = inf.signed > 0 ? 'bullish' : inf.signed < 0 ? 'bearish' : 'neutral';
                    return (<li key={i}><b>{inf.type} {inf.neighbour}</b> — news {inf.edge_sentiment} ({lean})</li>);
                  })}
                </ul>
              ) : (
                <p className="muted">No outgoing network edges.</p>
              )}
```

(Delete the old `<Link …>Open in Dashboard →</Link>` that was the last child of the block.)

- [ ] **Step 4: Run the GraphSidebar tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx`
Expected: PASS (the new order test passes; the existing Dashboard-link test still passes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphSidebar.test.tsx
git commit -m "fix(frontend): move Open in Dashboard under the node score"
```

---

## Task 4: Backend — `extract_relationships` cache bypass on `refresh`

Spec §4 backend. When `refresh=True`, skip the cache READ but still recompute and write.

**Files:**
- Modify: `backend/app/analysis/relationships.py`
- Test: `backend/tests/test_relationships.py`

- [ ] **Step 1: Add the failing test**

In `backend/tests/test_relationships.py`, add after `test_extract_is_cached_per_day` (around line 81):

```python
def test_extract_refresh_bypasses_cache(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    p = FakeProvider([EDGES_JSON, EDGES_JSON])  # two outputs available
    extract_relationships(_stock_with_news("x"), RESOLVER, p, "m", "fake", cache, NetworkConfig())
    extract_relationships(_stock_with_news("x"), RESOLVER, p, "m", "fake", cache, NetworkConfig(), refresh=True)
    assert p.calls == 2  # second call ignored the cached entry and recomputed
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest tests/test_relationships.py::test_extract_refresh_bypasses_cache -q`
Expected: FAIL — `extract_relationships() got an unexpected keyword argument 'refresh'`.

- [ ] **Step 3: Add the `refresh` param and gate the cache read**

In `backend/app/analysis/relationships.py`, change the signature (lines 85-95) to add `refresh`:

```python
def extract_relationships(
    stock,
    resolver: TickerResolver,
    provider: LLMProvider,
    model: str,
    provider_name: str,
    cache: Cache,
    cfg: NetworkConfig,
    *,
    now: datetime | None = None,
    refresh: bool = False,
) -> list[GraphEdge]:
```

Then gate the cache read (lines 100-106) behind `not refresh`:

```python
    key = f"relationships:{provider_name}:{model}:{stock.ticker}:{now.date().isoformat()}"
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            try:
                return [GraphEdge(**e) for e in json.loads(cached)]
            except Exception:
                pass  # corrupt entry -> recompute
```

(The `cache.set(...)` at the end is unchanged, so a refresh still updates the cache.)

- [ ] **Step 4: Run the relationships tests to verify they pass**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest tests/test_relationships.py -q`
Expected: PASS (new test passes; `test_extract_is_cached_per_day` still passes).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/relationships.py backend/tests/test_relationships.py
git commit -m "feat(backend): let extract_relationships bypass the cache on refresh"
```

---

## Task 5: Backend — `build_company_graph` + route `refresh` param

Spec §4 backend. Thread `refresh` from the HTTP query param into the extractor.

**Files:**
- Modify: `backend/app/network/service.py`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_network_service.py`

- [ ] **Step 1: Add the failing test**

In `backend/tests/test_network_service.py`, add after `test_company_graph_one_hop` (around line 36):

```python
def test_company_graph_forwards_refresh(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(service, "build_provider", lambda s: object())
    monkeypatch.setattr(service, "load_universe", lambda: [])
    monkeypatch.setattr(service, "get_stock_data", lambda t, *a, **k: _stock(t))
    monkeypatch.setattr(service, "build_news_provider", lambda s: _FakeNews())

    def fake_extract(stock, *a, refresh=False, **k):
        captured["refresh"] = refresh
        return []

    monkeypatch.setattr(service, "extract_relationships", fake_extract)
    service.build_company_graph("AAPL", Settings(), Cache(str(tmp_path / "c.db")), refresh=True)
    assert captured["refresh"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest tests/test_network_service.py::test_company_graph_forwards_refresh -q`
Expected: FAIL — `build_company_graph() got an unexpected keyword argument 'refresh'`.

- [ ] **Step 3: Add `refresh` to `build_company_graph`**

In `backend/app/network/service.py`, change the signature (lines 18-20):

```python
def build_company_graph(
    ticker: str, settings: Settings, cache: Cache, *, now: datetime | None = None, refresh: bool = False
) -> KnowledgeGraph:
```

And the `extract_relationships` call (line 48):

```python
        edges = extract_relationships(stock, resolver, provider, model, provider_id, cache, ncfg, now=now, refresh=refresh)
```

- [ ] **Step 4: Add the `refresh` query param to the route**

In `backend/app/api/routes.py`, update `get_company_graph` (lines 590-597):

```python
@router.get("/graph/company/{ticker}", response_model=KnowledgeGraph)
def get_company_graph(
    ticker: str,
    refresh: bool = False,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> KnowledgeGraph:
    """One-hop ego graph for a single ticker — powers 'expand' and 'revalidate'
    (refresh=true bypasses the 24h relationship cache)."""
    return build_company_graph(ticker, store.load(), cache, refresh=refresh)
```

- [ ] **Step 5: Run the network-service tests to verify they pass**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest tests/test_network_service.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/network/service.py backend/app/api/routes.py backend/tests/test_network_service.py
git commit -m "feat(backend): add refresh flag to the company-graph endpoint"
```

---

## Task 6: Frontend — `revalidateGraph` pure helper

Spec §4 frontend. Replace a company's extracted edges, preserve manual/imported, keep orphans.

**Files:**
- Modify: `frontend/src/lib/graphView.ts`
- Test: `frontend/src/lib/graphView.test.ts`

- [ ] **Step 1: Add the failing test**

In `frontend/src/lib/graphView.test.ts`, add `revalidateGraph` to the import on line 2:

```ts
import { applyFilters, directionColor, mergeGraph, mergeNodes, nodeRadius, revalidateGraph, searchNodes, sentimentColor, toLinks, type ViewNode } from './graphView';
```

Then append at the end of the file:

```ts
describe('revalidateGraph', () => {
  const working: KnowledgeGraph = {
    as_of: 't', scope: 'focus', built: 1, skipped: 0,
    nodes: ['AAPL', 'TSM', 'XYZ', 'man:ai'],
    edges: [
      { source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: 'old', url: '', as_of: '', origin: 'extracted' },
      // no origin → must be treated as extracted (and replaced); XYZ's only edge
      { source: 'AAPL', target: 'XYZ', type: 'competitor', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' },
      { source: 'AAPL', target: 'man:ai', type: 'partner', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'manual' },
    ],
    node_meta: { 'man:ai': { label: 'AI', kind: 'concept', source: 'manual' } },
  };
  const fragment: KnowledgeGraph = {
    as_of: 't2', scope: 'company:AAPL', built: 1, skipped: 0,
    nodes: ['AAPL', 'TSM', 'NEW'],
    edges: [
      { source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'positive', weight: 0.5, confidence: 0.9, evidence: 'fresh', url: '', as_of: 't2', origin: 'extracted' },
      { source: 'AAPL', target: 'NEW', type: 'partner', sentiment: 'positive', weight: 0.5, confidence: 0.9, evidence: '', url: '', as_of: 't2', origin: 'extracted' },
    ],
  };
  const find = (g: KnowledgeGraph, s: string, t: string, ty: string) =>
    g.edges.find((e) => e.source === s && e.target === t && e.type === ty);

  it('replaces extracted edges, preserves manual ones, keeps orphans, adds new', () => {
    const g = revalidateGraph(working, 'AAPL', fragment);
    expect(find(g, 'AAPL', 'TSM', 'supplier')?.evidence).toBe('fresh');   // refreshed
    expect(find(g, 'AAPL', 'XYZ', 'competitor')).toBeUndefined();          // stale (no-origin) dropped
    expect(find(g, 'AAPL', 'man:ai', 'partner')?.origin).toBe('manual');   // manual preserved
    expect(find(g, 'AAPL', 'NEW', 'partner')).toBeTruthy();                // new edge added
    expect(g.nodes).toContain('NEW');                                      // new node added
    expect(g.nodes).toContain('XYZ');                                      // orphan kept
    expect(g.edges.some((e) => e.source === 'XYZ' || e.target === 'XYZ')).toBe(false); // truly orphaned
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/graphView.test.ts`
Expected: FAIL — `revalidateGraph` is not exported.

- [ ] **Step 3: Implement `revalidateGraph`**

In `frontend/src/lib/graphView.ts`, append at the end of the file (it reuses `mergeGraph` and the imported `GraphEdge` type, both already in this module):

```ts
/** Refresh a company's relationships: drop the ticker's `extracted`-origin outgoing edges
 *  (a missing origin counts as extracted), keep its manual/imported edges and every other
 *  source's edges, then merge the freshly-extracted `fragment` (dedupe by source|target|type).
 *  Orphan neighbour nodes are kept — pure. */
export function revalidateGraph(
  working: KnowledgeGraph,
  ticker: string,
  fragment: KnowledgeGraph,
): KnowledgeGraph {
  const isExtracted = (e: GraphEdge) => (e.origin ?? 'extracted') === 'extracted';
  const kept = working.edges.filter((e) => !(e.source === ticker && isExtracted(e)));
  return mergeGraph({ ...working, edges: kept }, fragment);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/graphView.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/graphView.ts frontend/src/lib/graphView.test.ts
git commit -m "feat(frontend): add revalidateGraph helper (replace extracted edges)"
```

---

## Task 7: Frontend — API client `refresh` param

Spec §4 frontend. `getCompanyGraph` gains an optional `refresh` (backward compatible).

**Files:**
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Add the failing test**

In `frontend/src/api/client.test.ts`, add after the existing `'getCompanyGraph GETs /graph/company/{ticker}'` test (around line 89):

```ts
it('getCompanyGraph adds ?refresh=true when asked', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ nodes: ['AAPL'], edges: [] }) });
  vi.stubGlobal('fetch', fetchMock);
  await api.getCompanyGraph('AAPL', true);
  expect(fetchMock.mock.calls[0][0] as string).toContain('/graph/company/AAPL?refresh=true');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/api/client.test.ts -t "refresh=true"`
Expected: FAIL — the URL has no `?refresh=true`.

- [ ] **Step 3: Implement the param**

In `frontend/src/api/client.ts`, replace `getCompanyGraph` (lines 84-85):

```ts
  getCompanyGraph: (ticker: string, refresh = false) =>
    http<KnowledgeGraph>(`/graph/company/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
```

- [ ] **Step 4: Run the client tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS (new test passes; the existing one-arg test still passes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(frontend): getCompanyGraph supports a refresh flag"
```

---

## Task 8: Frontend — Revalidate action (hook + page + sidebar button)

Spec §4 frontend. Change the `useEgoGraph` mutation shape and update both call sites in the same task so the tree stays green.

**Files:**
- Modify: `frontend/src/hooks/queries.ts` (`useEgoGraph` takes `{ ticker, refresh? }`)
- Modify: `frontend/src/pages/Graph.tsx` (`expand` call shape, new `revalidate`, `revalidateGraph` import, pass `onRevalidate`)
- Modify: `frontend/src/components/GraphSidebar.tsx` (new `onRevalidate` prop + Revalidate button)
- Test: `frontend/src/components/GraphSidebar.test.tsx` (`onRevalidate` in `base()` + button behavior)

- [ ] **Step 1: Add the failing sidebar tests**

In `frontend/src/components/GraphSidebar.test.tsx`, add `onRevalidate: vi.fn(),` to `base()` (next to `onExpand: vi.fn(),`, line 19):

```ts
    onExpand: vi.fn(), onRevalidate: vi.fn(), loading: false,
```

Then add after the `'expands the selected node'` test (around line 65):

```ts
it('revalidates the selected ticker node', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={SELECTED} />);
  fireEvent.click(screen.getByRole('button', { name: /revalidate relationships/i }));
  expect(props.onRevalidate).toHaveBeenCalledWith('AAPL');
});

it('hides Revalidate for a concept node', () => {
  const concept: ViewNode = { ...SELECTED, id: 'man:ai-chip', label: 'AI Chip' };
  const props = base();
  wrap(<GraphSidebar {...props} selected={concept} />);
  expect(screen.queryByRole('button', { name: /revalidate relationships/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx -t "evalidate"`
Expected: FAIL — no "Revalidate relationships" button exists (and `onRevalidate` is not a prop yet).

- [ ] **Step 3: Add the `onRevalidate` prop + button to `GraphSidebar`**

In `frontend/src/components/GraphSidebar.tsx`, add to `GraphSidebarProps` (next to `onExpand`, line 39):

```ts
  onExpand: (ticker: string) => void;
  onRevalidate: (ticker: string) => void;
```

Add to the destructured props (next to `onExpand`, line 76):

```ts
    tab, onTab, onExpand, onRevalidate, loading,
```

Replace the single Expand `<button>` (the one moved next to the Dashboard link in Task 3) with an action row holding Expand + a ticker-only Revalidate button:

```tsx
              <div className="graph-actions">
                <button disabled={loading} onClick={() => onExpand(selected.id)}>Expand neighbours</button>
                {!selected.id.includes(':') && (
                  <button disabled={loading} onClick={() => onRevalidate(selected.id)}>Revalidate relationships</button>
                )}
              </div>
```

- [ ] **Step 4: Change the `useEgoGraph` hook shape**

In `frontend/src/hooks/queries.ts`, replace `useEgoGraph` (lines 122-124):

```ts
export function useEgoGraph() {
  return useMutation({
    mutationFn: ({ ticker, refresh }: { ticker: string; refresh?: boolean }) =>
      api.getCompanyGraph(ticker, refresh),
  });
}
```

- [ ] **Step 5: Update `Graph.tsx` — import, expand call, new revalidate handler, wire prop**

In `frontend/src/pages/Graph.tsx`:

Add `revalidateGraph` to the graphView import (line 10) — insert it alphabetically near `resolveManualTarget`:

```ts
import { addCompanyNode, addManualEdge, addManualNode, applyFilters, COMPANY_TICKER_RE, deleteEdge, deleteNode, mergeGraph, mergeNodes, renameNode, resolveManualTarget, revalidateGraph, toLinks, type ViewNode } from '../lib/graphView';
```

Update `expand` (line 100) to pass the object shape:

```ts
      const frag = await ego.mutateAsync({ ticker, refresh: false });
```

Add a `revalidate` handler immediately after the `expand` function (after line 106):

```ts
  const revalidate = async (ticker: string) => {
    setNotice(null);
    try {
      const frag = await ego.mutateAsync({ ticker, refresh: true });
      setWorking((w) => revalidateGraph(w ?? EMPTY_GRAPH, ticker, frag));
      setExpanded((s) => new Set(s).add(ticker));
      setDirty(true);
      setNotice(frag.edges.length === 0
        ? `No current relationships found for ${ticker}.`
        : `Refreshed relationships for ${ticker}.`);
    } catch { /* surfaced via the load-error banner */ }
  };
```

Pass the prop to `<GraphSidebar>` (next to `onExpand={expand}`, line 331):

```tsx
        onExpand={expand}
        onRevalidate={revalidate}
```

- [ ] **Step 6: Run the affected frontend tests**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx src/pages/Graph.test.tsx`
Expected: PASS (Graph.test.tsx still passes — its `api.getCompanyGraph` mock ignores the new args; the Expand-button flow resolves through `{ ticker, refresh: false }`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/queries.ts frontend/src/pages/Graph.tsx frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphSidebar.test.tsx
git commit -m "feat(frontend): add Revalidate relationships action to the graph explorer"
```

---

## Task 9: Full suite + lint + manual smoke

- [ ] **Step 1: Run the full frontend suite + lint**

Run: `cd frontend && npm test && npm run lint`
Expected: all tests pass; lint clean.

- [ ] **Step 2: Run the full backend suite**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Manual smoke (dev servers are usually already running with HMR)**

On `/graph`:
- Import tab → "Copy LLM prompt" copies a prompt containing today's date (with year) and a "between <from> and <today>" window matching Settings → News recency.
- Select a ticker node → "Open in Dashboard →" sits directly under the `score N` line, above Expand/Revalidate.
- Click "Revalidate relationships" → a notice appears ("Refreshed relationships for X." or "No current relationships found for X."); stale extracted edges for that node are replaced; manually-added edges remain.
- A `man:`/`ext:` concept node shows no Revalidate button.

- [ ] **Step 4: Final verification note**

Confirm the four spec items are all demonstrably working before merging. Do NOT claim completion without the suites passing (evidence over assertion).

---

## Self-Review Notes

- **Spec coverage:** §1 dates → Task 1 (+§-recency wiring Task 2); §2 rename → Task 1; §3 reorder → Task 3; §4 backend refresh → Tasks 4-5; §4 frontend (`revalidateGraph`, client, hook, page, sidebar) → Tasks 6-8. All covered.
- **Type consistency:** `llmPrompt(company, { recencyDays, now })`, `revalidateGraph(working, ticker, fragment)`, `getCompanyGraph(ticker, refresh)`, `useEgoGraph` → `{ ticker, refresh? }`, `extract_relationships(..., refresh=False)`, `build_company_graph(..., refresh=False)` — names/signatures match across tasks.
- **Green-between-tasks:** symbol rename + its importer are in Task 1; the `useEgoGraph` shape change + both call sites are together in Task 8; `getCompanyGraph`'s new arg is optional (Task 7 standalone-safe).
- **Edge cases:** missing-`news` Settings → falls back to 90 (Task 2 uses `?.news?.`); missing-`origin` edge treated as extracted (Task 6 test asserts this); `working===null` in revalidate guarded with `?? EMPTY_GRAPH`.
