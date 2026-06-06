# Company-Rooted Graph Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user start a knowledge graph from one company, expand any node one hop on demand (live, cache-aware), and save/load explored subgraphs per company with a short version history — as a pure research view that never changes the Discover board signal.

**Architecture:** One new backend primitive `build_company_graph(ticker)` (reusing the cached `extract_relationships`) serves both "root" and "expand." The frontend accumulates the explored subgraph in React state via a pure `mergeGraph` helper; save/load/list/delete go through new endpoints into the SQLite `Cache` under long-lived `graph_user_saved:` keys (history capped to 5 per root). The `/graph` page becomes the explorer; the daily focus-graph build is untouched.

**Tech Stack:** Backend FastAPI + Pydantic v2 + SQLite `Cache`; Frontend React 18 + Vite 5 + TS 5.6 + @tanstack/react-query v5 + vitest 2 + react-force-graph-2d (existing).

**Branch:** `feat/company-rooted-graph-explore` (already created; spec committed at `b0e6c3c`).

**Commit convention:** Conventional commits (`feat(backend):`, `feat(frontend):`, `test(...)`, `docs:`). **Do NOT add a `Co-Authored-By: Claude` trailer** (repo standing preference).

**Spec:** `docs/superpowers/specs/2026-06-06-company-rooted-graph-explore-design.md`

---

## File Structure

**Backend**
- Modify `backend/app/models/schemas.py` — add `SavedGraphVersion`, `SavedGraphSummary`.
- Modify `backend/app/network/service.py` — add `build_company_graph`.
- Modify `backend/app/network/store.py` — add saved-graph CRUD (`save_company_graph`, `load_company_graph`, `list_saved_graphs`, `delete_saved_graph`).
- Modify `backend/app/api/routes.py` — add `GET /api/graph/company/{ticker}`, `GET/POST /api/graph/saved`, `GET/DELETE /api/graph/saved/{root}`.
- Test: `backend/tests/test_network_schema.py`, `test_network_service.py`, `test_network_store.py`, `test_api_graph.py` (refactor to `dependency_overrides` + tmp cache — also fixes the known pollution).

**Frontend**
- Modify `frontend/src/types.ts` — add `SavedGraphVersion`, `SavedGraphSummary`.
- Modify `frontend/src/lib/graphView.ts` — add pure `mergeGraph`.
- Modify `frontend/src/api/client.ts` — add 5 client methods.
- Modify `frontend/src/hooks/queries.ts` — add ego/focus/saved hooks.
- Modify `frontend/src/components/GraphSidebar.tsx` — explorer controls (root input, expand, save/load/delete, load-focus, rebuild) + filters + detail.
- Modify `frontend/src/pages/Graph.tsx` — accumulate working state; wire handlers.
- Modify `frontend/src/styles.css` — minor control styling.
- Test: `frontend/src/lib/graphView.test.ts`, `api/client.test.ts`, `components/GraphSidebar.test.tsx`, `pages/Graph.test.tsx`.

---

## Task 1: Saved-graph schemas

**Files:**
- Modify: `backend/app/models/schemas.py` (after `KnowledgeGraph`, around line 124)
- Test: `backend/tests/test_network_schema.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_network_schema.py`:

```python
def test_saved_graph_version_round_trip():
    from app.models.schemas import SavedGraphSummary, SavedGraphVersion

    v = SavedGraphVersion(
        root="AAPL", saved_at="2026-06-06T00:00:00+00:00", expanded=["AAPL", "TSM"],
        graph=KnowledgeGraph(scope="company:AAPL", nodes=["AAPL", "TSM"], edges=[
            GraphEdge(source="AAPL", target="TSM", type="supplier")], built=1),
    )
    again = SavedGraphVersion.model_validate_json(v.model_dump_json())
    assert again.root == "AAPL" and again.expanded == ["AAPL", "TSM"]
    assert again.graph.edges[0].target == "TSM"
    s = SavedGraphSummary(root="AAPL", versions=["2026-06-06T00:00:00+00:00"])
    assert s.root == "AAPL" and s.versions == ["2026-06-06T00:00:00+00:00"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_network_schema.py::test_saved_graph_version_round_trip -v`
Expected: FAIL — `ImportError: cannot import name 'SavedGraphVersion'`.

- [ ] **Step 3: Implement** — in `backend/app/models/schemas.py`, immediately after the `KnowledgeGraph` class (line 124), add:

```python
class SavedGraphVersion(BaseModel):
    root: str
    saved_at: str = ""
    expanded: list[str] = Field(default_factory=list)
    graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)


class SavedGraphSummary(BaseModel):
    root: str
    versions: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_network_schema.py -v`
Expected: PASS (all tests in file).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_network_schema.py
git commit -m "feat(backend): SavedGraphVersion/SavedGraphSummary schemas for graph explorer"
```

---

## Task 2: `build_company_graph` (the root + expand primitive)

**Files:**
- Modify: `backend/app/network/service.py` (add a function; reuses existing imports)
- Test: `backend/tests/test_network_service.py`

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_network_service.py` (the file already defines `_stock` and `_wire`):

```python
def test_company_graph_one_hop(tmp_path, monkeypatch):
    edges = {"AAPL": [GraphEdge(source="AAPL", target="TSM", type="supplier")]}
    _wire(monkeypatch, edges)
    g = service.build_company_graph("aapl", Settings(), Cache(str(tmp_path / "c.db")))
    assert g.scope == "company:AAPL"
    assert set(g.nodes) == {"AAPL", "TSM"} and g.built == 1
    assert g.edges[0].target == "TSM"


def test_company_graph_no_edges_returns_lone_node(tmp_path, monkeypatch):
    _wire(monkeypatch, {})  # extract returns [] for AAPL
    g = service.build_company_graph("AAPL", Settings(), Cache(str(tmp_path / "c.db")))
    assert g.nodes == ["AAPL"] and g.edges == [] and g.built == 1


def test_company_graph_degrades_on_data_failure(tmp_path, monkeypatch):
    _wire(monkeypatch, {})

    def boom(*a, **k):
        raise ValueError("no data")

    monkeypatch.setattr(service, "get_stock_data", boom)
    g = service.build_company_graph("AAPL", Settings(), Cache(str(tmp_path / "c.db")))
    assert g.nodes == ["AAPL"] and g.edges == [] and g.built == 0


def test_company_graph_disabled_returns_lone_node(tmp_path, monkeypatch):
    _wire(monkeypatch, {})
    settings = Settings(); settings.network.enabled = False
    g = service.build_company_graph("AAPL", settings, Cache(str(tmp_path / "c.db")))
    assert g.nodes == ["AAPL"] and g.edges == [] and g.built == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_network_service.py -k company_graph -v`
Expected: FAIL — `AttributeError: module 'app.network.service' has no attribute 'build_company_graph'`.

- [ ] **Step 3: Implement** — in `backend/app/network/service.py`, append after `build_graph`:

```python
def build_company_graph(
    ticker: str, settings: Settings, cache: Cache, *, now: datetime | None = None
) -> KnowledgeGraph:
    """One-hop ego graph for a single ticker. Powers both 'start from company' and 'expand a node'.

    Degrades like build_graph: any provider/settings/universe/data failure returns a graph
    containing just the (lone) root node — never raises — so the explorer always has something
    to show.
    """
    now = now or datetime.now(timezone.utc)
    t = (ticker or "").upper().strip()
    scope = f"company:{t}"
    ncfg = settings.network
    if not t or not ncfg.enabled:
        return KnowledgeGraph(as_of=now.isoformat(), scope=scope, nodes=[t] if t else [])

    try:
        provider = build_provider(settings)
        provider_id = settings.active_provider
        model = settings.providers[provider_id].model
        resolver = TickerResolver(load_universe())
    except Exception:  # noqa: BLE001 — bad provider/settings/universe -> degrade, don't crash
        return KnowledgeGraph(as_of=now.isoformat(), scope=scope, nodes=[t])

    try:
        stock = get_stock_data(t, NETWORK_PERIOD, settings.indicator_params, cache)
        edges = extract_relationships(stock, resolver, provider, model, provider_id, cache, ncfg, now=now)
    except Exception:  # noqa: BLE001 — no data / extraction error -> lone node
        return KnowledgeGraph(as_of=now.isoformat(), scope=scope, nodes=[t])

    nodes = {t}
    for e in edges:
        nodes.add(e.target)
    return KnowledgeGraph(
        as_of=now.isoformat(), scope=scope, nodes=sorted(nodes), edges=edges, built=1, skipped=0
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_network_service.py -v`
Expected: PASS (existing `build_graph` tests + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/service.py backend/tests/test_network_service.py
git commit -m "feat(backend): build_company_graph one-hop ego primitive (root + expand)"
```

---

## Task 3: Saved-graph store (CRUD + 5-version history)

**Files:**
- Modify: `backend/app/network/store.py`
- Test: `backend/tests/test_network_store.py`

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_network_store.py`:

```python
from app.models.schemas import SavedGraphVersion
from app.network.store import (
    delete_saved_graph, list_saved_graphs, load_company_graph, save_company_graph,
)


def _ver(root, saved_at):
    return SavedGraphVersion(root=root, saved_at=saved_at,
                             graph=KnowledgeGraph(scope=f"company:{root}", nodes=[root]))


def test_saved_history_caps_and_orders(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    for i in range(6):
        save_company_graph(_ver("AAPL", f"t{i}"), cache)
    summary = next(s for s in list_saved_graphs(cache) if s.root == "AAPL")
    assert summary.versions == ["t5", "t4", "t3", "t2", "t1"]  # newest first, t0 evicted (cap 5)
    assert load_company_graph("AAPL", cache).saved_at == "t5"          # latest
    assert load_company_graph("AAPL", cache, "t3").saved_at == "t3"    # by version
    assert load_company_graph("AAPL", cache, "t0") is None             # evicted


def test_saved_root_is_upper_cased(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_company_graph(_ver("aapl", "t1"), cache)
    assert load_company_graph("AAPL", cache) is not None
    assert load_company_graph("aapl", cache) is not None  # lookup also normalizes


def test_saved_delete_version_then_root(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_company_graph(_ver("AAPL", "t1"), cache)
    save_company_graph(_ver("AAPL", "t2"), cache)
    assert delete_saved_graph("AAPL", cache, "t1") is True
    assert load_company_graph("AAPL", cache, "t1") is None
    assert load_company_graph("AAPL", cache, "t2") is not None
    assert delete_saved_graph("AAPL", cache) is True   # whole root
    assert load_company_graph("AAPL", cache) is None
    assert list_saved_graphs(cache) == []


def test_saved_load_missing_returns_none(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    assert load_company_graph("ZZZZ", cache) is None
    assert delete_saved_graph("ZZZZ", cache) is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_network_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'save_company_graph'`.

- [ ] **Step 3: Implement** — replace the top of `backend/app/network/store.py` imports and append the new functions. The file currently imports only `Cache` and `KnowledgeGraph`; update to:

```python
"""Persist knowledge graphs in the existing Cache (SQLite KV).

Two namespaces:
- `graph_snapshot:<scope>`  — the auto/daily focus snapshot (7-day TTL), unchanged.
- `graph_user_saved:<ROOT>` — user-saved explored subgraphs (≈10y TTL, history capped to 5).
"""
from __future__ import annotations

import json

from app.config.cache import Cache
from app.models.schemas import KnowledgeGraph, SavedGraphSummary, SavedGraphVersion

_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
_USER_SAVE_TTL_SECONDS = 3650 * 24 * 60 * 60  # ~10 years (effectively permanent)
_MAX_VERSIONS = 5
_INDEX_KEY = "graph_user_saved:__index__"
```

Keep the existing `_key`, `save_graph`, `load_graph` functions as-is. Then append:

```python
def _saved_key(root: str) -> str:
    return f"graph_user_saved:{root.upper().strip()}"


def _load_index(cache: Cache) -> list[str]:
    raw = cache.get(_INDEX_KEY)
    try:
        return json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 — corrupt index -> empty
        return []


def _save_index(roots: list[str], cache: Cache) -> None:
    cache.set(_INDEX_KEY, json.dumps(roots), _USER_SAVE_TTL_SECONDS)


def _load_versions(root: str, cache: Cache) -> list[SavedGraphVersion]:
    raw = cache.get(_saved_key(root))
    if not raw:
        return []
    try:
        return [SavedGraphVersion.model_validate(v) for v in json.loads(raw)]
    except Exception:  # noqa: BLE001 — corrupt entry -> none
        return []


def _store_versions(root: str, versions: list[SavedGraphVersion], cache: Cache) -> None:
    cache.set(_saved_key(root), json.dumps([v.model_dump() for v in versions]), _USER_SAVE_TTL_SECONDS)


def save_company_graph(version: SavedGraphVersion, cache: Cache) -> SavedGraphVersion:
    root = version.root.upper().strip()
    version = version.model_copy(update={"root": root})
    versions = ([version] + _load_versions(root, cache))[:_MAX_VERSIONS]  # newest first, capped
    _store_versions(root, versions, cache)
    idx = _load_index(cache)
    if root not in idx:
        idx.append(root)
        _save_index(idx, cache)
    return version


def load_company_graph(root: str, cache: Cache, version: str | None = None) -> SavedGraphVersion | None:
    versions = _load_versions(root, cache)
    if not versions:
        return None
    if version is None:
        return versions[0]  # latest
    return next((v for v in versions if v.saved_at == version), None)


def list_saved_graphs(cache: Cache) -> list[SavedGraphSummary]:
    out: list[SavedGraphSummary] = []
    for root in _load_index(cache):
        versions = _load_versions(root, cache)
        if versions:
            out.append(SavedGraphSummary(root=root, versions=[v.saved_at for v in versions]))
    return out


def delete_saved_graph(root: str, cache: Cache, version: str | None = None) -> bool:
    root = root.upper().strip()
    versions = _load_versions(root, cache)
    if not versions:
        return False
    if version is None:
        remaining: list[SavedGraphVersion] = []
    else:
        remaining = [v for v in versions if v.saved_at != version]
        if len(remaining) == len(versions):
            return False  # version not found
    if remaining:
        _store_versions(root, remaining, cache)
    else:
        _store_versions(root, [], cache)  # Cache has no delete; store empty
        _save_index([r for r in _load_index(cache) if r != root], cache)
    return True
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_network_store.py -v`
Expected: PASS (existing round-trip + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/store.py backend/tests/test_network_store.py
git commit -m "feat(backend): saved-graph store with per-root version history (cap 5, long TTL)"
```

---

## Task 4: API routes (company ego + saved CRUD) — with isolated test cache

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_graph.py` (rewrite to use `dependency_overrides` + tmp `Cache`)

- [ ] **Step 1: Rewrite the test file** — replace the entire contents of `backend/tests/test_api_graph.py` with:

```python
import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.config.cache import Cache
from app.deps import get_cache
from app.main import app
from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, StockScore
from app.network.store import load_graph
from app.screener.store import load_snapshot, save_snapshot


@pytest.fixture
def client(tmp_path):
    """Isolate every graph-route test from the real backend/data/app.db by overriding the
    cache dependency with a throwaway tmp DB (also fixes the known Phase-A pollution)."""
    cache = Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    try:
        yield TestClient(app), cache
    finally:
        app.dependency_overrides.pop(get_cache, None)


def test_get_graph_empty_when_none(client):
    tc, _ = client
    r = tc.get("/api/graph?scope=does-not-exist")
    assert r.status_code == 200 and r.json()["edges"] == []


def test_rebuild_builds_and_bakes(client, monkeypatch):
    tc, cache = client
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold", net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40, direction="sell", net=-0.9),
    ]), cache)
    graph = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)], built=1)
    monkeypatch.setattr(routes, "build_graph", lambda scope, settings, cache: graph)

    r = tc.post("/api/graph/rebuild")
    assert r.status_code == 200 and r.json()["built"] == 1
    assert load_graph(cache, "focus") is not None
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None


def test_rescan_applies_cached_graph(client, monkeypatch):
    tc, cache = client
    from app.network.store import save_graph
    save_graph(KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)]), cache)
    fresh = ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold", net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40, direction="sell", net=-0.9),
    ])
    monkeypatch.setattr(routes, "run_scan", lambda scope, settings, cache: fresh)

    r = tc.post("/api/screen/rescan")
    assert r.status_code == 200
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None  # propagation applied on rescan, no LLM


def test_company_graph_endpoint(client, monkeypatch):
    tc, _ = client
    g = KnowledgeGraph(scope="company:AAPL", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier")], built=1)
    monkeypatch.setattr(routes, "build_company_graph", lambda ticker, settings, cache: g)
    r = tc.get("/api/graph/company/AAPL")
    assert r.status_code == 200
    assert r.json()["scope"] == "company:AAPL" and r.json()["nodes"] == ["AAPL", "TSM"]


def test_saved_graph_crud(client):
    tc, _ = client
    payload = {
        "root": "AAPL", "expanded": ["AAPL"],
        "graph": {"as_of": "", "scope": "company:AAPL", "nodes": ["AAPL", "TSM"],
                  "edges": [], "built": 1, "skipped": 0},
    }
    r = tc.post("/api/graph/saved", json=payload)
    assert r.status_code == 200
    v = r.json()
    assert v["root"] == "AAPL" and v["saved_at"]  # server-stamped

    r = tc.get("/api/graph/saved")
    assert r.status_code == 200
    summ = r.json()
    assert summ[0]["root"] == "AAPL" and len(summ[0]["versions"]) == 1

    r = tc.get("/api/graph/saved/AAPL")
    assert r.status_code == 200 and r.json()["graph"]["nodes"] == ["AAPL", "TSM"]

    r = tc.delete("/api/graph/saved/AAPL")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert tc.get("/api/graph/saved/AAPL").status_code == 404
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_api_graph.py -v`
Expected: FAIL — new tests 404 (routes not defined) / `AttributeError: build_company_graph` on the monkeypatch target. (The 3 refactored tests should already pass.)

- [ ] **Step 3: Implement the routes** — in `backend/app/api/routes.py`:

(a) Add `from datetime import datetime, timezone` near the top imports.

(b) Extend the schema import block (lines 13–20) to include the two new models:

```python
from app.models.schemas import (
    DEFAULT_MODELS,
    AnalysisResult,
    KnowledgeGraph,
    SavedGraphSummary,
    SavedGraphVersion,
    ScreenBoard,
    Settings,
    StockData,
)
```

(c) Update the service/store imports (lines 24–25):

```python
from app.network.service import build_company_graph, build_graph
from app.network.store import (
    delete_saved_graph,
    list_saved_graphs,
    load_company_graph,
    load_graph,
    save_company_graph,
    save_graph,
)
```

(d) Add the new endpoints immediately after the existing `rebuild_graph` route (after line 207). **Order matters** — declare the literal `/graph/saved` list before the `/graph/saved/{root}` param route:

```python
@router.get("/graph/company/{ticker}", response_model=KnowledgeGraph)
def get_company_graph(
    ticker: str,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> KnowledgeGraph:
    """One-hop ego graph for a single ticker — powers both 'start from company' and 'expand'."""
    return build_company_graph(ticker, store.load(), cache)


@router.get("/graph/saved", response_model=list[SavedGraphSummary])
def list_saved(cache: Cache = Depends(get_cache)) -> list[SavedGraphSummary]:
    return list_saved_graphs(cache)


@router.post("/graph/saved", response_model=SavedGraphVersion)
def save_saved(payload: SavedGraphVersion, cache: Cache = Depends(get_cache)) -> SavedGraphVersion:
    stamped = payload.model_copy(update={"saved_at": datetime.now(timezone.utc).isoformat()})
    return save_company_graph(stamped, cache)


@router.get("/graph/saved/{root}", response_model=SavedGraphVersion)
def get_saved(
    root: str, version: str | None = None, cache: Cache = Depends(get_cache)
) -> SavedGraphVersion:
    found = load_company_graph(root, cache, version)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No saved graph for '{root}'")
    return found


@router.delete("/graph/saved/{root}")
def delete_saved(root: str, version: str | None = None, cache: Cache = Depends(get_cache)) -> dict:
    return {"deleted": delete_saved_graph(root, cache, version)}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_api_graph.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the whole backend suite** (guards against route-order regressions / pollution fix):

Run: `cd backend && python -m pytest -q`
Expected: PASS (all prior tests + the new ones).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_graph.py
git commit -m "feat(backend): company ego + saved-graph CRUD routes; isolate graph route tests"
```

---

## Task 5: Frontend types + pure `mergeGraph`

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/lib/graphView.ts`
- Test: `frontend/src/lib/graphView.test.ts`

- [ ] **Step 1: Write the failing test** — append to `frontend/src/lib/graphView.test.ts`:

```typescript
import { mergeGraph } from './graphView';

describe('mergeGraph', () => {
  const FRAG_A: KnowledgeGraph = {
    as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0, nodes: ['AAPL', 'TSM'],
    edges: [{ source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' }],
  };
  const FRAG_B: KnowledgeGraph = {
    as_of: 't', scope: 'company:TSM', built: 1, skipped: 0, nodes: ['TSM', 'FOO'],
    edges: [
      { source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' }, // dup
      { source: 'TSM', target: 'FOO', type: 'customer', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' },
    ],
  };

  it('returns the fragment when there is no prior graph', () => {
    const out = mergeGraph(null, FRAG_A);
    expect(out.nodes).toEqual(['AAPL', 'TSM']);
    expect(out.edges).toHaveLength(1);
  });

  it('unions nodes and dedupes edges by source|target|type', () => {
    const out = mergeGraph(FRAG_A, FRAG_B);
    expect(out.nodes.sort()).toEqual(['AAPL', 'FOO', 'TSM']);
    expect(out.edges).toHaveLength(2); // AAPL->TSM kept once, TSM->FOO added
    expect(out.edges.some((e) => e.target === 'FOO')).toBe(true);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/lib/graphView.test.ts`
Expected: FAIL — `mergeGraph is not a function` / import error.

- [ ] **Step 3a: Add types** — append to `frontend/src/types.ts`:

```typescript
export interface SavedGraphVersion { root: string; saved_at: string; expanded: string[]; graph: KnowledgeGraph; }
export interface SavedGraphSummary { root: string; versions: string[]; }
```

- [ ] **Step 3b: Implement `mergeGraph`** — append to `frontend/src/lib/graphView.ts`:

```typescript
import type { KnowledgeGraph } from '../types';

/** Accumulate an explored subgraph: union nodes, dedupe edges by source|target|type.
 *  Pure — used by the explorer to merge each one-hop fragment into the working graph. */
export function mergeGraph(into: KnowledgeGraph | null, fragment: KnowledgeGraph): KnowledgeGraph {
  if (!into) return { ...fragment, nodes: [...fragment.nodes], edges: [...fragment.edges] };
  const nodes = Array.from(new Set([...into.nodes, ...fragment.nodes]));
  const seen = new Set(into.edges.map((e) => `${e.source}|${e.target}|${e.type}`));
  const edges = [...into.edges];
  for (const e of fragment.edges) {
    const k = `${e.source}|${e.target}|${e.type}`;
    if (!seen.has(k)) { seen.add(k); edges.push(e); }
  }
  return { ...into, nodes, edges };
}
```

(Note: `graphView.ts` already imports several types from `../types` on line 1 — add `KnowledgeGraph` to that existing import instead of a second import line if your linter prefers; it is already imported there, so no new import is strictly needed. Verify line 1 includes `KnowledgeGraph`.)

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/lib/graphView.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/lib/graphView.ts frontend/src/lib/graphView.test.ts
git commit -m "feat(frontend): SavedGraph types and pure mergeGraph accumulator"
```

---

## Task 6: API client methods

**Files:**
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing tests** — append inside the `describe('api client', …)` block in `frontend/src/api/client.test.ts` (before the closing `});`):

```typescript
  it('getCompanyGraph GETs /graph/company/{ticker}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ nodes: ['AAPL'], edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getCompanyGraph('AAPL');
    expect(fetchMock.mock.calls[0][0] as string).toContain('/graph/company/AAPL');
  });

  it('saveGraph POSTs /graph/saved with a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ root: 'AAPL', saved_at: 't', expanded: [], graph: {} }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.saveGraph({ root: 'AAPL', saved_at: '', expanded: [], graph: { as_of: '', scope: 'x', nodes: [], edges: [], built: 0, skipped: 0 } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/saved');
    expect((init as RequestInit).method).toBe('POST');
  });

  it('listSavedGraphs GETs /graph/saved', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.listSavedGraphs();
    expect(fetchMock.mock.calls[0][0] as string).toMatch(/\/graph\/saved$/);
  });

  it('loadSavedGraph GETs a version when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ root: 'AAPL', saved_at: 't', expanded: [], graph: {} }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.loadSavedGraph('AAPL', 't1');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/graph/saved/AAPL');
    expect(url).toContain('version=t1');
  });

  it('deleteSavedGraph DELETEs /graph/saved/{root}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ deleted: true }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.deleteSavedGraph('AAPL');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/saved/AAPL');
    expect((init as RequestInit).method).toBe('DELETE');
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `api.getCompanyGraph is not a function`.

- [ ] **Step 3: Implement** — in `frontend/src/api/client.ts`:

(a) Extend the type import (lines 1–10) to add `SavedGraphSummary` and `SavedGraphVersion`.

(b) Add these methods inside the `api` object (after `rebuildGraph`, line 62):

```typescript
  getCompanyGraph: (ticker: string) =>
    http<KnowledgeGraph>(`/graph/company/${encodeURIComponent(ticker)}`),
  listSavedGraphs: () => http<SavedGraphSummary[]>('/graph/saved'),
  saveGraph: (v: SavedGraphVersion) =>
    http<SavedGraphVersion>('/graph/saved', { method: 'POST', body: JSON.stringify(v) }),
  loadSavedGraph: (root: string, version?: string) =>
    http<SavedGraphVersion>(
      `/graph/saved/${encodeURIComponent(root)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
    ),
  deleteSavedGraph: (root: string, version?: string) =>
    http<{ deleted: boolean }>(
      `/graph/saved/${encodeURIComponent(root)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
      { method: 'DELETE' },
    ),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(frontend): graph explorer API client methods (company + saved CRUD)"
```

---

## Task 7: Query hooks

**Files:**
- Modify: `frontend/src/hooks/queries.ts`

(No dedicated hook test — consistent with the repo, hooks are exercised via the page test in Task 9.)

- [ ] **Step 1: Implement** — append to `frontend/src/hooks/queries.ts`:

```typescript
import type { SavedGraphVersion } from '../types';

export function useEgoGraph() {
  return useMutation({ mutationFn: (ticker: string) => api.getCompanyGraph(ticker) });
}

export function useFocusGraph() {
  return useMutation({ mutationFn: () => api.getGraph() });
}

export function useSavedGraphs() {
  return useQuery({ queryKey: ['savedGraphs'], queryFn: api.listSavedGraphs });
}

export function useSaveGraph() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: SavedGraphVersion) => api.saveGraph(v),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['savedGraphs'] }),
  });
}

export function useLoadSavedGraph() {
  return useMutation({
    mutationFn: ({ root, version }: { root: string; version?: string }) =>
      api.loadSavedGraph(root, version),
  });
}

export function useDeleteSavedGraph() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ root, version }: { root: string; version?: string }) =>
      api.deleteSavedGraph(root, version),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['savedGraphs'] }),
  });
}
```

(`useMutation`, `useQuery`, `useQueryClient`, and `api` are already imported at the top of the file. Add the `SavedGraphVersion` type import shown above near the existing `import type { Settings }` line — or merge into it.)

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS (no type errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/queries.ts
git commit -m "feat(frontend): query hooks for ego/focus/saved graphs"
```

---

## Task 8: GraphSidebar explorer controls

**Files:**
- Modify: `frontend/src/components/GraphSidebar.tsx`
- Test: `frontend/src/components/GraphSidebar.test.tsx`

- [ ] **Step 1: Rewrite the test file** — replace the entire contents of `frontend/src/components/GraphSidebar.test.tsx` with:

```tsx
import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphSidebar } from './GraphSidebar';
import type { ViewNode } from '../lib/graphView';
import type { RelationType } from '../types';

const SELECTED: ViewNode = {
  id: 'AAPL', label: 'AAPL', direction: 'sell', score: 80, sector: 'Tech', onBoard: true,
  network: { ticker: 'AAPL', intensity: 0.5, signed: -0.4, reasons: ['supplier TSM (bearish)'],
    influences: [{ neighbour: 'TSM', name: 'Taiwan Semi', type: 'supplier', edge_sentiment: 'negative',
      neighbour_direction: 'sell', signed: -0.4, reason: 'supplier TSM (bearish)' }] },
};

function base() {
  return {
    root: '', onLoadRoot: vi.fn(), onExpand: vi.fn(), onLoadFocus: vi.fn(),
    onRebuild: vi.fn(), rebuilding: false, loading: false,
    canSave: true, onSave: vi.fn(), saving: false,
    saved: [], onLoadSaved: vi.fn(), onDeleteSaved: vi.fn(),
    nodeCount: 2, linkCount: 1,
    sectors: ['Tech'], sector: '', onSector: vi.fn(),
    enabledTypes: new Set<RelationType>(['supplier']), onToggleType: vi.fn(),
  };
}

function wrap(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

it('starts a root from the input', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/ticker/i), { target: { value: 'tsla' } });
  fireEvent.click(screen.getByRole('button', { name: /^start$/i }));
  expect(props.onLoadRoot).toHaveBeenCalledWith('tsla');
});

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

it('shows the selected node detail and a Dashboard link', () => {
  wrap(<GraphSidebar {...base()} selected={SELECTED} />);
  expect(screen.getByText(/supplier TSM/i)).toBeInTheDocument();
  const link = screen.getByRole('link', { name: /open in dashboard/i });
  expect(link).toHaveAttribute('href', expect.stringContaining('ticker=AAPL'));
});

it('fires save / load-focus', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /save graph/i }));
  fireEvent.click(screen.getByRole('button', { name: /load focus set/i }));
  expect(props.onSave).toHaveBeenCalled();
  expect(props.onLoadFocus).toHaveBeenCalled();
});

it('lists saved graphs and fires load / delete', () => {
  const props = { ...base(), saved: [{ root: 'AAPL', versions: ['t2', 't1'] }] };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^load AAPL$/i }));
  expect(props.onLoadSaved).toHaveBeenCalledWith('AAPL', undefined);
  fireEvent.click(screen.getByRole('button', { name: /delete AAPL/i }));
  expect(props.onDeleteSaved).toHaveBeenCalledWith('AAPL', undefined);
});

it('toggling an edge-type fires onToggleType', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /competitor/i }));
  expect(props.onToggleType).toHaveBeenCalledWith('competitor');
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx`
Expected: FAIL — new props/controls don't exist yet.

- [ ] **Step 3: Implement** — replace the entire contents of `frontend/src/components/GraphSidebar.tsx` with:

```tsx
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { RelationType, SavedGraphSummary } from '../types';
import type { ViewNode } from '../lib/graphView';

const EDGE_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];

export interface GraphSidebarProps {
  root: string;
  onLoadRoot: (ticker: string) => void;
  onExpand: (ticker: string) => void;
  onLoadFocus: () => void;
  onRebuild: () => void;
  rebuilding: boolean;
  loading: boolean;
  canSave: boolean;
  onSave: () => void;
  saving: boolean;
  saved: SavedGraphSummary[];
  onLoadSaved: (root: string, version?: string) => void;
  onDeleteSaved: (root: string, version?: string) => void;
  nodeCount: number;
  linkCount: number;
  sectors: string[];
  sector: string;
  onSector: (s: string) => void;
  enabledTypes: Set<RelationType>;
  onToggleType: (t: RelationType) => void;
  selected: ViewNode | null;
}

export function GraphSidebar(props: GraphSidebarProps) {
  const {
    onLoadRoot, onExpand, onLoadFocus, onRebuild, rebuilding, loading,
    canSave, onSave, saving, saved, onLoadSaved, onDeleteSaved,
    nodeCount, linkCount, sectors, sector, onSector, enabledTypes, onToggleType, selected,
  } = props;
  const [rootInput, setRootInput] = useState('');

  return (
    <aside className="graph-sidebar panel">
      <div className="panel-head"><span className="section-label">Explore graph</span></div>

      <div className="graph-explore-controls">
        <label>Start from company
          <input
            placeholder="Ticker (e.g. AAPL)"
            value={rootInput}
            onChange={(e) => setRootInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && rootInput.trim()) onLoadRoot(rootInput.trim()); }}
          />
        </label>
        <button disabled={loading || !rootInput.trim()} onClick={() => onLoadRoot(rootInput.trim())}>Start</button>
        <div className="graph-actions">
          <button className="secondary" disabled={loading} onClick={onLoadFocus}>Load focus set</button>
          <button className="secondary" disabled={rebuilding} onClick={onRebuild}>
            {rebuilding ? 'Rebuilding… (LLM)' : 'Rebuild focus (LLM)'}
          </button>
        </div>
        <button disabled={!canSave || saving} onClick={onSave}>{saving ? 'Saving…' : 'Save graph'}</button>
      </div>

      <p className="muted">{nodeCount} nodes · {linkCount} edges</p>

      {saved.length > 0 && (
        <div className="graph-saves">
          <span className="label">Saved graphs</span>
          {saved.map((s) => (
            <div key={s.root} className="graph-save-row">
              <button className="linklike" onClick={() => onLoadSaved(s.root, undefined)}>Load {s.root}</button>
              {s.versions.length > 1 && (
                <select defaultValue="" onChange={(e) => { if (e.target.value) onLoadSaved(s.root, e.target.value); }}>
                  <option value="">latest ({s.versions.length})</option>
                  {s.versions.map((v) => <option key={v} value={v}>{new Date(v).toLocaleString()}</option>)}
                </select>
              )}
              <button className="icon-btn" aria-label={`delete ${s.root}`} onClick={() => onDeleteSaved(s.root, undefined)}>✕</button>
            </div>
          ))}
        </div>
      )}

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
          <button disabled={loading} onClick={() => onExpand(selected.id)}>Expand neighbours</button>
          {selected.network && selected.network.influences.length > 0 ? (
            <ul className="factor-list">
              {selected.network.influences.map((inf, i) => {
                const lean = inf.signed > 0 ? 'bullish' : inf.signed < 0 ? 'bearish' : 'neutral';
                return (
                  <li key={i}><b>{inf.type} {inf.neighbour}</b> — news {inf.edge_sentiment} ({lean})</li>
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
          <p className="muted">Click a node for its detail, then Expand to grow the graph.</p>
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

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/components/GraphSidebar.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphSidebar.test.tsx
git commit -m "feat(frontend): graph sidebar explorer controls (root, expand, save/load)"
```

---

## Task 9: Graph page rework + styles

**Files:**
- Modify: `frontend/src/pages/Graph.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/pages/Graph.test.tsx`

- [ ] **Step 1: Rewrite the test file** — replace the entire contents of `frontend/src/pages/Graph.test.tsx` with:

```tsx
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
    getScreen: vi.fn(), getSectors: vi.fn(), getGraph: vi.fn(), rebuildGraph: vi.fn(),
    getCompanyGraph: vi.fn(), listSavedGraphs: vi.fn(), saveGraph: vi.fn(),
    loadSavedGraph: vi.fn(), deleteSavedGraph: vi.fn(),
  },
}));
import { api } from '../api/client';

const BOARD: ScreenBoard = { as_of: 't', scope: 'all', scanned: 0, skipped: 0, items: [] };
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
  vi.mocked(api.getScreen).mockResolvedValue(BOARD);
  vi.mocked(api.getSectors).mockResolvedValue([]);
  vi.mocked(api.listSavedGraphs).mockResolvedValue([]);
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
  fireEvent.click(await screen.findByRole('button', { name: 'sel-TSM' })); // select TSM
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
  fireEvent.click(screen.getByRole('button', { name: /save graph/i }));
  await waitFor(() => expect(api.saveGraph).toHaveBeenCalled());
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Graph.test.tsx`
Expected: FAIL — page still uses the old `useGraph` API / props mismatch.

- [ ] **Step 3: Implement the page** — replace the entire contents of `frontend/src/pages/Graph.tsx` with:

```tsx
import { useMemo, useState } from 'react';
import { GraphCanvas } from '../components/GraphCanvas';
import { GraphSidebar } from '../components/GraphSidebar';
import {
  useDeleteSavedGraph, useEgoGraph, useFocusGraph, useLoadSavedGraph,
  useRebuildGraph, useSaveGraph, useSavedGraphs, useScreen, useSectors,
} from '../hooks/queries';
import { applyFilters, mergeGraph, mergeNodes, toLinks, type ViewNode } from '../lib/graphView';
import type { KnowledgeGraph, RelationType } from '../types';

const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];
const EMPTY_GRAPH: KnowledgeGraph = { as_of: '', scope: 'explore', nodes: [], edges: [], built: 0, skipped: 0 };

export default function Graph() {
  const board = useScreen(undefined, undefined, 0); // full uncapped board for node colour/size
  const sectors = useSectors();
  const ego = useEgoGraph();
  const focus = useFocusGraph();
  const rebuild = useRebuildGraph();
  const saved = useSavedGraphs();
  const saveGraph = useSaveGraph();
  const loadSaved = useLoadSavedGraph();
  const deleteSaved = useDeleteSavedGraph();

  const [working, setWorking] = useState<KnowledgeGraph | null>(null);
  const [root, setRoot] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sector, setSector] = useState('');
  const [enabledTypes, setEnabledTypes] = useState<Set<RelationType>>(new Set(ALL_TYPES));
  const [notice, setNotice] = useState<string | null>(null);

  const loadRoot = async (ticker: string) => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setNotice(null);
    const frag = await ego.mutateAsync(t);
    setWorking(frag); setRoot(t); setExpanded(new Set()); setSelectedId(t);
    if (frag.edges.length === 0) setNotice(`No relationships found for ${t}.`);
  };

  const expand = async (ticker: string) => {
    setNotice(null);
    const frag = await ego.mutateAsync(ticker);
    setWorking((w) => mergeGraph(w, frag));
    setExpanded((s) => new Set(s).add(ticker));
    if (frag.edges.length === 0) setNotice(`No further relationships for ${ticker}.`);
  };

  const loadFocus = async () => {
    setNotice(null);
    const g = await focus.mutateAsync();
    setWorking(g); setRoot(''); setExpanded(new Set()); setSelectedId(null);
    if (g.nodes.length === 0) setNotice('No focus graph yet — Rebuild focus to extract it.');
  };

  const doRebuild = async () => {
    setNotice(null);
    const g = await rebuild.mutateAsync();
    setWorking(g); setRoot(''); setExpanded(new Set()); setSelectedId(null);
  };

  const doSave = async () => {
    if (!working || working.nodes.length === 0) return;
    await saveGraph.mutateAsync({
      root: root || working.nodes[0], saved_at: '', expanded: [...expanded], graph: working,
    });
  };

  const doLoadSaved = async (r: string, version?: string) => {
    const v = await loadSaved.mutateAsync({ root: r, version });
    setWorking(v.graph); setRoot(v.root); setExpanded(new Set(v.expanded)); setSelectedId(v.root || null);
  };

  const doDeleteSaved = async (r: string, version?: string) => {
    await deleteSaved.mutateAsync({ root: r, version });
  };

  const toggleType = (t: RelationType) =>
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  const resetFilters = () => { setSector(''); setEnabledTypes(new Set(ALL_TYPES)); };

  const view = useMemo(() => {
    const g = working ?? EMPTY_GRAPH;
    return applyFilters(mergeNodes(g, board.data), toLinks(g), sector || null, enabledTypes);
  }, [working, board.data, sector, enabledTypes]);

  const selected = useMemo<ViewNode | null>(
    () => view.nodes.find((n) => n.id === selectedId) ?? null,
    [view.nodes, selectedId],
  );

  const busy = ego.isPending || focus.isPending;
  const empty = !working || working.nodes.length === 0;
  const filteredEmpty = !empty && view.nodes.length === 0;

  return (
    <div className="graph-page">
      <div className="graph-main panel">
        {busy && <p className="muted">Loading…</p>}
        {ego.isError && <p className="error">Couldn't load: {(ego.error as Error).message}</p>}
        {notice && <p className="muted">{notice}</p>}
        {empty && !busy && (
          <div className="graph-empty">
            <p className="muted">Type a company ticker to start, or load the focus set.</p>
          </div>
        )}
        {filteredEmpty && (
          <div className="graph-empty">
            <p className="muted">No nodes match these filters.</p>
            <button className="secondary" onClick={resetFilters}>Reset filters</button>
          </div>
        )}
        {!empty && !filteredEmpty && (
          <GraphCanvas nodes={view.nodes} links={view.links} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </div>

      <GraphSidebar
        root={root}
        onLoadRoot={loadRoot}
        onExpand={expand}
        onLoadFocus={loadFocus}
        onRebuild={doRebuild}
        rebuilding={rebuild.isPending}
        loading={busy}
        canSave={!!working && working.nodes.length > 0}
        onSave={doSave}
        saving={saveGraph.isPending}
        saved={saved.data ?? []}
        onLoadSaved={doLoadSaved}
        onDeleteSaved={doDeleteSaved}
        nodeCount={view.nodes.length}
        linkCount={view.links.length}
        sectors={sectors.data ?? []}
        sector={sector}
        onSector={setSector}
        enabledTypes={enabledTypes}
        onToggleType={toggleType}
        selected={selected}
      />
    </div>
  );
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/pages/Graph.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Add styles** — append to the end of `frontend/src/styles.css`:

```css
.graph-explore-controls { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
.graph-explore-controls input { width: 100%; }
.graph-actions { display: flex; gap: 6px; }
.graph-actions .secondary { flex: 1; }
.graph-saves { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; }
.graph-save-row { display: flex; align-items: center; gap: 6px; }
.graph-save-row .linklike { background: none; border: none; color: #58a6ff; cursor: pointer; padding: 0; text-align: left; flex: 1; }
.graph-save-row .icon-btn { background: none; border: none; color: #8b949e; cursor: pointer; }
```

- [ ] **Step 6: Full frontend gate**

Run: `cd frontend && npx vitest run && npm run build`
Expected: all test files PASS; build succeeds (no TS errors).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Graph.tsx frontend/src/pages/Graph.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): company-rooted graph explorer page (root, expand, save/load)"
```

---

## Task 10: Full verification + live browser smoke

**Files:** none (verification only)

- [ ] **Step 1: Backend suite green**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Frontend suite + build green**

Run: `cd frontend && npx vitest run && npm run build`
Expected: all PASS, build clean.

- [ ] **Step 3: Live smoke (isolated DB — same protocol as Phase B)**

1. Start the backend against a **temp** `DATA_DIR` so the smoke never touches the real DB:
   - PowerShell: `$env:DATA_DIR="$PWD\backend\data_smoke"; cd backend; uvicorn app.main:app --port 8000`
2. Seed a provider key + a tiny board/graph if needed (or set the active provider to a configured one), then start the frontend: `cd frontend && npm run dev` (must be on **5173** for CORS).
3. In the browser at `/graph`:
   - Type a ticker → **Start** → root + neighbours render; node colours/sizes match the board.
   - Select a neighbour → **Expand neighbours** → graph grows; no console errors.
   - **Save graph**, reload the page, **Load <ROOT>** → the saved subgraph returns.
   - Toggle an edge-type filter and a sector filter → nodes/edges hide; **Reset filters** restores.
4. Stop both servers. Delete `backend/data_smoke/`.

- [ ] **Step 4: Confirm no real-DB pollution**

Run: `git -C D:/workspace/ai-stocks-news-analysis status --short`
Expected: no changes under `backend/data/` (the suite now uses `dependency_overrides`; smoke used a temp `DATA_DIR`).

- [ ] **Step 5: Final review + merge prep**

- Re-read the diff for stray `any`, leftover console logs, or dead code.
- Update memory (`MEMORY.md` + `project-state.md`) noting the explorer is built.
- Merge to `master` per the established flow (ff-merge, delete branch) **only when the user asks**; do not push without an explicit request.

---

## Self-Review (completed during planning)

- **Spec coverage:** ✅ `build_company_graph` (root+expand) → Task 2; manual on-demand expansion → Tasks 8–9; per-company saves w/ 5-version history → Task 3; pure research view (no signal change) → no `apply_network` call anywhere in new code (verified — only the untouched daily path calls it); coexistence + "Load focus set" + retained Rebuild → Tasks 8–9; long-lived `graph_user_saved:` keys → Task 3; 5 endpoints → Task 4; frontend accumulator + sidebar + page → Tasks 5–9; test-pollution fix → Task 4.
- **Placeholder scan:** ✅ none — every step has concrete code/commands.
- **Type consistency:** ✅ `SavedGraphVersion {root, saved_at, expanded, graph}` and `SavedGraphSummary {root, versions}` identical across schemas, store, routes, TS types, client, hooks, sidebar, page. `mergeGraph(into|null, fragment)` signature consistent (graphView ↔ page). Endpoint paths consistent (client ↔ routes ↔ tests). Hook names (`useEgoGraph`/`useFocusGraph`/`useSavedGraphs`/`useSaveGraph`/`useLoadSavedGraph`/`useDeleteSavedGraph`) consistent (hooks ↔ page).
