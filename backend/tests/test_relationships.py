from app.analysis.relationships import TickerResolver
from app.models.schemas import UniverseEntry

UNIVERSE = [
    UniverseEntry(ticker="AAPL", name="Apple Inc.", sector="Information Technology"),
    UniverseEntry(ticker="GOOGL", name="Alphabet Inc.", sector="Communication Services"),
    UniverseEntry(ticker="TSM", name="Taiwan Semiconductor Manufacturing", sector="Information Technology"),
]

RESOLVER = TickerResolver(UNIVERSE)


def test_resolve_by_exact_ticker():
    r = TickerResolver(UNIVERSE)
    assert r.resolve("whatever", "aapl") == "AAPL"


def test_resolve_by_normalized_name():
    r = TickerResolver(UNIVERSE)
    assert r.resolve("Apple", None) == "AAPL"           # suffix-stripped match
    assert r.resolve("Alphabet Inc.", None) == "GOOGL"


def test_resolve_drops_unknown():
    r = TickerResolver(UNIVERSE)
    assert r.resolve("Some Private Startup", "PRIV") is None


import json as _json
from app.analysis.relationships import extract_relationships
from app.config.cache import Cache
from app.models.schemas import NewsItem, NetworkConfig, StockData, PriceSummary, Fundamentals, Indicators


class FakeProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def _stock_with_news(*titles):
    return StockData(
        ticker="AAPL", company_name="Apple Inc.", as_of="t",
        price=PriceSummary(current=1, change=0, change_pct=0),
        candles=[], fundamentals=Fundamentals(), indicators=Indicators(),
        news=[NewsItem(title=t, url=f"https://n/{i}") for i, t in enumerate(titles)],
    )


EDGES_JSON = _json.dumps({"edges": [
    {"target_name": "Taiwan Semiconductor", "target_ticker": "TSM", "type": "supplier",
     "sentiment": "negative", "weight": 0.8, "confidence": 0.9, "evidence": "TSMC warns on supply"},
    {"target_name": "Unknown Private Co", "target_ticker": "PRIV", "type": "partner",
     "sentiment": "positive", "weight": 0.5, "confidence": 0.9, "evidence": "x"},
    {"target_name": "Alphabet", "target_ticker": "GOOGL", "type": "partner",
     "sentiment": "positive", "weight": 0.5, "confidence": 0.1, "evidence": "low conf"},
]})


def test_extract_parses_filters_and_grounds(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    edges = extract_relationships(
        _stock_with_news("TSMC warns on supply"), RESOLVER, FakeProvider([EDGES_JSON]),
        "m", "fake", cache, NetworkConfig())
    targets = {e.target for e in edges}
    assert targets == {"TSM"}             # PRIV dropped (unresolved), GOOGL dropped (low conf)
    assert edges[0].source == "AAPL" and edges[0].type == "supplier"


def test_extract_is_cached_per_day(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    p = FakeProvider([EDGES_JSON])  # only one output
    a = extract_relationships(_stock_with_news("x"), RESOLVER, p, "m", "fake", cache, NetworkConfig())
    b = extract_relationships(_stock_with_news("x"), RESOLVER, p, "m", "fake", cache, NetworkConfig())
    assert p.calls == 1 and len(a) == len(b)


def test_extract_degrades_to_empty_on_bad_json(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    edges = extract_relationships(_stock_with_news("x"), RESOLVER, FakeProvider(["not json"]),
                                  "m", "fake", cache, NetworkConfig())
    assert edges == []
