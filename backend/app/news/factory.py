"""Build a NewsProvider from settings, mirroring app/llm/factory.py (env-key fallback)."""
from __future__ import annotations

import os

from app.models.schemas import NEWS_DEFAULT_MCP_URLS, NewsProviderConfig, Settings
from app.news.base import NewsError, NewsProvider
from app.news.exa import ExaNewsProvider
from app.news.google import GoogleNewsProvider
from app.news.tavily import TavilyNewsProvider
from app.news.you import YouNewsProvider

_REGISTRY = {
    "google": GoogleNewsProvider,
    "tavily": TavilyNewsProvider,
    "exa": ExaNewsProvider,
    "you": YouNewsProvider,
}
_NEWS_ENV_KEYS = {"tavily": "TAVILY_API_KEY", "exa": "EXA_API_KEY", "you": "YDC_API_KEY"}
_NEWS_LABELS = {"google": "Google News", "tavily": "Tavily", "exa": "Exa", "you": "you.com"}


def resolve_news_config(provider_id: str, cfg: NewsProviderConfig) -> NewsProviderConfig:
    resolved = cfg.model_copy()
    if not resolved.api_key and provider_id in _NEWS_ENV_KEYS:
        resolved.api_key = os.environ.get(_NEWS_ENV_KEYS[provider_id], "")
    if not resolved.mcp_url and provider_id in NEWS_DEFAULT_MCP_URLS:
        resolved.mcp_url = NEWS_DEFAULT_MCP_URLS[provider_id]
    return resolved


def build_news_provider(settings: Settings, provider_id: str | None = None) -> NewsProvider:
    pid = provider_id or settings.news.active_provider
    cls = _REGISTRY.get(pid)
    if cls is None:
        raise NewsError(f"Unknown news provider '{pid}'")
    cfg = settings.news.providers.get(pid, NewsProviderConfig())
    return cls(resolve_news_config(pid, cfg))
