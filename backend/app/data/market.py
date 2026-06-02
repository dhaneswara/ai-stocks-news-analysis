from __future__ import annotations

import pandas as pd
import yfinance as yf

from app.models.schemas import Candle, Fundamentals, PriceSummary

# --- Network boundary (monkeypatched in tests) ---------------------------------


def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)


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
