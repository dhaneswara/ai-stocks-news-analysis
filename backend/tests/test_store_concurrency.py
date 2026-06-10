"""Thread-safety regressions for the @lru_cache singleton stores.

get_settings_store() and get_prediction_store() (app/deps.py) each return a
process-wide singleton whose single sqlite connection (check_same_thread=False)
is shared across FastAPI's threadpool. Concurrent access must be serialised, or
the shared cursor/transaction corrupts ("bad parameter or other API misuse",
"cannot commit - no transaction is active", ...). Mirrors test_cache.py.
"""
import threading

from app.config.settings_store import SettingsStore
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings


def _hammer(n_threads, work):
    errors: list[Exception] = []
    start = threading.Barrier(n_threads)

    def worker(n: int) -> None:
        start.wait()  # release all threads together to maximise interleaving
        try:
            work(n)
        except Exception as exc:  # noqa: BLE001 - record, don't swallow
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_settings_store_is_thread_safe(tmp_path):
    store = SettingsStore(str(tmp_path / "app.db"))

    def work(_n: int) -> None:
        for _ in range(60):
            store.save(Settings())  # INSERT OR REPLACE + commit
            store.load()            # SELECT

    errors = _hammer(8, work)
    assert not errors, f"settings-store race surfaced: {errors[:3]}"


def test_prediction_store_is_thread_safe(tmp_path):
    store = PredictionStore(str(tmp_path / "app.db"))

    def work(n: int) -> None:
        ticker = f"T{n}"
        for i in range(60):
            # changing entry_price exercises the multi-statement read-modify-write
            store.upsert_prediction(
                ticker=ticker, call_date="2026-06-09", provider="p", model="m",
                recommendation="buy", confidence=0.6, sentiment="bullish",
                entry_price=100.0 + i,
            )
            store.get_prediction(ticker, "2026-06-09")
            store.record_eval(ticker, "2026-06-09", 1, "2026-06-10", 110.0, 10.0, 1, 80.0)
            store.has_eval(ticker, "2026-06-09", 1)
            store.all_predictions()

    errors = _hammer(8, work)
    assert not errors, f"prediction-store race surfaced: {errors[:3]}"


def test_prediction_store_sources_isolated_under_threads(tmp_path):
    import threading
    from app.evaluation.store import PredictionStore

    store = PredictionStore(str(tmp_path / "p.db"))

    def hammer(source: str):
        for _ in range(50):
            store.upsert_prediction(ticker="AAPL", call_date="2026-06-09", provider="a",
                                    model="m", recommendation="buy", confidence=0.5,
                                    sentiment="bullish", entry_price=100.0, source=source)
            store.record_eval("AAPL", "2026-06-09", 1, "2026-06-10", 110.0, 10.0, 1, 80.0,
                              source=source)
            store.has_eval("AAPL", "2026-06-09", 1, source)

    threads = [threading.Thread(target=hammer, args=(s,)) for s in ("llm_fast", "technical")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = store.all_predictions()
    assert {r.source for r in rows} == {"llm_fast", "technical"}
    assert len(rows) == 2  # one row per source — no cross-source clobbering
    assert store.has_eval("AAPL", "2026-06-09", 1, "llm_fast")
    assert store.has_eval("AAPL", "2026-06-09", 1, "technical")
