"""you.com MCP adapter — tool `you-search`, Bearer auth, result {web:[…], news:[…]}."""
from __future__ import annotations

import json

from app.data.news import recent_news
from app.models.schemas import NewsItem, NewsProviderConfig
from app.news.base import NewsError, host_of
from app.news.mcp_client import call_tool_text


class YouNewsProvider:
    label = "you.com"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg

    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]:
        if not self._cfg.api_key:
            raise NewsError("you.com API key is not set")
        text = call_tool_text(
            self._cfg.mcp_url, "you-search", {"query": query},
            headers={"Authorization": f"Bearer {self._cfg.api_key}"},
        )
        return recent_news(_parse(text), days=recency_days)[:limit]


def _parse(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict):
        return []
    out: list[NewsItem] = []
    for bucket in ("news", "web"):                       # news first
        for r in data.get(bucket, []) or []:
            if not isinstance(r, dict) or not r.get("url"):
                continue
            url = str(r.get("url", ""))
            snippets = [s for s in (r.get("snippets") or []) if isinstance(s, str)]
            summary = " ".join(snippets) or str(r.get("description", ""))
            out.append(NewsItem(
                title=str(r.get("title", "")), url=url, source=host_of(url),
                published_at=str(r.get("page_age", "")), summary=summary,
            ))
    return out
