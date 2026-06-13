import pandas as pd

from app.data.market import build_candles, build_fundamentals, build_price, company_name, friendly_exchange


def _df():
    idx = pd.date_range("2026-05-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [10.5, 11.5, 12.5],
            "Low": [9.5, 10.5, 11.5],
            "Close": [10.2, 11.0, 12.0],
            "Volume": [100, 200, 300],
        },
        index=idx,
    )


def test_build_candles():
    candles = build_candles(_df())
    assert len(candles) == 3
    assert candles[0].time == "2026-05-01"
    assert candles[-1].close == 12.0


def test_build_price_change():
    price = build_price(_df())
    assert price.current == 12.0
    assert price.change == 1.0  # 12.0 - 11.0
    assert round(price.change_pct, 2) == 9.09


def test_build_fundamentals_uses_get():
    info = {"marketCap": 1000, "trailingPE": 25.0, "fiftyTwoWeekHigh": 15.0}
    f = build_fundamentals(info)
    assert f.market_cap == 1000
    assert f.pe_ratio == 25.0
    assert f.week52_high == 15.0
    assert f.eps is None


def test_company_name_fallback():
    assert company_name({"longName": "Apple Inc."}, "AAPL") == "Apple Inc."
    assert company_name({}, "AAPL") == "AAPL"


def test_friendly_exchange_maps_known_codes():
    assert friendly_exchange({"exchange": "NMS"}) == "NASDAQ"
    assert friendly_exchange({"exchange": "NYQ"}) == "NYSE"


def test_friendly_exchange_falls_back_to_full_name_then_code():
    assert friendly_exchange({"exchange": "XYZ", "fullExchangeName": "Some Exchange"}) == "Some Exchange"
    assert friendly_exchange({"exchange": "XYZ"}) == "XYZ"
    assert friendly_exchange({}) == ""


def test_fetch_close_series_returns_ordered_pairs(monkeypatch):
    import pandas as pd
    from app.data import market

    df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
    )
    monkeypatch.setattr(market, "fetch_history", lambda ticker, period="2y": df)

    series = market.fetch_close_series("AAPL", "1y")
    assert series == [("2026-06-01", 100.0), ("2026-06-02", 101.0), ("2026-06-03", 102.0)]


def test_drop_incomplete_removes_nan_ohlcv_rows():
    from app.data.market import drop_incomplete

    idx = pd.date_range("2026-05-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [10.5, 11.5, 12.5],
            "Low": [9.5, 10.5, 11.5],
            "Close": [10.2, 11.0, float("nan")],   # current day's bar not closed yet
            "Volume": [100.0, 200.0, 300.0],
        },
        index=idx,
    )
    clean = drop_incomplete(df)
    assert len(clean) == 2
    assert clean["Close"].iloc[-1] == 11.0


def test_nan_trailing_bar_does_not_poison_cache_roundtrip():
    """A NaN bar must not reach StockData: NaN serialises to JSON null and then fails
    to re-validate from cache (the 'Could not load MSFT' bug)."""
    from app.data.market import build_candles, build_price, drop_incomplete
    from app.models.schemas import Fundamentals, Indicators, StockData

    idx = pd.date_range("2026-05-01", periods=3, freq="D")
    df = drop_incomplete(
        pd.DataFrame(
            {
                "Open": [10.0, 11.0, 12.0],
                "High": [10.5, 11.5, 12.5],
                "Low": [9.5, 10.5, 11.5],
                "Close": [10.2, 11.0, float("nan")],
                "Volume": [100.0, 200.0, 300.0],
            },
            index=idx,
        )
    )
    sd = StockData(
        ticker="MSFT", company_name="Microsoft", as_of="t",
        price=build_price(df), candles=build_candles(df),
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )
    StockData.model_validate_json(sd.model_dump_json())   # must not raise
    assert sd.price.current == 11.0
