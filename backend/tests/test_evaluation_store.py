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


def test_scored_prediction_is_immutable_on_rerecord(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0)
    assert s.has_eval("AAPL", "2026-06-05", 1) is True
    # Once scored, re-recording at a different entry price is a no-op: scored history and the
    # original entry are preserved (re-running analysis must never destroy evals).
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="sell", confidence=0.2, sentiment="bearish", entry_price=201.0)
    assert s.has_eval("AAPL", "2026-06-05", 1) is True
    row = s.get_prediction("AAPL", "2026-06-05")
    assert row.entry_price == 200.0 and row.recommendation == "buy"


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


def test_clear_all_wipes_both_tables(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.upsert_prediction(ticker="MSFT", call_date="2026-06-05", provider="rules", model="",
                        recommendation="sell", confidence=0.3, sentiment="bearish",
                        entry_price=400.0, source="technical")
    s.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0)

    counts = s.clear_all()
    assert counts == {"predictions": 2, "evals": 1}
    assert s.all_predictions() == [] and s.all_evals() == []
    # Clearing an already-empty store is a no-op, not an error.
    assert s.clear_all() == {"predictions": 0, "evals": 0}
