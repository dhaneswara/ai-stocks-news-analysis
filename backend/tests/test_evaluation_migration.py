import sqlite3

from app.evaluation.store import PredictionStore


def _legacy_db(path: str) -> None:
    """Build a pre-source database exactly as the old store created it."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE predictions ("
        "ticker TEXT, call_date TEXT, provider TEXT, model TEXT, recommendation TEXT, "
        "confidence REAL, sentiment TEXT, entry_price REAL, created_at REAL, "
        "PRIMARY KEY (ticker, call_date))"
    )
    conn.execute(
        "CREATE TABLE prediction_evals ("
        "ticker TEXT, call_date TEXT, horizon INTEGER, eval_date TEXT, exit_price REAL, "
        "return_pct REAL, hit INTEGER, score REAL, "
        "PRIMARY KEY (ticker, call_date, horizon))"
    )
    conn.execute(
        "INSERT INTO predictions VALUES ('AAPL', '2026-06-05', 'anthropic', 'm', 'buy', "
        "0.8, 'bullish', 204.0, 1.0)"
    )
    conn.execute(
        "INSERT INTO prediction_evals VALUES ('AAPL', '2026-06-05', 1, '2026-06-06', "
        "210.0, 2.9, 1, 79.4)"
    )
    conn.commit()
    conn.close()


def test_legacy_rows_migrate_tagged_llm_fast(tmp_path):
    path = str(tmp_path / "p.db")
    _legacy_db(path)
    store = PredictionStore(path)
    rows = store.all_predictions()
    assert len(rows) == 1 and rows[0].source == "llm_fast"
    assert rows[0].recommendation == "buy" and rows[0].entry_price == 204.0
    evals = store.evals_for("AAPL", "2026-06-05")
    assert len(evals) == 1 and evals[0].source == "llm_fast" and evals[0].score == 79.4


def test_fast_and_deep_coexist_same_day_after_migration(tmp_path):
    path = str(tmp_path / "p.db")
    _legacy_db(path)
    store = PredictionStore(path)
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="sell", confidence=0.6, sentiment="bearish",
                            entry_price=204.0, source="llm_deep")
    assert store.get_prediction("AAPL", "2026-06-05", "llm_fast").recommendation == "buy"
    assert store.get_prediction("AAPL", "2026-06-05", "llm_deep").recommendation == "sell"
    assert len(store.all_predictions()) == 2


def test_migration_is_idempotent_on_reopen(tmp_path):
    path = str(tmp_path / "p.db")
    _legacy_db(path)
    PredictionStore(path)
    store = PredictionStore(path)  # reopen — must not duplicate or fail
    assert len(store.all_predictions()) == 1


def test_fresh_db_gets_new_schema(tmp_path):
    store = PredictionStore(str(tmp_path / "new.db"))
    store.upsert_prediction(ticker="MSFT", call_date="2026-06-05", provider="rules", model="",
                            recommendation="hold", confidence=0.1, sentiment="neutral",
                            entry_price=100.0, source="technical")
    assert store.get_prediction("MSFT", "2026-06-05", "technical") is not None
    assert store.get_prediction("MSFT", "2026-06-05") is None  # default looks up llm_fast


def test_entry_price_change_invalidates_only_that_source(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    for src in ("llm_fast", "technical"):
        store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                                recommendation="buy", confidence=0.8, sentiment="bullish",
                                entry_price=200.0, source=src)
        store.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0, source=src)
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=201.0, source="llm_fast")  # changed price
    assert store.has_eval("AAPL", "2026-06-05", 1, "llm_fast") is False
    assert store.has_eval("AAPL", "2026-06-05", 1, "technical") is True
