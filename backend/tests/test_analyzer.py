import json

from app.analysis.analyzer import analyze, build_user_prompt, extract_json
from app.models.schemas import (
    Fundamentals,
    Indicators,
    PriceSummary,
    Settings,
    StockData,
)

VALID_PAYLOAD = {
    "overall_summary": "Solid uptrend.",
    "news_analysis": "Positive earnings coverage.",
    "sentiment": "bullish",
    "current_recommendation": "buy",
    "confidence": 0.72,
    "signals": [
        {"date": "2026-04-15", "action": "buy", "price": 150.0, "confidence": 0.7, "reasoning": "Breakout."}
    ],
    "risks": ["Macro headwinds."],
}


def _stock():
    return StockData(
        ticker="AAPL",
        company_name="Apple Inc.",
        as_of="2026-06-02",
        price=PriceSummary(current=150.0, change=1.0, change_pct=0.7),
        candles=[],
        fundamentals=Fundamentals(pe_ratio=25.0),
        indicators=Indicators(dist_from_52wk_high_pct=-5.0),
        news=[],
    )


class FakeProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def test_extract_json_handles_code_fence():
    raw = "Here:\n```json\n{\"a\": 1}\n```\nthanks"
    assert extract_json(raw) == {"a": 1}


def test_extract_json_handles_fenced_nested():
    raw = '```json\n{"signals": [{"action": "buy", "price": 1}], "risks": ["x"]}\n```'
    result = extract_json(raw)
    assert result["signals"][0]["action"] == "buy"
    assert result["risks"] == ["x"]


def test_build_user_prompt_mentions_ticker_and_json():
    prompt = build_user_prompt(_stock())
    assert "AAPL" in prompt
    assert "JSON" in prompt


def test_analyze_parses_valid_result():
    provider = FakeProvider([json.dumps(VALID_PAYLOAD)])
    result = analyze(_stock(), provider, model="m", provider_name="fake")
    assert result.current_recommendation == "buy"
    assert result.signals[0].date == "2026-04-15"
    assert result.ticker == "AAPL"
    assert result.provider == "fake"
    assert provider.calls == 1


def test_analyze_retries_once_on_bad_json():
    provider = FakeProvider(["not json at all", json.dumps(VALID_PAYLOAD)])
    result = analyze(_stock(), provider, model="m", provider_name="fake")
    assert result.sentiment == "bullish"
    assert provider.calls == 2


def test_analyze_raises_after_two_failures():
    import pytest

    from app.llm.base import LLMError

    provider = FakeProvider(["nope", "still nope"])
    with pytest.raises(LLMError):
        analyze(_stock(), provider, model="m", provider_name="fake")
