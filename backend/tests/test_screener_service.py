import app.screener.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    KnowledgeGraph,
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
    monkeypatch.setattr(service, "load_universe", lambda scope=None, cache=None: [
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
    monkeypatch.setattr(service, "load_universe", lambda scope=None, cache=None: [
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


def test_iter_scan_yields_progress_then_board(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "load_universe", lambda scope=None, cache=None: [
        UniverseEntry(ticker="OK", name="O", sector="Tech"),
        UniverseEntry(ticker="BAD", name="X", sector="Tech"),
        UniverseEntry(ticker="OK2", name="O2", sector="Tech"),
    ])

    def fake_get(ticker, *a, **k):
        if ticker == "BAD":
            raise ValueError("no price history")
        return _stock(ticker)

    monkeypatch.setattr(service, "get_stock_data", fake_get)
    steps = list(service.iter_scan(None, Settings(), Cache(str(tmp_path / "c.db"))))

    progress = [s for s in steps if isinstance(s, service.ScanProgress)]
    # One tick per ticker, emitted BEFORE its fetch — counts cover completed tickers only.
    assert [(p.ticker, p.scanned, p.total, p.skipped) for p in progress] == [
        ("OK", 0, 3, 0), ("BAD", 1, 3, 0), ("OK2", 2, 3, 1),
    ]
    board = steps[-1]
    assert isinstance(board, ScreenBoard)
    assert board.scanned == 3 and board.skipped == 1
    assert [i.ticker for i in board.items] == ["OK", "OK2"]


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


def test_merge_sector_recomputes_scanned_skipped():
    # The full board claims scanned=30 from an earlier scan; a sector rescan must NOT leave that
    # stale (the live bug: board reported "30 scanned" while holding far more merged items).
    full = ScreenBoard(scope="all", scanned=30, skipped=0, items=[
        StockScore(ticker="OLD", name="O", sector="Tech", price=1, change_pct=0, score=10, direction="hold"),
        StockScore(ticker="KEEP", name="K", sector="Energy", price=1, change_pct=0, score=20, direction="hold"),
    ])
    fresh = ScreenBoard(scope="Tech", scanned=2, skipped=1, items=[
        StockScore(ticker="NEW1", name="N1", sector="Tech", price=1, change_pct=0, score=99, direction="buy"),
        StockScore(ticker="NEW2", name="N2", sector="Tech", price=1, change_pct=0, score=50, direction="buy"),
    ])
    merged = merge_sector(full, fresh)
    assert len(merged.items) == 3                              # KEEP + NEW1 + NEW2
    assert merged.scanned == len(merged.items) + fresh.skipped  # honest, not the stale 30
    assert merged.skipped == fresh.skipped
    assert merged.scanned >= len(merged.items)


def test_portfolio_universe_unions_watchlist_and_ontology_tickers(monkeypatch):
    s = Settings()
    s.watchlist = ["AAPL", "msft "]
    monkeypatch.setattr(service, "active_graph", lambda cache: KnowledgeGraph(
        nodes=["MSFT", "NVDA", "ext:openai", "man:concept"]))
    out = service.portfolio_universe(s, cache=None)
    # watchlist first (deduped, upper-cased), then ontology TICKER nodes (ext:/man: skipped)
    assert out == ["AAPL", "MSFT", "NVDA"]


def test_scan_portfolio_scope_synthesizes_entries_and_tags(monkeypatch):
    s = Settings()
    s.watchlist = ["AAPL", "PRIV"]   # PRIV is NOT in sp500.json
    monkeypatch.setattr(service, "active_graph", lambda cache: KnowledgeGraph(nodes=[]))

    def fake_get(ticker, *a, **k):
        st = _stock(ticker)
        return st.model_copy(update={"exchange": "NASDAQ", "sector": "Tech"})

    monkeypatch.setattr(service, "get_stock_data", fake_get)
    board = service.run_scan("portfolio", s, Cache(str(__import__("tempfile").mkdtemp() + "/c.db")))

    assert board.scope == "portfolio"
    by = {i.ticker: i for i in board.items}
    assert by["AAPL"].in_sp500 is True and by["PRIV"].in_sp500 is False
    assert by["PRIV"].exchange == "NASDAQ"           # from fetched StockData
    assert by["PRIV"].sector == "Tech"               # synth entry had no sector -> fall back to stock


def test_scan_all_includes_custom_companies(tmp_path, monkeypatch):
    from app.data import universe
    cache = Cache(str(tmp_path / "c.db"))
    universe.add_custom(UniverseEntry(ticker="PRIV", name="Priv", sector="Tech", exchange="NYSE"), cache)

    # Tiny committed list + the custom merge, so the scan stays fast and deterministic.
    monkeypatch.setattr(
        service, "load_universe",
        lambda sector=None, cache=None: ([UniverseEntry(ticker="AAA", name="A", sector="Tech")]
                                         + (universe.list_custom(cache) if cache else [])))
    monkeypatch.setattr(service, "get_stock_data", lambda t, *a, **k: _stock(t))

    board = service.run_scan(None, Settings(), cache)
    tickers = {i.ticker for i in board.items}
    assert "PRIV" in tickers and "AAA" in tickers
    assert next(i for i in board.items if i.ticker == "PRIV").in_sp500 is False


def test_combined_base_index_portfolio_overrides_all(tmp_path):
    from app.screener.store import combined_base_index
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAA", name="A", price=1, change_pct=0, score=10, direction="hold"),
        StockScore(ticker="BBB", name="B", price=1, change_pct=0, score=20, direction="hold"),
    ]), cache)
    save_snapshot(ScreenBoard(scope="portfolio", items=[
        StockScore(ticker="BBB", name="B", price=1, change_pct=0, score=99, direction="buy"),
    ]), cache)
    idx = combined_base_index(cache)
    assert set(idx) == {"AAA", "BBB"}
    assert idx["BBB"].score == 99   # portfolio wins on conflict
    assert idx["AAA"].score == 10   # all-only ticker retained


def test_upsert_score_appends_when_absent_and_sorts(tmp_path):
    from app.screener.store import upsert_score, load_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=50, direction="hold"),
    ]), cache)
    fresh = StockScore(ticker="BBB", name="B", sector="Energy", price=1, change_pct=0, score=90, direction="buy")
    board = upsert_score(fresh, None, cache)
    assert [i.ticker for i in board.items] == ["BBB", "AAA"]            # re-sorted by score desc
    assert [i.ticker for i in load_snapshot(cache, "all").items] == ["BBB", "AAA"]  # persisted


def test_upsert_score_replaces_existing_case_insensitively(tmp_path):
    from app.screener.store import upsert_score, load_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=90, direction="buy"),
        StockScore(ticker="BBB", name="B", sector="Energy", price=1, change_pct=0, score=80, direction="sell"),
    ]), cache)
    # The new row keeps the caller's casing ("aaa"); normalisation is the caller's responsibility.
    fresh = StockScore(ticker="aaa", name="A", sector="Tech", price=2, change_pct=1, score=10, direction="sell")
    board = upsert_score(fresh, None, cache)
    assert [i.ticker for i in board.items] == ["BBB", "aaa"]           # AAA re-scored to 10, sinks below BBB
    assert len([i for i in board.items if i.ticker.upper() == "AAA"]) == 1  # no duplicate


def test_upsert_score_routes_portfolio_scope_to_portfolio_snapshot(tmp_path):
    from app.screener.store import upsert_score, load_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    fresh = StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=50, direction="hold")
    upsert_score(fresh, "portfolio", cache)
    assert load_snapshot(cache, "portfolio").items[0].ticker == "AAA"  # created under portfolio
    assert load_snapshot(cache, "all") is None                          # all untouched


def test_upsert_score_routes_sector_scope_to_all_snapshot(tmp_path):
    from app.screener.store import upsert_score, load_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    fresh = StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=50, direction="hold")
    upsert_score(fresh, "Tech", cache)                                  # a sector name, not "portfolio"
    assert load_snapshot(cache, "all").items[0].ticker == "AAA"        # routed to the broad board
    assert load_snapshot(cache, "Tech") is None                         # never keyed by sector
