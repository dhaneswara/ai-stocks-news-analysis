"""Tests for GET /api/news/providers and GET /api/news/test."""
import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.config.cache import Cache
from app.deps import get_cache
from app.main import app
from app.news.base import NewsError


@pytest.fixture
def client(tmp_path):
    """Isolate news-route tests from the real app.db via a throwaway tmp cache."""
    cache = Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_cache, None)


# ---------------------------------------------------------------------------
# 1. /api/news/providers
# ---------------------------------------------------------------------------

def test_list_news_providers_returns_four_rows(client):
    r = client.get("/api/news/providers")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 4
    google = next(p for p in data if p["id"] == "google")
    assert google["configured"] is True
    assert google["label"] == "Google News"


# ---------------------------------------------------------------------------
# 2. /api/news/test — success path
# ---------------------------------------------------------------------------

def test_test_news_provider_ok(client, monkeypatch):
    """When build_news_provider returns a provider whose search() returns [], expect ok=True."""

    class _FakeProvider:
        def search(self, query, *, limit, recency_days):
            return []

    monkeypatch.setattr(routes, "build_news_provider", lambda settings, provider_id: _FakeProvider())

    r = client.get("/api/news/test?provider=tavily")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["message"] == "Tavily OK"


# ---------------------------------------------------------------------------
# 3. /api/news/test — error path
# ---------------------------------------------------------------------------

def test_test_news_provider_error(client, monkeypatch):
    """When build_news_provider raises NewsError, expect ok=False with the message."""

    def _raise(settings, provider_id):
        raise NewsError("bad key")

    monkeypatch.setattr(routes, "build_news_provider", _raise)

    r = client.get("/api/news/test?provider=exa")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "bad key" in body["message"]
