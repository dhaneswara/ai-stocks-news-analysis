from app.models.schemas import Settings, Signal, StockData, StockScore, UniverseEntry


def test_settings_defaults():
    s = Settings()
    assert s.active_provider == "anthropic"
    assert set(s.providers) == {"anthropic", "openai", "gemini", "ollama", "deepseek"}
    assert s.providers["ollama"].base_url == "http://localhost:11434"
    assert s.indicator_params.sma_windows == [50, 200]


def test_signal_round_trip():
    sig = Signal(date="2026-04-15", action="buy", price=10.0, confidence=0.7, reasoning="x")
    assert sig.model_dump()["action"] == "buy"


def test_stockdata_requires_price():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StockData(ticker="AAPL", company_name="Apple", as_of="2026-06-02")  # missing price


def test_stockscore_exchange_and_membership_default():
    s = StockScore(ticker="X", name="X", price=1.0, change_pct=0.0, score=1.0, direction="hold")
    assert s.exchange == "" and s.in_sp500 is True  # defaults keep old cached boards valid


def test_universe_entry_optional_exchange():
    assert UniverseEntry(ticker="X", name="X", sector="Tech").exchange == ""


def test_stockdata_exchange_and_sector_default():
    d = StockData(
        ticker="X", company_name="X", as_of="t",
        price={"current": 1, "change": 0, "change_pct": 0},
        candles=[], fundamentals={}, indicators={},
    )
    assert d.exchange == "" and d.sector == ""
