import pandas as pd

from app.config.cache import Cache
from app.models.schemas import IndicatorParams
from app.services import stock_service


def _df():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    return pd.DataFrame(
        {
            "Open": range(60),
            "High": [v + 1 for v in range(60)],
            "Low": [v - 1 for v in range(60)],
            "Close": range(60),
            "Volume": [1000] * 60,
        },
        index=idx,
    ).astype("float64")


def test_get_stock_data_composes_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple Inc."})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])

    cache = Cache(str(tmp_path / "app.db"))
    data = stock_service.get_stock_data("AAPL", "2y", IndicatorParams(), cache)

    assert data.ticker == "AAPL"
    assert data.company_name == "Apple Inc."
    assert len(data.candles) == 60
    assert len(data.indicators.sma50) > 0
    # Second call should hit cache even if fetch now raises.
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: (_ for _ in ()).throw(RuntimeError("no net")))
    again = stock_service.get_stock_data("AAPL", "2y", IndicatorParams(), cache)
    assert again.ticker == "AAPL"


def test_get_stock_data_empty_history_raises(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: pd.DataFrame())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    cache = Cache(str(tmp_path / "app.db"))
    with pytest.raises(ValueError):
        stock_service.get_stock_data("BADTICKER", "2y", IndicatorParams(), cache)


def test_get_stock_data_refetches_when_cache_corrupt(tmp_path, monkeypatch):
    """A poisoned cache entry (NaN prices serialized to JSON null) must be discarded
    and re-fetched, not raise a validation error on every load."""
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Microsoft"})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])

    cache = Cache(str(tmp_path / "app.db"))
    cache.set(
        "stock:MSFT:1y",
        '{"ticker":"MSFT","company_name":"x","as_of":"t",'
        '"price":{"current":null,"change":null,"change_pct":null,"currency":"USD"},'
        '"candles":[],"fundamentals":{},"indicators":{},"news":[]}',
        600,
    )
    data = stock_service.get_stock_data("MSFT", "1y", IndicatorParams(), cache)
    assert data.ticker == "MSFT"
    assert data.price.current == 59.0  # _df() last Close = range(60)[-1]
