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
    _activate_graph(cache)
    runner.run(Settings(), cache)                    # bake the signal in first
    set_active_ontology(None, cache)
    runner.run(Settings(), cache)                    # nothing active -> strip
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is None


def test_run_disabled_or_no_board_is_a_noop(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    s = Settings()
    s.network.enabled = False
    assert runner.run(s, cache)["enabled"] is False
    assert runner.run(Settings(), cache)["baked"] == 0   # enabled but no board yet
