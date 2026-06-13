import json
import pytest
from app.models.schemas import NewsProviderConfig
from app.news import exa as emod
from app.news.base import NewsError
from app.news.exa import ExaNewsProvider

SAMPLE = json.dumps({"results": [
    {"title": "Exa hit", "url": "https://bloomberg.com/a", "text": "body text",
     "publishedDate": "2026-06-11T00:00:00Z", "author": "Reporter"},
    {"title": "no url"},
]})

def test_exa_parses_and_maps(monkeypatch):
    captured = {}
    def fake_call(url, tool, arguments, *, headers=None, timeout=20.0):
        captured.update(url=url, tool=tool, arguments=arguments, headers=headers)
        return SAMPLE
    monkeypatch.setattr(emod, "call_tool_text", fake_call)
    cfg = NewsProviderConfig(api_key="exakey", mcp_url="https://mcp.exa.ai/mcp")
    out = ExaNewsProvider(cfg).search("NVDA", limit=4, recency_days=3650)
    assert captured["tool"] == "web_search_exa"
    assert captured["headers"] == {"x-api-key": "exakey"}
    assert captured["arguments"] == {"query": "NVDA", "numResults": 4}
    assert len(out) == 1
    assert (out[0].title, out[0].url, out[0].summary, out[0].source) == (
        "Exa hit", "https://bloomberg.com/a", "body text", "Reporter")

def test_exa_requires_key():
    with pytest.raises(NewsError):
        ExaNewsProvider(NewsProviderConfig()).search("x", limit=4, recency_days=90)
