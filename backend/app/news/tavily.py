"""Tavily MCP adapter — tool `tavily_search`, key in the URL query, result `results[]`."""
from __future__ import annotations

import json

from app.data.news import recent_news
from app.models.schemas import NewsItem, NewsProviderConfig
from app.news.base import NewsError, host_of
from app.news.mcp_client import call_tool_text


class TavilyNewsProvider:
    label = "Tavily"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg

    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]:
        if not self._cfg.api_key:
            raise NewsError("Tavily API key is not set")
        url = f"{self._cfg.mcp_url.rstrip('/')}/?tavilyApiKey={self._cfg.api_key}"
        args = {"query": query, "max_results": limit, "topic": "news", "days": recency_days}
        items = _parse(call_tool_text(url, "tavily_search", args))
        return recent_news(items, days=recency_days)


def _parse(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    rows = data.get("results", []) if isinstance(data, dict) else []
    out: list[NewsItem] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        url = str(r.get("url", ""))
        out.append(NewsItem(
            title=str(r.get("title", "")), url=url, source=host_of(url),
            published_at=str(r.get("published_date", "")), summary=str(r.get("content", "")),
        ))
    return out
