import json

import pandas as pd
from fastapi.testclient import TestClient

from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store
from app.evaluation.store import PredictionStore
from app.main import app
from app.services import analysis_service, stock_service


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "predictions.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store
    return TestClient(app), store


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


def teardown_function():
    app.dependency_overrides.clear()


def test_get_stock(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple Inc."})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    client, _ = _client(tmp_path)

    resp = client.get("/api/stock/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert len(body["candles"]) == 60


def test_get_stock_bad_ticker_404(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: pd.DataFrame())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    client, _ = _client(tmp_path)
    assert client.get("/api/stock/NOPE").status_code == 404


def test_settings_put_masks_keys_and_persists(tmp_path):
    client, store = _client(tmp_path)
    payload = client.get("/api/settings").json()
    payload["active_provider"] = "openai"
    payload["providers"]["openai"]["api_key"] = "sk-secret"

    resp = client.put("/api/settings", json=payload)
    assert resp.status_code == 200
    assert resp.json()["providers"]["openai"]["api_key"] == "****"
    # Persisted real key is retrievable from the store directly.
    assert store.load().providers["openai"].api_key == "sk-secret"


def test_settings_put_keeps_existing_key_when_masked(tmp_path):
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["openai"].api_key = "sk-real"
    store.save(s)

    payload = client.get("/api/settings").json()  # openai key comes back as "****"
    payload["active_provider"] = "openai"
    client.put("/api/settings", json=payload)
    assert store.load().providers["openai"].api_key == "sk-real"


def test_analyze_missing_key_returns_502(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple"})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    client, store = _client(tmp_path)
    # default active_provider=anthropic with empty key -> 502
    assert client.post("/api/analyze/AAPL").status_code == 502


def test_analyze_success(tmp_path, monkeypatch):
    payload = {
        "overall_summary": "ok",
        "news_analysis": "ok",
        "sentiment": "neutral",
        "current_recommendation": "hold",
        "confidence": 0.5,
        "signals": [],
        "risks": [],
    }

    class FakeProvider:
        name = "fake"

        def complete(self, system, user):
            return json.dumps(payload)

    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple"})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())

    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.post("/api/analyze/AAPL")
    assert resp.status_code == 200
    assert resp.json()["current_recommendation"] == "hold"


def test_list_providers(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert ids == {"anthropic", "openai", "gemini", "ollama", "deepseek"}


from app.api import routes as api_routes


def test_chat_stream_emits_steps_then_final(tmp_path, monkeypatch):
    # Fake provider: one tool call (watchlist), then a markdown final answer.
    outputs = ['Thought: check\nAction: watchlist({})', "Thought: done\nFinal Answer: **Done.**"]

    class _FakeProvider:
        name = "fake"

        def complete(self, system, user, json_mode=True, stop=None):
            return outputs.pop(0)

        def list_models(self):
            return []

    monkeypatch.setattr(api_routes, "build_provider", lambda settings: _FakeProvider())
    client, _ = _client(tmp_path)

    resp = client.post("/api/chat/stream",
                       json={"messages": [{"role": "user", "content": "What's in my watchlist?"}]})
    assert resp.status_code == 200
    body = resp.text
    assert "event: step" in body
    assert "event: final" in body
    assert "Done." in body


def test_chat_stream_rejects_empty_messages(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/chat/stream", json={"messages": []})
    assert resp.status_code == 422


def test_market_tiingo_test_no_key(tmp_path, monkeypatch):
    import app.api.routes as routes
    monkeypatch.setattr(routes, "_tiingo_key", lambda: "")
    client, _ = _client(tmp_path)
    r = client.post("/api/market/tiingo/test")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "No Tiingo API key configured"}


def test_market_tiingo_test_passes_through(tmp_path, monkeypatch):
    import app.api.routes as routes
    monkeypatch.setattr(routes, "_tiingo_key", lambda: "k")
    monkeypatch.setattr(routes, "tiingo_test", lambda key: (True, "Connected"))
    client, _ = _client(tmp_path)
    r = client.post("/api/market/tiingo/test")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "Connected"}


def test_market_tiingo_test_never_500_on_resolver_error(tmp_path, monkeypatch):
    import app.api.routes as routes

    def boom():
        raise RuntimeError("settings store down")

    monkeypatch.setattr(routes, "_tiingo_key", boom)
    client, _ = _client(tmp_path)
    r = client.post("/api/market/tiingo/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "settings store down" in body["message"]
