from app.config.cache import Cache
from app.evaluation import signals
from app.evaluation.signals import record_deterministic_pair
from app.evaluation.store import PredictionStore
from app.models.schemas import (
    Candle, Fundamentals, Indicators, NetworkSignal, PriceSummary, Settings, StockData,
    StockScore,
)


def _stock(ticker="AAPL"):
    return StockData(
        ticker=ticker, company_name="X", as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=204.0, change=1.0, change_pct=0.5),
        candles=[
            Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
            Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
        ],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def _score(ticker="AAPL", *, base_net=0.3, net=0.3, direction="buy", network=None):
    return StockScore(ticker=ticker, name="X", sector="", price=204.0, change_pct=0.5,
                      score=70.0, direction=direction, net=net, base_net=base_net,
                      base_score=70.0, as_of="t", network=network)


def test_pair_records_technical_and_network(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    cache = Cache(str(tmp_path / "c.db"))
    sig = NetworkSignal(ticker="AAPL", intensity=0.5, signed=-0.4)
    monkeypatch.setattr(signals, "score_one",
                        lambda t, s, c: _score(base_net=0.3, net=-0.2, direction="sell",
                                               network=sig))
    record_deterministic_pair(_stock(), Settings(), cache, store)

    tech = store.get_prediction("AAPL", "2026-06-05", "technical")
    assert tech is not None and tech.recommendation == "buy"      # from base_net 0.3
    assert tech.entry_price == 204.0 and tech.provider == "rules"
    assert abs(tech.confidence - 0.3) < 1e-9

    net = store.get_prediction("AAPL", "2026-06-05", "network")
    assert net is not None and net.recommendation == "sell"       # blended direction
    assert abs(net.confidence - 0.2) < 1e-9


def test_pair_skips_network_row_without_signal(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score(network=None))
    record_deterministic_pair(_stock(), Settings(), Cache(str(tmp_path / "c.db")), store)
    assert store.get_prediction("AAPL", "2026-06-05", "technical") is not None
    assert store.get_prediction("AAPL", "2026-06-05", "network") is None


def test_pair_noop_without_candles(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score())
    stock = _stock()
    stock.candles = []
    record_deterministic_pair(stock, Settings(), Cache(str(tmp_path / "c.db")), store)
    assert store.all_predictions() == []


def test_snapshot_watchlist_records_and_isolates_failures(tmp_path, monkeypatch):
    from app.evaluation.signals import snapshot_watchlist

    store = PredictionStore(str(tmp_path / "p.db"))
    cache = Cache(str(tmp_path / "c.db"))
    settings = Settings()  # default watchlist: ["AAPL", "MSFT"]

    def fake_stock(ticker, period, params, cache_):
        if ticker == "MSFT":
            raise ValueError("no data")
        return _stock(ticker)

    monkeypatch.setattr(signals, "get_stock_data", fake_stock)
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score(t))
    out = snapshot_watchlist(settings, cache, store)
    assert out["recorded"] == 1
    assert out["skipped"] == [{"ticker": "MSFT", "reason": "no data"}]
    assert store.get_prediction("AAPL", "2026-06-05", "technical") is not None


def test_snapshot_watchlist_counts_no_candle_tickers_as_skipped(tmp_path, monkeypatch):
    from app.evaluation.signals import snapshot_watchlist

    store = PredictionStore(str(tmp_path / "p.db"))
    settings = Settings()
    settings.watchlist = ["AAPL"]
    empty = _stock("AAPL")
    empty.candles = []
    monkeypatch.setattr(signals, "get_stock_data", lambda t, p, ip, c: empty)
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score("AAPL"))
    out = snapshot_watchlist(settings, Cache(str(tmp_path / "c.db")), store)
    assert out["recorded"] == 0
    assert out["skipped"] == [{"ticker": "AAPL", "reason": "no candles"}]
    assert store.all_predictions() == []


def _seed_llm_history(store):
    base = dict(ticker="NVDA", provider="a", model="m", sentiment="bullish", entry_price=100.0)
    store.upsert_prediction(**base, call_date="2026-05-12", recommendation="buy",
                            confidence=0.8, source="llm_fast")
    store.record_eval("NVDA", "2026-05-12", 5, "2026-05-19", 101.2, 1.2, 1, 62.0,
                      source="llm_fast")
    store.upsert_prediction(**base, call_date="2026-05-20", recommendation="buy",
                            confidence=0.9, source="llm_deep")
    store.record_eval("NVDA", "2026-05-20", 5, "2026-05-27", 96.9, -3.1, 0, 19.0,
                      source="llm_deep")


def test_track_record_block_formats_history(tmp_path):
    from app.evaluation.signals import build_track_record_block

    store = PredictionStore(str(tmp_path / "p.db"))
    _seed_llm_history(store)
    block = build_track_record_block("nvda", store, Settings())
    assert "2026-05-20 [deep] BUY (conf 90%)" in block
    assert "2026-05-12 [fast] BUY (conf 80%)" in block
    assert "+1.2% @5d ✓" in block and "-3.1% @5d ✗" in block
    assert "you hit 50% at 5 trading days" in block
    assert "skew overconfident" in block          # miss conf 0.9 >= hit conf 0.8
    assert block.endswith("Calibrate this call's confidence accordingly.")


def test_track_record_block_gates(tmp_path):
    from app.evaluation.signals import build_track_record_block

    store = PredictionStore(str(tmp_path / "p.db"))
    assert build_track_record_block("NVDA", store, Settings()) is None  # no history

    store.upsert_prediction(ticker="NVDA", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0, source="llm_fast")
    assert build_track_record_block("NVDA", store, Settings()) is None  # nothing matured

    disabled = Settings()
    disabled.evaluation.enabled = False
    _seed_llm_history(store)
    assert build_track_record_block("NVDA", store, disabled) is None   # feature off

    # deterministic rows alone never produce a block
    store2 = PredictionStore(str(tmp_path / "p2.db"))
    store2.upsert_prediction(ticker="NVDA", call_date="2026-06-01", provider="rules", model="",
                             recommendation="buy", confidence=0.4, sentiment="bullish",
                             entry_price=100.0, source="technical")
    store2.record_eval("NVDA", "2026-06-01", 5, "2026-06-08", 105.0, 5.0, 1, 100.0,
                       source="technical")
    assert build_track_record_block("NVDA", store2, Settings()) is None


def _signal_pred(store, source, call_date, rec, *, ticker="AAPL", conf=0.5):
    store.upsert_prediction(ticker=ticker, call_date=call_date, provider="x", model="",
                            recommendation=rec, confidence=conf, sentiment="neutral",
                            entry_price=100.0, source=source)


def _signal_eval(store, source, call_date, score, hit, *, ticker="AAPL", horizon=5):
    store.record_eval(ticker, call_date, horizon, "2026-06-09", 100.0, 1.0, hit, score,
                      source=source)


def test_build_signals_empty(tmp_path):
    from datetime import date
    from app.evaluation.signals import build_signals

    store = PredictionStore(str(tmp_path / "p.db"))
    out = build_signals("AAPL", store, today=date(2026, 6, 10))
    assert out.ticker == "AAPL" and out.winner is None
    assert out.agreement.counted == 0
    assert all(v is None for v in out.sources.values())


def test_build_signals_latest_tracks_winner_and_agreement(tmp_path):
    from datetime import date
    from app.evaluation.signals import build_signals

    store = PredictionStore(str(tmp_path / "p.db"))
    # technical: 3 matured, strong — qualifies and wins
    for d in ("2026-06-03", "2026-06-04", "2026-06-05"):
        _signal_pred(store, "technical", d, "buy")
        _signal_eval(store, "technical", d, 80.0, 1)
    # llm_fast: 2 matured only — does not qualify for the crown
    for d in ("2026-06-04", "2026-06-05"):
        _signal_pred(store, "llm_fast", d, "sell")
        _signal_eval(store, "llm_fast", d, 90.0, 1)
    # network: stale (outside the 7-day window) — recorded but must not vote
    _signal_pred(store, "network", "2026-05-20", "hold")

    out = build_signals("AAPL", store, today=date(2026, 6, 10))
    assert out.winner == "technical"
    tech = out.sources["technical"]
    assert tech.latest.call_date == "2026-06-05" and tech.latest.recommendation == "buy"
    assert tech.track.n_calls == 3 and tech.track.n_matured == 3
    assert tech.track.hit_rate == 100.0 and tech.track.grade == "Strong"
    assert out.sources["llm_deep"] is None
    assert out.agreement.counted == 2          # technical + llm_fast; network too old
    assert out.agreement.conflict is True
    assert out.agreement.agreeing == 1


def test_build_signals_winner_tie_yields_no_crown(tmp_path):
    from datetime import date
    from app.evaluation.signals import build_signals

    store = PredictionStore(str(tmp_path / "p.db"))
    for src in ("technical", "llm_fast"):
        for d in ("2026-06-03", "2026-06-04", "2026-06-05"):
            _signal_pred(store, src, d, "buy")
            _signal_eval(store, src, d, 70.0, 1)
    out = build_signals("AAPL", store, today=date(2026, 6, 10))
    assert out.winner is None


def test_build_signals_winner_tiebreak_prefers_more_matured(tmp_path):
    from datetime import date
    from app.evaluation.signals import build_signals

    store = PredictionStore(str(tmp_path / "p.db"))
    # Same avg score (70.0) but DIFFERENT matured counts -> larger count wins the crown.
    # (A full tie on BOTH avg and matured count yields no crown — see the test above.)
    for d in ("2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"):
        _signal_pred(store, "technical", d, "buy")
        _signal_eval(store, "technical", d, 70.0, 1)
    for d in ("2026-06-03", "2026-06-04", "2026-06-05"):
        _signal_pred(store, "llm_fast", d, "buy")
        _signal_eval(store, "llm_fast", d, 70.0, 1)
    out = build_signals("AAPL", store, today=date(2026, 6, 10))
    assert out.winner == "technical"   # equal avg -> larger matured count takes the crown
