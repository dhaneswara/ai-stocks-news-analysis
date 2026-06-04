from datetime import datetime, timezone

from app.data.truth_social import filter_recent, parse_posts

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)

SAMPLE = [
    {"id": "1", "created_at": "2026-06-04T10:00:00Z",
     "content": "<p>Tariffs on China are <b>massive</b>!</p>", "url": "https://t/1"},
    {"id": "2", "created_at": "2026-06-01T09:00:00Z",
     "content": "<p>Old post</p>", "url": "https://t/2"},
]


def test_parse_posts_strips_html():
    posts = parse_posts(SAMPLE)
    assert posts[0].content == "Tariffs on China are massive!"
    assert posts[0].id == "1"
    assert posts[0].url == "https://t/1"


def test_filter_recent_keeps_only_in_window():
    recent = filter_recent(parse_posts(SAMPLE), hours=48, now=NOW)
    assert [p.id for p in recent] == ["1"]  # post 2 is >48h old


def test_filter_recent_drops_unparseable_dates():
    posts = parse_posts([{"id": "x", "created_at": "not-a-date", "content": "hi"}])
    assert filter_recent(posts, hours=48, now=NOW) == []


from app.config.cache import Cache
from app.data import truth_social


def test_fetch_recent_posts_filters(monkeypatch):
    monkeypatch.setattr(truth_social, "_fetch_archive", lambda url: SAMPLE)
    posts = truth_social.fetch_recent_posts(48, now=NOW)
    assert [p.id for p in posts] == ["1"]


def test_fetch_recent_posts_returns_empty_on_error(monkeypatch):
    def boom(_url):
        raise RuntimeError("network down")

    monkeypatch.setattr(truth_social, "_fetch_archive", boom)
    assert truth_social.fetch_recent_posts(48, now=NOW) == []


def test_cached_pull_avoids_second_fetch(tmp_path, monkeypatch):
    calls = {"n": 0}

    def counting(_url):
        calls["n"] += 1
        return SAMPLE

    monkeypatch.setattr(truth_social, "_fetch_archive", counting)
    cache = Cache(str(tmp_path / "c.db"))
    a = truth_social.fetch_recent_posts_cached(48, truth_social.ARCHIVE_URL, cache, now=NOW)
    b = truth_social.fetch_recent_posts_cached(48, truth_social.ARCHIVE_URL, cache, now=NOW)
    assert [p.id for p in a] == ["1"] and [p.id for p in b] == ["1"]
    assert calls["n"] == 1  # second call served from cache
