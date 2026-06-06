import app.network.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Fundamentals, GraphEdge, Indicators, PriceSummary, ScreenBoard, Settings,
    StockData, StockScore, UniverseEntry,
)


def _stock(ticker):
    return StockData(ticker=ticker, company_name=f"{ticker} Inc.", as_of="t",
                     price=PriceSummary(current=1, change=0, change_pct=0),
                     candles=[], fundamentals=Fundamentals(), indicators=Indicators())


def _wire(monkeypatch, edges_for):
    monkeypatch.setattr(service, "build_provider", lambda s: object())
    monkeypatch.setattr(service, "load_universe", lambda: [
        UniverseEntry(ticker="AAPL", name="Apple", sector="Tech"),
        UniverseEntry(ticker="TSM", name="Taiwan Semi", sector="Tech")])
    monkeypatch.setattr(service, "get_stock_data", lambda t, *a, **k: _stock(t))
    monkeypatch.setattr(service, "extract_relationships",
                        lambda stock, *a, **k: edges_for.get(stock.ticker, []))


def test_focus_is_watchlist_plus_top_n(tmp_path, monkeypatch):
    edges = {"AAPL": [GraphEdge(source="AAPL", target="TSM", type="supplier")]}
    _wire(monkeypatch, edges)
    board = ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="MS", price=1, change_pct=0, score=90, direction="buy")])
    monkeypatch.setattr(service, "load_snapshot", lambda cache, scope="all": board)
    settings = Settings(); settings.watchlist = ["AAPL"]; settings.network.focus_top_n = 5
    g = service.build_graph(None, settings, Cache(str(tmp_path / "c.db")))
    assert set(g.nodes) >= {"AAPL", "TSM"} and g.built == 2  # AAPL (watchlist) + MSFT (top-n)
    assert any(e.target == "TSM" for e in g.edges)


def test_skips_failures(tmp_path, monkeypatch):
    _wire(monkeypatch, {})
    monkeypatch.setattr(service, "load_snapshot", lambda cache, scope="all": None)

    def boom(t, *a, **k):
        if t == "TSM":
            raise ValueError("no data")
        return _stock(t)

    monkeypatch.setattr(service, "get_stock_data", boom)
    settings = Settings(); settings.watchlist = ["AAPL", "TSM"]
    g = service.build_graph(None, settings, Cache(str(tmp_path / "c.db")))
    assert g.built == 1 and g.skipped == 1


def test_disabled_returns_empty(tmp_path, monkeypatch):
    _wire(monkeypatch, {})
    monkeypatch.setattr(service, "load_snapshot", lambda cache, scope="all": None)
    settings = Settings(); settings.network.enabled = False
    g = service.build_graph(None, settings, Cache(str(tmp_path / "c.db")))
    assert g.edges == [] and g.built == 0
