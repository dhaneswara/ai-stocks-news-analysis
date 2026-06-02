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
