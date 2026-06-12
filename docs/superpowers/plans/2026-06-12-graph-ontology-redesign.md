# Graph Ontology Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Named, versioned ontologies with exactly one ACTIVE ontology feeding every network-signal consumer; retire the auto-built news graph + import overlay as scoring sources; add custom company nodes and a watchlist toggle to the Graph page.

**Architecture:** New `ontology:*` Cache-KV namespace (mirrors the existing saved-graph idiom) + an `ontology:__active__` pointer; a single `active_graph(cache)` accessor replaces `effective_graph(cache, "focus")` at all scoring sites; activation/save-of-active re-bakes the Discover snapshot. Frontend swaps the per-root save UI for an ontology toolbar + Ontologies tab.

**Tech Stack:** FastAPI + pydantic + SQLite KV cache (backend), React + TanStack Query + react-force-graph-2d + vitest (frontend). Spec: `docs/superpowers/specs/2026-06-12-graph-ontology-redesign-design.md`.

**Conventions:** Backend tests: `cd backend && .venv/Scripts/python.exe -m pytest -q`. Frontend: `cd frontend && npm test` / `npm run build`. Conventional Commits, **no Claude co-author trailer**. Work on branch `feat/graph-ontology`.

---

## File map

| File | Change |
|---|---|
| `backend/app/models/schemas.py` | + `OntologyVersion`, `OntologySummary`, `ActiveOntology`; − `SavedGraphVersion`, `SavedGraphSummary` (Task 5) |
| `backend/app/network/store.py` | + ontology CRUD/active/`active_graph`; − `save_graph`, `load_graph`, `effective_graph`, `load_overlay`, `merge_graphs`, saved-graph fns (Task 5) |
| `backend/app/api/routes.py` | + ontology endpoints, `_rebake_board`; cutover `_persist_rescan`/`get_graph`; − rebuild + saved endpoints |
| `backend/app/screener/service.py`, `backend/app/services/analysis_service.py`, `backend/app/analysis/agent.py` | `effective_graph(cache, "focus")` → `active_graph(cache)` |
| `backend/app/network/service.py` | − `build_graph`, `_focus_set` (keep `build_company_graph`) |
| `backend/app/network/runner.py`, `__main__.py` | re-bake-only daily job |
| `backend/tests/` | new `test_ontology_store.py`; rework `test_api_graph.py`, `test_graph_overlay.py` → `test_graph_imports.py`, `test_network_runner.py`, `test_network_service.py`, `test_score_one.py`, `test_analysis_service.py` |
| `frontend/src/types.ts`, `api/client.ts`, `hooks/queries.ts` | ontology types/methods/hooks; − saved-graph + overlay ones |
| `frontend/src/pages/Graph.tsx` | ontology toolbar, load-active boot, hint; − overlay merge |
| `frontend/src/components/GraphSidebar.tsx` | Ontologies tab; company form; watchlist button |
| `frontend/src/components/GraphCanvas.tsx` | background menu (Add company), node menu (+company/+watchlist) |
| `frontend/src/lib/graphView.ts` | + `COMPANY_TICKER_RE`, `addCompanyNode` |
| `frontend/src/lib/explorerStore.ts` | + `ontologyName` field |
| `README.md`, `backend/README.md`, `frontend/README.md` | docs |

---

### Task 1: Ontology schemas + store CRUD

**Files:**
- Modify: `backend/app/models/schemas.py` (after `SavedGraphSummary`, ~line 146)
- Modify: `backend/app/network/store.py` (append; extend imports)
- Test: `backend/tests/test_ontology_store.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_ontology_store.py
from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, OntologyVersion
from app.network.store import (
    active_graph, delete_ontology, get_active_ontology, list_ontologies, load_ontology,
    save_ontology, set_active_ontology,
)


def _cache(tmp_path):
    return Cache(str(tmp_path / "c.db"))


def _version(name="My Map", n=1):
    g = KnowledgeGraph(scope="explore", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)] * n)
    return OntologyVersion(name=name, saved_at=f"t{n}", expanded=["AAPL"], graph=g)


def test_save_and_load_roundtrip(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version(), cache)
    found = load_ontology("My Map", cache)
    assert found is not None and found.graph.nodes == ["AAPL", "TSM"]
    assert load_ontology("nope", cache) is None


def test_names_are_case_insensitively_unique(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("Tech"), cache)
    save_ontology(_version("tech", n=2), cache)        # updates "Tech", not a new entry
    names = [o.name for o in list_ontologies(cache)]
    assert names == ["Tech"]
    assert len(load_ontology("TECH", cache).graph.edges) == 1  # latest version loads
    assert len(list_ontologies(cache)[0].versions) == 2


def test_version_history_capped_at_five(tmp_path):
    cache = _cache(tmp_path)
    for i in range(7):
        save_ontology(_version(n=i), cache)
    assert len(list_ontologies(cache)[0].versions) == 5


def test_list_carries_counts_and_active_flag(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)
    save_ontology(_version("B"), cache)
    set_active_ontology("b", cache)                    # case-insensitive activate
    by_name = {o.name: o for o in list_ontologies(cache)}
    assert by_name["A"].active is False and by_name["B"].active is True
    assert by_name["A"].node_count == 2 and by_name["A"].edge_count == 1
    assert get_active_ontology(cache) == "B"


def test_activate_unknown_name_is_refused(tmp_path):
    cache = _cache(tmp_path)
    assert set_active_ontology("ghost", cache) is False
    assert get_active_ontology(cache) is None


def test_delete_clears_active_pointer(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)
    set_active_ontology("A", cache)
    assert delete_ontology("A", cache) is True
    assert get_active_ontology(cache) is None
    assert list_ontologies(cache) == []


def test_delete_single_version_keeps_pointer(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A", n=1), cache)
    save_ontology(_version("A", n=2), cache)
    set_active_ontology("A", cache)
    assert delete_ontology("A", cache, version="t1") is True
    assert get_active_ontology(cache) == "A"
    assert list_ontologies(cache)[0].versions == ["t2"]


def test_active_graph_empty_when_none_active(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)                # saved but NOT active
    g = active_graph(cache)
    assert g.nodes == [] and g.edges == []


def test_active_graph_returns_latest_active_revision(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A", n=1), cache)
    set_active_ontology("A", cache)
    save_ontology(_version("A", n=2), cache)           # newer revision of the active name
    assert len(active_graph(cache).edges) == 1 and active_graph(cache).nodes == ["AAPL", "TSM"]


def test_set_active_none_clears(tmp_path):
    cache = _cache(tmp_path)
    save_ontology(_version("A"), cache)
    set_active_ontology("A", cache)
    assert set_active_ontology(None, cache) is True
    assert get_active_ontology(cache) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_ontology_store.py -q`
Expected: ImportError (`OntologyVersion` / store functions not defined).

- [ ] **Step 3: Add the schemas**

In `backend/app/models/schemas.py`, directly after `SavedGraphSummary`:

```python
class OntologyVersion(BaseModel):
    """One saved revision of a named ontology (the user-curated graph behind scoring)."""
    name: str
    saved_at: str = ""
    expanded: list[str] = Field(default_factory=list)
    graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)


class OntologySummary(BaseModel):
    name: str
    versions: list[str] = Field(default_factory=list)   # saved_at stamps, newest first
    node_count: int = 0                                 # of the latest version
    edge_count: int = 0
    active: bool = False


class ActiveOntology(BaseModel):
    """GET/PUT /api/graph/active body — name=None means scoring runs with no network signal."""
    name: Optional[str] = None
```

- [ ] **Step 4: Implement the store**

In `backend/app/network/store.py`: extend the schema import to
`from app.models.schemas import (ImportSetSummary, KnowledgeGraph, OntologySummary, OntologyVersion, SavedGraphSummary, SavedGraphVersion)` and append:

```python
# --- named ontologies (the user-curated graphs behind scoring) ---------------------------------

_ONTOLOGY_INDEX_KEY = "ontology:__index__"
_ONTOLOGY_ACTIVE_KEY = "ontology:__active__"


def _ontology_key(name: str) -> str:
    return f"ontology:{name}"


def _load_ontology_index(cache: Cache) -> list[str]:
    raw = cache.get(_ONTOLOGY_INDEX_KEY)
    try:
        return json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 — corrupt index -> empty
        return []


def _save_ontology_index(names: list[str], cache: Cache) -> None:
    cache.set(_ONTOLOGY_INDEX_KEY, json.dumps(names), _USER_SAVE_TTL_SECONDS)


def canonical_ontology_name(name: str, cache: Cache) -> str | None:
    """The stored spelling of `name`, matched case-insensitively; None when unknown."""
    want = (name or "").strip().lower()
    return next((n for n in _load_ontology_index(cache) if n.lower() == want), None)


def _load_ontology_versions(name: str, cache: Cache) -> list[OntologyVersion]:
    raw = cache.get(_ontology_key(name))
    if not raw:
        return []
    try:
        return [OntologyVersion.model_validate(v) for v in json.loads(raw)]
    except Exception:  # noqa: BLE001 — corrupt entry -> none
        return []


def _store_ontology_versions(name: str, versions: list[OntologyVersion], cache: Cache) -> None:
    cache.set(_ontology_key(name), json.dumps([v.model_dump() for v in versions]),
              _USER_SAVE_TTL_SECONDS)


def save_ontology(version: OntologyVersion, cache: Cache) -> OntologyVersion:
    """Create-or-update under a case-insensitively unique name; newest first, capped at 5."""
    name = canonical_ontology_name(version.name, cache) or version.name.strip()
    version = version.model_copy(update={"name": name})
    versions = ([version] + _load_ontology_versions(name, cache))[:_MAX_VERSIONS]
    _store_ontology_versions(name, versions, cache)
    idx = _load_ontology_index(cache)
    if name not in idx:
        idx.append(name)
        _save_ontology_index(idx, cache)
    return version


def load_ontology(name: str, cache: Cache, version: str | None = None) -> OntologyVersion | None:
    canon = canonical_ontology_name(name, cache)
    if canon is None:
        return None
    versions = _load_ontology_versions(canon, cache)
    if not versions:
        return None
    if version is None:
        return versions[0]  # latest
    return next((v for v in versions if v.saved_at == version), None)


def list_ontologies(cache: Cache) -> list[OntologySummary]:
    active = get_active_ontology(cache)
    out: list[OntologySummary] = []
    for name in _load_ontology_index(cache):
        versions = _load_ontology_versions(name, cache)
        if versions:
            latest = versions[0].graph
            out.append(OntologySummary(
                name=name, versions=[v.saved_at for v in versions],
                node_count=len(latest.nodes), edge_count=len(latest.edges),
                active=name == active,
            ))
    return out


def delete_ontology(name: str, cache: Cache, version: str | None = None) -> bool:
    canon = canonical_ontology_name(name, cache)
    if canon is None:
        return False
    versions = _load_ontology_versions(canon, cache)
    if not versions:
        return False
    remaining = [] if version is None else [v for v in versions if v.saved_at != version]
    if version is not None and len(remaining) == len(versions):
        return False  # version not found
    if remaining:
        _store_ontology_versions(canon, remaining, cache)
    else:
        _store_ontology_versions(canon, [], cache)  # Cache has no delete; store empty
        _save_ontology_index([n for n in _load_ontology_index(cache) if n != canon], cache)
        if get_active_ontology(cache) == canon:
            set_active_ontology(None, cache)        # the master pointer must never dangle
    return True


def get_active_ontology(cache: Cache) -> str | None:
    raw = cache.get(_ONTOLOGY_ACTIVE_KEY)
    return raw or None


def set_active_ontology(name: str | None, cache: Cache) -> bool:
    """Point scoring at `name` (case-insensitive; canonical spelling stored). None clears."""
    if name is None:
        cache.set(_ONTOLOGY_ACTIVE_KEY, "", _USER_SAVE_TTL_SECONDS)
        return True
    canon = canonical_ontology_name(name, cache)
    if canon is None:
        return False
    cache.set(_ONTOLOGY_ACTIVE_KEY, canon, _USER_SAVE_TTL_SECONDS)
    return True


def active_graph(cache: Cache) -> KnowledgeGraph:
    """The graph every scoring path consumes: the active ontology's latest revision, or an
    empty graph when none is active (=> no network signal, by design)."""
    name = get_active_ontology(cache)
    if not name:
        return KnowledgeGraph(scope="active")
    found = load_ontology(name, cache)
    return found.graph if found else KnowledgeGraph(scope="active")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_ontology_store.py -q`
Expected: all PASS. Then the full suite (`-q`) — still green (nothing consumed yet).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schemas.py backend/app/network/store.py backend/tests/test_ontology_store.py
git commit -m "feat(backend): named-ontology store with one active pointer"
```

---

### Task 2: Ontology API endpoints + re-bake

**Files:**
- Modify: `backend/app/api/routes.py` (imports; new routes after `get_company_graph`, ~line 524)
- Test: `backend/tests/test_api_graph.py` (append a new section)

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_api_graph.py`)

```python
# --- ontologies --------------------------------------------------------------------------------

def _onto_payload(name="Tech Map"):
    return {
        "name": name, "expanded": ["AAPL"],
        "graph": {"as_of": "", "scope": "explore", "nodes": ["AAPL", "TSM"],
                  "edges": [{"source": "AAPL", "target": "TSM", "type": "supplier",
                             "sentiment": "negative", "weight": 1.0, "confidence": 1.0,
                             "evidence": "", "url": "", "as_of": ""}],
                  "built": 0, "skipped": 0},
    }


def _seed_board(cache):
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50,
                   direction="hold", net=0.0, base_score=50, base_net=0.0),
    ]), cache)


def test_ontology_crud(client):
    tc, _ = client
    r = tc.post("/api/graph/ontologies", json=_onto_payload())
    assert r.status_code == 200 and r.json()["saved_at"]          # server-stamped

    summ = tc.get("/api/graph/ontologies").json()
    assert summ[0]["name"] == "Tech Map" and summ[0]["active"] is False
    assert summ[0]["node_count"] == 2 and summ[0]["edge_count"] == 1

    r = tc.get("/api/graph/ontologies/tech map")                  # case-insensitive
    assert r.status_code == 200 and r.json()["graph"]["nodes"] == ["AAPL", "TSM"]

    r = tc.delete("/api/graph/ontologies/Tech Map")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert tc.get("/api/graph/ontologies/Tech Map").status_code == 404


def test_ontology_name_validation(client):
    tc, _ = client
    assert tc.post("/api/graph/ontologies", json=_onto_payload("")).status_code == 422
    assert tc.post("/api/graph/ontologies", json=_onto_payload("x" * 41)).status_code == 422
    assert tc.post("/api/graph/ontologies", json=_onto_payload("a/b")).status_code == 422


def test_activate_rebakes_board_and_get_graph_serves_active(client):
    tc, cache = client
    _seed_board(cache)
    tc.post("/api/graph/ontologies", json=_onto_payload())
    assert tc.get("/api/graph/active").json()["name"] is None
    assert tc.get("/api/graph").json()["edges"] == []             # nothing active yet

    r = tc.put("/api/graph/active", json={"name": "Tech Map"})
    assert r.status_code == 200 and r.json()["name"] == "Tech Map"
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None                               # re-baked on activate
    assert tc.get("/api/graph").json()["edges"]                   # display = active graph

    r = tc.put("/api/graph/active", json={"name": None})          # deactivate -> signal off
    assert r.status_code == 200 and r.json()["name"] is None
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is None


def test_activate_unknown_404(client):
    tc, _ = client
    assert tc.put("/api/graph/active", json={"name": "ghost"}).status_code == 404


def test_saving_the_active_ontology_rebakes(client):
    tc, cache = client
    _seed_board(cache)
    tc.post("/api/graph/ontologies", json=_onto_payload())
    tc.put("/api/graph/active", json={"name": "Tech Map"})

    empty = _onto_payload()
    empty["graph"]["edges"] = []                                  # new revision: no edges
    tc.post("/api/graph/ontologies", json=empty)
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is None                                   # master changed -> re-baked


def test_deleting_the_active_ontology_rebakes_to_no_signal(client):
    tc, cache = client
    _seed_board(cache)
    tc.post("/api/graph/ontologies", json=_onto_payload())
    tc.put("/api/graph/active", json={"name": "Tech Map"})
    tc.delete("/api/graph/ontologies/Tech Map")
    assert tc.get("/api/graph/active").json()["name"] is None
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_graph.py -q`
Expected: new tests FAIL with 404 (routes missing).

- [ ] **Step 3: Implement the routes**

In `backend/app/api/routes.py` — extend the schemas import with `ActiveOntology, OntologySummary, OntologyVersion`; extend the `app.network.store` import with `active_graph, delete_ontology, get_active_ontology, list_ontologies, load_ontology, save_ontology, set_active_ontology`. Insert after `get_company_graph`:

```python
_ONTOLOGY_NAME_MAX = 40


def _valid_ontology_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > _ONTOLOGY_NAME_MAX or "/" in name:
        raise HTTPException(status_code=422,
                            detail="Ontology name must be 1-40 characters with no '/'.")
    return name


def _rebake_board(settings: Settings, cache: Cache) -> None:
    """Re-blend the Discover snapshot against the active graph so NET scores flip
    immediately — no rescan needed."""
    board = load_snapshot(cache, "all")
    if board is not None:
        save_snapshot(apply_network(board, active_graph(cache), settings), cache)


@router.get("/graph/ontologies", response_model=list[OntologySummary])
def get_ontologies(cache: Cache = Depends(get_cache)) -> list[OntologySummary]:
    return list_ontologies(cache)


@router.post("/graph/ontologies", response_model=OntologyVersion)
def post_ontology(
    payload: OntologyVersion,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> OntologyVersion:
    name = _valid_ontology_name(payload.name)
    stamped = payload.model_copy(update={
        "name": name, "saved_at": datetime.now(timezone.utc).isoformat()})
    saved = save_ontology(stamped, cache)
    if saved.name == (get_active_ontology(cache) or ""):
        _rebake_board(store.load(), cache)  # saving the master changes what scoring sees
    return saved


@router.get("/graph/ontologies/{name}", response_model=OntologyVersion)
def get_ontology(name: str, version: str | None = None,
                 cache: Cache = Depends(get_cache)) -> OntologyVersion:
    found = load_ontology(name, cache, version)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No ontology '{name}'")
    return found


@router.delete("/graph/ontologies/{name}")
def delete_ontology_route(
    name: str, version: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> dict:
    was_active = get_active_ontology(cache)
    deleted = delete_ontology(name, cache, version)
    if deleted and was_active is not None and get_active_ontology(cache) is None:
        _rebake_board(store.load(), cache)  # active pointer was cleared -> signal off
    return {"deleted": deleted}


@router.get("/graph/active", response_model=ActiveOntology)
def get_active(cache: Cache = Depends(get_cache)) -> ActiveOntology:
    return ActiveOntology(name=get_active_ontology(cache))


@router.put("/graph/active", response_model=ActiveOntology)
def put_active(
    payload: ActiveOntology,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ActiveOntology:
    if not set_active_ontology(payload.name, cache):
        raise HTTPException(status_code=404, detail=f"No ontology '{payload.name}'")
    _rebake_board(store.load(), cache)
    return ActiveOntology(name=get_active_ontology(cache))
```

(Note: `test_activate_rebakes...` asserts `GET /api/graph` serves the active graph — that
flip happens in Task 3; mark that one assertion with the Task 3 change if running tasks
strictly in order, or run Tasks 2–3 before expecting full green.)

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_graph.py -q`
Expected: all new tests PASS except the two `tc.get("/api/graph")` assertions (old route still serves focus) — acceptable interim; they go green in Task 3. If you prefer strict green, do Task 3's `get_graph` rewrite in this commit.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_graph.py
git commit -m "feat(backend): ontology CRUD + active-pointer API with board re-bake"
```

---

### Task 3: Scoring cutover to `active_graph`

**Files:**
- Modify: `backend/app/screener/service.py:96`, `backend/app/services/analysis_service.py:35`, `backend/app/analysis/agent.py:221`, `backend/app/api/routes.py` (`_persist_rescan`, `get_graph`)
- Test: `backend/tests/test_score_one.py`, `backend/tests/test_analysis_service.py`, `backend/tests/test_api_graph.py` (rescan test)

- [ ] **Step 1: Swap the four scoring reads**

In each file change the import `from app.network.store import effective_graph` → `from app.network.store import active_graph` and the call `effective_graph(cache, "focus")` → `active_graph(cache)` (in `agent.py` it's `effective_graph(ctx.cache, "focus")` → `active_graph(ctx.cache)`):
- `screener/service.py` `score_one`
- `services/analysis_service.py` `gather_stock_context`
- `analysis/agent.py` `app_signals`
- `api/routes.py` `_persist_rescan` (line ~433) — routes keeps importing both until Task 4 removes the rest.

Rewrite `get_graph` in `routes.py`:

```python
@router.get("/graph", response_model=KnowledgeGraph)
def get_graph(cache: Cache = Depends(get_cache)) -> KnowledgeGraph:
    """The graph scoring currently uses: the active ontology's latest revision (empty when none)."""
    return active_graph(cache)
```

- [ ] **Step 2: Update the seeding in affected tests**

Anywhere a test seeds scoring via the focus snapshot, replace with save+activate. Pattern (apply in `test_analysis_service.py` ~lines 127-136 and 207-216, `test_api_graph.py::test_rescan_applies_cached_graph`):

```python
# OLD
from app.network.store import save_graph
save_graph(KnowledgeGraph(scope="focus", edges=[...]), cache)
# NEW
from app.models.schemas import OntologyVersion
from app.network.store import save_ontology, set_active_ontology
save_ontology(OntologyVersion(name="test", saved_at="t",
                              graph=KnowledgeGraph(scope="explore", edges=[...])), cache)
set_active_ontology("test", cache)
```

In `test_score_one.py` (~line 52) change the monkeypatched name:

```python
monkeypatch.setattr(service, "active_graph",
                    lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
```

(keep the test's original raising style; only the attribute name changes). Also grep for other seeds: `cd backend && git grep -n "save_graph\|effective_graph" tests/` and convert each the same way — EXCEPT `tests/test_graph_overlay.py` (reworked in Task 4).

- [ ] **Step 3: Run the backend suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: green except `tests/test_graph_overlay.py` / `tests/test_network_*` failures that belong to Task 4's retirement (if any appear, note them — they must be exactly the files Task 4 reworks).

- [ ] **Step 4: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(backend): scoring reads the active ontology instead of the news graph"
```

---

### Task 4: Retire the news-graph machinery

**Files:**
- Modify: `backend/app/network/store.py` (delete `save_graph`, `load_graph`, `_key`, `_SNAPSHOT_TTL_SECONDS`, `merge_graphs`, `load_overlay`, `effective_graph`, and ALL saved-graph functions `_saved_key`…`delete_saved_graph` + `_INDEX_KEY`; drop `SavedGraphSummary, SavedGraphVersion` from imports)
- Modify: `backend/app/network/service.py` (delete `build_graph`, `_focus_set`; module docstring → "One-hop company extraction powering the explorer.")
- Modify: `backend/app/network/runner.py`, `backend/app/network/__main__.py`
- Modify: `backend/app/api/routes.py` (delete `rebuild_graph`, `list_saved`, `save_saved`, `get_saved`, `delete_saved` routes; purge dead imports: `build_graph`, `save_graph`, `load_graph`, `load_overlay`, `effective_graph`, `save_company_graph`, `load_company_graph`, `list_saved_graphs`, `delete_saved_graph`, `SavedGraphSummary`, `SavedGraphVersion`)
- Modify: `backend/app/models/schemas.py` (delete `SavedGraphVersion`, `SavedGraphSummary`)
- Test: rename `backend/tests/test_graph_overlay.py` → `backend/tests/test_graph_imports.py` (keep import-set CRUD tests; delete `test_effective_graph_*`); rework `backend/tests/test_network_runner.py`; in `backend/tests/test_network_service.py` delete `build_graph`/`_focus_set` tests (keep `build_company_graph` ones); in `backend/tests/test_api_graph.py` delete `test_rebuild_builds_and_bakes`, `test_saved_graph_crud`, `test_import_then_get_graph_includes_overlay`, `test_import_feeds_scoring_after_rebuild`, `test_get_graph_scope_imported_returns_only_overlay`, `test_get_graph_empty_when_none` (scope param gone — replace with `test_get_graph_empty_when_no_active`: `tc.get("/api/graph")` → `edges == []`), and in `test_list_and_delete_import` / `test_get_single_import_set` drop the final `tc.get("/api/graph")` overlay assertions (sets no longer surface there).

- [ ] **Step 1: New runner**

```python
# backend/app/network/runner.py
from __future__ import annotations

import logging

from app.analysis.network import apply_network
from app.config.cache import Cache
from app.models.schemas import Settings
from app.network.store import active_graph, get_active_ontology
from app.screener.store import load_snapshot, save_snapshot

logger = logging.getLogger("network")


def run(settings: Settings, cache: Cache) -> dict:
    """Re-blend the board snapshot against the ACTIVE ontology (daily job after the screener).
    No LLM build anymore — the ontology is user-curated on the Graph page."""
    if not settings.network.enabled:
        logger.info("Network signal disabled; nothing to do.")
        return {"enabled": False, "baked": 0}
    board = load_snapshot(cache, "all")
    if board is None:
        logger.info("No board snapshot yet; nothing to bake.")
        return {"enabled": True, "baked": 0, "active": get_active_ontology(cache) or ""}
    graph = active_graph(cache)
    save_snapshot(apply_network(board, graph, settings), cache)
    logger.info("Baked: rows=%d edges=%d active=%s",
                len(board.items), len(graph.edges), get_active_ontology(cache) or "(none)")
    return {"enabled": True, "baked": len(board.items), "edges": len(graph.edges),
            "active": get_active_ontology(cache) or ""}
```

- [ ] **Step 2: New `__main__`** (drop the `build_graph` dry-run)

```python
# backend/app/network/__main__.py
from __future__ import annotations

import argparse
import logging
import os
import sys

from app.deps import DATA_DIR, get_cache, get_settings_store
from app.network.runner import run
from app.network.store import active_graph, get_active_ontology


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.network",
        description="Re-bake the active ontology's network signal into the board snapshot.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Log what would bake, no save.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)
    settings = get_settings_store().load()
    cache = get_cache()
    log = logging.getLogger("network")
    if args.dry_run:
        g = active_graph(cache)
        log.info("Dry run: active=%s edges=%d", get_active_ontology(cache) or "(none)", len(g.edges))
        return 0
    log.info("Done: %s", run(settings, cache))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Rework `test_network_runner.py`**

```python
# backend/tests/test_network_runner.py
from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, OntologyVersion, ScreenBoard, Settings, StockScore
from app.network import runner
from app.network.store import save_ontology, set_active_ontology
from app.screener.store import load_snapshot, save_snapshot


def _board():
    return ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50,
                   direction="hold", net=0.0, base_score=50, base_net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40,
                   direction="sell", net=-0.9, base_score=40, base_net=-0.9),
    ])


def _activate_graph(cache):
    save_ontology(OntologyVersion(name="t", saved_at="v1", graph=KnowledgeGraph(edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)])), cache)
    set_active_ontology("t", cache)


def test_run_bakes_active_ontology_into_board(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    _activate_graph(cache)
    out = runner.run(Settings(), cache)
    assert out["baked"] == 2 and out["active"] == "t"
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None


def test_run_with_no_active_ontology_strips_signal(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    runner.run(Settings(), cache)                    # nothing active
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is None


def test_run_disabled_or_no_board_is_a_noop(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    s = Settings()
    s.network.enabled = False
    assert runner.run(s, cache)["enabled"] is False
    assert runner.run(Settings(), cache)["baked"] == 0   # enabled but no board yet
```

- [ ] **Step 4: Apply the deletions** listed under **Files**, then sweep:

Run: `cd backend && git grep -n "effective_graph\|load_overlay\|merge_graphs\|build_graph\|save_graph\|load_graph\|SavedGraph\|save_company_graph\|load_company_graph\|list_saved_graphs\|delete_saved_graph\|graph/rebuild\|graph/saved"`
Expected: ZERO hits in `app/` (only `build_company_graph` remains — note the grep above intentionally matches it via `build_graph`? No: `build_graph` does not match `build_company_graph` as a *word*, but plain substring grep matches — verify remaining hits are exactly `build_company_graph` and import-set functions). Fix any stragglers.

- [ ] **Step 5: Run the FULL backend suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: all green (414+ tests, minus deleted, plus new).

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(backend)!: retire the news focus graph, overlay scoring and per-root saves"
```

---

### Task 5: Frontend types, client methods and hooks

**Files:**
- Modify: `frontend/src/types.ts:262-263` (replace `SavedGraphVersion`/`SavedGraphSummary`)
- Modify: `frontend/src/api/client.ts` (replace saved-graph + `getOverlay` methods)
- Modify: `frontend/src/hooks/queries.ts` (replace saved-graph + overlay hooks)
- Test: `frontend/src/api/client.test.ts` (replace the 4 saved-graph tests)

- [ ] **Step 1: types.ts**

```ts
export interface OntologyVersion { name: string; saved_at: string; expanded: string[]; graph: KnowledgeGraph; }
export interface OntologySummary { name: string; versions: string[]; node_count: number; edge_count: number; active: boolean; }
```

- [ ] **Step 2: client.ts** — replace `listSavedGraphs/saveGraph/loadSavedGraph/deleteSavedGraph/getOverlay` with:

```ts
listOntologies: () => http<OntologySummary[]>('/graph/ontologies'),
saveOntology: (v: OntologyVersion) =>
  http<OntologyVersion>('/graph/ontologies', { method: 'POST', body: JSON.stringify(v) }),
loadOntology: (name: string, version?: string) =>
  http<OntologyVersion>(
    `/graph/ontologies/${encodeURIComponent(name)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
  ),
deleteOntology: (name: string, version?: string) =>
  http<{ deleted: boolean }>(
    `/graph/ontologies/${encodeURIComponent(name)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
    { method: 'DELETE' },
  ),
getActiveOntology: () => http<{ name: string | null }>('/graph/active'),
setActiveOntology: (name: string | null) =>
  http<{ name: string | null }>('/graph/active', { method: 'PUT', body: JSON.stringify({ name }) }),
```

(update the type import list accordingly: `OntologySummary, OntologyVersion` in, `SavedGraphSummary, SavedGraphVersion` out).

- [ ] **Step 3: queries.ts** — replace `useSavedGraphs/useSaveGraph/useLoadSavedGraph/useDeleteSavedGraph/useOverlay` with:

```ts
const SCORE_KEYS = [['ontologies'], ['screen'], ['score'], ['signals']] as const;

function invalidateOntologyWorld(qc: ReturnType<typeof useQueryClient>) {
  for (const key of SCORE_KEYS) qc.invalidateQueries({ queryKey: [...key] });
}

export function useOntologies() {
  return useQuery({ queryKey: ['ontologies'], queryFn: api.listOntologies });
}

export function useActiveOntology() {
  return useQuery({ queryKey: ['ontologies', 'active'], queryFn: api.getActiveOntology });
}

export function useSaveOntology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: OntologyVersion) => api.saveOntology(v),
    // Saving the ACTIVE ontology re-bakes the board server-side — refresh score readers too.
    onSuccess: () => invalidateOntologyWorld(qc),
  });
}

export function useLoadOntology() {
  return useMutation({
    mutationFn: ({ name, version }: { name: string; version?: string }) =>
      api.loadOntology(name, version),
  });
}

export function useDeleteOntology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, version }: { name: string; version?: string }) =>
      api.deleteOntology(name, version),
    onSuccess: () => invalidateOntologyWorld(qc),
  });
}

export function useSetActiveOntology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string | null) => api.setActiveOntology(name),
    onSuccess: () => invalidateOntologyWorld(qc),
  });
}
```

(import `OntologyVersion` instead of `SavedGraphVersion` at the top.)

- [ ] **Step 4: client.test.ts** — replace the four saved-graph tests with:

```ts
it('saveOntology POSTs /graph/ontologies', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
  await api.saveOntology({ name: 'Tech', saved_at: '', expanded: [], graph: { as_of: '', scope: 'x', nodes: [], edges: [], built: 0, skipped: 0 } });
  expect((fetchMock.mock.calls[0][0] as string)).toContain('/graph/ontologies');
  expect(fetchMock.mock.calls[0][1].method).toBe('POST');
});

it('loadOntology encodes the name and carries the version', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
  await api.loadOntology('Tech Map', 't1');
  expect((fetchMock.mock.calls[0][0] as string)).toContain('/graph/ontologies/Tech%20Map?version=t1');
});

it('setActiveOntology PUTs the name (null deactivates)', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ name: null }) });
  vi.stubGlobal('fetch', fetchMock);
  await api.setActiveOntology(null);
  expect((fetchMock.mock.calls[0][0] as string)).toContain('/graph/active');
  expect(fetchMock.mock.calls[0][1].method).toBe('PUT');
  expect(fetchMock.mock.calls[0][1].body).toBe('{"name":null}');
});

it('deleteOntology DELETEs /graph/ontologies/{name}', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ deleted: true }) });
  vi.stubGlobal('fetch', fetchMock);
  await api.deleteOntology('Tech');
  expect((fetchMock.mock.calls[0][0] as string)).toContain('/graph/ontologies/Tech');
  expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
});
```

- [ ] **Step 5: Run** `cd frontend && npx vitest run src/api/client.test.ts` — PASS. (`npm test` still fails in Graph tests — fixed next task.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/api frontend/src/hooks/queries.ts
git commit -m "feat(frontend): ontology API client and hooks replace per-root saves"
```

---

### Task 6: Graph page — ontology toolbar, Ontologies tab, boot + hint

**Files:**
- Modify: `frontend/src/pages/Graph.tsx`
- Modify: `frontend/src/components/GraphSidebar.tsx`
- Modify: `frontend/src/lib/explorerStore.ts` (add `ontologyName: string` to `ExplorerState`)
- Modify: `frontend/src/styles.css` (`.ontology-bar` flex row, small)
- Test: `frontend/src/pages/Graph.test.tsx`, `frontend/src/components/GraphSidebar.test.tsx`

- [ ] **Step 1: explorerStore** — add `ontologyName: string;` to `ExplorerState` (keep `KEY = 'graphExplorer:v1'`; restored v1 states simply lack the field — callers default it to `''`).

- [ ] **Step 2: Graph.tsx rework.** Replace the saved-graph hooks/handlers with ontology ones:

```tsx
const ontologies = useOntologies();
const activeOnto = useActiveOntology();
const saveOntology = useSaveOntology();
const loadOntology = useLoadOntology();
const deleteOntology = useDeleteOntology();
const setActiveOnto = useSetActiveOntology();
const [ontologyName, setOntologyName] = useState(restored?.ontologyName ?? '');
```

Handlers (replace `doSave`, `doLoadSaved`, `doDeleteSaved`, `clearGraph`):

```tsx
const doSaveAs = async (name: string) => {
  const n = name.trim();
  if (!working || working.nodes.length === 0) return;
  if (!n) { setNotice('Name the ontology first.'); return; }
  setNotice(null);
  try {
    const saved = await saveOntology.mutateAsync({
      name: n, saved_at: '', expanded: [...expanded], graph: working,
    });
    setOntologyName(saved.name);   // canonical spelling from the server
    setDirty(false);
  } catch { setNotice('Could not save this ontology.'); }
};

const doNew = () => {
  setWorking(null); setOntologyName(''); setRoot(''); setExpanded(new Set());
  setSelectedId(null); setNotice(null); setDirty(false);
};

const doLoadOntology = async (name: string, version?: string) => {
  setNotice(null);
  try {
    const v = await loadOntology.mutateAsync({ name, version });
    setWorking(v.graph); setOntologyName(v.name); setExpanded(new Set(v.expanded));
    setRoot(''); setSelectedId(null); setDirty(false); setTab('explore');
  } catch { setNotice(`Could not load the ontology ${name}.`); }
};

const doDeleteOntology = async (name: string, version?: string) => {
  try { await deleteOntology.mutateAsync({ name, version }); }
  catch { setNotice(`Could not delete ${name}.`); }
};

const doActivate = async (name: string | null) => {
  setNotice(null);
  try { await setActiveOnto.mutateAsync(name); }
  catch { setNotice('Could not change the active ontology.'); }
};
```

Boot precedence (restored canvas wins; else load the active ontology once):

```tsx
const booted = useRef(false);
useEffect(() => {
  if (booted.current || restored?.working || !activeOnto.data?.name || working) return;
  booted.current = true;
  void doLoadOntology(activeOnto.data.name);
}, [activeOnto.data]);   // eslint-disable-line react-hooks/exhaustive-deps — boot-once
```

Status hint + toolbar at the top of `.graph-main` (replace the existing `dirty && …unsaved-hint` line):

```tsx
const activeName = activeOnto.data?.name ?? null;
const onActive = !dirty && !!ontologyName && ontologyName === activeName;
const hint = onActive ? null
  : `Analysis currently uses ${activeName ? `“${activeName}”` : 'no network signal'}${dirty ? ' — unsaved changes here' : ''}.`;
```

```tsx
<div className="ontology-bar">
  <input
    placeholder="Ontology name" aria-label="ontology name"
    value={ontologyName} onChange={(e) => setOntologyName(e.target.value)}
  />
  <button
    disabled={!working || working.nodes.length === 0 || saveOntology.isPending}
    onClick={() => doSaveAs(ontologyName || window.prompt('Name this ontology', '') || '')}
  >
    {saveOntology.isPending ? 'Saving…' : 'Save'}
  </button>
  <button
    className="secondary" disabled={!working || working.nodes.length === 0}
    onClick={() => { const n = window.prompt('Save as…', ontologyName ? `${ontologyName} copy` : ''); if (n) void doSaveAs(n); }}
  >
    Save as
  </button>
  <button className="secondary" onClick={doNew}>New</button>
  {hint && <span className="muted">{hint}</span>}
</div>
```

Also: persist `ontologyName` in the explorer-state effect; **delete the overlay merge** from the `view` memo (drop `useOverlay` and the whole `if (ov …)` block — `view` becomes `applyFilters(mergeNodes(g, board.data), toLinks(g), null, enabledTypes)`); update `GraphSidebar` props (next step); remove `onSave/canSave/saveAs/saving/onClear` wiring.

- [ ] **Step 3: GraphSidebar.tsx.** Props delta — remove `onSave, onClear, canSave, saveAs, saving, saved, onLoadSaved, onDeleteSaved`; add:

```ts
ontologies: OntologySummary[];
activeName: string | null;
onLoadOntology: (name: string, version?: string) => void;
onDeleteOntology: (name: string, version?: string) => void;
onActivate: (name: string | null) => void;
```

Tab button label: `Ontologies{ontologies.length ? ` (${ontologies.length})` : ''}` (keep the internal key `'saved'`). In the explore tab, drop the Save/Clear `graph-actions` block (keep the counts line). Replace the saved-tab body with:

```tsx
{tab === 'saved' && (
  <div className="graph-tab">
    <div className="graph-save-row">
      <span className="muted">None (network signal off)</span>
      {activeName === null
        ? <span className="badge hold">ACTIVE</span>
        : <button className="linklike" onClick={() => onActivate(null)}>Set active</button>}
    </div>
    {ontologies.map((o) => (
      <div key={o.name} className="graph-save-row">
        <button className="linklike" onClick={() => onLoadOntology(o.name)}>Load {o.name}</button>
        <span className="muted">{o.node_count}n · {o.edge_count}e</span>
        {o.active
          ? <span className="badge buy">ACTIVE</span>
          : <button className="linklike" onClick={() => onActivate(o.name)}>Set active</button>}
        {o.versions.length > 1 && (
          <select defaultValue="" onChange={(e) => { if (e.target.value) onLoadOntology(o.name, e.target.value); }}>
            <option value="">latest ({o.versions.length})</option>
            {o.versions.map((v) => <option key={v} value={v}>{new Date(v).toLocaleString()}</option>)}
          </select>
        )}
        <button className="icon-btn" aria-label={`delete ${o.name}`} onClick={() => onDeleteOntology(o.name)}>✕</button>
      </div>
    ))}
    {ontologies.length === 0 && <p className="muted">No ontologies yet — build a graph and Save it.</p>}
  </div>
)}
```

- [ ] **Step 4: styles.css** — append:

```css
.ontology-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.ontology-bar input { max-width: 220px; }
```

- [ ] **Step 5: Update tests.**
`Graph.test.tsx`: swap the api mock surface to `listOntologies, saveOntology, loadOntology, deleteOntology, getActiveOntology, setActiveOntology` (drop `listSavedGraphs/saveGraph/loadSavedGraph/deleteSavedGraph/getOverlay`); default `listOntologies → []`, `getActiveOntology → { name: null }`. Rewrite the save test to type a name then click Save and assert `api.saveOntology` got `{ name: 'Tech', … }`; delete the overlay-render test; add: "boots into the active ontology when nothing restored" (`getActiveOntology → { name: 'Tech' }`, `loadOntology` resolves a graph → canvas non-empty + name field shows `Tech`), and "hint names the active ontology when canvas differs". `GraphSidebar.test.tsx`: update the prop fixture (drop removed props, add the five new ones) and add an Ontologies-tab test: rows render counts, ACTIVE badge on the active row, `Set active` fires `onActivate('A')`, the None row fires `onActivate(null)`.

- [ ] **Step 6: Run** `cd frontend && npm test` then `npm run build` — both green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): ontology toolbar, Ontologies tab and active-ontology hint"
```

---

### Task 7: Custom company nodes

**Files:**
- Modify: `frontend/src/lib/graphView.ts` (+ `COMPANY_TICKER_RE`, `addCompanyNode`)
- Modify: `frontend/src/components/GraphCanvas.tsx` (background right-click menu + node menu item; new props)
- Modify: `frontend/src/components/GraphSidebar.tsx` (company form, like the rel-form)
- Modify: `frontend/src/pages/Graph.tsx` (state + handler + props)
- Test: `frontend/src/lib/graphView.test.ts`, `frontend/src/pages/Graph.test.tsx`

- [ ] **Step 1: Failing unit tests** (append to `graphView.test.ts`)

```ts
import { addCompanyNode } from './graphView';

it('addCompanyNode adds an upper-cased ticker node with company meta', () => {
  const g = addCompanyNode({ as_of: '', scope: 'explore', nodes: [], edges: [], built: 0, skipped: 0 },
    { ticker: 'tsm', label: 'TSMC' });
  expect(g.nodes).toEqual(['TSM']);
  expect(g.node_meta?.TSM).toEqual({ label: 'TSMC', kind: 'company', source: 'manual' });
});

it('addCompanyNode rejects bad tickers and duplicates', () => {
  const base = { as_of: '', scope: 'explore', nodes: ['TSM'], edges: [], built: 0, skipped: 0 };
  expect(addCompanyNode(base, { ticker: 'not a ticker!!' })).toBe(base);
  expect(addCompanyNode(base, { ticker: 'TSM' })).toBe(base);
});
```

- [ ] **Step 2: Implement in graphView.ts**

```ts
export const COMPANY_TICKER_RE = /^[A-Za-z][A-Za-z0-9.\-]{0,9}$/;

/** Add a manual COMPANY node (id = upper-cased ticker, expandable + scoreable), unlike the
 *  `man:` concept nodes. No-op on invalid ticker or existing id. */
export function addCompanyNode(graph: KnowledgeGraph, c: { ticker: string; label?: string }): KnowledgeGraph {
  const id = c.ticker.trim().toUpperCase();
  if (!COMPANY_TICKER_RE.test(c.ticker.trim()) || graph.nodes.includes(id)) return graph;
  const node_meta = { ...(graph.node_meta ?? {}) };
  node_meta[id] = { label: (c.label ?? '').trim() || id, kind: 'company', source: 'manual' };
  return { ...graph, nodes: [...graph.nodes, id], node_meta };
}
```

- [ ] **Step 3: Wire the UI.**
`GraphCanvas` props add `onAddCompany: () => void;`. Node right-click menu gains `{ label: 'Add company…', onClick: onAddCompany }` (before "Add relationship"), and add a background handler on `ForceGraph2D`:

```tsx
onBackgroundRightClick={(e: MouseEvent) => {
  e.preventDefault();
  setMenu({ ...localXY(e), items: [{ label: 'Add company…', onClick: onAddCompany }] });
}}
```

`Graph.tsx`: `const [addingCompany, setAddingCompany] = useState(false);` +

```tsx
const addCompany = (data: { ticker: string; label: string }) => {
  const t = data.ticker.trim();
  if (!COMPANY_TICKER_RE.test(t)) { setNotice('Ticker must be 1–10 letters/digits, e.g. TSM.'); return; }
  const base = working ?? { ...EMPTY_GRAPH, nodes: [], edges: [], node_meta: {} };
  setWorking(addCompanyNode(base, { ticker: t, label: data.label }));
  setSelectedId(t.toUpperCase()); setDirty(true); setAddingCompany(false); setNotice(null);
};
```

pass `onAddCompany={() => { setAddingCompany(true); setTab('explore'); }}` to the canvas — and because an empty canvas hides `GraphCanvas`, also surface an "Add company…" secondary button next to "Start" in the sidebar explore tab. `GraphSidebar` gains `addingCompany: boolean; onSubmitCompany: (d: { ticker: string; label: string }) => void; onCancelCompany: () => void; onStartAddCompany: () => void;` and renders (above the Start control, mirroring the rel-form):

```tsx
{addingCompany && (
  <div className="graph-section rel-form">
    <span className="label">Add a company</span>
    <input placeholder="Ticker (e.g. TSM)" value={coTicker} onChange={(e) => setCoTicker(e.target.value)}
           onKeyDown={(e) => { if (e.key === 'Enter') submitCompany(); }} />
    <input placeholder="Name (optional)" value={coLabel} onChange={(e) => setCoLabel(e.target.value)} />
    <div className="graph-actions">
      <button onClick={submitCompany}>Add</button>
      <button className="secondary" onClick={onCancelCompany}>Cancel</button>
    </div>
  </div>
)}
```

with local state `const [coTicker, setCoTicker] = useState(''); const [coLabel, setCoLabel] = useState('');` and `const submitCompany = () => { if (!coTicker.trim()) return; onSubmitCompany({ ticker: coTicker.trim(), label: coLabel.trim() }); setCoTicker(''); setCoLabel(''); };`. The standing button: `<button className="secondary" onClick={onStartAddCompany}>Add company…</button>` after "Start".

- [ ] **Step 4: Graph.test.tsx** — add a flow test: open Add company form, type `tsm` + name, submit → a node `TSMC`-labelled appears in the working graph (assert via the save payload or sidebar detail); bad ticker shows the notice.

- [ ] **Step 5: Run** `cd frontend && npm test` — green. **Commit:**

```bash
git add frontend/src
git commit -m "feat(frontend): add custom company nodes to the graph"
```

---

### Task 8: Watchlist toggle on graph companies

**Files:**
- Modify: `frontend/src/pages/Graph.tsx` (`useWatchlist`, props)
- Modify: `frontend/src/components/GraphCanvas.tsx` (node menu item; props `watchlist: string[]`, `onToggleWatch: (id: string) => void`)
- Modify: `frontend/src/components/GraphSidebar.tsx` (detail-panel button; same two props)
- Test: `frontend/src/components/GraphSidebar.test.tsx`, `frontend/src/pages/Graph.test.tsx`

- [ ] **Step 1: Graph.tsx**

```tsx
const watch = useWatchlist();
const toggleWatch = (id: string) => (watch.list.includes(id) ? watch.remove(id) : watch.add(id));
```

Pass `watchlist={watch.list}` + `onToggleWatch={toggleWatch}` to BOTH `GraphCanvas` and `GraphSidebar`.

- [ ] **Step 2: GraphCanvas node menu** — company nodes only (`!n.id.includes(':')`):

```tsx
onNodeRightClick={(n: any, e: MouseEvent) => {
  e.preventDefault();
  const items: MenuItem[] = [
    { label: 'Add company…', onClick: onAddCompany },
    { label: 'Add relationship', onClick: () => onAddRelationship(n.id) },
  ];
  if (!String(n.id).includes(':')) {
    items.push(watchlist.includes(n.id)
      ? { label: `★ Remove ${n.id} from watchlist`, onClick: () => onToggleWatch(n.id) }
      : { label: `☆ Add ${n.id} to watchlist`, onClick: () => onToggleWatch(n.id) });
  }
  items.push({ label: 'Delete node', danger: true, onClick: () => onDeleteNode(n.id) });
  setMenu({ ...localXY(e), items });
}}
```

- [ ] **Step 3: GraphSidebar detail panel** — under "Expand neighbours", for `!selected.id.includes(':')`:

```tsx
{!selected.id.includes(':') && (
  <button className="secondary" onClick={() => onToggleWatch(selected.id)}>
    {watchlist.includes(selected.id) ? `★ Remove from watchlist` : `☆ Add to watchlist`}
  </button>
)}
```

- [ ] **Step 4: Tests.** `GraphSidebar.test.tsx`: with `selected = { id: 'TSM', … }` and `watchlist: []` the button reads "☆ Add to watchlist" and fires `onToggleWatch('TSM')`; with `watchlist: ['TSM']` it reads "★ Remove from watchlist"; with a `man:` selected node it's absent. `Graph.test.tsx`: settings mock already carries a watchlist — assert `api.saveSettings` is called with the ticker appended after clicking the sidebar button (mirrors `useWatchlist.test.tsx` style).

- [ ] **Step 5: Run** `cd frontend && npm test && npm run build` — green. **Commit:**

```bash
git add frontend/src
git commit -m "feat(frontend): watchlist add/remove from graph company nodes"
```

---

### Task 9: Docs + final verification

**Files:**
- Modify: `README.md` (Graph feature paragraph; daily-ops mention of `python -m app.network` = re-bake; note the active-ontology cutover)
- Modify: `backend/README.md` (endpoints: remove `/graph/rebuild` + `/graph/saved*`, add `/graph/ontologies*` + `/graph/active`; rewrite the "Knowledge-graph daily build" section → "Network re-bake (active ontology)")
- Modify: `frontend/README.md` (Graph page bullet: ontology workflow, Save/Save as/New, Set active, add-company, watchlist toggle)

- [ ] **Step 1: Edit the three READMEs.** Key copy points: ontologies are user-named and versioned; exactly one is ACTIVE and is the only graph scoring consumes (none active = no network signal); rescans/snapshots/LLM prompts all follow it; imports are merge-into-canvas building blocks; news extraction lives in Expand neighbours; the daily `python -m app.network` job now only re-bakes the board against the active ontology.

- [ ] **Step 2: Full verification**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q          # all green
cd ../frontend && npm test && npm run build                  # all green
```

- [ ] **Step 3: Commit docs**

```bash
git add README.md backend/README.md frontend/README.md
git commit -m "docs: ontology-driven graph workflow"
```

- [ ] **Step 4: Merge** (after user sign-off; repo convention is local ff-merge)

```bash
git checkout master && git merge --ff-only feat/graph-ontology
```

---

## Self-review notes

- Spec coverage: store/API (Tasks 1–2), cutover + no-fallback (Task 3), retirement (Task 4), frontend client (Task 5), toolbar/tab/boot/hint (Task 6), company nodes (Task 7), watchlist (Task 8), docs/consequences (Task 9). Import sets keep working untouched (`test_graph_imports.py` retains coverage).
- Live-reload caution: the user's dev backend runs `--reload` — Task 4's deletions go live immediately; the frontend (Tasks 5+) catches up within the same session. Do backend Tasks 1–4 and frontend Tasks 5–6 in one sitting to keep the running app coherent.
- The `tc.get("/api/graph")` assertions in Task 2's tests depend on Task 3's `get_graph` rewrite — run Tasks 2 and 3 together if strict per-task green is wanted.
