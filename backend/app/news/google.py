"""Default provider: Google News RSS (reuses data/news.search_news) + the recency filter."""
from __future__ import annotations

from app.data.news import recent_news, search_news
from app.models.schemas import NewsItem, NewsProviderConfig


class GoogleNewsProvider:
    label = "Google News"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg  # Google needs no key

    def search(
        self, query: str, *, limit: int, recency_days: int
    ) -> list[NewsItem]:
        return recent_news(search_news(query, limit), days=recency_days)
