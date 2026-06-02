from __future__ import annotations

from app.models.schemas import RuleHit, StockData


def evaluate_rules(stock: StockData, rsi_low: float = 30.0, rsi_high: float = 70.0) -> list[RuleHit]:
    """Detect crossover events on the latest bar (stateless: latest vs prior point)."""
    hits: list[RuleHit] = []
    ind = stock.indicators
    date = stock.candles[-1].time if stock.candles else ""

    rsi = ind.rsi14
    if len(rsi) >= 2:
        prev, curr = rsi[-2].value, rsi[-1].value
        if prev >= rsi_low and curr < rsi_low:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="rsi_oversold", action="buy",
                                candle_date=date, message=f"RSI(14) crossed below {rsi_low:g} ({curr:.1f}) — oversold."))
        elif prev <= rsi_high and curr > rsi_high:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="rsi_overbought", action="sell",
                                candle_date=date, message=f"RSI(14) crossed above {rsi_high:g} ({curr:.1f}) — overbought."))

    s50, s200 = ind.sma50, ind.sma200
    if len(s50) >= 2 and len(s200) >= 2:
        p50, c50 = s50[-2].value, s50[-1].value
        p200, c200 = s200[-2].value, s200[-1].value
        if p50 <= p200 and c50 > c200:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="golden_cross", action="buy",
                                candle_date=date, message="SMA50 crossed above SMA200 (golden cross)."))
        elif p50 >= p200 and c50 < c200:
            hits.append(RuleHit(ticker=stock.ticker, rule_id="death_cross", action="sell",
                                candle_date=date, message="SMA50 crossed below SMA200 (death cross)."))

    return hits
