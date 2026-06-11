import json

from fastapi.testclient import TestClient

from app.analysis.trace_store import AgentTraceStore
from app.api import routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store, get_trace_store
from app.evaluation.store import PredictionStore
from app.llm.base import LLMError
from app.main import app
from app.models.schemas import AnalysisResult, Candle
from tests.test_analyzer import FakeProvider, _stock


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    settings_store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "pred.db"))
    trace_store = AgentTraceStore(str(tmp_path / "trace.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: settings_store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store
    app.dependency_overrides[get_trace_store] = lambda: trace_store
    return TestClient(app), settings_store, pred_store, trace_store


def teardown_function():
    app.dependency_overrides.clear()


def _ready_settings(settings_store, *, watchlist=None, enabled=True):
    """Default settings pass the endpoint pre-flight: evaluation on + an API key set
    (so the env never leaks into the key check)."""
    s = settings_store.load()
    s.evaluation.enabled = enabled
    s.providers[s.active_provider].api_key = "k"
    if watchlist is not None:
        s.watchlist = watchlist
    settings_store.save(s)
    return s


def _stock_with_candles(ticker="AAPL"):
    s = _stock()
    s.ticker = ticker
    s.candles = [
        Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
        Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
    ]
    return s


def _result(ticker="AAPL"):
    return AnalysisResult(
        ticker=ticker, provider="fake", model="m", generated_at="t",
        overall_summary="s", news_analysis="n", sentiment="bullish",
        current_recommendation="buy", confidence=0.7,
    )


def _events(text):
    """Parse an SSE body into [(event_name, payload_dict), ...]."""
    out = []
    for frame in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _seed_prediction(pred_store, ticker, call_date, source):
    pred_store.upsert_prediction(
        ticker=ticker, call_date=call_date, provider="x", model="m",
        recommendation="buy", confidence=0.5, sentiment="bullish",
        entry_price=204.0, source=source,
    )


# ---------------- pre-flight ----------------

def test_watchlist_stream_rejects_unknown_mode(tmp_path):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store)
    resp = client.get("/api/analyze/watchlist/stream?mode=weird")
    assert resp.status_code == 422


def test_watchlist_stream_errors_when_evaluation_disabled(tmp_path):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, enabled=False)
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    assert resp.status_code == 200
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["error"]
    assert "disabled" in evs[0][1]["message"]


def test_watchlist_stream_errors_when_key_missing(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    s = settings_store.load()
    s.evaluation.enabled = True          # key left empty on purpose
    settings_store.save(s)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["error"]
    assert "API key" in evs[0][1]["message"]


def test_watchlist_stream_errors_when_provider_build_fails(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store)

    def boom(settings):
        raise LLMError("provider down")
    monkeypatch.setattr(routes, "build_provider", boom)
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["error"]
    assert "provider down" in evs[0][1]["message"]


def test_watchlist_stream_empty_watchlist_is_a_noop_run(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=[])
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["start", "done"]
    assert evs[0][1]["total"] == 0
    summary = evs[1][1]
    assert (summary["analyzed"], summary["skipped"], summary["failed"]) == (0, 0, 0)


# ---------------- fast mode ----------------

def test_fast_run_analyzes_every_ticker(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL", "MSFT"])
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    calls = []

    def fake_run(t, p, s, c, ps):
        calls.append(t)
        return _result(t)
    monkeypatch.setattr(routes, "run_analysis", fake_run)

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert calls == ["AAPL", "MSFT"]
    names = [n for n, _ in evs]
    assert names == ["start", "ticker", "ticker", "ticker", "ticker", "done"]
    assert evs[0][1]["tickers"] == ["AAPL", "MSFT"]
    done_events = [p for n, p in evs if n == "ticker" and p["status"] == "done"]
    assert [d["ticker"] for d in done_events] == ["AAPL", "MSFT"]
    assert done_events[0]["recommendation"] == "buy"
    summary = evs[-1][1]
    assert (summary["analyzed"], summary["skipped"], summary["failed"]) == (2, 0, 0)


def test_fast_run_skips_ticker_already_recorded_for_last_trading_day(tmp_path, monkeypatch):
    client, settings_store, pred_store, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    _seed_prediction(pred_store, "AAPL", "2026-06-05", "llm_fast")  # = last candle date
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    calls = []
    monkeypatch.setattr(routes, "run_analysis",
                        lambda t, p, s, c, ps: calls.append(t) or _result(t))

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert calls == []                                   # analyzer never invoked
    statuses = [p["status"] for n, p in evs if n == "ticker"]
    assert statuses == ["running", "skipped"]
    assert evs[-1][1]["skipped"] == 1


def test_fast_run_is_not_skipped_by_a_deep_call(tmp_path, monkeypatch):
    """Cross-source independence: an llm_deep row must not suppress the fast run."""
    client, settings_store, pred_store, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    _seed_prediction(pred_store, "AAPL", "2026-06-05", "llm_deep")
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    monkeypatch.setattr(routes, "run_analysis", lambda t, p, s, c, ps: _result(t))

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    assert _events(resp.text)[-1][1]["analyzed"] == 1


def test_fast_run_isolates_a_failing_ticker(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL", "MSFT"])
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))

    def fake_stock(t, p, ip, c):
        if t == "AAPL":
            raise ValueError("boom")
        return _stock_with_candles(t)
    monkeypatch.setattr(routes, "get_stock_data", fake_stock)
    monkeypatch.setattr(routes, "run_analysis", lambda t, p, s, c, ps: _result(t))

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    by_status = {p["ticker"]: p["status"] for n, p in evs
                 if n == "ticker" and p["status"] != "running"}
    assert by_status == {"AAPL": "failed", "MSFT": "done"}
    failed = [p for n, p in evs if n == "ticker" and p["status"] == "failed"][0]
    assert "boom" in failed["error"]
    summary = evs[-1][1]
    assert (summary["analyzed"], summary["skipped"], summary["failed"]) == (1, 0, 1)
