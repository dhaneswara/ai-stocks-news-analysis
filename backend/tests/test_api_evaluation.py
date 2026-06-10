import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store
from app.evaluation.store import PredictionStore
from app.main import app


@pytest.fixture
def client(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_prediction_store] = lambda: store
    try:
        yield TestClient(app), cache, store
    finally:
        app.dependency_overrides.pop(get_cache, None)
        app.dependency_overrides.pop(get_prediction_store, None)


def test_get_evaluation_empty(client):
    tc, _, _ = client
    r = tc.get("/api/evaluation")
    assert r.status_code == 200 and r.json()["companies"] == []


def test_get_evaluation_runs_lazy_eval(client, monkeypatch):
    tc, _, store = client
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0)
    monkeypatch.setattr(routes, "evaluate_pending",
                        lambda s, settings: store.record_eval("AAPL", "2026-06-01", 1,
                                                              "2026-06-02", 102.0, 2.0, 1, 70.0))
    r = tc.get("/api/evaluation")
    assert r.status_code == 200
    body = r.json()
    assert body["companies"][0]["rollup"]["ticker"] == "AAPL"
    assert body["companies"][0]["calls"][0]["results"][0]["status"] == "final"


def test_explain_endpoint(client, monkeypatch):
    tc, _, store = client
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="sell", confidence=0.9, sentiment="bearish",
                            entry_price=100.0)
    monkeypatch.setattr(routes, "explain_prediction",
                        lambda ticker, call_date, settings, cache, store, source="llm_fast": "because reasons")
    r = tc.post("/api/evaluation/AAPL/2026-06-01/explain")
    assert r.status_code == 200 and r.json()["explanation"] == "because reasons"


def test_explain_missing_is_404(client, monkeypatch):
    tc, _, _ = client

    def boom(*a, **k):
        raise ValueError("nope")

    monkeypatch.setattr(routes, "explain_prediction", boom)
    r = tc.post("/api/evaluation/ZZZ/2026-06-01/explain")
    assert r.status_code == 404


def test_delete_tracked(client):
    tc, _, store = client
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0)
    r = tc.delete("/api/evaluation/AAPL")
    assert r.status_code == 200 and r.json()["deleted"] == 1
    assert store.all_predictions() == []


def test_explain_route_passes_source(tmp_path, monkeypatch):
    captured = {}

    def fake_explain(ticker, call_date, settings, cache, store, source="llm_fast"):
        captured["source"] = source
        return "ok"

    monkeypatch.setattr(routes, "explain_prediction", fake_explain)
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_settings_store] = lambda: SettingsStore(str(tmp_path / "s.db"))
    app.dependency_overrides[get_prediction_store] = lambda: PredictionStore(str(tmp_path / "p.db"))
    try:
        client = TestClient(app)
        resp = client.post("/api/evaluation/AAPL/2026-06-01/explain?source=technical")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert captured["source"] == "technical"


def test_explain_route_rejects_unknown_source():
    client = TestClient(app)
    resp = client.post("/api/evaluation/AAPL/2026-06-01/explain?source=garbage")
    assert resp.status_code == 422
