from app.analysis.relationships import TickerResolver
from app.models.schemas import UniverseEntry

UNIVERSE = [
    UniverseEntry(ticker="AAPL", name="Apple Inc.", sector="Information Technology"),
    UniverseEntry(ticker="GOOGL", name="Alphabet Inc.", sector="Communication Services"),
    UniverseEntry(ticker="TSM", name="Taiwan Semiconductor Manufacturing", sector="Information Technology"),
]


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
