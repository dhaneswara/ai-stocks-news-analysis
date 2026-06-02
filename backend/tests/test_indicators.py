import pandas as pd

from app.analysis.indicators import (
    compute_indicators,
    dist_from_52wk_high_pct,
    rsi,
    sma,
)
from app.models.schemas import IndicatorParams


def _close(values):
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


def test_sma_last_value():
    s = _close([1, 2, 3, 4, 5])
    result = sma(s, 3)
    assert result.iloc[-1] == 4.0  # mean(3,4,5)


def test_rsi_all_gains_is_100():
    s = _close(list(range(1, 40)))  # strictly increasing
    assert rsi(s, 14).iloc[-1] > 99.9


def test_rsi_all_losses_is_0():
    s = _close(list(range(40, 1, -1)))  # strictly decreasing
    assert rsi(s, 14).iloc[-1] < 0.1


def test_dist_from_52wk_high():
    highs = _close([50, 80, 100, 90])
    assert dist_from_52wk_high_pct(highs, last_close=90.0) == -10.0


def test_compute_indicators_shape():
    idx = pd.date_range("2024-01-01", periods=260, freq="D")
    df = pd.DataFrame(
        {
            "Open": range(260),
            "High": [v + 1 for v in range(260)],
            "Low": [v - 1 for v in range(260)],
            "Close": range(260),
            "Volume": [1000] * 260,
        },
        index=idx,
    ).astype("float64")
    ind = compute_indicators(df, IndicatorParams())
    assert len(ind.sma50) > 0
    assert len(ind.sma200) > 0
    assert all(0 <= p.value <= 100 for p in ind.rsi14)
    assert ind.dist_from_52wk_high_pct is not None
