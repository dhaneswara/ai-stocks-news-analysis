from app.evaluation import service
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings


def _seed(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0)
    return store


# 6 trading days starting at the call date: +1d and +5d exist, +20d does not yet.
SERIES = [
    ("2026-06-01", 100.0),
    ("2026-06-02", 101.0),  # +1d -> +1.0%
    ("2026-06-03", 102.0),
    ("2026-06-04", 103.0),
    ("2026-06-05", 104.0),
    ("2026-06-08", 106.0),  # +5d -> +6.0%
]


def test_matures_only_available_horizons(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(service, "fetch_close_series", lambda ticker, period="2y": SERIES)
    summary = service.evaluate_pending(store, Settings())
    assert summary["evaluated"] == 2          # 1d and 5d matured
    assert summary["pending"] == 1            # 20d not yet
    assert store.has_eval("AAPL", "2026-06-01", 1) is True
    assert store.has_eval("AAPL", "2026-06-01", 5) is True
    assert store.has_eval("AAPL", "2026-06-01", 20) is False
    e1 = next(e for e in store.evals_for("AAPL", "2026-06-01") if e.horizon == 1)
    assert round(e1.return_pct, 4) == 1.0 and e1.hit == 1


def test_idempotent_on_rerun(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(service, "fetch_close_series", lambda ticker, period="2y": SERIES)
    service.evaluate_pending(store, Settings())
    summary = service.evaluate_pending(store, Settings())
    assert summary["evaluated"] == 0          # nothing new to do
    assert summary["pending"] == 1


def test_dry_run_does_not_persist(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(service, "fetch_close_series", lambda ticker, period="2y": SERIES)
    summary = service.evaluate_pending(store, Settings(), persist=False)
    assert summary["evaluated"] == 2
    assert store.all_evals() == []            # nothing written


def test_fetch_failure_skips_ticker(tmp_path, monkeypatch):
    store = _seed(tmp_path)

    def boom(ticker, period="2y"):
        raise RuntimeError("no network")

    monkeypatch.setattr(service, "fetch_close_series", boom)
    summary = service.evaluate_pending(store, Settings())
    assert summary["evaluated"] == 0 and store.all_evals() == []


def test_scoring_failure_is_isolated(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(service, "fetch_close_series", lambda ticker, period="2y": SERIES)

    def boom(*a, **k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(store, "record_eval", boom)
    # Must not raise even though record_eval fails for this ticker.
    summary = service.evaluate_pending(store, Settings())
    assert store.all_evals() == []


def _rising_series():
    from datetime import date, timedelta
    d0 = date(2026, 6, 1)
    return [((d0 + timedelta(days=i)).isoformat(), 100.0 + i) for i in range(30)]


def test_multi_source_rows_scored_independently(tmp_path, monkeypatch):
    from app.evaluation.service import evaluate_pending
    from app.evaluation.store import PredictionStore
    from app.models.schemas import Settings

    store = PredictionStore(str(tmp_path / "p.db"))
    base = dict(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                confidence=0.8, sentiment="bullish", entry_price=100.0)
    store.upsert_prediction(**base, recommendation="buy", source="llm_fast")
    store.upsert_prediction(**base, recommendation="sell", source="llm_deep")
    store.upsert_prediction(**base, recommendation="buy", source="technical")
    monkeypatch.setattr("app.evaluation.service.fetch_close_series",
                        lambda t, p: _rising_series())
    evaluate_pending(store, Settings())
    fast = store.evals_for("AAPL", "2026-06-01", "llm_fast")
    deep = store.evals_for("AAPL", "2026-06-01", "llm_deep")
    tech = store.evals_for("AAPL", "2026-06-01", "technical")
    assert len(fast) == len(deep) == len(tech) == 3  # horizons 1/5/20
    assert all(e.hit for e in fast) and all(e.hit for e in tech)   # buy in a rising series
    assert all(not e.hit for e in deep)                            # sell in a rising series
