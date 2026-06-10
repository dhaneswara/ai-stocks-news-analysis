import json

from fastapi.testclient import TestClient

from app.analysis.trace_store import AgentTraceStore
from app.api import routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store, get_trace_store
from app.evaluation import signals
from app.evaluation.store import PredictionStore
from app.main import app
from app.models.schemas import Candle, StockScore
from tests.test_analyzer import VALID_PAYLOAD, FakeProvider, _stock


def _stock_with_candles():
    s = _stock()
    s.candles = [
        Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
        Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
    ]
    return s


def _fake_score():
    return StockScore(ticker="AAPL", name="Apple", sector="", price=204.0, change_pct=0.5,
                      score=70.0, direction="buy", net=0.3, base_net=0.3, base_score=70.0,
                      as_of="t")


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    settings_store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "pred.db"))
    trace_store = AgentTraceStore(str(tmp_path / "trace.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: settings_store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store
    app.dependency_overrides[get_trace_store] = lambda: trace_store
    return TestClient(app), pred_store, trace_store


def teardown_function():
    app.dependency_overrides.clear()


def test_deep_stream_emits_steps_and_final(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context", lambda t, p, s, c, prov: _stock())
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider([f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}']),
    )
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: step" in resp.text
    assert "event: final" in resp.text
    assert '"current_recommendation":"buy"' in resp.text


def test_deep_stream_404_when_no_price_data(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path)

    def boom(*a, **k):
        raise ValueError("No price history for ticker 'ZZZZ'")
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "gather_stock_context", boom)
    resp = client.get("/api/analyze/ZZZZ/deep/stream")
    assert resp.status_code == 404


def test_deep_stream_emits_error_event_when_provider_fails(tmp_path, monkeypatch):
    from app.llm.base import LLMError

    class _Raising:
        name = "raise"

        def complete(self, system, user, json_mode=True, stop=None):
            raise LLMError("provider down")

    client, _, _ = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context", lambda t, p, s, c, prov: _stock())
    monkeypatch.setattr(routes, "build_provider", lambda settings: _Raising())
    resp = client.get("/api/analyze/AAPL/deep/stream")
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "provider down" in resp.text


def test_deep_final_records_llm_deep_pair_and_trace(tmp_path, monkeypatch):
    client, pred_store, trace_store = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context",
                        lambda t, p, s, c, prov: _stock_with_candles())
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider([f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}']),
    )
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _fake_score())
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    deep = pred_store.get_prediction("AAPL", "2026-06-05", "llm_deep")
    assert deep is not None and deep.recommendation == "buy" and deep.entry_price == 204.0
    assert pred_store.get_prediction("AAPL", "2026-06-05", "technical") is not None
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_fast") is None
    traces = trace_store.recent("AAPL")
    assert len(traces) == 1 and '"fell_back":false' in traces[0]


def test_deep_fallback_records_as_llm_fast(tmp_path, monkeypatch):
    client, pred_store, trace_store = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context",
                        lambda t, p, s, c, prov: _stock_with_candles())
    # Two protocol-breaking turns exhaust the nudge -> agent fails -> single-shot fallback
    # consumes the third output as plain JSON.
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider(["nonsense", "still nonsense", json.dumps(VALID_PAYLOAD)]),
    )
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _fake_score())
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_fast") is not None
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_deep") is None
    assert '"fell_back":true' in trace_store.recent("AAPL")[0]


def test_get_traces_returns_recent(tmp_path):
    client, _, trace_store = _client(tmp_path)
    trace_store.upsert(ticker="AAPL", call_date="2026-06-05", provider="anthropic", model="m",
                       trace_json='{"ticker":"AAPL","provider":"anthropic","model":"m",'
                                  '"started_at":"t"}')
    resp = client.get("/api/traces/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1 and body[0]["ticker"] == "AAPL"


def test_deep_disabled_evaluation_still_persists_trace(tmp_path, monkeypatch):
    client, pred_store, trace_store = _client(tmp_path)
    # Flip evaluation off in the overridden settings store.
    from app.deps import get_settings_store as _gss
    settings_store = app.dependency_overrides[_gss]()
    s = settings_store.load()
    s.evaluation.enabled = False
    settings_store.save(s)

    monkeypatch.setattr(routes, "gather_stock_context",
                        lambda t, p, s, c, prov: _stock_with_candles())
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider([f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}']),
    )
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    assert pred_store.all_predictions() == []          # recording gated off
    assert len(trace_store.recent("AAPL")) == 1        # trace is observability — always kept
