from app.models.schemas import Settings, Signal, StockData


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
