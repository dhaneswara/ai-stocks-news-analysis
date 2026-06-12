import json

from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.main import app
from app.models.schemas import ScreenBoard, Settings, StockScore
from app.screener.service import ScanProgress
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


def test_sector_rescan_with_no_full_board_is_still_readable(tmp_path, monkeypatch):
    # First-ever scan being sector-scoped: there is no "all" board to merge into. The sector
    # board must be promoted to the "all" snapshot (save_snapshot keys by scope) or GET /screen
    # never sees it.
    cache = Cache(str(tmp_path / "c.db"))
    sector_board = _board().model_copy(update={"scope": "Energy"})
    monkeypatch.setattr(routes, "run_scan", lambda scope, settings, cache: sector_board)
    client = _client(cache)
    client.post("/api/screen/rescan?sector=Energy")
    body = client.get("/api/screen").json()
    app.dependency_overrides.clear()
    assert len(body["items"]) == 3


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_rescan_stream_ticks_then_persists(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))

    def fake_iter(scope, settings, cache):
        yield ScanProgress(ticker="AAA", scanned=0, total=3, skipped=0)
        yield ScanProgress(ticker="BBB", scanned=1, total=3, skipped=0)
        yield _board()

    monkeypatch.setattr(routes, "iter_scan", fake_iter)
    client = _client(cache)
    resp = client.get("/api/screen/rescan/stream")
    events = _sse_events(resp.text)
    board = client.get("/api/screen").json()
    app.dependency_overrides.clear()

    assert resp.headers["content-type"].startswith("text/event-stream")
    assert [e[0] for e in events] == ["tick", "tick", "done"]
    assert events[0][1]["ticker"] == "AAA" and events[0][1]["total"] == 3
    assert events[1][1]["scanned"] == 1
    assert events[-1][1]["scanned"] == 3 and events[-1][1]["skipped"] == 0
    assert len(board["items"]) == 3  # the snapshot was saved on done


def test_rescan_stream_surfaces_failure_as_error_event(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))

    def fake_iter(scope, settings, cache):
        yield ScanProgress(ticker="AAA", scanned=0, total=3, skipped=0)
        raise RuntimeError("universe file corrupt")

    monkeypatch.setattr(routes, "iter_scan", fake_iter)
    client = _client(cache)
    events = _sse_events(client.get("/api/screen/rescan/stream").text)
    board = client.get("/api/screen").json()
    app.dependency_overrides.clear()

    assert [e[0] for e in events] == ["tick", "error"]
    assert "universe file corrupt" in events[-1][1]["message"]
    assert board["items"] == []  # nothing saved on failure


def test_sectors_endpoint(tmp_path):
    client = _client(Cache(str(tmp_path / "c.db")))
    body = client.get("/api/screen/sectors").json()
    app.dependency_overrides.clear()
    assert "Information Technology" in body


def test_screen_limit_zero_returns_all_uncapped(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)  # 3 items

    class _SmallStore:
        def load(self):
            s = Settings()
            s.screener.top_n = 2
            return s

    app.dependency_overrides[routes.get_settings_store] = lambda: _SmallStore()
    app.dependency_overrides[routes.get_cache] = lambda: cache
    client = TestClient(app)
    capped = client.get("/api/screen").json()["items"]          # no limit -> top_n = 2
    all_items = client.get("/api/screen?limit=0").json()["items"]  # limit=0 -> uncapped
    app.dependency_overrides.clear()
    assert len(capped) == 2
    assert len(all_items) == 3
