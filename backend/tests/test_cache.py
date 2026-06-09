import threading

from app.config.cache import Cache


def test_set_get_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "app.db"))
    cache.set("k", "v", ttl_seconds=60)
    assert cache.get("k") == "v"


def test_missing_key_returns_none(tmp_path):
    cache = Cache(str(tmp_path / "app.db"))
    assert cache.get("nope") is None


def test_expired_key_returns_none(tmp_path):
    cache = Cache(str(tmp_path / "app.db"))
    cache.set("k", "v", ttl_seconds=-1)  # already expired
    assert cache.get("k") is None


def test_shared_connection_is_thread_safe(tmp_path):
    """get_cache() is an @lru_cache singleton, so ONE sqlite connection
    (check_same_thread=False) is shared across FastAPI's threadpool. Concurrent
    expired-get()/set() must not collide on the connection's transaction state.

    Regression: sqlite3.OperationalError 'cannot commit - no transaction is
    active' when one thread's commit() closed the transaction another thread's
    DELETE had opened.
    """
    cache = Cache(str(tmp_path / "app.db"))
    errors: list[Exception] = []
    n_threads = 8
    start = threading.Barrier(n_threads)

    def worker(n: int) -> None:
        start.wait()  # release all threads at once to maximise interleaving
        try:
            for _ in range(150):
                cache.set(f"k{n}", "v", ttl_seconds=-1)  # already expired
                cache.get(f"k{n}")                        # expired -> DELETE + commit
        except Exception as exc:  # noqa: BLE001 - record, don't swallow
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"shared-connection race surfaced: {errors[:3]}"
