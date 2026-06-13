import json
import pytest
from app.models.schemas import NewsProviderConfig
from app.news import tavily as tmod
from app.news.base import NewsError
from app.news.tavily import TavilyNewsProvider

SAMPLE = json.dumps({"results": [
    {"title": "NVDA partners with X", "url": "https://www.reuters.com/a",
     "content": "snippet text", "published_date": "2026-06-12T00:00:00Z"},
    {"title": "no url skipped"},
]})

def test_tavily_parses_results_and_maps_fields(monkeypatch):
    captured = {}
    def fake_call(url, tool, arguments, *, headers=None, timeout=20.0):
        captured.update(url=url, tool=tool, arguments=arguments)
        return SAMPLE
    monkeypatch.setattr(tmod, "call_tool_text", fake_call)
    cfg = NewsProviderConfig(api_key="key", mcp_url="https://mcp.tavily.com/mcp/")
    out = TavilyNewsProvider(cfg).search("NVDA", limit=5, recency_days=3650)
    assert captured["tool"] == "tavily_search"
    assert "tavilyApiKey=key" in captured["url"]
    assert captured["arguments"] == {"query": "NVDA", "max_results": 5, "topic": "news", "days": 3650}
    assert len(out) == 1
    item = out[0]
    assert (item.title, item.url, item.summary, item.source) == (
        "NVDA partners with X", "https://www.reuters.com/a", "snippet text", "reuters.com")

def test_tavily_requires_key():
    with pytest.raises(NewsError):
        TavilyNewsProvider(NewsProviderConfig()).search("x", limit=5, recency_days=90)
