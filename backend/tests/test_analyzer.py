import json

from app.analysis.analyzer import analyze, build_user_prompt, extract_json
from app.models.schemas import (
    Candle,
    Fundamentals,
    Indicators,
    MarketMood,
    Mention,
    MoodTheme,
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
        self.json_modes = []   # records the json_mode of each call (agent passes False)
        self.stops = []        # records the stop sequences of each call (agent passes a list)

    def complete(self, system, user, json_mode=True, stop=None):
        self.calls += 1
        self.json_modes.append(json_mode)
        self.stops.append(stop)
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


def _stock_with_candles():
    return StockData(
        ticker="AAPL",
        company_name="Apple Inc.",
        as_of="2026-06-02",
        price=PriceSummary(current=120.0, change=1.0, change_pct=0.8),
        candles=[
            Candle(time="2026-04-10", open=99, high=101, low=98, close=100.0, volume=1),
            Candle(time="2026-04-13", open=108, high=112, low=107, close=110.0, volume=1),
            Candle(time="2026-04-14", open=118, high=122, low=117, close=120.0, volume=1),
        ],
        fundamentals=Fundamentals(pe_ratio=25.0),
        indicators=Indicators(dist_from_52wk_high_pct=-5.0),
        news=[],
    )


def test_analyze_snaps_signal_dates_to_trading_days():
    # Model returns a signal on 2026-04-12 (a Sunday) — not a real candle.
    payload = {
        **VALID_PAYLOAD,
        "signals": [
            {"date": "2026-04-12", "action": "sell", "price": 999.0, "confidence": 0.6,
             "reasoning": "Off-grid date should snap to the nearest trading day."}
        ],
    }
    provider = FakeProvider([json.dumps(payload)])
    result = analyze(_stock_with_candles(), provider, model="m", provider_name="fake")
    sig = result.signals[0]
    assert sig.date == "2026-04-13"   # nearest candle to the 12th
    assert sig.price == 110.0         # price re-anchored to that day's close


def _stock_from_closes(rows):
    """rows: list of (date, close) -> minimal StockData for guard tests."""
    candles = [Candle(time=d, open=c, high=c, low=c, close=c, volume=1) for d, c in rows]
    return StockData(
        ticker="TST",
        company_name="Test Co.",
        as_of=rows[-1][0],
        price=PriceSummary(current=rows[-1][1], change=0.0, change_pct=0.0),
        candles=candles,
        fundamentals=Fundamentals(),
        indicators=Indicators(),
        news=[],
    )


def _payload_with_signals(signals):
    return {**VALID_PAYLOAD, "signals": signals}


def _analyze_signals(rows, signals):
    provider = FakeProvider([json.dumps(_payload_with_signals(signals))])
    result = analyze(_stock_from_closes(rows), provider, model="m", provider_name="fake")
    return [(s.action, s.price) for s in result.signals]


def test_guard_drops_buy_at_local_peak_keeps_dip_buy():
    rows = [("2026-01-05", 100.0), ("2026-01-06", 110.0), ("2026-01-07", 120.0),
            ("2026-01-08", 130.0), ("2026-01-09", 140.0), ("2026-01-12", 150.0)]
    signals = [
        {"date": "2026-01-06", "action": "buy", "price": 110.0, "confidence": 0.6, "reasoning": "dip"},
        {"date": "2026-01-12", "action": "buy", "price": 150.0, "confidence": 0.6, "reasoning": "peak"},
    ]
    out = _analyze_signals(rows, signals)
    assert ("buy", 110.0) in out
    assert ("buy", 150.0) not in out   # buying the local peak is dropped


def test_guard_drops_sell_at_local_trough_keeps_rally_sell():
    rows = [("2026-02-02", 150.0), ("2026-02-03", 140.0), ("2026-02-04", 130.0),
            ("2026-02-05", 120.0), ("2026-02-06", 110.0), ("2026-02-09", 100.0)]
    signals = [
        {"date": "2026-02-02", "action": "sell", "price": 150.0, "confidence": 0.6, "reasoning": "rally"},
        {"date": "2026-02-09", "action": "sell", "price": 100.0, "confidence": 0.6, "reasoning": "trough"},
    ]
    out = _analyze_signals(rows, signals)
    assert ("sell", 150.0) in out
    assert ("sell", 100.0) not in out  # selling the local trough is dropped


def test_guard_drops_fully_inverted_set():
    # PLTR-shaped: a lone buy at the top, then sells below it -> nothing survives.
    rows = [("2026-01-15", 100.0), ("2026-01-16", 130.0), ("2026-01-20", 160.0),
            ("2026-01-21", 177.0), ("2026-02-02", 160.0), ("2026-03-10", 151.0),
            ("2026-04-01", 140.0), ("2026-05-20", 137.0), ("2026-06-03", 143.0)]
    signals = [
        {"date": "2026-01-21", "action": "buy", "price": 177.0, "confidence": 0.6, "reasoning": "x"},
        {"date": "2026-03-10", "action": "sell", "price": 151.0, "confidence": 0.6, "reasoning": "x"},
        {"date": "2026-05-20", "action": "sell", "price": 137.0, "confidence": 0.6, "reasoning": "x"},
        {"date": "2026-06-03", "action": "sell", "price": 143.0, "confidence": 0.6, "reasoning": "x"},
    ]
    out = _analyze_signals(rows, signals)
    assert out == []


def test_guard_keeps_coherent_buy_low_sell_high_set():
    rows = [("2026-01-05", 100.0), ("2026-01-06", 90.0), ("2026-01-07", 110.0),
            ("2026-01-08", 130.0), ("2026-01-09", 120.0), ("2026-01-12", 105.0),
            ("2026-01-13", 140.0)]
    signals = [
        {"date": "2026-01-06", "action": "buy", "price": 90.0, "confidence": 0.6, "reasoning": "x"},
        {"date": "2026-01-08", "action": "sell", "price": 130.0, "confidence": 0.6, "reasoning": "x"},
        {"date": "2026-01-12", "action": "buy", "price": 105.0, "confidence": 0.6, "reasoning": "x"},
        {"date": "2026-01-13", "action": "sell", "price": 140.0, "confidence": 0.6, "reasoning": "x"},
    ]
    out = _analyze_signals(rows, signals)
    assert len(out) == 4               # a clean buy-low/sell-high set is untouched


def _stock_with_mood():
    s = _stock()
    s.market_mood = MarketMood(
        lean="risk_off", confidence=0.7, summary="Tariff threats.",
        themes=[MoodTheme(label="Tariffs on China", lean="bearish", quote="massive")],
        as_of="2026-06-04T12:00:00Z", post_count=3,
    )
    s.trump_mentions = [Mention(post_id="1", created_at="2026-06-04T10:00:00Z",
                                matched="$AAPL", excerpt="love $AAPL", url="https://t/1")]
    return s


def test_prompt_includes_mood_and_mentions():
    prompt = build_user_prompt(_stock_with_mood())
    assert "MARKET MOOD" in prompt
    assert "risk_off" in prompt
    assert "TRUMP MENTIONS" in prompt
    assert "$AAPL" in prompt


def test_prompt_has_placeholders_when_signal_absent():
    prompt = build_user_prompt(_stock())  # no mood, no mentions
    assert "TRUMP MENTIONS" in prompt
    assert "(none)" in prompt


def test_analyze_surfaces_market_mood_on_result():
    provider = FakeProvider([json.dumps(VALID_PAYLOAD)])
    result = analyze(_stock_with_mood(), provider, model="m", provider_name="fake")
    assert result.market_mood is not None
    assert result.market_mood.lean == "risk_off"


def test_format_network_and_result_carries_it():
    from app.analysis.analyzer import _format_network, build_user_prompt
    from app.models.schemas import NetworkInfluence, NetworkSignal
    from tests.test_screener_service import _stock

    stock = _stock("AAPL")
    stock.network = NetworkSignal(ticker="AAPL", intensity=0.5, signed=-0.4, influences=[
        NetworkInfluence(neighbour="TSM", name="Taiwan Semi", type="supplier",
                         edge_sentiment="negative", neighbour_direction="sell",
                         signed=-0.4, reason="supplier TSM (bearish)")], reasons=["supplier TSM (bearish)"])
    assert "TSM" in _format_network(stock.network)
    assert "NETWORK" in build_user_prompt(stock).upper()
