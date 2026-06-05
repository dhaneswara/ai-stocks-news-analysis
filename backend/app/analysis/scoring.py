"""Pure, deterministic opportunity scoring — no LLM, no I/O.

Each helper turns a `StockData` (plus Trump mentions) into a `_Sig`:
- intensity (0..1): how strongly the signal is firing → drives the 0–100 score.
- signed (-1..1): directional vote (+ bullish / − bearish); 0 means attention-only
  (volume surges and Trump mentions raise the score but never vote on direction).
- reason: a short human chip for the board.

`score_stock` (next task) blends these by weight.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.alerts.rules import evaluate_rules
from app.models.schemas import Mention, ScreenerConfig, StockData


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class _Sig:
    intensity: float = 0.0
    signed: float = 0.0
    reason: str = ""


def _last(points) -> float | None:
    return points[-1].value if points else None


def _return(candles, lookback: int) -> float | None:
    if len(candles) <= lookback:
        return None
    prev = candles[-1 - lookback].close
    if prev == 0:
        return None
    return candles[-1].close / prev - 1.0


def _rsi_signal(stock: StockData, cfg: ScreenerConfig) -> _Sig:
    rsi = _last(stock.indicators.rsi14)
    if rsi is None:
        return _Sig()
    if rsi <= cfg.rsi_low:
        inten = _clamp((cfg.rsi_low - rsi) / cfg.rsi_low)
        return _Sig(inten, inten, f"RSI {rsi:.0f} (oversold)")
    if rsi >= cfg.rsi_high:
        inten = _clamp((rsi - cfg.rsi_high) / (100.0 - cfg.rsi_high))
        return _Sig(inten, -inten, f"RSI {rsi:.0f} (overbought)")
    return _Sig()


def _low_proximity_signal(stock: StockData) -> _Sig:
    low = stock.fundamentals.week52_low
    price = stock.price.current
    if not low or low <= 0:
        return _Sig()
    dist = (price - low) / low
    if dist <= 0.10:
        inten = _clamp(1.0 - dist / 0.10)
        return _Sig(inten, inten, "near 52-wk low")
    return _Sig()


def _cross_signal(stock: StockData, cfg: ScreenerConfig) -> _Sig:
    for hit in evaluate_rules(stock, cfg.rsi_low, cfg.rsi_high):
        if hit.rule_id == "golden_cross":
            return _Sig(1.0, 1.0, "golden cross")
        if hit.rule_id == "death_cross":
            return _Sig(1.0, -1.0, "death cross")
    return _Sig()


def _trend_signal(stock: StockData) -> _Sig:
    price = stock.price.current
    s50 = _last(stock.indicators.sma50)
    s200 = _last(stock.indicators.sma200)
    if s50 is None or s200 is None:
        return _Sig()
    if price > s50 > s200:
        return _Sig(0.6, 0.6, "uptrend (price>SMA50>SMA200)")
    if price < s50 < s200:
        return _Sig(0.6, -0.6, "downtrend (price<SMA50<SMA200)")
    if price > s50:
        return _Sig(0.3, 0.3, "above SMA50")
    if price < s50:
        return _Sig(0.3, -0.3, "below SMA50")
    return _Sig()


def _momentum_signal(stock: StockData) -> _Sig:
    r = _return(stock.candles, 21)  # ~1 trading month
    if r is None:
        return _Sig()
    inten = _clamp(abs(r) / 0.15)  # a 15% move = full intensity
    sign = 1.0 if r >= 0 else -1.0
    return _Sig(inten, sign * inten, f"{r * 100:+.0f}% 1mo")


def _breakout_signal(stock: StockData) -> _Sig:
    dist = stock.indicators.dist_from_52wk_high_pct
    if dist is None:
        return _Sig()
    if dist >= -2.0:  # within 2% of the 52-wk high
        return _Sig(0.6, 0.6, "near 52-wk high (breakout)")
    return _Sig()


def _volume_signal(stock: StockData) -> _Sig:
    vols = [c.volume for c in stock.candles[-21:-1]]  # the prior 20 bars
    if len(vols) < 20:
        return _Sig()
    avg = sum(vols) / len(vols)
    if avg <= 0:
        return _Sig()
    ratio = stock.candles[-1].volume / avg
    if ratio >= 1.5:
        return _Sig(_clamp((ratio - 1.0) / 2.0), 0.0, f"volume {ratio:.1f}x avg")
    return _Sig()


def _catalyst_signal(mentions: list[Mention]) -> _Sig:
    if not mentions:
        return _Sig()
    inten = _clamp(0.5 * len(mentions))
    label = "Trump mention" if len(mentions) == 1 else f"Trump mention x{len(mentions)}"
    return _Sig(inten, 0.0, label)
