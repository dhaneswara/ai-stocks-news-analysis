import json

from app.config.cache import Cache
from app.models.schemas import (
    Fundamentals,
    Indicators,
    PriceSummary,
    Settings,
    StockData,
)
from app.services import analysis_service

PAYLOAD = {
    "overall_summary": "ok",
    "news_analysis": "ok",
    "sentiment": "neutral",
    "current_recommendation": "hold",
    "confidence": 0.5,
    "signals": [],
    "risks": [],
}


def _stock():
    return StockData(
        ticker="AAPL",
        company_name="Apple Inc.",
        as_of="2026-06-02",
        price=PriceSummary(current=1.0, change=0.0, change_pct=0.0),
        candles=[],
        fundamentals=Fundamentals(),
        indicators=Indicators(),
        news=[],
    )


class FakeProvider:
    name = "fake"

    def complete(self, system, user):
        return json.dumps(PAYLOAD)


def test_run_analysis_uses_provider_and_caches(tmp_path, monkeypatch):
    settings = Settings()
    settings.active_provider = "anthropic"
    settings.providers["anthropic"].model = "claude-x"
    settings.providers["anthropic"].api_key = "k"  # key-check passes before cache path

    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())

    cache = Cache(str(tmp_path / "app.db"))
    result = analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert result.current_recommendation == "hold"
    assert result.provider == "anthropic"
    assert result.model == "claude-x"

    # Cached: even if provider now blows up, cached value returns.
    def boom(_s):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(analysis_service, "build_provider", boom)
    again = analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert again.current_recommendation == "hold"
