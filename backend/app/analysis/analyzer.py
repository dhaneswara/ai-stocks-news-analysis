from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from app.llm.base import LLMError, LLMProvider
from app.models.schemas import DISCLAIMER, AnalysisResult, StockData

_SYSTEM_PROMPT = (
    "You are a cautious equity research assistant for a swing trader. "
    "You analyze price action, simple indicators, fundamentals, and recent news. "
    "You are NOT a guaranteed predictor; you provide reasoned decision support. "
    "Respond with ONLY a single JSON object, no prose, no code fences."
)

_JSON_SCHEMA_HINT = """Return JSON with exactly these fields:
{
  "overall_summary": string,
  "news_analysis": string,
  "sentiment": "bullish" | "neutral" | "bearish",
  "current_recommendation": "buy" | "sell" | "hold",
  "confidence": number between 0 and 1,
  "signals": [ { "date": "YYYY-MM-DD", "action": "buy" | "sell", "price": number, "confidence": number, "reasoning": string } ],
  "risks": [ string ]
}
Signal dates MUST fall within the provided price history range."""


def build_user_prompt(stock: StockData) -> str:
    rsi_latest = stock.indicators.rsi14[-1].value if stock.indicators.rsi14 else None
    sma50_latest = stock.indicators.sma50[-1].value if stock.indicators.sma50 else None
    sma200_latest = stock.indicators.sma200[-1].value if stock.indicators.sma200 else None
    date_range = (
        f"{stock.candles[0].time} to {stock.candles[-1].time}" if stock.candles else "n/a"
    )
    headlines = "\n".join(
        f"- [{n.published_at}] {n.title} ({n.source})" for n in stock.news[:10]
    ) or "- (no recent headlines found)"

    return f"""Analyze {stock.company_name} ({stock.ticker}) for a swing trader.

PRICE HISTORY: {len(stock.candles)} daily candles, {date_range}.
CURRENT PRICE: {stock.price.current} ({stock.price.change_pct:.2f}% vs prev close).

INDICATORS (latest):
- RSI(14): {rsi_latest}
- SMA50: {sma50_latest}
- SMA200: {sma200_latest}
- Distance from 52-week high: {stock.indicators.dist_from_52wk_high_pct}%

FUNDAMENTALS:
- Market cap: {stock.fundamentals.market_cap}
- P/E: {stock.fundamentals.pe_ratio}
- EPS: {stock.fundamentals.eps}
- 52wk high/low: {stock.fundamentals.week52_high} / {stock.fundamentals.week52_low}

RECENT NEWS HEADLINES:
{headlines}

{_JSON_SCHEMA_HINT}"""


def extract_json(raw: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    if not fenced:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    return json.loads(candidate)


def _to_result(payload: dict, ticker: str, provider_name: str, model: str) -> AnalysisResult:
    if not isinstance(payload, dict):
        raise TypeError("LLM response was not a JSON object")
    # Drop any reserved keys the model may have echoed, so they don't collide
    # with the values we set explicitly below.
    reserved = {"ticker", "provider", "model", "generated_at", "disclaimer"}
    fields = {k: v for k, v in payload.items() if k not in reserved}
    return AnalysisResult(
        ticker=ticker,
        provider=provider_name,
        model=model,
        generated_at=datetime.now(timezone.utc).isoformat(),
        disclaimer=DISCLAIMER,
        **fields,
    )


def analyze(
    stock: StockData, provider: LLMProvider, model: str, provider_name: str
) -> AnalysisResult:
    system = _SYSTEM_PROMPT
    user = build_user_prompt(stock)

    raw = provider.complete(system, user)
    try:
        return _to_result(extract_json(raw), stock.ticker, provider_name, model)
    except (json.JSONDecodeError, ValidationError, TypeError):
        pass  # fall through to one repair attempt

    repair = (
        user
        + "\n\nYour previous reply was not valid JSON for the schema. "
        "Reply with ONLY the corrected JSON object."
    )
    raw2 = provider.complete(system, repair)
    try:
        return _to_result(extract_json(raw2), stock.ticker, provider_name, model)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise LLMError(f"Model did not return valid analysis JSON: {exc}") from exc
