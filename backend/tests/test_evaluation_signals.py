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
