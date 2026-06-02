from __future__ import annotations

from urllib.parse import quote_plus

import feedparser
import httpx

from app.models.schemas import NewsItem

_RSS_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _fetch_feed(query: str) -> str:
    url = _RSS_URL.format(q=quote_plus(query))
    resp = httpx.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text


def parse_feed(xml: str, limit: int = 10) -> list[NewsItem]:
    feed = feedparser.parse(xml)
    items: list[NewsItem] = []
    for entry in feed.entries[:limit]:
        src = entry.get("source")
        source = src.get("title", "") if src else ""
        items.append(
            NewsItem(
                title=entry.get("title", ""),
                source=source,
                published_at=entry.get("published", ""),
                url=entry.get("link", ""),
                summary=entry.get("summary", ""),
            )
        )
    return items


def get_news(ticker: str, company_name: str = "", limit: int = 10) -> list[NewsItem]:
    query = f"{company_name} ({ticker}) stock" if company_name else f"{ticker} stock"
    try:
        return parse_feed(_fetch_feed(query), limit)
    except Exception:
        return []
