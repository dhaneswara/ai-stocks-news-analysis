from app.data.news import get_news, parse_feed

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Apple hits new high - Reuters</title>
  <link>https://example.com/a</link>
  <pubDate>Mon, 01 Jun 2026 12:00:00 GMT</pubDate>
  <source url="https://reuters.com">Reuters</source>
  <description>Apple shares rose.</description>
</item>
<item>
  <title>Apple earnings preview - CNBC</title>
  <link>https://example.com/b</link>
  <pubDate>Sun, 31 May 2026 09:00:00 GMT</pubDate>
  <source url="https://cnbc.com">CNBC</source>
  <description>Preview text.</description>
</item>
</channel></rss>"""


def test_parse_feed_extracts_items():
    items = parse_feed(SAMPLE_RSS, limit=10)
    assert len(items) == 2
    assert items[0].title == "Apple hits new high - Reuters"
    assert items[0].url == "https://example.com/a"
    assert items[0].source == "Reuters"


def test_parse_feed_respects_limit():
    assert len(parse_feed(SAMPLE_RSS, limit=1)) == 1


def test_get_news_returns_empty_on_fetch_error(monkeypatch):
    def boom(_query):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.data.news._fetch_feed", boom)
    assert get_news("AAPL", "Apple Inc.") == []
