import json

from app.config.cache import Cache
from app.models.schemas import (
    Fundamentals,
    Indicators,
    MarketMood,
    Mention,
    PriceSummary,
    Settings,
    StockData,
    TruthPost,
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


def test_run_analysis_attaches_truth_signal(tmp_path, monkeypatch):
    settings = Settings()  # truth_signal.enabled defaults True
    settings.providers["anthropic"].api_key = "k"

    captured = {}

    def fake_analyze(stock, provider, model, provider_name):
        captured["mentions"] = stock.trump_mentions
        captured["mood"] = stock.market_mood
        from app.analysis.analyzer import analyze as real
        return real(stock, provider, model, provider_name)

    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(analysis_service, "analyze", fake_analyze)
    monkeypatch.setattr(
        analysis_service.truth_social, "fetch_recent_posts_cached",
        lambda *a, **k: [TruthPost(id="1", created_at="2026-06-04T10:00:00Z",
                                   content="$AAPL great", url="https://t/1")],
    )
    monkeypatch.setattr(
        analysis_service.political, "summarize_market_mood",
        lambda *a, **k: MarketMood(lean="risk_on", confidence=0.6, post_count=1),
    )

    cache = Cache(str(tmp_path / "app.db"))
    analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert captured["mood"].lean == "risk_on"
    assert any(m.matched == "$AAPL" for m in captured["mentions"])


def test_run_analysis_skips_signal_when_disabled(tmp_path, monkeypatch):
    settings = Settings()
    settings.truth_signal.enabled = False
    settings.providers["anthropic"].api_key = "k"

    called = {"fetch": False}

    def must_not_fetch(*a, **k):
        called["fetch"] = True
        return []

    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(analysis_service.truth_social, "fetch_recent_posts_cached", must_not_fetch)

    cache = Cache(str(tmp_path / "app.db"))
    result = analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert result.current_recommendation == "hold"
    assert called["fetch"] is False  # disabled => no fetch
