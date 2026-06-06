import app.api.routes as routes
from fastapi.testclient import TestClient
from app.deps import get_cache
from app.main import app
from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore
from app.network.store import load_graph
from app.screener.store import load_snapshot, save_snapshot

client = TestClient(app)


def test_get_graph_empty_when_none():
    r = client.get("/api/graph?scope=does-not-exist")
    assert r.status_code == 200 and r.json()["edges"] == []


def test_rebuild_builds_and_bakes(monkeypatch):
    cache = get_cache()
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold", net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40, direction="sell", net=-0.9),
    ]), cache)
    graph = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)], built=1)
    monkeypatch.setattr(routes, "build_graph", lambda scope, settings, cache: graph)

    r = client.post("/api/graph/rebuild")
    assert r.status_code == 200 and r.json()["built"] == 1
    assert load_graph(cache, "focus") is not None
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None
