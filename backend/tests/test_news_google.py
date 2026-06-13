from app.models.schemas import NewsItem, NewsProviderConfig
from app.news import google as gmod
from app.news.google import GoogleNewsProvider


def test_google_provider_searches_and_applies_recency(monkeypatch):
    captured = {}

    def fake_search_news(query, limit):
        captured["query"], captured["limit"] = query, limit
        return [
            NewsItem(
                title="A",
                source="",
                published_at="2026-06-10T00:00:00Z",
                url="http://a",
                summary="s",
            )
        ]

    monkeypatch.setattr(gmod, "search_news", fake_search_news)
    out = GoogleNewsProvider(NewsProviderConfig()).search(
        "NVDA stock", limit=7, recency_days=3650
    )
    assert captured == {"query": "NVDA stock", "limit": 7}
    assert [i.title for i in out] == ["A"]
