"""Exa MCP adapter — tool `web_search_exa`, key in the `x-api-key` header, result `results[]`."""
from __future__ import annotations

import json

from app.data.news import recent_news
from app.models.schemas import NewsItem, NewsProviderConfig
from app.news.base import NewsError, host_of
from app.news.mcp_client import call_tool_text


class ExaNewsProvider:
    label = "Exa"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg

    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]:
        if not self._cfg.api_key:
            raise NewsError("Exa API key is not set")
        text = call_tool_text(
            self._cfg.mcp_url, "web_search_exa", {"query": query, "numResults": limit},
            headers={"x-api-key": self._cfg.api_key},
        )
        return recent_news(_parse(text), days=recency_days)


def _parse(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    rows = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    out: list[NewsItem] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        url = str(r.get("url", ""))
        out.append(NewsItem(
            title=str(r.get("title", "")), url=url,
            source=str(r.get("author", "")) or host_of(url),
            published_at=str(r.get("publishedDate", "")), summary=str(r.get("text", "")),
        ))
    return out
