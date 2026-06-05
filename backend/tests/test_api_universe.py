from fastapi.testclient import TestClient

from app.api import routes
from app.main import app


def test_refresh_route_success(monkeypatch):
    monkeypatch.setattr(
        routes.universe, "refresh_universe",
        lambda: {"count": 503, "sectors": {"Energy": 21}, "source": "wiki"},
    )
    body = TestClient(app).post("/api/universe/refresh").json()
    assert body["count"] == 503 and body["sectors"]["Energy"] == 21


def test_refresh_route_returns_502_on_failure(monkeypatch):
    def boom():
        raise ValueError("network down")

    monkeypatch.setattr(routes.universe, "refresh_universe", boom)
    resp = TestClient(app).post("/api/universe/refresh")
    assert resp.status_code == 502
    assert "network down" in resp.json()["detail"]
