import json
import pytest
from app.models.schemas import NewsProviderConfig
from app.news import you as ymod
from app.news.base import NewsError
from app.news.you import YouNewsProvider

SAMPLE = json.dumps({
    "news": [{"title": "deal news", "url": "https://www.ft.com/n",
              "snippets": ["NVDA to acquire", "Y"], "page_age": "2026-06-12T00:00:00Z"}],
    "web": [{"title": "web hit", "url": "https://example.com/w",
             "description": "desc only", "page_age": "2026-06-11T00:00:00Z"}],
})

def test_you_parses_news_then_web_and_joins_snippets(monkeypatch):
    captured = {}
    def fake_call(url, tool, arguments, *, headers=None, timeout=20.0):
        captured.update(url=url, tool=tool, arguments=arguments, headers=headers)
        return SAMPLE
    monkeypatch.setattr(ymod, "call_tool_text", fake_call)
    cfg = NewsProviderConfig(api_key="ydc", mcp_url="https://api.you.com/mcp")
    out = YouNewsProvider(cfg).search("NVDA", limit=5, recency_days=3650)
    assert captured["tool"] == "you-search"
    assert captured["headers"] == {"Authorization": "Bearer ydc"}
    assert captured["arguments"] == {"query": "NVDA"}
    assert [i.title for i in out] == ["deal news", "web hit"]  # news bucket first
    assert out[0].summary == "NVDA to acquire Y"
    assert out[1].summary == "desc only"

def test_you_requires_key():
    with pytest.raises(NewsError):
        YouNewsProvider(NewsProviderConfig()).search("x", limit=5, recency_days=90)
