import app.screener.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Candle, Fundamentals, GraphEdge, Indicators, KnowledgeGraph, OntologyVersion,
    PriceSummary, ScreenBoard, Settings, StockData, StockScore,
)
from app.network.store import save_ontology, set_active_ontology
from app.screener.service import score_one
from app.screener.store import save_snapshot


def _stock(ticker="AAPL"):
    return StockData(
        ticker=ticker, company_name="Apple", as_of="2026-06-06",
        price=PriceSummary(current=100, change=1, change_pct=1.0),
        candles=[Candle(time="2026-06-05", open=1, high=1, low=1, close=1, volume=1)],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def test_score_one_base(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    s = Settings()
    s.network.enabled = False
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert isinstance(out, StockScore) and out.ticker == "AAPL"
    assert out.network is None          # no blend when network disabled


def test_score_one_blends_network(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    save_ontology(OntologyVersion(name="test", saved_at="t",
                                  graph=KnowledgeGraph(scope="explore", nodes=["AAPL", "MSFT"], edges=[
                                      GraphEdge(source="AAPL", target="MSFT", type="partner",
                                                sentiment="positive", weight=1.0, confidence=1.0)])),
                  cache)
    set_active_ontology("test", cache)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="Microsoft", price=1, change_pct=0, score=60,
                   direction="buy", net=0.5, base_score=60.0, base_net=0.5)]), cache)
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert out.network is not None and out.network.signed > 0
    assert out.components.get("network") is not None


def test_score_one_network_failure_degrades(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    # active_graph raising must NOT break scoring — base score still returned.
    monkeypatch.setattr(service, "active_graph",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert isinstance(out, StockScore) and out.network is None


def test_score_one_blends_reverse_symmetric_edge(tmp_path, monkeypatch):
    # Edge MSFT -> AAPL (partner). Scoring AAPL must pick it up via the reverse direction.
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    save_ontology(OntologyVersion(name="test", saved_at="t",
                                  graph=KnowledgeGraph(scope="explore", nodes=["AAPL", "MSFT"], edges=[
                                      GraphEdge(source="MSFT", target="AAPL", type="partner",
                                                sentiment="positive", weight=1.0, confidence=1.0)])),
                  cache)
    set_active_ontology("test", cache)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="Microsoft", price=1, change_pct=0, score=60,
                   direction="buy", net=0.5, base_score=60.0, base_net=0.5)]), cache)
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert out.network is not None and out.network.signed > 0
    assert out.network.influences[0].neighbour == "MSFT"


def test_score_one_skips_reverse_directional_edge(tmp_path, monkeypatch):
    # Edge MSFT -> AAPL (supplier) is directional: AAPL (the target) gets no signal.
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    save_ontology(OntologyVersion(name="test", saved_at="t",
                                  graph=KnowledgeGraph(scope="explore", nodes=["AAPL", "MSFT"], edges=[
                                      GraphEdge(source="MSFT", target="AAPL", type="supplier",
                                                sentiment="positive", weight=1.0, confidence=1.0)])),
                  cache)
    set_active_ontology("test", cache)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="Microsoft", price=1, change_pct=0, score=60,
                   direction="buy", net=0.5, base_score=60.0, base_net=0.5)]), cache)
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert out.network is None
