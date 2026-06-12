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


from app.models.schemas import UniverseEntry


def _stub_universe(monkeypatch):
    monkeypatch.setattr(routes.universe, "load_universe", lambda: [
        UniverseEntry(ticker="AAPL", name="Apple", sector="Tech"),
        UniverseEntry(ticker="MSFT", name="Microsoft", sector="Tech"),
    ])


def test_import_creates_a_set(client, monkeypatch):
    tc, _ = client
    _stub_universe(monkeypatch)
    body = {"name": "demo", "payload": {"edges": [
        {"source": "AAPL", "target": "MSFT", "type": "partner",
         "sentiment": "positive", "weight": 1.0, "confidence": 1.0}]}}
    r = tc.post("/api/graph/import", json=body)
    assert r.status_code == 200
    rep = r.json()
    assert rep["edges_added"] == 1 and rep["id"]
    sets = tc.get("/api/graph/imports").json()
    assert len(sets) == 1 and sets[0]["edge_count"] == 1


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


def test_deleting_latest_version_of_active_ontology_rebakes(client):
    tc, cache = client
    _seed_board(cache)
    tc.post("/api/graph/ontologies", json=_onto_payload())            # v1: 1 edge
    empty = _onto_payload()
    empty["graph"]["edges"] = []
    r = tc.post("/api/graph/ontologies", json=empty)                  # v2 (latest): no edges
    v2_stamp = r.json()["saved_at"]
    tc.put("/api/graph/active", json={"name": "Tech Map"})
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is None                                       # v2 active: no signal

    tc.delete(f"/api/graph/ontologies/tech map?version={v2_stamp}")   # case-insensitive delete
    assert tc.get("/api/graph/active").json()["name"] == "Tech Map"   # pointer survives
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None                                   # re-baked against v1
