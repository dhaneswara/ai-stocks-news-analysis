from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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


def search_news(query: str, limit: int = 5) -> list[NewsItem]:
    """Targeted feed search for an arbitrary query (used by the deep-analysis agent)."""
    try:
        return parse_feed(_fetch_feed(query), limit)
    except Exception:
        return []


def get_news(ticker: str, company_name: str = "", limit: int = 10) -> list[NewsItem]:
    query = f"{company_name} ({ticker}) stock" if company_name else f"{ticker} stock"
    try:
        return parse_feed(_fetch_feed(query), limit)
    except Exception:
        return []


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    d = None
    try:
        d = parsedate_to_datetime(s)          # RFC-822 (Google News RSS)
    except Exception:  # noqa: BLE001
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))  # ISO-8601 (Exa/you.com)
        except Exception:  # noqa: BLE001
            return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def recent_news(items: list[NewsItem], *, days: int, now: datetime | None = None) -> list[NewsItem]:
    """Drop items older than `days`, newest-first; unparseable dates are kept and sorted last.
    `days <= 0` disables the cutoff (keep all, just sorted). Pure (pass `now` in tests)."""
    now = now or datetime.now(timezone.utc)
    kept = items
    if days and days > 0:
        cutoff = now.timestamp() - days * 86400
        kept = [it for it in items if (_parse_date(it.published_at) is None
                                       or _parse_date(it.published_at).timestamp() >= cutoff)]

    def _key(it: NewsItem) -> float:
        d = _parse_date(it.published_at)
        return d.timestamp() if d else float("-inf")

    return sorted(kept, key=_key, reverse=True)
