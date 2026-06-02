from app.alerts.rules import evaluate_rules
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    PriceSummary,
    StockData,
)


def _pts(values):
    return [IndicatorPoint(time=f"2026-06-0{i+1}", value=v) for i, v in enumerate(values)]


def _stock(rsi=None, sma50=None, sma200=None, last_date="2026-06-02"):
    return StockData(
        ticker="AAPL",
        company_name="Apple Inc.",
        as_of="t",
        price=PriceSummary(current=1.0, change=0.0, change_pct=0.0),
        candles=[Candle(time="2026-06-01", open=1, high=1, low=1, close=1, volume=1),
                 Candle(time=last_date, open=1, high=1, low=1, close=1, volume=1)],
        fundamentals=Fundamentals(),
        indicators=Indicators(rsi14=_pts(rsi or []), sma50=_pts(sma50 or []), sma200=_pts(sma200 or [])),
        news=[],
    )


def test_golden_cross_fires_buy():
    hits = evaluate_rules(_stock(sma50=[9, 11], sma200=[10, 10]))
    assert [(h.rule_id, h.action) for h in hits] == [("golden_cross", "buy")]
    assert hits[0].candle_date == "2026-06-02"


def test_death_cross_fires_sell():
    hits = evaluate_rules(_stock(sma50=[11, 9], sma200=[10, 10]))
    assert [(h.rule_id, h.action) for h in hits] == [("death_cross", "sell")]


def test_no_cross_when_persisting():
    hits = evaluate_rules(_stock(sma50=[12, 13], sma200=[10, 10]))
    assert hits == []


def test_rsi_oversold_fires_buy():
    hits = evaluate_rules(_stock(rsi=[35, 28]))
    assert [(h.rule_id, h.action) for h in hits] == [("rsi_oversold", "buy")]


def test_rsi_overbought_fires_sell():
    hits = evaluate_rules(_stock(rsi=[65, 72]))
    assert [(h.rule_id, h.action) for h in hits] == [("rsi_overbought", "sell")]


def test_rsi_no_fire_when_already_below():
    hits = evaluate_rules(_stock(rsi=[25, 26]))
    assert hits == []


def test_short_series_skipped():
    hits = evaluate_rules(_stock(rsi=[28], sma50=[11], sma200=[10]))
    assert hits == []


def test_custom_thresholds():
    hits = evaluate_rules(_stock(rsi=[45, 39]), rsi_low=40, rsi_high=80)
    assert [(h.rule_id) for h in hits] == ["rsi_oversold"]
