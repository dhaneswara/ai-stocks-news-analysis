from app.evaluation.store import PredictionStore


def _store(tmp_path):
    return PredictionStore(str(tmp_path / "p.db"))


def test_upsert_and_get(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="aapl", call_date="2026-06-05", provider="anthropic",
                        model="m", recommendation="buy", confidence=0.8,
                        sentiment="bullish", entry_price=200.0)
    row = s.get_prediction("AAPL", "2026-06-05")
    assert row is not None
    assert row.ticker == "AAPL" and row.recommendation == "buy" and row.entry_price == 200.0


def test_upsert_replaces_latest_wins(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="sell", confidence=0.6, sentiment="bearish", entry_price=200.0)
    assert len(s.all_predictions()) == 1
    assert s.get_prediction("AAPL", "2026-06-05").recommendation == "sell"


def test_changing_entry_price_clears_child_evals(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0)
    assert s.has_eval("AAPL", "2026-06-05", 1) is True
    # Re-record with a different entry price -> stale evals are dropped
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=201.0)
    assert s.has_eval("AAPL", "2026-06-05", 1) is False


def test_record_and_read_evals(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.record_eval("AAPL", "2026-06-05", 5, "2026-06-12", 206.0, 3.0, 1, 80.0)
    evals = s.evals_for("AAPL", "2026-06-05")
    assert len(evals) == 1 and evals[0].horizon == 5 and evals[0].score == 80.0
    assert len(s.all_evals()) == 1


def test_delete_ticker_removes_rows(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0)
    deleted = s.delete_ticker("aapl")
    assert deleted == 1
    assert s.all_predictions() == [] and s.all_evals() == []
