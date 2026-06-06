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
