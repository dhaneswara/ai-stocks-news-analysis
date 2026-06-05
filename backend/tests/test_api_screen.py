from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.main import app
from app.models.schemas import ScreenBoard, Settings, StockScore
from app.screener.store import save_snapshot


class _Store:
    def load(self):
        return Settings()


def _client(cache):
    app.dependency_overrides[routes.get_settings_store] = lambda: _Store()
    app.dependency_overrides[routes.get_cache] = lambda: cache
    return TestClient(app)


def _board():
    return ScreenBoard(as_of="t", scope="all", scanned=3, skipped=0, items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=90, direction="buy"),
        StockScore(ticker="BBB", name="B", sector="Energy", price=1, change_pct=0, score=80, direction="sell"),
        StockScore(ticker="CCC", name="C", sector="Tech", price=1, change_pct=0, score=70, direction="hold"),
    ])


def test_screen_empty_when_no_snapshot(tmp_path):
    client = _client(Cache(str(tmp_path / "c.db")))
    body = client.get("/api/screen").json()
    app.dependency_overrides.clear()
    assert body["items"] == [] and body["as_of"] == ""


def test_screen_returns_and_filters(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    client = _client(cache)
    all_items = client.get("/api/screen").json()["items"]
    tech = client.get("/api/screen?sector=Tech").json()["items"]
    buys = client.get("/api/screen?direction=buy").json()["items"]
    app.dependency_overrides.clear()
    assert [i["ticker"] for i in all_items] == ["AAA", "BBB", "CCC"]
    assert {i["ticker"] for i in tech} == {"AAA", "CCC"}
    assert [i["ticker"] for i in buys] == ["AAA"]


def test_screen_respects_limit(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    client = _client(cache)
    body = client.get("/api/screen?limit=2").json()
    app.dependency_overrides.clear()
    assert len(body["items"]) == 2


def test_rescan_persists_and_returns(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(routes, "run_scan", lambda scope, settings, cache: _board())
    client = _client(cache)
    body = client.post("/api/screen/rescan").json()
    assert body["scanned"] == 3
    again = client.get("/api/screen").json()
    app.dependency_overrides.clear()
    assert len(again["items"]) == 3  # persisted snapshot is read back


def test_sectors_endpoint(tmp_path):
    client = _client(Cache(str(tmp_path / "c.db")))
    body = client.get("/api/screen/sectors").json()
    app.dependency_overrides.clear()
    assert "Information Technology" in body
