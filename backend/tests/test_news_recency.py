from datetime import datetime, timezone
from app.data.news import recent_news
from app.models.schemas import NewsItem

NOW = datetime(2026, 6, 13, tzinfo=timezone.utc)

def _item(title, published_at):
    return NewsItem(title=title, source="", published_at=published_at, url=f"http://x/{title}", summary="")

def test_drops_old_and_sorts_newest_first_rfc822():
    items = [
        _item("old", "Tue, 01 Jan 2026 12:00:00 GMT"),
        _item("fresh", "Wed, 10 Jun 2026 12:00:00 GMT"),
    ]
    out = recent_news(items, days=90, now=NOW)
    assert [i.title for i in out] == ["fresh"]

def test_parses_iso_dates():
    items = [_item("iso", "2026-06-10T12:00:00Z")]
    assert [i.title for i in recent_news(items, days=90, now=NOW)] == ["iso"]

def test_keeps_unparseable_dates_sorted_last():
    items = [_item("nodate", "garbage"), _item("fresh", "2026-06-12T00:00:00Z")]
    out = recent_news(items, days=90, now=NOW)
    assert [i.title for i in out] == ["fresh", "nodate"]

def test_days_zero_disables_cutoff():
    items = [_item("old", "Tue, 01 Jan 2020 12:00:00 GMT")]
    assert len(recent_news(items, days=0, now=NOW)) == 1
