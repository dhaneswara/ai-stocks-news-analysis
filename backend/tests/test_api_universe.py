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


def test_add_list_delete_custom_company(tmp_path, monkeypatch):
    from app.config.cache import Cache
    from app.deps import get_cache
    from app.models.schemas import UniverseEntry
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    try:
        monkeypatch.setattr(routes.universe, "resolve_custom_entry",
                            lambda ticker, params, cache: (
                                UniverseEntry(ticker="PRIV", name="Priv", sector="Tech", exchange="NYSE"), 42.5))
        client = TestClient(app)
        r = client.post("/api/universe/custom", json={"ticker": "priv"})
        assert r.status_code == 200
        assert r.json()["entry"]["ticker"] == "PRIV" and r.json()["price"] == 42.5
        assert any(e["ticker"] == "PRIV" for e in client.get("/api/universe/custom").json())
        assert client.delete("/api/universe/custom/PRIV").json()["deleted"] is True
        assert client.get("/api/universe/custom").json() == []
    finally:
        app.dependency_overrides.clear()


def test_add_custom_rejects_unknown(tmp_path, monkeypatch):
    from app.config.cache import Cache
    from app.deps import get_cache
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    try:
        monkeypatch.setattr(routes.universe, "resolve_custom_entry",
                            lambda *a, **k: (_ for _ in ()).throw(ValueError("No price history")))
        resp = TestClient(app).post("/api/universe/custom", json={"ticker": "NOPE"})
        assert resp.status_code == 422
        assert "No price history" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
