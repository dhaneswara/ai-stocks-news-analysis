from fastapi.testclient import TestClient

from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store
from app.evaluation.store import PredictionStore
from app.main import app


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    settings_store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "pred.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: settings_store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store
    return TestClient(app), pred_store


def teardown_function():
    app.dependency_overrides.clear()


def test_signals_endpoint_shape(tmp_path):
    client, store = _client(tmp_path)
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="rules", model="",
                            recommendation="buy", confidence=0.3, sentiment="bullish",
                            entry_price=204.0, source="technical")
    body = client.get("/api/signals/aapl").json()
    assert body["ticker"] == "AAPL"
    assert body["sources"]["technical"]["latest"]["recommendation"] == "buy"
    assert body["sources"]["llm_fast"] is None
    assert body["winner"] is None
    assert set(body["sources"].keys()) == {"llm_fast", "llm_deep", "technical", "network"}
