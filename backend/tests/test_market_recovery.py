from datetime import date, datetime, timezone

import pandas as pd

from app.data import market


def _utc(y, m, d, h=12):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


def test_latest_completed_trading_day_weekday_returns_prior_weekday():
    # Tue 2026-06-16 noon UTC (08:00 ET) -> Mon 2026-06-15
    assert market.latest_completed_trading_day(_utc(2026, 6, 16)) == date(2026, 6, 15)


def test_latest_completed_trading_day_monday_returns_prior_friday():
    # Mon 2026-06-15 -> Fri 2026-06-12 (skips Sun 14, Sat 13)
    assert market.latest_completed_trading_day(_utc(2026, 6, 15)) == date(2026, 6, 12)


def test_latest_completed_trading_day_weekend_returns_friday():
    assert market.latest_completed_trading_day(_utc(2026, 6, 13)) == date(2026, 6, 12)  # Sat
    assert market.latest_completed_trading_day(_utc(2026, 6, 14)) == date(2026, 6, 12)  # Sun


def test_latest_completed_trading_day_et_boundary():
    # 02:00 UTC Tue maps to 22:00 ET Mon -> ET date is Mon 15 -> prior weekday Fri 12
    assert market.latest_completed_trading_day(_utc(2026, 6, 16, 2)) == date(2026, 6, 12)


def _bars(dates, close_start=100.0):
    idx = pd.to_datetime(list(dates))
    n = len(idx)
    return pd.DataFrame(
        {
            "Open": [close_start + i for i in range(n)],
            "High": [close_start + i + 0.5 for i in range(n)],
            "Low": [close_start + i - 0.5 for i in range(n)],
            "Close": [close_start + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=idx,
    )


def test_splice_tail_appends_only_finalized_tail():
    base = _bars(["2026-06-10", "2026-06-11", "2026-06-12"])
    extra = _bars(["2026-06-12", "2026-06-15", "2026-06-16"], close_start=200.0)  # dup + new + today
    out = market._splice_tail(base, extra, date(2026, 6, 15))
    assert [pd.Timestamp(t).strftime("%Y-%m-%d") for t in out.index] == [
        "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-15",
    ]
    # existing 06-12 row is NOT overwritten by the extra's 06-12 (keep base)
    assert out.loc[out.index[2], "Close"] == 102.0
    # 06-16 (> target) was dropped — the intraday guard
    assert "2026-06-16" not in [pd.Timestamp(t).strftime("%Y-%m-%d") for t in out.index]


def test_splice_tail_empty_extra_is_noop():
    base = _bars(["2026-06-11", "2026-06-12"])
    assert market._splice_tail(base, pd.DataFrame(), date(2026, 6, 15)) is base


def test_splice_tail_fills_when_base_empty():
    extra = _bars(["2026-06-12", "2026-06-15"], close_start=200.0)
    out = market._splice_tail(pd.DataFrame(), extra, date(2026, 6, 15))
    assert len(out) == 2 and out["Close"].iloc[-1] == 201.0


def test_last_date_handles_empty():
    assert market._last_date(pd.DataFrame()) is None
    assert market._last_date(_bars(["2026-06-12"])) == date(2026, 6, 12)


def test_splice_tail_tz_aware_base_with_naive_extra():
    """The real yfinance->Tiingo scenario: base carries NY tz, extra (Tiingo) is tz-naive."""
    ny_tz = "America/New_York"
    base_idx = pd.DatetimeIndex([
        pd.Timestamp("2026-06-10", tz=ny_tz),
        pd.Timestamp("2026-06-12", tz=ny_tz),
    ])
    base = pd.DataFrame({"Open": [10, 12], "Close": [10, 12]}, index=base_idx)
    extra_naive = pd.DataFrame(
        {"Open": [15, 16], "Close": [15, 16]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-06-15"), pd.Timestamp("2026-06-16")]),
    )
    out = market._splice_tail(base, extra_naive, date(2026, 6, 15))
    assert out.index.tz is not None            # tz preserved
    assert len(out) == 3
    assert pd.Timestamp(out.index[-1]).date() == date(2026, 6, 15)   # 06-16 dropped
    assert out["Close"].iloc[-1] == 15.0
