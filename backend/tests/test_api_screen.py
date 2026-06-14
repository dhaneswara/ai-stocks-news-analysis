import json

from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.main import app
from app.evaluation.store import PredictionStore
from app.models.schemas import (
    Candle,
    Fundamentals,
    Indicators,
    PriceSummary,
    ScreenBoard,
    Settings,
    StockData,
    StockScore,
)
from app.screener.service import ScanProgress
from app.screener.store import load_snapshot, save_snapshot


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


def test_screen_portfolio_scope_reads_portfolio_snapshot(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config.cache import Cache
    from app.config.settings_store import SettingsStore
    from app.deps import get_cache, get_settings_store
    from app.models.schemas import ScreenBoard, StockScore
    from app.screener.store import save_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: SettingsStore(str(tmp_path / "s.db"))
    try:
        save_snapshot(ScreenBoard(scope="all", items=[
            StockScore(ticker="AAA", name="A", price=1, change_pct=0, score=10, direction="hold")]), cache)
        save_snapshot(ScreenBoard(scope="portfolio", items=[
            StockScore(ticker="BBB", name="B", price=1, change_pct=0, score=99, direction="buy")]), cache)
        r = TestClient(app).get("/api/screen?scope=portfolio")
        assert r.status_code == 200
        assert [i["ticker"] for i in r.json()["items"]] == ["BBB"]   # not the all board
    finally:
        app.dependency_overrides.clear()


def test_portfolio_tickers_endpoint(tmp_path, monkeypatch):
    import app.api.routes as routes
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config.cache import Cache
    from app.config.settings_store import SettingsStore
    from app.deps import get_cache, get_settings_store
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_settings_store] = lambda: SettingsStore(str(tmp_path / "s.db"))
    try:
        monkeypatch.setattr(routes, "portfolio_universe", lambda settings, cache: ["AAPL", "MSFT"])
        r = TestClient(app).get("/api/portfolio/tickers")
        assert r.status_code == 200 and r.json()["tickers"] == ["AAPL", "MSFT"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/screen/rescan/{ticker} — single-row rescan
# ---------------------------------------------------------------------------

def _stock(ticker="BBB"):
    return StockData(
        ticker=ticker, company_name="B", as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=10.0, change=1.0, change_pct=1.0),
        candles=[Candle(time="2026-06-05", open=1, high=1, low=1, close=10.0, volume=1)],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def _fresh(ticker="BBB", score=99.0):
    return StockScore(ticker=ticker, name="B", sector="Energy", price=10.0, change_pct=1.0,
                      score=score, direction="buy", net=0.4, base_net=0.4, base_score=score, as_of="new")


def test_rescan_ticker_persists_and_returns_fresh_score(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)  # AAA 90, BBB 80, CCC 70
    pstore = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(routes, "get_stock_data", lambda *a, **k: _stock("BBB"))
    monkeypatch.setattr(routes, "score_one", lambda *a, **k: _fresh("BBB", 99.0))
    try:
        app.dependency_overrides[routes.get_prediction_store] = lambda: pstore
        client = _client(cache)
        body = client.post("/api/screen/rescan/BBB").json()

        assert body["ticker"] == "BBB" and body["score"] == 99.0
        items = load_snapshot(cache, "all").items
        assert [i.ticker for i in items] == ["BBB", "AAA", "CCC"]          # BBB re-scored to 99, re-sorted
        assert pstore.get_prediction("BBB", "2026-06-05", "technical") is not None  # eval recorded
    finally:
        app.dependency_overrides.clear()


def test_rescan_ticker_skips_eval_when_disabled(tmp_path, monkeypatch):
    class _OffStore:
        def load(self):
            s = Settings()
            s.evaluation.enabled = False
            return s

    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    pstore = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(routes, "get_stock_data", lambda *a, **k: _stock("BBB"))
    monkeypatch.setattr(routes, "score_one", lambda *a, **k: _fresh("BBB", 99.0))
    try:
        app.dependency_overrides[routes.get_settings_store] = lambda: _OffStore()
        app.dependency_overrides[routes.get_cache] = lambda: cache
        app.dependency_overrides[routes.get_prediction_store] = lambda: pstore
        client = TestClient(app)
        client.post("/api/screen/rescan/BBB")
        assert pstore.all_predictions() == []                              # nothing recorded
    finally:
        app.dependency_overrides.clear()


def test_rescan_ticker_404_on_no_data(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    pstore = PredictionStore(str(tmp_path / "p.db"))

    def boom(*a, **k):
        raise ValueError("no price history")

    monkeypatch.setattr(routes, "get_stock_data", boom)
    try:
        app.dependency_overrides[routes.get_prediction_store] = lambda: pstore
        client = _client(cache)
        resp = client.post("/api/screen/rescan/NOPE")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
