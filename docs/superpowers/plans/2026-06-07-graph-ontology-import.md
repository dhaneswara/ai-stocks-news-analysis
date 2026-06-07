# External Ontology Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users enrich the knowledge graph by importing an app-defined JSON "ontology model" (produced by an external tool like ChatGPT); imported relationships persist in a separate overlay and feed the network signal like native edges.

**Architecture:** A pure normalization function maps an external JSON model into a `KnowledgeGraph` fragment (hybrid ticker resolution + 6-or-`other` relation types + `origin="imported"`). Fragments are stored as removable named "import sets" in a new long-TTL `graph_imported:*` namespace and unioned into the focus graph **at read time** via `effective_graph()`, so imports survive rebuilds and the saved snapshot stays idempotent. The frontend gains an Import tab (paste/upload JSON + a copy-paste ChatGPT prompt) and renders imported/external elements distinctly.

**Tech Stack:** Backend — Python 3.13, FastAPI, Pydantic v2, SQLite KV `Cache`, pytest. Frontend — React + TypeScript, TanStack Query, react-force-graph-2d, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-06-07-graph-ontology-import-design.md`

**Conventions (from `stocks-app-conventions`):**
- Backend tests: from `backend/`, run `.venv/Scripts/python.exe -m pytest -q`.
- Frontend tests/build: from `frontend/`, run `npx vitest run` and `npm run build`.
- Commits: Conventional Commits, one per task. **NO `Co-Authored-By: Claude` trailer.**
- Work happens on branch `feat/graph-ontology-import` (already created; the spec commit lives there).

---

## File structure

**Backend**
- Modify `backend/app/models/schemas.py` — new fields/types (Task 1).
- Create `backend/app/network/import_model.py` — `normalize_import`, `map_relation_type` (Task 2).
- Modify `backend/app/network/store.py` — `merge_graphs`, overlay CRUD, `load_overlay`, `effective_graph` (Task 3).
- Modify `backend/app/api/routes.py` — import endpoints + `effective_graph` wiring (Task 4).
- Modify `backend/app/network/runner.py` — bake overlay into the scheduled snapshot (Task 5).
- Create `backend/tests/test_import_model.py` (Tasks 1–2), `backend/tests/test_graph_overlay.py` (Task 3), `backend/tests/test_network_runner.py` (Task 5); extend `backend/tests/test_api_graph.py` (Task 4).

**Frontend**
- Modify `frontend/src/types.ts` — types (Task 6).
- Modify `frontend/src/lib/graphView.ts` — `mergeNodes`/`toLinks`/`mergeGraph`/`ViewNode`/`ViewLink` (Task 7).
- Create `frontend/src/lib/importPrompt.ts` — prompt template (Task 8).
- Modify `frontend/src/api/client.ts` + `frontend/src/hooks/queries.ts` (Task 9).
- Modify `frontend/src/components/GraphSidebar.tsx` + `frontend/src/components/GraphCanvas.tsx` + `frontend/src/styles.css` (Task 10).
- Modify `frontend/src/pages/Graph.tsx` (Task 11).
- Tests: extend `frontend/src/lib/graphView.test.ts` (Task 7), create `frontend/src/lib/importPrompt.test.ts` (Task 8), extend `frontend/src/api/client.test.ts` (Task 9), extend `frontend/src/components/GraphSidebar.test.tsx` (Task 10), extend `frontend/src/pages/Graph.test.tsx` (Task 11).

---

## Task 1: Backend schemas

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_import_model.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_import_model.py`:

```python
from app.models.schemas import GraphEdge, ImportReport, ImportSetSummary, KnowledgeGraph, NodeMeta


def test_new_schema_defaults():
    e = GraphEdge(source="AAPL", target="MSFT", type="other")
    assert e.origin == "extracted"          # back-compat default
    g = KnowledgeGraph()
    assert g.node_meta == {}                 # back-compat default
    m = NodeMeta(label="OpenAI", kind="private_company", source="imported")
    assert m.source == "imported"
    assert ImportSetSummary().edge_count == 0
    assert ImportReport().warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_import_model.py -q` (from `backend/`)
Expected: FAIL — `ImportError` (`ImportReport`/`ImportSetSummary`/`NodeMeta` not defined) or `"other"` not a valid `RelationType`.

- [ ] **Step 3: Edit `schemas.py`**

Change the `RelationType` alias (around line 104) to add `"other"`:

```python
RelationType = Literal["supplier", "customer", "partner", "competitor", "owner", "subsidiary", "other"]
```

Add a `NodeMeta` model just above `GraphEdge`:

```python
class NodeMeta(BaseModel):
    label: str = ""
    kind: str = ""
    source: Literal["native", "imported"] = "native"
```

Add `origin` to `GraphEdge` (after `as_of`):

```python
    as_of: str = ""
    origin: Literal["extracted", "imported"] = "extracted"
```

Add `node_meta` to `KnowledgeGraph` (after `edges`):

```python
    edges: list[GraphEdge] = Field(default_factory=list)
    node_meta: dict[str, NodeMeta] = Field(default_factory=dict)
```

Add two new models near the other graph models (e.g. after `SavedGraphSummary`):

```python
class ImportSetSummary(BaseModel):
    id: str = ""
    name: str = ""
    as_of: str = ""
    created_at: str = ""
    node_count: int = 0
    edge_count: int = 0


class ImportReport(BaseModel):
    id: str = ""
    name: str = ""
    nodes_added: int = 0
    edges_added: int = 0
    dropped: int = 0
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_import_model.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite (no regressions from the `Literal` change)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all existing tests green).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_import_model.py
git commit -m "feat(graph): add import schemas (node_meta, edge origin, other type)"
```

---

## Task 2: Normalization pipeline (`import_model.py`)

**Files:**
- Create: `backend/app/network/import_model.py`
- Test: `backend/tests/test_import_model.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_import_model.py`:

```python
from app.analysis.relationships import TickerResolver
from app.models.schemas import UniverseEntry
from app.network.import_model import map_relation_type, normalize_import

UNIVERSE = [
    UniverseEntry(ticker="AAPL", name="Apple", sector="Tech"),
    UniverseEntry(ticker="NVDA", name="NVIDIA", sector="Tech"),
]


def _resolver():
    return TickerResolver(UNIVERSE)


def test_map_relation_type():
    assert map_relation_type("supplier") == "supplier"
    assert map_relation_type("invests_in") == "owner"
    assert map_relation_type("licenses") == "partner"
    assert map_relation_type("totally-unknown") == "other"
    assert map_relation_type(None) == "other"


def test_resolves_tickers_and_keeps_externals():
    payload = {
        "name": "x",
        "nodes": [
            {"id": "NVDA", "label": "NVIDIA", "kind": "company"},
            {"id": "OpenAI", "label": "OpenAI", "kind": "private_company"},
        ],
        "edges": [
            {"source": "NVDA", "target": "OpenAI", "type": "customer",
             "sentiment": "positive", "weight": 0.8, "confidence": 0.7},
        ],
    }
    graph, report = normalize_import(payload, _resolver())
    assert "NVDA" in graph.nodes                     # resolved to ticker
    assert "ext:openai" in graph.nodes               # external, namespaced
    assert graph.node_meta["ext:openai"].label == "OpenAI"
    assert graph.node_meta["ext:openai"].source == "imported"
    e = graph.edges[0]
    assert e.source == "NVDA" and e.target == "ext:openai"
    assert e.origin == "imported"
    assert report.nodes_added == 2 and report.edges_added == 1


def test_type_mapping_defaults_and_clamp():
    payload = {"edges": [
        {"source": "AAPL", "target": "NVDA", "type": "acquired",
         "sentiment": "??", "weight": 5, "confidence": -1},
    ]}
    graph, _ = normalize_import(payload, _resolver())
    e = graph.edges[0]
    assert e.type == "owner"            # acquired -> owner
    assert e.sentiment == "neutral"     # invalid -> neutral
    assert e.weight == 1.0 and e.confidence == 0.0   # clamped to 0..1


def test_drops_self_loops_and_dedupes():
    payload = {"edges": [
        {"source": "AAPL", "target": "AAPL", "type": "partner"},          # self-loop -> dropped
        {"source": "AAPL", "target": "NVDA", "type": "partner"},
        {"source": "AAPL", "target": "NVDA", "type": "partner"},          # dup -> dropped
    ]}
    graph, report = normalize_import(payload, _resolver())
    assert len(graph.edges) == 1
    assert report.dropped == 2


def test_non_dict_payload_is_safe():
    graph, report = normalize_import("not a dict", _resolver())
    assert graph.edges == [] and report.warnings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_import_model.py -q`
Expected: FAIL — `ModuleNotFoundError: app.network.import_model`.

- [ ] **Step 3: Create `backend/app/network/import_model.py`**

```python
"""Validate + normalize an externally-authored ontology model into a KnowledgeGraph fragment.

Pure: no I/O, no LLM. Resolves entities to universe tickers via TickerResolver (hybrid: a match
becomes a ticker node; a miss becomes an ``ext:<slug>`` node with a node_meta entry). Maps relation
types onto the six canonical types or ``other``. Tags every edge ``origin="imported"``. Degrades
leniently: malformed nodes/edges are skipped and counted, never raised.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.analysis.relationships import TickerResolver
from app.models.schemas import GraphEdge, ImportReport, KnowledgeGraph, NodeMeta

MAX_IMPORT_EDGES = 1000

_CANONICAL = {"supplier", "customer", "partner", "competitor", "owner", "subsidiary"}

_SYNONYMS = {
    "invests_in": "owner", "investor": "owner", "stake": "owner", "owns": "owner",
    "acquired": "owner", "acquires": "owner", "acquisition": "owner", "parent": "owner",
    "owned_by": "subsidiary", "unit": "subsidiary", "division": "subsidiary",
    "licenses": "partner", "licensee": "partner", "licensor": "partner", "alliance": "partner",
    "collaborates": "partner", "collaboration": "partner", "partners": "partner",
    "jv": "partner", "joint_venture": "partner",
    "vendor": "supplier", "supplies": "supplier", "supplier_of": "supplier",
    "buys_from": "customer", "client": "customer", "buyer": "customer",
    "rival": "competitor", "competes": "competitor", "competes_with": "competitor",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def map_relation_type(raw: Any) -> str:
    t = str(raw or "").strip().lower()
    if t in _CANONICAL:
        return t
    return _SYNONYMS.get(t, "other")


def _clamp01(x: Any, default: float = 0.5) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


def normalize_import(
    payload: Any, resolver: TickerResolver, *, now: datetime | None = None
) -> tuple[KnowledgeGraph, ImportReport]:
    now = now or datetime.now(timezone.utc)
    report = ImportReport()
    if not isinstance(payload, dict):
        report.warnings.append("Payload is not a JSON object; nothing imported.")
        return KnowledgeGraph(scope="imported", as_of=now.isoformat()), report

    as_of = str(payload.get("as_of") or now.isoformat())
    id_map: dict[str, str] = {}
    node_meta: dict[str, NodeMeta] = {}

    def resolve_entity(raw_id: Any, label: str = "", kind: str = "") -> str:
        rid = str(raw_id or "").strip()
        lbl = str(label or rid).strip()
        if not rid:
            return ""
        if rid in id_map:
            return id_map[rid]
        ticker = resolver.resolve(lbl, rid)
        if ticker:
            id_map[rid] = ticker
            return ticker
        ext = f"ext:{_slug(lbl or rid)}"
        id_map[rid] = ext
        node_meta[ext] = NodeMeta(label=lbl or rid, kind=str(kind or ""), source="imported")
        return ext

    for n in payload.get("nodes", []) or []:
        if isinstance(n, dict) and (n.get("id") or n.get("label")):
            resolve_entity(n.get("id") or n.get("label"), n.get("label", ""), n.get("kind", ""))

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    dropped = 0
    for e in payload.get("edges", []) or []:
        if not isinstance(e, dict):
            dropped += 1
            continue
        src = resolve_entity(e.get("source", ""))
        tgt = resolve_entity(e.get("target", ""))
        if not src or not tgt or src == tgt:
            dropped += 1
            continue
        rel = map_relation_type(e.get("type"))
        sent = e.get("sentiment", "neutral")
        if sent not in ("positive", "negative", "neutral"):
            sent = "neutral"
        key = (src, tgt, rel)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        edges.append(GraphEdge(
            source=src, target=tgt, type=rel, sentiment=sent,
            weight=_clamp01(e.get("weight")), confidence=_clamp01(e.get("confidence")),
            evidence=str(e.get("evidence", ""))[:200], url=str(e.get("url", "")),
            as_of=as_of, origin="imported",
        ))

    edges.sort(key=lambda x: x.weight * x.confidence, reverse=True)
    if len(edges) > MAX_IMPORT_EDGES:
        report.warnings.append(
            f"Import capped at {MAX_IMPORT_EDGES} edges; {len(edges) - MAX_IMPORT_EDGES} dropped."
        )
        dropped += len(edges) - MAX_IMPORT_EDGES
        edges = edges[:MAX_IMPORT_EDGES]

    nodes = sorted({e.source for e in edges} | {e.target for e in edges})
    node_set = set(nodes)
    node_meta = {k: v for k, v in node_meta.items() if k in node_set}

    report.nodes_added = len(nodes)
    report.edges_added = len(edges)
    report.dropped = dropped
    graph = KnowledgeGraph(
        scope="imported", as_of=as_of, nodes=nodes, edges=edges, node_meta=node_meta, built=1
    )
    return graph, report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_import_model.py -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/import_model.py backend/tests/test_import_model.py
git commit -m "feat(graph): add normalize_import pipeline (resolve, map types, provenance)"
```

---

## Task 3: Overlay store (`merge_graphs`, CRUD, `effective_graph`)

**Files:**
- Modify: `backend/app/network/store.py`
- Test: `backend/tests/test_graph_overlay.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_graph_overlay.py`:

```python
from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, NodeMeta
from app.network.store import (
    add_import_set, delete_import_set, effective_graph, list_import_sets,
    load_overlay, merge_graphs, save_graph,
)


def _edge(s, t, ty="partner"):
    return GraphEdge(source=s, target=t, type=ty, origin="imported")


def test_merge_graphs_unions_nodes_edges_and_meta():
    a = KnowledgeGraph(nodes=["AAPL", "NVDA"], edges=[_edge("AAPL", "NVDA")])
    b = KnowledgeGraph(
        nodes=["NVDA", "ext:openai"], edges=[_edge("AAPL", "NVDA"), _edge("NVDA", "ext:openai")],
        node_meta={"ext:openai": NodeMeta(label="OpenAI", source="imported")},
    )
    out = merge_graphs(a, b)
    assert sorted(out.nodes) == ["AAPL", "NVDA", "ext:openai"]
    assert len(out.edges) == 2                       # AAPL->NVDA deduped
    assert out.node_meta["ext:openai"].label == "OpenAI"


def test_overlay_crud_and_load(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g = KnowledgeGraph(scope="imported", nodes=["AAPL", "NVDA"], edges=[_edge("AAPL", "NVDA")])
    s = add_import_set("set one", g, cache, created_at="2026-06-07T00:00:00+00:00")
    assert s.edge_count == 1
    assert [x.id for x in list_import_sets(cache)] == [s.id]
    overlay = load_overlay(cache)
    assert overlay.edges[0].source == "AAPL"
    assert delete_import_set(s.id, cache) is True
    assert list_import_sets(cache) == []
    assert load_overlay(cache).edges == []


def test_effective_graph_merges_focus_and_overlay(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_graph(KnowledgeGraph(scope="focus", nodes=["AAPL"], edges=[_edge("AAPL", "TSM", "supplier")]), cache)
    add_import_set("o", KnowledgeGraph(nodes=["AAPL", "NVDA"], edges=[_edge("AAPL", "NVDA")]),
                   cache, created_at="2026-06-07T00:00:00+00:00")
    eff = effective_graph(cache, "focus")
    assert eff.scope == "focus"
    assert len(eff.edges) == 2
    assert {e.target for e in eff.edges} == {"TSM", "NVDA"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_graph_overlay.py -q`
Expected: FAIL — `ImportError` (`merge_graphs`/`add_import_set`/… not defined).

- [ ] **Step 3: Edit `store.py`**

Add to the import line at the top (it currently imports `KnowledgeGraph, SavedGraphSummary, SavedGraphVersion`):

```python
from app.models.schemas import ImportSetSummary, KnowledgeGraph, SavedGraphSummary, SavedGraphVersion
```

Append to the end of `store.py`:

```python
# --- imported overlay (external ontology models) ----------------------------------------------

_IMPORT_TTL_SECONDS = _USER_SAVE_TTL_SECONDS  # ~10y; survives rebuilds and the daily job
_IMPORT_INDEX_KEY = "graph_imported:__index__"


def _imported_key(set_id: str) -> str:
    return f"graph_imported:{set_id}"


def merge_graphs(a: KnowledgeGraph, b: KnowledgeGraph) -> KnowledgeGraph:
    """Union two graphs: nodes unioned, edges deduped by (source,target,type), node_meta merged
    (b wins on key clash). Returns a copy of `a` with the merged fields (keeps a's scope/as_of)."""
    nodes = sorted(set(a.nodes) | set(b.nodes))
    seen = {(e.source, e.target, e.type) for e in a.edges}
    edges = list(a.edges)
    for e in b.edges:
        k = (e.source, e.target, e.type)
        if k not in seen:
            seen.add(k)
            edges.append(e)
    node_meta = {**a.node_meta, **b.node_meta}
    return a.model_copy(update={"nodes": nodes, "edges": edges, "node_meta": node_meta})


def _load_import_index(cache: Cache) -> list[str]:
    raw = cache.get(_IMPORT_INDEX_KEY)
    try:
        return json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 — corrupt index -> empty
        return []


def _save_import_index(ids: list[str], cache: Cache) -> None:
    cache.set(_IMPORT_INDEX_KEY, json.dumps(ids), _IMPORT_TTL_SECONDS)


def add_import_set(name: str, graph: KnowledgeGraph, cache: Cache, *, created_at: str) -> ImportSetSummary:
    summary = ImportSetSummary(
        id=created_at, name=name or "", as_of=graph.as_of, created_at=created_at,
        node_count=len(graph.nodes), edge_count=len(graph.edges),
    )
    cache.set(
        _imported_key(created_at),
        json.dumps({"summary": summary.model_dump(), "graph": graph.model_dump()}),
        _IMPORT_TTL_SECONDS,
    )
    idx = _load_import_index(cache)
    if created_at not in idx:
        idx.append(created_at)
        _save_import_index(idx, cache)
    return summary


def _load_import_set(set_id: str, cache: Cache) -> tuple[ImportSetSummary, KnowledgeGraph] | None:
    raw = cache.get(_imported_key(set_id))
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return (
            ImportSetSummary.model_validate(obj["summary"]),
            KnowledgeGraph.model_validate(obj["graph"]),
        )
    except Exception:  # noqa: BLE001 — corrupt entry -> skip
        return None


def list_import_sets(cache: Cache) -> list[ImportSetSummary]:
    out: list[ImportSetSummary] = []
    for sid in _load_import_index(cache):
        loaded = _load_import_set(sid, cache)
        if loaded:
            out.append(loaded[0])
    return out


def delete_import_set(set_id: str, cache: Cache) -> bool:
    idx = _load_import_index(cache)
    if set_id not in idx:
        return False
    cache.set(_imported_key(set_id), "", 1)  # Cache has no delete; empty value -> treated as absent
    _save_import_index([s for s in idx if s != set_id], cache)
    return True


def load_overlay(cache: Cache) -> KnowledgeGraph:
    overlay = KnowledgeGraph(scope="imported")
    for sid in _load_import_index(cache):
        loaded = _load_import_set(sid, cache)
        if loaded:
            overlay = merge_graphs(overlay, loaded[1])
    return overlay


def effective_graph(cache: Cache, scope: str = "focus") -> KnowledgeGraph:
    """The graph scoring/display should consume: the saved snapshot unioned with the overlay.
    The saved snapshot itself is never mutated, so rebuilds stay idempotent."""
    base = load_graph(cache, scope)
    overlay = load_overlay(cache)
    if base is None:
        return overlay
    if not overlay.edges and not overlay.nodes:
        return base
    return merge_graphs(base, overlay)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_graph_overlay.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/store.py backend/tests/test_graph_overlay.py
git commit -m "feat(graph): add imported-overlay store, merge_graphs, effective_graph"
```

---

## Task 4: Import endpoints + scoring/display wiring

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_graph.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_graph.py`:

```python
from app.models.schemas import UniverseEntry


def _stub_universe(monkeypatch):
    monkeypatch.setattr(routes.universe, "load_universe", lambda: [
        UniverseEntry(ticker="AAPL", name="Apple", sector="Tech"),
        UniverseEntry(ticker="MSFT", name="Microsoft", sector="Tech"),
    ])


def test_import_then_get_graph_includes_overlay(client, monkeypatch):
    tc, _ = client
    _stub_universe(monkeypatch)
    body = {"name": "demo", "payload": {"edges": [
        {"source": "AAPL", "target": "MSFT", "type": "partner",
         "sentiment": "positive", "weight": 1.0, "confidence": 1.0}]}}
    r = tc.post("/api/graph/import", json=body)
    assert r.status_code == 200
    rep = r.json()
    assert rep["edges_added"] == 1 and rep["id"]
    g = tc.get("/api/graph").json()  # scope defaults to focus -> effective_graph
    assert any(e["source"] == "AAPL" and e["origin"] == "imported" for e in g["edges"])


def test_import_feeds_scoring_after_rebuild(client, monkeypatch):
    tc, cache = client
    _stub_universe(monkeypatch)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50,
                   direction="hold", net=0.0, base_score=50, base_net=0.0)]), cache)
    monkeypatch.setattr(routes, "build_graph",
                        lambda scope, settings, cache: KnowledgeGraph(scope="focus"))
    tc.post("/api/graph/import", json={"name": "d", "payload": {"edges": [
        {"source": "AAPL", "target": "MSFT", "type": "partner",
         "sentiment": "positive", "weight": 1.0, "confidence": 1.0}]}})
    r = tc.post("/api/graph/rebuild")
    assert r.status_code == 200
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None and aapl.network.signed > 0  # imported edge moved the signal


def test_list_and_delete_import(client, monkeypatch):
    tc, _ = client
    _stub_universe(monkeypatch)
    tc.post("/api/graph/import", json={"name": "d", "payload": {"edges": [
        {"source": "AAPL", "target": "MSFT", "type": "partner"}]}})
    sets = tc.get("/api/graph/imports").json()
    assert len(sets) == 1
    sid = sets[0]["id"]
    r = tc.delete("/api/graph/imports", params={"set_id": sid})
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert tc.get("/api/graph/imports").json() == []
    g = tc.get("/api/graph").json()
    assert all(e.get("origin") != "imported" for e in g["edges"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_graph.py -q`
Expected: FAIL — 404 on `/api/graph/import` (route not defined).

- [ ] **Step 3: Edit `routes.py` imports**

Add `Query` to the FastAPI import:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
```

Add the two new schemas to the existing `app.models.schemas` import block (it already imports `KnowledgeGraph`, `SavedGraphSummary`, etc. — just insert these two alphabetically):

```python
    ImportReport,
    ImportSetSummary,
```

Extend the `app.network.store` import block:

```python
from app.network.store import (
    add_import_set,
    delete_import_set,
    delete_saved_graph,
    effective_graph,
    list_import_sets,
    list_saved_graphs,
    load_company_graph,
    load_graph,
    load_overlay,
    save_company_graph,
    save_graph,
)
```

Add the normalizer + resolver imports near the other analysis imports:

```python
from app.analysis.relationships import TickerResolver
from app.network.import_model import normalize_import
```

(`from app.data import universe` is already imported — it supplies `universe.load_universe`.)

- [ ] **Step 4: Edit `get_graph` to be overlay-aware**

Replace the existing `get_graph` body (around line 219):

```python
@router.get("/graph", response_model=KnowledgeGraph)
def get_graph(scope: str = "focus", cache: Cache = Depends(get_cache)) -> KnowledgeGraph:
    if scope == "imported":
        return load_overlay(cache)
    if scope == "focus":
        return effective_graph(cache, "focus")
    graph = load_graph(cache, scope)
    return graph if graph is not None else KnowledgeGraph(scope=scope)
```

- [ ] **Step 5: Edit `rebuild_graph` to bake the effective graph**

Replace the snapshot-bake line inside `rebuild_graph`:

```python
    settings = store.load()
    graph = build_graph(None, settings, cache)
    save_graph(graph, cache)
    board = load_snapshot(cache, "all")
    if board is not None:
        save_snapshot(apply_network(board, effective_graph(cache, "focus"), settings), cache)
    return graph
```

- [ ] **Step 6: Edit `screen_rescan` to read the effective graph**

In `screen_rescan`, change the `graph = load_graph(cache, "focus")` line:

```python
    board = run_scan(sector, settings, cache)
    graph = effective_graph(cache, "focus")
```

(The rest of `screen_rescan` is unchanged — both branches already use `graph`.)

- [ ] **Step 7: Add the three import routes**

Add after the saved-graph routes (after `delete_saved`):

```python
@router.post("/graph/import", response_model=ImportReport)
def import_graph(payload: dict, cache: Cache = Depends(get_cache)) -> ImportReport:
    body = payload or {}
    name = str(body.get("name", ""))
    model = body.get("payload", body)  # accept {name, payload} or a bare model
    resolver = TickerResolver(universe.load_universe())
    graph, report = normalize_import(model, resolver)
    created_at = datetime.now(timezone.utc).isoformat()
    summary = add_import_set(name, graph, cache, created_at=created_at)
    report.id = summary.id
    report.name = summary.name
    return report


@router.get("/graph/imports", response_model=list[ImportSetSummary])
def list_imports(cache: Cache = Depends(get_cache)) -> list[ImportSetSummary]:
    return list_import_sets(cache)


@router.delete("/graph/imports")
def delete_import(set_id: str = Query(...), cache: Cache = Depends(get_cache)) -> dict:
    return {"deleted": delete_import_set(set_id, cache)}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_graph.py -q`
Expected: PASS (new + existing graph-route tests).

- [ ] **Step 9: Run the full backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_graph.py
git commit -m "feat(graph): import endpoints + effective-graph wiring for scoring/display"
```

---

## Task 5: Scheduled job bakes the overlay

**Files:**
- Modify: `backend/app/network/runner.py`
- Test: `backend/tests/test_network_runner.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_network_runner.py`:

```python
from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore
from app.network import runner
from app.network.store import add_import_set
from app.screener.store import load_snapshot, save_snapshot


def test_runner_bakes_overlay(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50,
                   direction="hold", net=0.0, base_score=50, base_net=0.0)]), cache)
    monkeypatch.setattr(runner, "build_graph",
                        lambda scope, settings, cache: KnowledgeGraph(scope="focus"))
    add_import_set("o", KnowledgeGraph(scope="imported", nodes=["AAPL", "MSFT"], edges=[
        GraphEdge(source="AAPL", target="MSFT", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0, origin="imported")]),
        cache, created_at="2026-06-07T00:00:00+00:00")

    runner.run(Settings(), cache)
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None and aapl.network.signed > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_runner.py -q`
Expected: FAIL — `aapl.network is None` (runner bakes only the empty built graph, not the overlay).

- [ ] **Step 3: Edit `runner.py`**

Change the import and the bake line:

```python
from app.network.service import build_graph
from app.network.store import effective_graph, save_graph
```

```python
    graph = build_graph(scope, settings, cache)
    save_graph(graph, cache)
    board = load_snapshot(cache, "all")
    if board is not None:
        save_snapshot(apply_network(board, effective_graph(cache), settings), cache)  # bake influence in
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/runner.py backend/tests/test_network_runner.py
git commit -m "feat(graph): scheduled network job bakes the imported overlay"
```

---

## Task 6: Frontend types

**Files:**
- Modify: `frontend/src/types.ts`

- [ ] **Step 1: Edit `types.ts`**

Change the `RelationType` alias (line 22) to add `'other'`:

```typescript
export type RelationType = 'supplier' | 'customer' | 'partner' | 'competitor' | 'owner' | 'subsidiary' | 'other';
```

Add `NodeMeta` just above `GraphEdge`:

```typescript
export interface NodeMeta { label: string; kind: string; source: 'native' | 'imported'; }
```

Add `origin` to `GraphEdge`:

```typescript
export interface GraphEdge {
  source: string; target: string; type: RelationType; sentiment: EdgeSentiment;
  weight: number; confidence: number; evidence: string; url: string; as_of: string;
  origin?: 'extracted' | 'imported';
}
```

Add `node_meta` to `KnowledgeGraph`:

```typescript
export interface KnowledgeGraph {
  as_of: string; scope: string; nodes: string[]; edges: GraphEdge[]; built: number; skipped: number;
  node_meta?: Record<string, NodeMeta>;
}
```

Add the two import types at the end of the file:

```typescript
export interface ImportSetSummary {
  id: string; name: string; as_of: string; created_at: string; node_count: number; edge_count: number;
}
export interface ImportReport {
  id: string; name: string; nodes_added: number; edges_added: number; dropped: number; warnings: string[];
}
```

- [ ] **Step 2: Type-check (no dedicated test; the build is the gate)**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: PASS (no type errors introduced).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types.ts
git commit -m "feat(graph): add frontend types for import (node_meta, origin, other)"
```

---

## Task 7: `graphView.ts` — external nodes, origin, meta merge

**Files:**
- Modify: `frontend/src/lib/graphView.ts`
- Test: `frontend/src/lib/graphView.test.ts` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/graphView.test.ts`:

```typescript
describe('imported nodes + meta', () => {
  const IMPORTED: KnowledgeGraph = {
    as_of: 't', scope: 'imported', built: 1, skipped: 0,
    nodes: ['AAPL', 'ext:openai'],
    node_meta: { 'ext:openai': { label: 'OpenAI', kind: 'private_company', source: 'imported' } },
    edges: [
      { source: 'AAPL', target: 'ext:openai', type: 'other', sentiment: 'positive',
        weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' },
    ],
  };

  it('marks ext/meta nodes external with their label', () => {
    const nodes = mergeNodes(IMPORTED, BOARD);
    const ext = nodes.find((n) => n.id === 'ext:openai')!;
    expect(ext.external).toBe(true);
    expect(ext.label).toBe('OpenAI');
    expect(ext.onBoard).toBe(false);
    const aapl = nodes.find((n) => n.id === 'AAPL')!;
    expect(aapl.external).toBe(false); // on the board -> not external
  });

  it('carries edge origin onto links', () => {
    expect(toLinks(IMPORTED)[0].origin).toBe('imported');
  });

  it('mergeGraph unions node_meta', () => {
    const out = mergeGraph(
      { as_of: 't', scope: 'x', built: 0, skipped: 0, nodes: ['AAPL'], edges: [] },
      IMPORTED,
    );
    expect(out.node_meta?.['ext:openai']?.label).toBe('OpenAI');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/lib/graphView.test.ts`
Expected: FAIL — `ext.external` is undefined; `toLinks(...).origin` undefined; `node_meta` not unioned.

- [ ] **Step 3: Edit `graphView.ts`**

Extend `ViewNode`:

```typescript
export interface ViewNode {
  id: string;
  label: string;
  direction: NodeDirection;
  score: number;
  sector: string;
  onBoard: boolean;
  external: boolean;       // imported / non-ticker node (rendered distinctly)
  kind: string;            // node_meta kind, '' for tickers
  network?: NetworkSignal | null;
}
```

Extend `ViewLink` with `origin`:

```typescript
export interface ViewLink {
  source: string;
  target: string;
  type: RelationType;
  sentiment: GraphEdge['sentiment'];
  weight: number;
  confidence: number;
  evidence: string;
  url: string;
  origin?: 'extracted' | 'imported';
}
```

Replace `mergeNodes`:

```typescript
export function mergeNodes(graph: KnowledgeGraph, board?: ScreenBoard | null): ViewNode[] {
  const byTicker = new Map(board?.items.map((s) => [s.ticker, s]) ?? []);
  const meta = graph.node_meta ?? {};
  return graph.nodes.map((id) => {
    const s = byTicker.get(id);
    const m = meta[id];
    return {
      id,
      label: m?.label || id,
      direction: (s?.direction ?? 'unknown') as NodeDirection,
      score: s?.score ?? 0,
      sector: s?.sector ?? '',
      onBoard: !!s,
      external: !s && (!!m || id.startsWith('ext:')),
      kind: m?.kind ?? '',
      network: s?.network ?? null,
    };
  });
}
```

Replace `toLinks`:

```typescript
export function toLinks(graph: KnowledgeGraph): ViewLink[] {
  return graph.edges.map((e) => ({
    source: e.source, target: e.target, type: e.type, sentiment: e.sentiment,
    weight: e.weight, confidence: e.confidence, evidence: e.evidence, url: e.url,
    origin: e.origin ?? 'extracted',
  }));
}
```

Replace `mergeGraph` (union `node_meta`):

```typescript
export function mergeGraph(into: KnowledgeGraph | null, fragment: KnowledgeGraph): KnowledgeGraph {
  if (!into) {
    return {
      ...fragment, nodes: [...fragment.nodes], edges: [...fragment.edges],
      node_meta: { ...(fragment.node_meta ?? {}) },
    };
  }
  const nodes = Array.from(new Set([...into.nodes, ...fragment.nodes]));
  const seen = new Set(into.edges.map((e) => `${e.source}|${e.target}|${e.type}`));
  const edges = [...into.edges];
  for (const e of fragment.edges) {
    const k = `${e.source}|${e.target}|${e.type}`;
    if (!seen.has(k)) { seen.add(k); edges.push(e); }
  }
  const node_meta = { ...(into.node_meta ?? {}), ...(fragment.node_meta ?? {}) };
  return { ...into, nodes, edges, node_meta };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/lib/graphView.test.ts`
Expected: PASS (new + existing graphView tests — the existing `mergeNodes`/`mergeGraph` cases still hold).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/graphView.ts frontend/src/lib/graphView.test.ts
git commit -m "feat(graph): graphView supports external nodes, edge origin, meta merge"
```

---

## Task 8: ChatGPT prompt template

**Files:**
- Create: `frontend/src/lib/importPrompt.ts`
- Test: `frontend/src/lib/importPrompt.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/importPrompt.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { chatGptPrompt } from './importPrompt';

describe('chatGptPrompt', () => {
  it('injects the company and keeps the JSON contract', () => {
    const p = chatGptPrompt('NVDA');
    expect(p).toContain('NVDA');
    expect(p).toContain('"nodes"');
    expect(p).toContain('"edges"');
    expect(p).toContain('supplier|customer|partner|competitor|owner|subsidiary|other');
  });
  it('falls back to a placeholder when empty', () => {
    expect(chatGptPrompt('')).toContain('[COMPANY]');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/lib/importPrompt.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `frontend/src/lib/importPrompt.ts`**

```typescript
/** The copy-paste prompt shown in the Import tab. `[COMPANY]` is filled with the current root. */
export function chatGptPrompt(company: string): string {
  const c = company || '[COMPANY]';
  return `Research ${c} and its business relationships with other companies, based on recent, real news. Output ONLY a single JSON object — no prose, no code fences — in exactly this shape:

{
  "name": "<short label>",
  "as_of": "<YYYY-MM-DD>",
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
- Include only relationships supported by real information; add a source "url" where possible.`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npx vitest run src/lib/importPrompt.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/importPrompt.ts frontend/src/lib/importPrompt.test.ts
git commit -m "feat(graph): add in-app ChatGPT import-prompt template"
```

---

## Task 9: API client + hooks

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`
- Test: `frontend/src/api/client.test.ts` (extend)

- [ ] **Step 1: Write the failing tests**

Append inside the `describe('api client', …)` block in `frontend/src/api/client.test.ts`:

```typescript
  it('importGraph POSTs /graph/import with {name, payload}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 't', edges_added: 1 }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.importGraph('demo', { edges: [] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/import');
    expect((init as RequestInit).method).toBe('POST');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ name: 'demo', payload: { edges: [] } });
  });

  it('listImports GETs /graph/imports', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.listImports();
    expect(fetchMock.mock.calls[0][0] as string).toMatch(/\/graph\/imports$/);
  });

  it('deleteImport DELETEs with set_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ deleted: true }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.deleteImport('2026-06-07T00:00:00+00:00');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/imports?set_id=');
    expect(url as string).toContain('%3A'); // colon encoded
    expect((init as RequestInit).method).toBe('DELETE');
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/api/client.test.ts`
Expected: FAIL — `api.importGraph` is not a function.

- [ ] **Step 3: Edit `client.ts`**

Add `ImportReport`, `ImportSetSummary` to the type import block at the top. Then add these methods to the `api` object (e.g. after `deleteSavedGraph`):

```typescript
  importGraph: (name: string, payload: unknown) =>
    http<ImportReport>('/graph/import', { method: 'POST', body: JSON.stringify({ name, payload }) }),
  listImports: () => http<ImportSetSummary[]>('/graph/imports'),
  deleteImport: (id: string) =>
    http<{ deleted: boolean }>(`/graph/imports?set_id=${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getOverlay: () => http<KnowledgeGraph>('/graph?scope=imported'),
```

- [ ] **Step 4: Edit `queries.ts`**

Add `useImports`, `useOverlay`, `useImportGraph`, `useDeleteImport` (place after `useDeleteSavedGraph`):

```typescript
export function useImports() {
  return useQuery({ queryKey: ['graphImports'], queryFn: api.listImports });
}

export function useOverlay() {
  return useQuery({ queryKey: ['graph', 'imported'], queryFn: api.getOverlay });
}

export function useImportGraph() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: unknown }) => api.importGraph(name, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['graphImports'] });
      qc.invalidateQueries({ queryKey: ['graph', 'imported'] });
      qc.invalidateQueries({ queryKey: ['screen'] });
    },
  });
}

export function useDeleteImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteImport(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['graphImports'] });
      qc.invalidateQueries({ queryKey: ['graph', 'imported'] });
      qc.invalidateQueries({ queryKey: ['screen'] });
    },
  });
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/api/client.test.ts
git commit -m "feat(graph): client + hooks for import/list/delete/overlay"
```

---

## Task 10: Import tab (GraphSidebar) + canvas styling

**Files:**
- Modify: `frontend/src/components/GraphSidebar.tsx`, `frontend/src/components/GraphCanvas.tsx`, `frontend/src/styles.css`
- Test: `frontend/src/components/GraphSidebar.test.tsx` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/GraphSidebar.test.tsx`. First extend the `base()` factory return object with the new props:

```typescript
    imports: [] as ImportSetSummary[],
    onImport: vi.fn(),
    onDeleteImport: vi.fn(),
    importing: false,
    importReport: null,
    importError: null,
    promptDefault: 'AAPL',
```

Add `ImportSetSummary` to the type import at the top of the test file, then add these tests:

```typescript
it('switches to the Import tab', () => {
  const props = base();
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /^import$/i }));
  expect(props.onTab).toHaveBeenCalledWith('import');
});

it('imports valid pasted JSON', () => {
  const props = { ...base(), tab: 'import' as const };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/paste.*json/i), {
    target: { value: '{"edges":[{"source":"AAPL","target":"NVDA","type":"partner"}]}' },
  });
  fireEvent.click(screen.getByRole('button', { name: /^import model$/i }));
  expect(props.onImport).toHaveBeenCalledWith(
    '', { edges: [{ source: 'AAPL', target: 'NVDA', type: 'partner' }] },
  );
});

it('shows an inline error for malformed JSON and does not call onImport', () => {
  const props = { ...base(), tab: 'import' as const };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.change(screen.getByPlaceholderText(/paste.*json/i), { target: { value: '{not json' } });
  fireEvent.click(screen.getByRole('button', { name: /^import model$/i }));
  expect(props.onImport).not.toHaveBeenCalled();
  expect(screen.getByText(/invalid json/i)).toBeInTheDocument();
});

it('lists import sets and fires delete', () => {
  const props = {
    ...base(), tab: 'import' as const,
    imports: [{ id: 't1', name: 'demo', as_of: '', created_at: 't1', node_count: 2, edge_count: 1 }],
  };
  wrap(<GraphSidebar {...props} selected={null} />);
  fireEvent.click(screen.getByRole('button', { name: /delete demo/i }));
  expect(props.onDeleteImport).toHaveBeenCalledWith('t1');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/components/GraphSidebar.test.tsx`
Expected: FAIL — no Import tab/controls.

- [ ] **Step 3: Edit `GraphSidebar.tsx`**

Update the imports (the file already imports `useState`, `Link`, `ViewNode`, `RelationType`, `SavedGraphSummary`). Extend the types import to add the two new types, and add the prompt import:

```typescript
import type { ImportReport, ImportSetSummary, RelationType, SavedGraphSummary } from '../types';
import { chatGptPrompt } from '../lib/importPrompt';
```

Change `EDGE_TYPES` to include `other`:

```typescript
const EDGE_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary', 'other'];
```

Change the `tab` type in `GraphSidebarProps` and add the new props:

```typescript
  tab: 'explore' | 'saved' | 'import';
  onTab: (t: 'explore' | 'saved' | 'import') => void;
  // …existing props…
  imports: ImportSetSummary[];
  onImport: (name: string, payload: unknown) => void;
  onDeleteImport: (id: string) => void;
  importing: boolean;
  importReport: ImportReport | null;
  importError: string | null;
  promptDefault: string;
```

Destructure the new props in the component body (add to the existing destructure):

```typescript
    imports, onImport, onDeleteImport, importing, importReport, importError, promptDefault,
```

Add local state for the import form near the existing `rootInput` state:

```typescript
  const [jsonText, setJsonText] = useState('');
  const [setName, setSetName] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);

  const doImport = () => {
    setParseError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      setParseError('Invalid JSON — check the pasted model.');
      return;
    }
    onImport(setName.trim(), parsed);
  };

  const onFile = (file: File | undefined) => {
    if (!file) return;
    file.text().then((t) => setJsonText(t)).catch(() => setParseError('Could not read the file.'));
  };

  const copyPrompt = () => {
    void navigator.clipboard?.writeText(chatGptPrompt(promptDefault));
  };
```

Add the Import tab button in the `.graph-tabs` block (after the Saved button):

```tsx
        <button type="button" className={`tab${tab === 'import' ? ' active' : ''}`} onClick={() => onTab('import')}>
          Import
        </button>
```

Add the Import tab panel. Change the final `tab === 'saved' ? (...) : (...)` structure so there are three branches — wrap the existing saved panel and add the import panel. The simplest edit: after the closing of the explore-tab block and the saved-tab block, render the import panel when `tab === 'import'`. Replace the outer ternary with explicit conditionals:

```tsx
      {tab === 'explore' && (
        <div className="graph-tab">
          {/* …existing explore-tab contents unchanged… */}
        </div>
      )}

      {tab === 'saved' && (
        <div className="graph-tab">
          {/* …existing saved-tab contents unchanged… */}
        </div>
      )}

      {tab === 'import' && (
        <div className="graph-tab">
          <button type="button" className="secondary" onClick={copyPrompt}>Copy ChatGPT prompt</button>
          <p className="muted">Paste the model JSON your external tool produced:</p>
          <input placeholder="Set name (optional)" value={setName} onChange={(e) => setSetName(e.target.value)} />
          <textarea
            className="graph-json"
            placeholder="Paste import JSON…"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            rows={8}
          />
          <input type="file" accept="application/json,.json" onChange={(e) => onFile(e.target.files?.[0])} />
          <button disabled={importing || !jsonText.trim()} onClick={doImport}>
            {importing ? 'Importing…' : 'Import model'}
          </button>
          {parseError && <p className="error">{parseError}</p>}
          {importError && <p className="error">{importError}</p>}
          {importReport && (
            <p className="muted">
              Imported {importReport.edges_added} edges, {importReport.nodes_added} nodes
              {importReport.dropped ? `, ${importReport.dropped} dropped` : ''}.
              {importReport.warnings.map((w, i) => <span key={i}><br />{w}</span>)}
            </p>
          )}
          <div className="graph-section">
            <span className="label">Imported sets</span>
            {imports.length ? (
              <div className="graph-saves">
                {imports.map((s) => (
                  <div key={s.id} className="graph-save-row">
                    <span>{s.name || '(unnamed)'} · {s.edge_count} edges</span>
                    <button className="icon-btn" aria-label={`delete ${s.name || s.id}`} onClick={() => onDeleteImport(s.id)}>✕</button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No imported models yet.</p>
            )}
          </div>
        </div>
      )}
```

> Note: keep the existing explore-tab and saved-tab JSX exactly as-is; only the wrapping condition changes from the `? :` ternary to the `&&` blocks above.

- [ ] **Step 4: Edit `GraphCanvas.tsx` — external/import styling**

Change `nodeColor` to grey external nodes, and add a dashed line for imported links:

```tsx
        nodeColor={(n: any) => (isDim(n.id) ? '#30363d' : n.external ? '#6e7681' : directionColor(n.direction))}
```

Add this prop to `<ForceGraph2D>` (e.g. after `linkWidth`):

```tsx
        linkLineDash={(l: any) => (l.origin === 'imported' ? [4, 2] : [])}
```

- [ ] **Step 5: Edit `styles.css` — import controls**

Append near the other `.graph-*` rules in `frontend/src/styles.css`:

```css
.graph-json {
  width: 100%;
  font-family: var(--mono, monospace);
  font-size: 12px;
  resize: vertical;
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/components/GraphSidebar.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/GraphSidebar.tsx frontend/src/components/GraphCanvas.tsx frontend/src/components/GraphSidebar.test.tsx frontend/src/styles.css
git commit -m "feat(graph): Import tab (paste/upload + prompt) and imported-element styling"
```

---

## Task 11: Wire the Graph page (import + overlay union)

**Files:**
- Modify: `frontend/src/pages/Graph.tsx`
- Test: `frontend/src/pages/Graph.test.tsx` (extend)

- [ ] **Step 1: Update the api mock + add the failing test**

The page will call `useImports`/`useOverlay`/`useImportGraph`/`useDeleteImport` on every render, so the existing `vi.mock('../api/client', …)` block must expose those methods or **every** existing test breaks. Update the mock's `api` object:

```typescript
vi.mock('../api/client', () => ({
  api: {
    getScreen: vi.fn(),
    getCompanyGraph: vi.fn(), listSavedGraphs: vi.fn(), saveGraph: vi.fn(),
    loadSavedGraph: vi.fn(), deleteSavedGraph: vi.fn(),
    listImports: vi.fn(), getOverlay: vi.fn(), importGraph: vi.fn(), deleteImport: vi.fn(),
  },
}));
```

Add overlay fixtures near `BOARD`:

```typescript
const EMPTY_OVERLAY: KnowledgeGraph = { as_of: '', scope: 'imported', built: 0, skipped: 0, nodes: [], edges: [], node_meta: {} };
const OVERLAY: KnowledgeGraph = {
  as_of: 't', scope: 'imported', built: 1, skipped: 0,
  nodes: ['AAPL', 'ext:openai'],
  node_meta: { 'ext:openai': { label: 'OpenAI', kind: 'private_company', source: 'imported' } },
  edges: [{ source: 'AAPL', target: 'ext:openai', type: 'other', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' }],
};
```

Add defaults to `beforeEach` (empty overlay/imports keep all existing node-count assertions intact):

```typescript
  vi.mocked(api.listImports).mockResolvedValue([]);
  vi.mocked(api.getOverlay).mockResolvedValue(EMPTY_OVERLAY);
```

Append the new test:

```typescript
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
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/pages/Graph.test.tsx`
Expected: FAIL — shows "2 nodes" and no `sel-ext:openai` button (overlay not unioned yet).

- [ ] **Step 3: Edit `Graph.tsx`**

**Replace** the existing `../hooks/queries` import and the `../types` import with these (adds the four new hooks + `ImportReport`):

```typescript
import {
  useDeleteImport, useDeleteSavedGraph, useEgoGraph, useImportGraph, useImports,
  useLoadSavedGraph, useOverlay, useSaveGraph, useSavedGraphs, useScreen,
} from '../hooks/queries';
import type { ImportReport, KnowledgeGraph, RelationType } from '../types';
```

Change `ALL_TYPES` to include `other`:

```typescript
const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary', 'other'];
```

Change the `tab` state type and add the new hooks + import state:

```typescript
  const [tab, setTab] = useState<'explore' | 'saved' | 'import'>('explore');
  // …existing state…
  const imports = useImports();
  const overlay = useOverlay();
  const importGraph = useImportGraph();
  const deleteImport = useDeleteImport();
  const [importReport, setImportReport] = useState<ImportReport | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const doImport = async (name: string, payload: unknown) => {
    setImportError(null);
    try {
      const report = await importGraph.mutateAsync({ name, payload });
      setImportReport(report);
    } catch {
      setImportError('Could not import this model.');
    }
  };

  const doDeleteImport = async (id: string) => {
    try { await deleteImport.mutateAsync(id); } catch { setImportError('Could not remove the set.'); }
  };
```

Update the `view` memo to union overlay edges incident to working nodes:

```typescript
  const view = useMemo(() => {
    const g = working ?? EMPTY_GRAPH;
    let merged = g;
    const ov = overlay.data;
    if (ov && ov.edges.length) {
      const present = new Set(g.nodes);
      const incident = ov.edges.filter((e) => present.has(e.source) || present.has(e.target));
      if (incident.length) {
        const frag: KnowledgeGraph = {
          ...ov, edges: incident,
          nodes: Array.from(new Set(incident.flatMap((e) => [e.source, e.target]))),
        };
        merged = mergeGraph(g, frag);
      }
    }
    return applyFilters(mergeNodes(merged, board.data), toLinks(merged), null, enabledTypes);
  }, [working, board.data, enabledTypes, overlay.data]);
```

Pass the new props to `<GraphSidebar>`:

```tsx
        imports={imports.data ?? []}
        onImport={doImport}
        onDeleteImport={doDeleteImport}
        importing={importGraph.isPending}
        importReport={importReport}
        importError={importError}
        promptDefault={root || selectedId || ''}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/pages/Graph.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the full frontend suite + build**

Run (from `frontend/`): `npx vitest run` then `npm run build`
Expected: PASS for both (no type errors, all tests green).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Graph.tsx frontend/src/pages/Graph.test.tsx
git commit -m "feat(graph): wire Import tab and overlay-incident union into the explorer"
```

---

## Task 12: Full verification + live smoke + memory

**Files:** none (verification only) + memory update.

- [ ] **Step 1: Backend suite**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest -q`
Expected: ALL PASS.

- [ ] **Step 2: Frontend suite + build**

Run (from `frontend/`): `npx vitest run` and `npm run build`
Expected: ALL PASS; build succeeds.

- [ ] **Step 3: Live browser smoke (isolated data dir)**

Follow the same protocol used by prior graph phases: start the backend with an isolated temp `DATA_DIR` (back up + restore the real cache so the smoke run never touches `backend/data/app.db`). Then in the UI:
1. Open `/graph`, Start from a company (e.g. `AAPL`).
2. Import tab → Copy ChatGPT prompt (confirm clipboard) → paste a small model (e.g. `AAPL`→`MSFT` partner + `AAPL`→`OpenAI` customer) → Import. Confirm the report and that the imported edges appear (dashed; `OpenAI` grey/external).
3. Discover board → confirm `AAPL`'s score/network reflects the import after a rescan/rebuild.
4. Delete the import set → confirm the edge and its score influence disappear.

- [ ] **Step 4: Update memory**

Update `C:\Users\girid\.claude\projects\D--workspace-ai-stocks-news-analysis\memory\project-state.md` to record the external-ontology-import feature as built & merged (JSON import, hybrid resolution, 6+other types, imported overlay feeding scoring, Import tab + prompt template), and refresh the `MEMORY.md` one-line pointer.

- [ ] **Step 5: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to merge `feat/graph-ontology-import` into `master` (ff-merge locally, per repo convention).

---

## Notes for the implementer

- **Degrade, don't crash** is the house style: backend normalization and store reads swallow errors and return safe empties (`# noqa: BLE001`). Don't add 500s for malformed imports.
- **Idempotent rebuilds:** never write the overlay into `graph_snapshot:focus`. Only `effective_graph()` unions it at read time. If you find yourself calling `save_graph` with merged edges, stop — that's the rejected approach.
- **Import set id** is the `created_at` ISO timestamp; it contains `:` and `+`, so always `encodeURIComponent` it in the client and pass it as the `set_id` query param (never a path segment).
- **Scoring reality check:** an imported edge moves a score only when its `source` resolves to a board ticker; an off-board/external source contributes nothing. This is expected (see spec caveats), not a bug to "fix."
