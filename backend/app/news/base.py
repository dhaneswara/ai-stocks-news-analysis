"""News provider abstraction: one interface, many sources (Google RSS / MCP search servers)."""
from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from app.models.schemas import NewsItem


class NewsError(Exception):
    """Any news-fetch failure; callers degrade to an empty list."""


class NewsProvider(Protocol):
    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]: ...


def host_of(url: str) -> str:
    """The display host for a result URL ('www.' stripped); '' when unparseable."""
    try:
        net = urlparse(url).netloc
    except Exception:  # noqa: BLE001
        return ""
    return net[4:] if net.startswith("www.") else net
