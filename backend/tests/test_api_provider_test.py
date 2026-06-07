from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_settings_store
from app.main import app


def _client(tmp_path):
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    store = SettingsStore(str(tmp_path / "s.db"))
    app.dependency_overrides[get_settings_store] = lambda: store
    return TestClient(app), store


def teardown_function():
    app.dependency_overrides.clear()


def test_provider_test_ok(tmp_path, monkeypatch):
    class FakeProvider:
        name = "anthropic"

        def __init__(self, cfg):
            pass

        def complete(self, system, user):
            return "pong"

    monkeypatch.setattr(routes, "build_provider", lambda s: FakeProvider(None))
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.post("/api/providers/anthropic/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_provider_test_failure_reports_message(tmp_path, monkeypatch):
    from app.llm.base import LLMError

    def boom(_s):
        raise LLMError("bad key")

    monkeypatch.setattr(routes, "build_provider", boom)
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.post("/api/providers/anthropic/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "bad key" in resp.json()["message"]


def test_providers_lists_deepseek(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    by_id = {p["id"]: p for p in resp.json()}
    assert "deepseek" in by_id
    assert by_id["deepseek"]["label"] == "DeepSeek"
    assert by_id["deepseek"]["default_model"] == "deepseek-chat"


def test_list_models_endpoint_ok(tmp_path, monkeypatch):
    class FakeProvider:
        name = "anthropic"

        def __init__(self, cfg):
            pass

        def list_models(self):
            return ["m-a", "m-b"]

    monkeypatch.setattr(routes, "build_provider", lambda s: FakeProvider(None))
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.get("/api/providers/anthropic/models")
    assert resp.status_code == 200
    assert resp.json()["models"] == ["m-a", "m-b"]
    assert resp.json()["error"] == ""


def test_list_models_endpoint_reports_error(tmp_path, monkeypatch):
    from app.llm.base import LLMError

    def boom(_s):
        raise LLMError("no key")

    monkeypatch.setattr(routes, "build_provider", boom)
    client, store = _client(tmp_path)

    resp = client.get("/api/providers/anthropic/models")
    assert resp.status_code == 200
    assert resp.json()["models"] == []
    assert "no key" in resp.json()["error"]


def test_list_models_unknown_provider_404(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/providers/bogus/models")
    assert resp.status_code == 404
