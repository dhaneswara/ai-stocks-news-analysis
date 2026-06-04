from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.main import app
from app.models.schemas import MarketMood, Settings, TruthPost


def _client_with(store, cache):
    app.dependency_overrides[routes.get_settings_store] = lambda: store
    app.dependency_overrides[routes.get_cache] = lambda: cache
    return TestClient(app)


def test_truth_mood_disabled(tmp_path):
    class Store:
        def load(self):
            s = Settings()
            s.truth_signal.enabled = False
            return s

    client = _client_with(Store(), Cache(str(tmp_path / "c.db")))
    body = client.get("/api/truth/mood").json()
    app.dependency_overrides.clear()
    assert body == {"enabled": False, "post_count": 0, "mood": None}


def test_truth_mood_returns_mood(tmp_path, monkeypatch):
    class Store:
        def load(self):
            s = Settings()
            s.providers["anthropic"].api_key = "k"
            return s

    monkeypatch.setattr(
        routes.truth_social, "fetch_recent_posts_cached",
        lambda *a, **k: [TruthPost(id="1", created_at="2026-06-04T10:00:00Z", content="x", url="")],
    )
    monkeypatch.setattr(routes, "build_provider", lambda s: object())
    monkeypatch.setattr(
        routes.political, "summarize_market_mood",
        lambda *a, **k: MarketMood(lean="risk_off", confidence=0.7, post_count=1),
    )

    client = _client_with(Store(), Cache(str(tmp_path / "c.db")))
    body = client.get("/api/truth/mood").json()
    app.dependency_overrides.clear()
    assert body["enabled"] is True
    assert body["post_count"] == 1
    assert body["mood"]["lean"] == "risk_off"
