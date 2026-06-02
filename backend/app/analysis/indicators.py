from __future__ import annotations

import pandas as pd

from app.models.schemas import IndicatorParams, IndicatorPoint, Indicators


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    # All-gains => avg_loss 0 => rs inf => out 100 (NaN only where avg_loss is NaN too).
    out = out.where(avg_loss != 0, 100.0)
    return out


def dist_from_52wk_high_pct(high: pd.Series, last_close: float) -> float:
    window = high.tail(252)
    high_val = float(window.max())
    if high_val == 0:
        return 0.0
    return round((last_close - high_val) / high_val * 100, 2)


def _series_to_points(series: pd.Series) -> list[IndicatorPoint]:
    points: list[IndicatorPoint] = []
    for ts, value in series.dropna().items():
        points.append(
            IndicatorPoint(time=pd.Timestamp(ts).strftime("%Y-%m-%d"), value=round(float(value), 4))
        )
    return points


def compute_indicators(df: pd.DataFrame, params: IndicatorParams) -> Indicators:
    close = df["Close"].astype("float64")
    sma50_win = params.sma_windows[0] if len(params.sma_windows) > 0 else 50
    sma200_win = params.sma_windows[1] if len(params.sma_windows) > 1 else 200
    last_close = float(close.iloc[-1])
    return Indicators(
        sma50=_series_to_points(sma(close, sma50_win)),
        sma200=_series_to_points(sma(close, sma200_win)),
        rsi14=_series_to_points(rsi(close, params.rsi_length)),
        dist_from_52wk_high_pct=dist_from_52wk_high_pct(df["High"].astype("float64"), last_close),
    )
