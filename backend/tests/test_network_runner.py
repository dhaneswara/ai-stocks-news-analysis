import app.network.runner as runner
from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore
from app.network.store import load_graph
from app.screener.store import load_snapshot, save_snapshot


def test_run_builds_saves_and_bakes_into_board(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold", net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40, direction="sell", net=-0.9),
    ]), cache)
    graph = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)], built=1)
    monkeypatch.setattr(runner, "build_graph", lambda scope, settings, cache: graph)

    result = runner.run(Settings(), cache)
    assert result["enabled"] and result["built"] == 1
    assert load_graph(cache, "focus") is not None
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None  # influence baked into the stored board


def test_run_disabled_is_noop(tmp_path):
    settings = Settings(); settings.network.enabled = False
    assert runner.run(settings, Cache(str(tmp_path / "c.db")))["enabled"] is False
