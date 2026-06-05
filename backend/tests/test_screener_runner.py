import app.screener.runner as runner
from app.config.cache import Cache
from app.models.schemas import ScreenBoard, Settings, StockScore
from app.screener.store import load_snapshot


def test_run_saves_snapshot(tmp_path, monkeypatch):
    board = ScreenBoard(as_of="t", scope="all", scanned=1, items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=5, direction="hold")])
    monkeypatch.setattr(runner, "run_scan", lambda scope, settings, cache: board)
    cache = Cache(str(tmp_path / "c.db"))
    summary = runner.run(Settings(), cache)
    assert summary["scanned"] == 1
    assert load_snapshot(cache, "all").items[0].ticker == "AAA"


def test_run_disabled_skips_scan(tmp_path, monkeypatch):
    settings = Settings()
    settings.screener.enabled = False
    called = {"scan": False}
    monkeypatch.setattr(runner, "run_scan", lambda *a, **k: called.__setitem__("scan", True))
    summary = runner.run(settings, Cache(str(tmp_path / "c.db")))
    assert summary == {"enabled": False, "scanned": 0}
    assert called["scan"] is False
