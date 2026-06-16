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


class _FakeResp:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._ok = status_ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("HTTP 500")

    def json(self):
        return self._payload


_TIINGO_PAYLOAD = [
    {"date": "2026-06-15T00:00:00.000Z", "open": 10.0, "high": 11.0, "low": 9.0,
     "close": 10.5, "volume": 1234, "adjClose": 9.9},
]


def test_fetch_tiingo_eod_parses_raw_ohlcv(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "secret")
    monkeypatch.setattr(market.httpx, "get", lambda *a, **k: _FakeResp(_TIINGO_PAYLOAD))
    df = market.fetch_tiingo_eod("AAPL", date(2026, 6, 13))
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df["Close"].iloc[0] == 10.5  # raw close, not adjClose 9.9
    assert df.index[0].strftime("%Y-%m-%d") == "2026-06-15"


def test_fetch_tiingo_eod_empty_without_key(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(market.httpx, "get", lambda *a, **k: called.append(1) or _FakeResp([]))
    df = market.fetch_tiingo_eod("AAPL", date(2026, 6, 13))
    assert df.empty and called == []  # no key -> no HTTP call


def test_fetch_tiingo_eod_empty_on_http_error(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "secret")
    monkeypatch.setattr(market.httpx, "get", lambda *a, **k: _FakeResp([], status_ok=False))
    assert market.fetch_tiingo_eod("AAPL", date(2026, 6, 13)).empty


def test_fetch_tiingo_eod_empty_on_malformed_payload(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "secret")
    bad_payload = [{"date": "2026-06-15T00:00:00.000Z", "close": 10.5}]  # missing open/high/low/volume
    monkeypatch.setattr(market.httpx, "get", lambda *a, **k: _FakeResp(bad_payload))
    assert market.fetch_tiingo_eod("AAPL", date(2026, 6, 13)).empty


def test_fetch_yf_recent_drops_incomplete_and_flattens_multiindex(monkeypatch):
    idx = pd.to_datetime(["2026-06-12", "2026-06-15", "2026-06-16"])
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
    df = pd.DataFrame(
        [
            [10, 10.5, 9.5, 10.2, 100],
            [11, 11.5, 10.5, 11.0, 200],
            [12, 12.5, 11.5, float("nan"), 300],  # not-yet-closed bar -> dropped
        ],
        index=idx, columns=cols,
    )
    monkeypatch.setattr(market.yf, "download", lambda *a, **k: df)
    out = market.fetch_yf_recent("AAPL")
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(out) == 2  # the NaN-Close 06-16 row was dropped by drop_incomplete
    assert out["Close"].iloc[-1] == 11.0


def test_fetch_yf_recent_empty_on_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(market.yf, "download", boom)
    assert market.fetch_yf_recent("AAPL").empty
