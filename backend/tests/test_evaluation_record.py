from app.config.cache import Cache
from app.evaluation.service import record_prediction
from app.evaluation.store import PredictionStore
from app.models.schemas import (
    AnalysisResult,
    Candle,
    Fundamentals,
    Indicators,
    PriceSummary,
    Settings,
    StockData,
)
from app.services import analysis_service


def _stock_with_candles():
    return StockData(
        ticker="AAPL", company_name="Apple Inc.", as_of="2026-06-07T00:00:00Z",
        price=PriceSummary(current=205.0, change=1.0, change_pct=0.5),
        candles=[
            Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
            Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
        ],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def _result():
    return AnalysisResult(
        ticker="AAPL", provider="anthropic", model="m", generated_at="t",
        overall_summary="", news_analysis="", sentiment="bullish",
        current_recommendation="buy", confidence=0.8,
    )


def test_record_prediction_uses_last_candle(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    record_prediction(_stock_with_candles(), _result(), store)
    row = store.get_prediction("AAPL", "2026-06-05")
    assert row is not None
    assert row.call_date == "2026-06-05" and row.entry_price == 204.0
    assert row.recommendation == "buy" and row.confidence == 0.8


def test_record_prediction_no_candles_is_noop(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    stock = _stock_with_candles()
    stock.candles = []
    record_prediction(stock, _result(), store)
    assert store.all_predictions() == []


def test_run_analysis_records_when_store_passed(tmp_path, monkeypatch):
    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())

    class FakeProvider:
        name = "fake"
        def complete(self, system, user):
            import json
            return json.dumps({"overall_summary": "ok", "news_analysis": "ok",
                               "sentiment": "bullish", "current_recommendation": "buy",
                               "confidence": 0.8, "signals": [], "risks": []})

    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(analysis_service, "record_deterministic_pair", lambda *a, **k: None)
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))

    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)
    assert store.get_prediction("AAPL", "2026-06-05") is not None


def test_run_analysis_skips_recording_when_disabled(tmp_path, monkeypatch):
    settings = Settings()
    settings.evaluation.enabled = False
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())

    class FakeProvider:
        name = "fake"
        def complete(self, system, user):
            import json
            return json.dumps({"overall_summary": "ok", "news_analysis": "ok",
                               "sentiment": "bullish", "current_recommendation": "buy",
                               "confidence": 0.8, "signals": [], "risks": []})

    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(analysis_service, "record_deterministic_pair", lambda *a, **k: None)
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))

    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)
    assert store.all_predictions() == []


def test_run_analysis_also_records_deterministic_pair(tmp_path, monkeypatch):
    import json as _json
    from app.evaluation import signals
    from app.models.schemas import StockScore

    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())

    class FakeProvider:
        name = "fake"
        def complete(self, system, user):
            return _json.dumps({"overall_summary": "ok", "news_analysis": "ok",
                                "sentiment": "bullish", "current_recommendation": "buy",
                                "confidence": 0.8, "signals": [], "risks": []})

    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(
        signals, "score_one",
        lambda t, s, c: StockScore(ticker="AAPL", name="Apple", sector="", price=204.0,
                                   change_pct=0.5, score=70.0, direction="buy", net=0.3,
                                   base_net=0.3, base_score=70.0, as_of="t"))
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)
    assert store.get_prediction("AAPL", "2026-06-05", "llm_fast") is not None
    assert store.get_prediction("AAPL", "2026-06-05", "technical") is not None


def _seed_analysis_cache(cache, settings, ticker="AAPL", period="2y"):
    """Plant a cached result under the exact key run_analysis builds for today."""
    from datetime import date

    cfg = settings.providers[settings.active_provider]
    key = f"analysis:{ticker}:{settings.active_provider}:{cfg.model}:{period}:{date.today().isoformat()}"
    cache.set(key, _result().model_dump_json(), 3600)


def _no_provider(monkeypatch):
    def boom(settings):
        raise AssertionError("provider must not be built on a cache hit")
    monkeypatch.setattr(analysis_service, "build_provider", boom)


def test_run_analysis_cache_hit_records_missing_prediction(tmp_path, monkeypatch):
    # The trap: an analysis cached today whose prediction row is gone (recorded while
    # evaluation was off, or wiped by Clear all results). The cache-hit path must record
    # it — otherwise every same-day re-run serves the cache and the call never lands.
    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())
    pair = {"called": False}
    monkeypatch.setattr(analysis_service, "record_deterministic_pair",
                        lambda *a, **k: pair.__setitem__("called", True))
    _no_provider(monkeypatch)
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    _seed_analysis_cache(cache, settings)

    result = analysis_service.run_analysis("AAPL", "2y", settings, cache, store)

    assert result.current_recommendation == "buy"  # served from cache (provider untouched)
    row = store.get_prediction("AAPL", "2026-06-05")
    assert row is not None and row.entry_price == 204.0 and row.confidence == 0.8
    assert pair["called"] is True  # the technical/network pair rides along, as on fresh path


def test_run_analysis_cache_hit_keeps_existing_prediction(tmp_path, monkeypatch):
    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())
    pair = {"called": False}
    monkeypatch.setattr(analysis_service, "record_deterministic_pair",
                        lambda *a, **k: pair.__setitem__("called", True))
    _no_provider(monkeypatch)
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    _seed_analysis_cache(cache, settings)
    store.upsert_prediction(  # already recorded earlier today, with different values
        ticker="AAPL", call_date="2026-06-05", provider="x", model="m",
        recommendation="sell", confidence=0.5, sentiment="bearish",
        entry_price=204.0, source="llm_fast",
    )

    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)

    row = store.get_prediction("AAPL", "2026-06-05")
    assert row.recommendation == "sell" and row.confidence == 0.5  # not overwritten
    assert pair["called"] is False


def test_run_analysis_cache_hit_respects_disabled_gate(tmp_path, monkeypatch):
    settings = Settings()
    settings.evaluation.enabled = False
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())
    _no_provider(monkeypatch)
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    _seed_analysis_cache(cache, settings)

    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)
    assert store.all_predictions() == []


def test_run_analysis_cache_hit_without_store_is_unchanged(tmp_path, monkeypatch):
    # The alerts path passes no store — a cache hit must stay a plain cached read.
    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())
    _no_provider(monkeypatch)
    cache = Cache(str(tmp_path / "c.db"))
    _seed_analysis_cache(cache, settings)

    result = analysis_service.run_analysis("AAPL", "2y", settings, cache)
    assert result.current_recommendation == "buy"


def test_run_analysis_disabled_gates_pair_recording_too(tmp_path, monkeypatch):
    import json as _json

    settings = Settings()
    settings.evaluation.enabled = False
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())

    class FakeProvider:
        name = "fake"
        def complete(self, system, user):
            return _json.dumps({"overall_summary": "ok", "news_analysis": "ok",
                                "sentiment": "bullish", "current_recommendation": "buy",
                                "confidence": 0.8, "signals": [], "risks": []})

    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    called = {"pair": False}
    monkeypatch.setattr(analysis_service, "record_deterministic_pair",
                        lambda *a, **k: called.__setitem__("pair", True))
    store = PredictionStore(str(tmp_path / "p.db"))
    analysis_service.run_analysis("AAPL", "2y", settings, Cache(str(tmp_path / "c.db")), store)
    assert called["pair"] is False        # the enabled gate covers the pair call as well
    assert store.all_predictions() == []
