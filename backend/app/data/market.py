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


def _last_date(df: pd.DataFrame | None) -> date | None:
    """The date of the last row, or None for an empty/None frame."""
    if df is None or len(df) == 0:
        return None
    return pd.Timestamp(df.index[-1]).date()


def _splice_tail(base: pd.DataFrame, extra: pd.DataFrame | None, target: date) -> pd.DataFrame:
    """Append rows from `extra` that fall strictly after `base`'s last date and on/before
    `target` (the latest completed trading day). Existing rows are never replaced (base wins on a
    date clash), and any row after `target` — e.g. today's in-progress bar — is dropped. This is
    the single enforcement point of the finalized-only invariant."""
    if extra is None or len(extra) == 0:
        return base
    base_last = _last_date(base)
    if len(base.columns):
        cols = [c for c in base.columns if c in extra.columns]
    else:
        cols = list(extra.columns)
    keep = [ts for ts in extra.index
            if (base_last is None or pd.Timestamp(ts).date() > base_last)
            and pd.Timestamp(ts).date() <= target]
    if not keep:
        return base
    add = extra.loc[keep, cols].copy()
    tz = getattr(base.index, "tz", None)
    add.index = pd.DatetimeIndex([pd.Timestamp(pd.Timestamp(ts).date(), tz=tz) for ts in add.index])
    out = pd.concat([base, add]) if len(base) else add
    return out[~out.index.duplicated(keep="first")].sort_index()


def _tiingo_key() -> str:
    """Tiingo API key, settings-first then env. Reads the saved Settings via the deps
    singleton (function-local import — no import cycle; deps never imports market), falling
    back to the TIINGO_API_KEY env var, mirroring the news/LLM settings-first-then-env pattern."""
    from app.deps import get_settings_store
    saved = get_settings_store().load().market_data.tiingo_api_key
    return saved or os.environ.get("TIINGO_API_KEY", "")


def tiingo_test(api_key: str) -> tuple[bool, str]:
    """Best-effort connectivity/entitlement check for a Tiingo key: an authenticated GET to the
    Tiingo daily metadata endpoint (same host/auth as the EOD fallback). Never raises."""
    try:
        resp = httpx.get(
            "https://api.tiingo.com/tiingo/daily/AAPL",
            params={"token": api_key},
            timeout=20,
        )
        resp.raise_for_status()
        return True, "Connected"
    except Exception as exc:  # noqa: BLE001 — surface the failure as a message, never raise
        return False, str(exc)


def fetch_tiingo_eod(ticker: str, start_date: date) -> pd.DataFrame:
    """Independent daily-OHLCV fallback. Returns raw (split/dividend-unadjusted) OHLCV from
    `start_date` onward, indexed by tz-naive normalized dates — matching the `auto_adjust=False`
    yfinance series so a tail bar splices cleanly. Best-effort: returns an empty frame when the
    key is unset, or the request, payload, or parse is unusable (a missing field included) — the
    orchestrator relies on this never raising."""
    key = _tiingo_key()
    if not key:
        return pd.DataFrame()
    try:
        resp = httpx.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={"startDate": start_date.isoformat(), "token": key},
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return pd.DataFrame()
        src = pd.DataFrame(rows)
        idx = pd.to_datetime(src["date"], utc=True).dt.tz_convert(None).dt.normalize()
        return pd.DataFrame(
            {
                "Open": src["open"].astype("float64").to_numpy(),
                "High": src["high"].astype("float64").to_numpy(),
                "Low": src["low"].astype("float64").to_numpy(),
                "Close": src["close"].astype("float64").to_numpy(),
                "Volume": src["volume"].astype("float64").to_numpy(),
            },
            index=pd.DatetimeIndex(idx),
        )
    except Exception:  # noqa: BLE001 — best-effort fallback; degrade to no data
        return pd.DataFrame()


def fetch_yf_recent(ticker: str) -> pd.DataFrame:
    """Alternate-path best-effort fetch of the recent window via `yf.download` — a genuinely
    different request than the long `Ticker.history`, so it can return a finalized tail bar that
    the primary call dropped as NaN. Empty on any failure."""
    try:
        df = yf.download(ticker, period="5d", interval="1d", auto_adjust=False, progress=False)
    except Exception:  # noqa: BLE001 — best-effort; degrade to no data
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return drop_incomplete(df)


def fetch_yf_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """The primary source: a yfinance daily-history pull with the not-yet-closed bar dropped."""
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    return drop_incomplete(df)


def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Primary yfinance fetch with latest-finalized-bar recovery. When yfinance drops the latest
    completed trading day (NaN Close -> drop_incomplete), recover it via an alternate yfinance path,
    then via Tiingo EOD. Only finalized bars are spliced (never today's in-progress bar), so the
    series stays safe to score and evaluate. Best-effort: returns the freshest series it can and
    never raises for a recovery failure (a still-stale series surfaces via the frontend badge)."""
    df = fetch_yf_history(ticker, period)
    target = latest_completed_trading_day()
    last = _last_date(df)
    if last is not None and last >= target:
        return df

    df = _splice_tail(df, fetch_yf_recent(ticker), target)
    last = _last_date(df)
    if last is not None and last >= target:
        return df

    if _tiingo_key():
        start = (last + timedelta(days=1)) if last else (target - timedelta(days=7))
        df = _splice_tail(df, fetch_tiingo_eod(ticker, start), target)
    return df


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
