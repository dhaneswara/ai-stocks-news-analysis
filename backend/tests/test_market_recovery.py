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
