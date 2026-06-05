import app.screener.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    PriceSummary,
    ScreenBoard,
    Settings,
    StockData,
    StockScore,
    UniverseEntry,
)
from app.screener.store import load_snapshot, merge_sector, save_snapshot


def _stock(ticker, rsi_last=50.0, week52_low=50.0):
    rsi = [IndicatorPoint(time="d0", value=50.0), IndicatorPoint(time="d1", value=rsi_last)]
    sma = [IndicatorPoint(time="d0", value=100.0), IndicatorPoint(time="d1", value=100.0)]
    candles = [Candle(time=f"d{i}", open=100.0, high=100.0, low=100.0, close=100.0, volume=1e6)
               for i in range(30)]
    return StockData(
        ticker=ticker, company_name=f"{ticker} Inc.", as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=100.0, change=0.0, change_pct=0.0, currency="USD"),
        candles=candles, fundamentals=Fundamentals(week52_low=week52_low, week52_high=150.0),
        indicators=Indicators(sma50=sma, sma200=sma, rsi14=rsi, dist_from_52wk_high_pct=-10.0),
    )


def test_run_scan_ranks_and_tags_sector(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "load_universe", lambda scope=None: [
        UniverseEntry(ticker="AAA", name="A", sector="Tech"),
        UniverseEntry(ticker="BBB", name="B", sector="Tech"),
    ])

    def fake_get(ticker, period, params, cache):
        # AAA is oversold + near its low -> a stronger setup than the neutral BBB.
        return _stock(ticker, rsi_last=20.0, week52_low=99.0) if ticker == "AAA" else _stock(ticker)

    monkeypatch.setattr(service, "get_stock_data", fake_get)
    board = service.run_scan(None, Settings(), Cache(str(tmp_path / "c.db")))
    assert board.scanned == 2 and board.skipped == 0
    assert [i.ticker for i in board.items][0] == "AAA"
    assert all(i.sector == "Tech" for i in board.items)
    assert board.scope == "all" and board.as_of


def test_run_scan_skips_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "load_universe", lambda scope=None: [
        UniverseEntry(ticker="OK", name="O", sector="Tech"),
        UniverseEntry(ticker="BAD", name="X", sector="Tech"),
    ])

    def fake_get(ticker, *a, **k):
        if ticker == "BAD":
            raise ValueError("no price history")
        return _stock(ticker)

    monkeypatch.setattr(service, "get_stock_data", fake_get)
    board = service.run_scan(None, Settings(), Cache(str(tmp_path / "c.db")))
    assert board.scanned == 2 and board.skipped == 1
    assert [i.ticker for i in board.items] == ["OK"]


def test_snapshot_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    board = ScreenBoard(as_of="t", scope="all", scanned=1, items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1.0, change_pct=0.0,
                   score=10.0, direction="hold")])
    save_snapshot(board, cache)
    assert load_snapshot(cache, "all").items[0].ticker == "AAA"
    assert load_snapshot(cache, "Energy") is None


def test_merge_sector_replaces_only_that_sector():
    full = ScreenBoard(scope="all", items=[
        StockScore(ticker="OLD", name="O", sector="Tech", price=1, change_pct=0, score=10, direction="hold"),
        StockScore(ticker="KEEP", name="K", sector="Energy", price=1, change_pct=0, score=20, direction="hold"),
    ])
    fresh = ScreenBoard(scope="Tech", items=[
        StockScore(ticker="NEW", name="N", sector="Tech", price=1, change_pct=0, score=99, direction="buy"),
    ])
    merged = merge_sector(full, fresh)
    tickers = [i.ticker for i in merged.items]
    assert "OLD" not in tickers and "NEW" in tickers and "KEEP" in tickers
    assert tickers[0] == "NEW"  # re-ranked by score desc
