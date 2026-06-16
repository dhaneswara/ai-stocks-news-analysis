from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import yfinance as yf

from app.models.schemas import Candle, Fundamentals, PriceSummary

# --- Network boundary (monkeypatched in tests) ---------------------------------

_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def drop_incomplete(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with a NaN in any OHLCV column — typically the current day's
    not-yet-closed bar, which yfinance returns with a NaN Close. Left in, the NaN
    survives model construction (NaN is a valid float) but pydantic serialises it to
    JSON null when StockData is cached, which then fails to re-validate on read."""
    cols = [c for c in _OHLCV if c in df.columns]
    return df.dropna(subset=cols) if cols else df


def latest_completed_trading_day(now: datetime | None = None) -> date:
    """The most recent weekday strictly before `now`'s US-Eastern calendar date — the latest
    *completed* trading day. Holidays are not modeled (mirrors the frontend marketClock), so on a
    market holiday this is a mild, rare over-report. `now` may be tz-aware or naive-UTC; default is
    the current instant. Uses pandas' tz conversion (pytz, vendored via yfinance) — not stdlib
    zoneinfo, which would need `tzdata` on Windows."""
    ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    et_date = ts.tz_convert("America/New_York").date()
    cur = et_date - timedelta(days=1)
    while cur.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        cur -= timedelta(days=1)
    return cur


def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    return drop_incomplete(df)


def fetch_close_series(ticker: str, period: str = "2y") -> list[tuple[str, float]]:
    """Ordered (YYYY-MM-DD, close) pairs for the period — trading days only."""
    df = fetch_history(ticker, period)
    closes = df["Close"].astype("float64")
    return [(pd.Timestamp(ts).strftime("%Y-%m-%d"), float(v)) for ts, v in closes.items()]


def fetch_info(ticker: str) -> dict:
    try:
        return dict(yf.Ticker(ticker).info)
    except Exception:
        return {}


# --- Pure builders -------------------------------------------------------------


def build_candles(df: pd.DataFrame) -> list[Candle]:
    candles: list[Candle] = []
    for ts, row in df.iterrows():
        candles.append(
            Candle(
                time=pd.Timestamp(ts).strftime("%Y-%m-%d"),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
        )
    return candles


def build_price(df: pd.DataFrame) -> PriceSummary:
    close = df["Close"].astype("float64")
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    change = current - prev
    change_pct = (change / prev * 100) if prev else 0.0
    return PriceSummary(current=round(current, 4), change=round(change, 4), change_pct=change_pct)


def build_fundamentals(info: dict) -> Fundamentals:
    return Fundamentals(
        market_cap=info.get("marketCap"),
        pe_ratio=info.get("trailingPE"),
        eps=info.get("trailingEps"),
        dividend_yield=info.get("dividendYield"),
        week52_high=info.get("fiftyTwoWeekHigh"),
        week52_low=info.get("fiftyTwoWeekLow"),
    )


def company_name(info: dict, ticker: str) -> str:
    return info.get("longName") or info.get("shortName") or ticker


_EXCHANGE_NAMES = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NaN": "",
    "NYQ": "NYSE", "PCX": "NYSE Arca", "ASE": "NYSE American", "BTS": "BATS",
}


def friendly_exchange(info: dict) -> str:
    """Human-readable exchange from yfinance `.info` — maps the common short codes, else
    falls back to `fullExchangeName`, else the raw code, else ''."""
    code = str(info.get("exchange") or "").strip()
    if code in _EXCHANGE_NAMES:
        return _EXCHANGE_NAMES[code]
    full = str(info.get("fullExchangeName") or "").strip()
    return full or code
