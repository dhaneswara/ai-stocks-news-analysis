from app.analysis.scoring import (
    _breakout_signal,
    _catalyst_signal,
    _cross_signal,
    _low_proximity_signal,
    _momentum_signal,
    _rsi_signal,
    _trend_signal,
    _volume_signal,
)
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    Mention,
    PriceSummary,
    ScreenerConfig,
    StockData,
)

CFG = ScreenerConfig()


def _pts(values):
    return [IndicatorPoint(time=f"d{i}", value=float(v)) for i, v in enumerate(values)]


def _candles(closes, vols=None):
    vols = vols or [1_000_000.0] * len(closes)
    return [
        Candle(time=f"d{i}", open=c, high=c, low=c, close=c, volume=float(v))
        for i, (c, v) in enumerate(zip(closes, vols))
    ]


def _stock(*, rsi_series=(50.0, 50.0), sma50_series=(100.0, 100.0), sma200_series=(100.0, 100.0),
           price=100.0, change_pct=0.0, week52_low=50.0, week52_high=150.0, dist_high=-10.0,
           closes=None, vols=None, ticker="AAPL", company="Apple Inc."):
    closes = closes if closes is not None else [100.0] * 30
    return StockData(
        ticker=ticker, company_name=company, as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=price, change=0.0, change_pct=change_pct, currency="USD"),
        candles=_candles(closes, vols),
        fundamentals=Fundamentals(week52_low=week52_low, week52_high=week52_high),
        indicators=Indicators(sma50=_pts(sma50_series), sma200=_pts(sma200_series),
                              rsi14=_pts(rsi_series), dist_from_52wk_high_pct=dist_high),
    )


def test_rsi_oversold_is_bullish():
    sig = _rsi_signal(_stock(rsi_series=(40, 25)), CFG)
    assert sig.signed > 0 and sig.intensity > 0 and "oversold" in sig.reason


def test_rsi_overbought_is_bearish():
    sig = _rsi_signal(_stock(rsi_series=(60, 80)), CFG)
    assert sig.signed < 0 and "overbought" in sig.reason


def test_rsi_neutral_is_silent():
    assert _rsi_signal(_stock(rsi_series=(50, 55)), CFG).intensity == 0


def test_low_proximity_near_low_is_bullish():
    sig = _low_proximity_signal(_stock(price=52, week52_low=50))
    assert sig.signed > 0 and "52-wk low" in sig.reason


def test_low_proximity_far_is_silent():
    assert _low_proximity_signal(_stock(price=100, week52_low=50)).intensity == 0


def test_golden_cross_is_bullish():
    sig = _cross_signal(_stock(sma50_series=(99, 101), sma200_series=(100, 100)), CFG)
    assert sig.signed == 1.0 and "golden" in sig.reason


def test_death_cross_is_bearish():
    sig = _cross_signal(_stock(sma50_series=(101, 99), sma200_series=(100, 100)), CFG)
    assert sig.signed == -1.0 and "death" in sig.reason


def test_trend_uptrend_and_downtrend():
    up = _trend_signal(_stock(price=120, sma50_series=(110, 110), sma200_series=(100, 100)))
    down = _trend_signal(_stock(price=80, sma50_series=(90, 90), sma200_series=(100, 100)))
    assert up.signed > 0 and down.signed < 0


def test_momentum_positive_and_insufficient():
    pos = _momentum_signal(_stock(closes=[100.0] * 29 + [115.0]))
    assert pos.signed > 0 and "1mo" in pos.reason
    assert _momentum_signal(_stock(closes=[100.0] * 10)).intensity == 0


def test_breakout_near_high_only():
    assert _breakout_signal(_stock(dist_high=-1.0)).signed > 0
    assert _breakout_signal(_stock(dist_high=-20.0)).intensity == 0


def test_volume_surge_has_no_direction():
    vols = [1_000_000.0] * 29 + [3_000_000.0]
    sig = _volume_signal(_stock(closes=[100.0] * 30, vols=vols))
    assert sig.intensity > 0 and sig.signed == 0 and "avg" in sig.reason
    assert _volume_signal(_stock(closes=[100.0] * 30)).intensity == 0


def test_catalyst_boosts_without_direction():
    m = [Mention(post_id="1", created_at="t", matched="$AAPL", excerpt="x", url="")]
    sig = _catalyst_signal(m)
    assert sig.intensity > 0 and sig.signed == 0
    assert _catalyst_signal([]).intensity == 0
