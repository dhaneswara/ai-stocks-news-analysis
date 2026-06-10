from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from pydantic import ValidationError

from app.llm.base import LLMError, LLMProvider
from app.models.schemas import DISCLAIMER, AnalysisResult, MarketMood, Mention, NetworkSignal, Signal, StockData

_SYSTEM_PROMPT = (
    "You are a cautious equity research assistant for a swing trader. "
    "You analyze price action, simple indicators, fundamentals, and recent news, and you "
    "weigh the news together with the technicals and fundamentals when forming a recommendation. "
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
  "key_factors": [ string ],
  "signals": [ { "date": "YYYY-MM-DD", "action": "buy" | "sell", "price": number, "confidence": number, "reasoning": string } ],
  "risks": [ string ]
}
Base current_recommendation on ALL the evidence together — the technical indicators
(RSI, SMA50/200, distance from 52-week high), the fundamentals, AND the recent news headlines.
"key_factors" must list 3-6 concrete drivers behind current_recommendation, each citing a
specific input and its lean — e.g. "RSI 72 - overbought (bearish)", "Price above SMA200 -
uptrend intact (bullish)", "News: cloud revenue beat reported (bullish)". Include at least one
news-derived factor whenever headlines are provided.
Signal dates MUST fall within the provided price history range.
TIMING DISCIPLINE — buy low, sell high. A BUY marks a favorable ENTRY at a relatively LOW
price: a pullback/dip, oversold RSI (roughly < 40), or a bounce off support / a rising SMA.
A SELL marks a favorable EXIT at a relatively HIGH price: a rally or local peak, overbought
RSI (roughly > 65), or resistance near the 52-week high. Do NOT place a BUY at or near a
local price PEAK, or a SELL at or near a local TROUGH. Across the whole set your BUY prices
should generally sit BELOW your SELL prices — a sequence that buys high and then sells lower
is wrong and must be corrected before you answer.
Identify BOTH buy entries and sell exits where the data supports them — over a multi-year
history there are usually some of each, so do NOT return only buys. Aim for roughly 3-8
signals spanning the range, each on a distinct date. Each signal's "reasoning" must name the
price-level logic (e.g. "oversold bounce off ~120 support" for a buy; "overbought into
resistance near the 52-wk high" for a sell)."""


def _format_mood(mood: MarketMood | None) -> str:
    if mood is None or mood.post_count == 0:
        return "- (Trump / Truth Social signal disabled or no recent posts)"
    themes = "; ".join(f"{t.label} ({t.lean})" for t in mood.themes) or "(none)"
    return (
        f"- Lean: {mood.lean} (confidence {mood.confidence:.2f})\n"
        f"- Summary: {mood.summary}\n"
        f"- Themes: {themes}"
    )


def _format_mentions(mentions: list[Mention]) -> str:
    if not mentions:
        return "- (none)"
    return "\n".join(f'- [{m.created_at}] "{m.excerpt}" ({m.url})' for m in mentions[:8])


def _format_network(net: NetworkSignal | None) -> str:
    if net is None or not net.influences:
        return "- (no company-network signal)"
    lines = []
    for i in net.influences[:6]:
        lean = "bullish" if i.signed > 0 else "bearish" if i.signed < 0 else "neutral"
        lines.append(
            f"- {i.type} {i.neighbour} ({i.name}): neighbour is {i.neighbour_direction}, "
            f"news {i.edge_sentiment} -> {lean} for {net.ticker}"
        )
    return "\n".join(lines)


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

    track_block = ""
    if stock.track_record:
        track_block = (
            "YOUR TRACK RECORD ON THIS TICKER (your own past tracked calls, scored against "
            "actual prices):\n" + stock.track_record +
            "\nWeigh this as calibration evidence about your own judgement on this name.\n\n"
        )

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

MARKET MOOD (recent Trump / Truth Social posts):
{_format_mood(stock.market_mood)}

TRUMP MENTIONS OF THIS COMPANY:
{_format_mentions(stock.trump_mentions)}

Weigh MARKET MOOD as a macro overlay and TRUMP MENTIONS as a stock-specific factor, the same way
you weigh news — but treat political-post inference as noisy and low-certainty: it must not
override strong technical or fundamental evidence, and you must NOT create dated buy/sell signals
from these posts (they inform the current recommendation only).

COMPANY NETWORK (relationships inferred from news; one hop):
{_format_network(stock.network)}

Weigh COMPANY NETWORK as a stock-specific factor like news, but treat it as noisy and
low-certainty: it must not override strong technical or fundamental evidence, and you must NOT
create dated buy/sell signals from it (it informs the current recommendation only).

{track_block}{_JSON_SCHEMA_HINT}"""


def extract_json(raw: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    candidate = fenced.group(1) if fenced else raw
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]
    return json.loads(candidate)


def _to_result(payload: dict, ticker: str, provider_name: str, model: str) -> AnalysisResult:
    if not isinstance(payload, dict):
        raise TypeError("LLM response was not a JSON object")
    # Drop any reserved keys the model may have echoed, so they don't collide
    # with the values we set explicitly below.
    reserved = {"ticker", "provider", "model", "generated_at", "disclaimer", "market_mood", "network"}
    fields = {k: v for k, v in payload.items() if k not in reserved}
    return AnalysisResult(
        ticker=ticker,
        provider=provider_name,
        model=model,
        generated_at=datetime.now(timezone.utc).isoformat(),
        disclaimer=DISCLAIMER,
        **fields,
    )


def _snap_signals(result: AnalysisResult, stock: StockData) -> AnalysisResult:
    """Snap each signal to the nearest real trading day (and that day's close) so every
    marker lands on a candle the chart actually has, instead of a weekend/holiday the
    model may have guessed."""
    if not stock.candles:
        return result
    cand = [(c.time, date.fromisoformat(c.time), c.close) for c in stock.candles]
    last = cand[-1]
    for sig in result.signals:
        try:
            target = date.fromisoformat(sig.date[:10])
        except (ValueError, TypeError):
            sig.date, sig.price = last[0], last[2]
            continue
        best = min(cand, key=lambda c: abs((c[1] - target).days))
        sig.date = best[0]
        sig.price = round(best[2], 4)
    return result


# Sanity-guard thresholds, expressed as a position within a signal's local price window
# (0.0 = window low, 1.0 = window high). A buy above _BUY_MAX_LOCAL_POS sits near a local
# peak; a sell below _SELL_MIN_LOCAL_POS sits near a local trough. Both are dropped.
_BUY_MAX_LOCAL_POS = 0.66
_SELL_MIN_LOCAL_POS = 0.34


def _local_window_radius(n: int) -> int:
    """Trading-day radius for the 'local' price window, scaled to history length."""
    return min(30, max(5, n // 10))


def _filter_incoherent_signals(result: AnalysisResult, stock: StockData) -> AnalysisResult:
    """Deterministic safety net so the chart never advises buying high / selling low.

    A signal is dropped if it fails EITHER check:
      1. Local window — a BUY must sit in the lower part of the surrounding price range (not
         at a local peak); a SELL must sit in the upper part (not at a local trough).
      2. Cross-signal — a BUY must have at least one later SELL priced above it (a profitable
         exit exists); a SELL must have at least one earlier BUY priced below it (it exits a
         real entry at a gain). Signals with no counterpart yet (e.g. the most recent entry)
         are exempt from this second check.

    Runs after _snap_signals, so every signal's date/price already matches a real candle.
    """
    candles = stock.candles
    if not candles or not result.signals:
        return result

    closes = [c.close for c in candles]
    index_by_date = {c.time: i for i, c in enumerate(candles)}
    n = len(closes)
    radius = _local_window_radius(n)
    sigs = sorted(result.signals, key=lambda s: s.date)

    kept: list[Signal] = []
    for s in sigs:
        # 1) Position within the local price window.
        i = index_by_date.get(s.date)
        if i is not None:
            window = closes[max(0, i - radius) : min(n, i + radius + 1)]
            lo, hi = min(window), max(window)
            if hi > lo:
                pos = (s.price - lo) / (hi - lo)
                if s.action == "buy" and pos > _BUY_MAX_LOCAL_POS:
                    continue
                if s.action == "sell" and pos < _SELL_MIN_LOCAL_POS:
                    continue

        # 2) Cross-signal coherence (only enforced when a counterpart exists).
        if s.action == "buy":
            later_sells = [t.price for t in sigs if t.action == "sell" and t.date > s.date]
            if later_sells and max(later_sells) <= s.price:
                continue
        else:
            earlier_buys = [t.price for t in sigs if t.action == "buy" and t.date < s.date]
            if earlier_buys and min(earlier_buys) >= s.price:
                continue

        kept.append(s)

    result.signals = kept
    return result


def analyze(
    stock: StockData, provider: LLMProvider, model: str, provider_name: str
) -> AnalysisResult:
    system = _SYSTEM_PROMPT
    user = build_user_prompt(stock)

    def _finalize(text: str) -> AnalysisResult:
        result = _to_result(extract_json(text), stock.ticker, provider_name, model)
        result.market_mood = stock.market_mood
        result.network = stock.network
        return _filter_incoherent_signals(_snap_signals(result, stock), stock)

    raw = provider.complete(system, user)
    try:
        return _finalize(raw)
    except (json.JSONDecodeError, ValidationError, TypeError):
        pass  # fall through to one repair attempt

    repair = (
        user
        + "\n\nYour previous reply was not valid JSON for the schema. "
        "Reply with ONLY the corrected JSON object."
    )
    raw2 = provider.complete(system, repair)
    try:
        return _finalize(raw2)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise LLMError(f"Model did not return valid analysis JSON: {exc}") from exc
