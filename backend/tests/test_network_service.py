import app.network.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Fundamentals, GraphEdge, Indicators, PriceSummary, Settings,
    StockData,
)


def _stock(ticker):
    return StockData(ticker=ticker, company_name=f"{ticker} Inc.", as_of="t",
                     price=PriceSummary(current=1, change=0, change_pct=0),
                     candles=[], fundamentals=Fundamentals(), indicators=Indicators())


def _wire(monkeypatch, edges_for):
    monkeypatch.setattr(service, "build_provider", lambda s: object())
    monkeypatch.setattr(service, "load_universe", lambda: [])
    monkeypatch.setattr(service, "get_stock_data", lambda t, *a, **k: _stock(t))
    monkeypatch.setattr(service, "extract_relationships",
                        lambda stock, *a, **k: edges_for.get(stock.ticker, []))


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
