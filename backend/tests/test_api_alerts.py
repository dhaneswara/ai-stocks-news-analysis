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


def test_alerts_test_requires_telegram_config(tmp_path):
    client, store = _client(tmp_path)
    s = store.load()
    s.alerts.channel = "telegram"  # no token/chat
    store.save(s)
    resp = client.post("/api/alerts/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_alerts_test_ok(tmp_path, monkeypatch):
    class FakeNotifier:
        def send(self, title, body):
            return None

    monkeypatch.setattr(routes, "build_notifier", lambda cfg, dry_run=False: FakeNotifier())
    client, store = _client(tmp_path)
    s = store.load()
    s.alerts.channel = "telegram"
    s.alerts.telegram_bot_token = "t"
    s.alerts.telegram_chat_id = "c"
    store.save(s)
    resp = client.post("/api/alerts/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_alerts_test_reports_send_failure(tmp_path, monkeypatch):
    class BoomNotifier:
        def send(self, title, body):
            raise RuntimeError("bad token")

    monkeypatch.setattr(routes, "build_notifier", lambda cfg, dry_run=False: BoomNotifier())
    client, store = _client(tmp_path)
    s = store.load()
    s.alerts.channel = "telegram"
    s.alerts.telegram_bot_token = "t"
    s.alerts.telegram_chat_id = "c"
    store.save(s)
    resp = client.post("/api/alerts/test")
    assert resp.json()["ok"] is False
    assert "bad token" in resp.json()["message"]
