import pytest

from app.config.cache import Cache
from app.evaluation import service
from app.evaluation.store import PredictionStore
from app.models.schemas import (
    Fundamentals,
    Indicators,
    NewsItem,
    PriceSummary,
    Settings,
    StockData,
)


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return "The call missed an earnings surprise that reversed the trend."


def _seed(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="sell", confidence=0.9, sentiment="bearish",
                            entry_price=100.0)
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 105.0, 5.0, 0, 0.0)
    return store


def _stock():
    return StockData(
        ticker="AAPL", company_name="Apple Inc.", as_of="t",
        price=PriceSummary(current=105.0, change=0.0, change_pct=0.0),
        candles=[], fundamentals=Fundamentals(), indicators=Indicators(),
        news=[NewsItem(title="Apple beats earnings")],
    )


def test_explain_returns_and_caches(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    cache = Cache(str(tmp_path / "c.db"))
    fake = FakeProvider()
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(service, "build_provider", lambda s: fake)

    text = service.explain_prediction("AAPL", "2026-06-01", Settings(), cache, store)
    assert "earnings" in text and fake.calls == 1

    # Second call is served from cache (provider not invoked again).
    again = service.explain_prediction("AAPL", "2026-06-01", Settings(), cache, store)
    assert again == text and fake.calls == 1


def test_explain_missing_prediction_raises(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    cache = Cache(str(tmp_path / "c.db"))
    with pytest.raises(ValueError):
        service.explain_prediction("ZZZ", "2026-06-01", Settings(), cache, store)


def test_explain_survives_news_fetch_failure(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    cache = Cache(str(tmp_path / "c.db"))
    fake = FakeProvider()

    def boom(*a, **k):
        raise RuntimeError("no data")

    monkeypatch.setattr(service, "get_stock_data", boom)
    monkeypatch.setattr(service, "build_provider", lambda s: fake)
    text = service.explain_prediction("AAPL", "2026-06-01", Settings(), cache, store)
    assert text and fake.calls == 1
