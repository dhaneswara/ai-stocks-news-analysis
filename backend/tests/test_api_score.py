import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.config.cache import Cache
from app.deps import get_cache
from app.main import app
from app.models.schemas import StockScore


@pytest.fixture
def client(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    try:
        yield TestClient(app), cache
    finally:
        app.dependency_overrides.pop(get_cache, None)


def test_get_score_ok(client, monkeypatch):
    tc, _ = client
    monkeypatch.setattr(routes, "score_one", lambda ticker, settings, cache: StockScore(
        ticker=ticker, name="Apple", price=1, change_pct=0, score=72.0, direction="buy", net=0.3))
    r = tc.get("/api/score/aapl")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL" and body["score"] == 72.0 and body["direction"] == "buy"


def test_get_score_404_on_bad_ticker(client, monkeypatch):
    tc, _ = client

    def boom(ticker, settings, cache):
        raise ValueError("No price history for ZZZZ")

    monkeypatch.setattr(routes, "score_one", boom)
    r = tc.get("/api/score/ZZZZ")
    assert r.status_code == 404 and "No price history" in r.json()["detail"]
