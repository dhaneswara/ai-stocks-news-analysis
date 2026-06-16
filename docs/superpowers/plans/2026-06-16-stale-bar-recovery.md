# Stale-bar recovery (latest finalized daily bar) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `app/data/market.py::fetch_history` recover the latest *finalized* daily bar (via an alternate yfinance path, then Tiingo EOD) when yfinance drops it with a NaN Close, so technical & network analysis run on current finalized data without polluting the evaluation tables.

**Architecture:** `fetch_history` becomes a thin orchestrator over independently-patchable source seams. The raw Yahoo call is extracted to `fetch_yf_history`; a short-window alternate path `fetch_yf_recent` and an independent vendor `fetch_tiingo_eod` fill the tail only when the series is behind `latest_completed_trading_day()`. A single pure helper `_splice_tail` enforces the load-bearing invariant: only bars dated `> last kept bar` and `<= latest completed trading day` are appended — never today's in-progress bar. Recovery is best-effort and never raises; with no `TIINGO_API_KEY` it degrades to the yfinance-retry path.

**Tech Stack:** Python 3.13, pandas (pytz-backed tz conversion — already how the candle index is NY-tz; no `tzdata`/`zoneinfo`), yfinance, `httpx` (already vendored), pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-stale-bar-recovery-design.md`

**Branch:** `feat/stale-bar-recovery` (already checked out).

**Test harness:** from `backend/`, run `.venv/Scripts/python.exe -m pytest -q`. The venv does not persist across tool calls — always invoke the interpreter by path. `tests/conftest.py` already sandboxes `DATA_DIR`.

---

## File Structure

- **Modify:** `backend/app/data/market.py` — add imports (`os`, `datetime`, `httpx`); add `latest_completed_trading_day`, `_last_date`, `_splice_tail`, `_tiingo_key`, `fetch_tiingo_eod`, `fetch_yf_recent`; rename the current `fetch_history` body to `fetch_yf_history`; rewrite `fetch_history` as the orchestrator. All other functions (`drop_incomplete`, `fetch_close_series`, `fetch_info`, `build_*`) unchanged. `fetch_close_series` keeps calling `fetch_history` and so inherits recovery for free.
- **Create:** `backend/tests/test_market_recovery.py` — all new tests for the helpers and orchestrator (keeps `test_market.py` focused on the existing builders).

The public `fetch_history(ticker, period="2y")` signature is unchanged, so `get_stock_data`, the screener scan, and the evaluation service need **zero** edits. Existing tests that monkeypatch `market.fetch_history` keep working (they bypass the orchestrator).

---

### Task 1: `latest_completed_trading_day` (US-Eastern, weekday-only)

**Files:**
- Modify: `backend/app/data/market.py`
- Test: `backend/tests/test_market_recovery.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_market_recovery.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: FAIL — `AttributeError: module 'app.data.market' has no attribute 'latest_completed_trading_day'`

- [ ] **Step 3: Add imports and implement**

In `backend/app/data/market.py`, replace the top imports:

```python
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import yfinance as yf

from app.models.schemas import Candle, Fundamentals, PriceSummary
```

Then add (place after `drop_incomplete`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_recovery.py
git commit -m "feat(backend): add latest_completed_trading_day helper"
```

---

### Task 2: `_splice_tail` + `_last_date` (the finalized-only invariant)

**Files:**
- Modify: `backend/app/data/market.py`
- Test: `backend/tests/test_market_recovery.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_market_recovery.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: FAIL — `AttributeError: module 'app.data.market' has no attribute '_splice_tail'`

- [ ] **Step 3: Implement**

Add to `backend/app/data/market.py` (after `latest_completed_trading_day`):

```python
def _last_date(df: pd.DataFrame | None) -> date | None:
    """The date of the last row, or None for an empty/None frame."""
    if df is None or len(df) == 0:
        return None
    return pd.Timestamp(df.index[-1]).date()


def _splice_tail(base: pd.DataFrame, extra: pd.DataFrame, target: date) -> pd.DataFrame:
    """Append rows from `extra` that fall strictly after `base`'s last date and on/before
    `target` (the latest completed trading day). Existing rows are never replaced (base wins on a
    date clash), and any row after `target` — e.g. today's in-progress bar — is dropped. This is
    the single enforcement point of the finalized-only invariant."""
    if extra is None or len(extra) == 0:
        return base
    base_last = _last_date(base)
    cols = [c for c in base.columns if c in extra.columns] if len(base.columns) else list(extra.columns)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_recovery.py
git commit -m "feat(backend): add _splice_tail finalized-only merge helper"
```

---

### Task 3: `fetch_tiingo_eod` + `_tiingo_key` (independent vendor fallback)

**Files:**
- Modify: `backend/app/data/market.py`
- Test: `backend/tests/test_market_recovery.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_market_recovery.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: FAIL — `AttributeError: module 'app.data.market' has no attribute 'fetch_tiingo_eod'`

- [ ] **Step 3: Implement**

Add to `backend/app/data/market.py` (after `_splice_tail`):

```python
def _tiingo_key() -> str:
    """Tiingo API key from the environment (mirrors the news-provider env-key fallback)."""
    return os.environ.get("TIINGO_API_KEY", "")


def fetch_tiingo_eod(ticker: str, start_date: date) -> pd.DataFrame:
    """Independent daily-OHLCV fallback. Returns raw (split/dividend-unadjusted) OHLCV from
    `start_date` onward, indexed by tz-naive normalized dates — matching the `auto_adjust=False`
    yfinance series so a tail bar splices cleanly. Best-effort: returns an empty frame when the
    key is unset, the request errors, or the payload is empty."""
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
    except Exception:  # noqa: BLE001 — best-effort fallback; degrade to no data
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    src = pd.DataFrame(rows)
    idx = pd.to_datetime(src["date"], utc=True).dt.tz_localize(None).dt.normalize()
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_recovery.py
git commit -m "feat(backend): add Tiingo EOD fallback fetch"
```

---

### Task 4: `fetch_yf_recent` (alternate yfinance path)

**Files:**
- Modify: `backend/app/data/market.py`
- Test: `backend/tests/test_market_recovery.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_market_recovery.py`:

```python
def test_fetch_yf_recent_drops_incomplete_and_flattens_multiindex(monkeypatch):
    idx = pd.to_datetime(["2026-06-12", "2026-06-15"])
    cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
    df = pd.DataFrame(
        [[10, 10.5, 9.5, 10.2, 100], [11, 11.5, 10.5, 11.0, 200]],
        index=idx, columns=cols,
    )
    monkeypatch.setattr(market.yf, "download", lambda *a, **k: df)
    out = market.fetch_yf_recent("AAPL")
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(out) == 2 and out["Close"].iloc[-1] == 11.0


def test_fetch_yf_recent_empty_on_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(market.yf, "download", boom)
    assert market.fetch_yf_recent("AAPL").empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: FAIL — `AttributeError: module 'app.data.market' has no attribute 'fetch_yf_recent'`

- [ ] **Step 3: Implement**

Add to `backend/app/data/market.py` (after `fetch_tiingo_eod`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_recovery.py
git commit -m "feat(backend): add alternate-path yfinance recent fetch"
```

---

### Task 5: Orchestrate — extract `fetch_yf_history`, rewrite `fetch_history`

**Files:**
- Modify: `backend/app/data/market.py:22-24` (the current `fetch_history`)
- Test: `backend/tests/test_market_recovery.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_market_recovery.py`:

```python
TARGET = date(2026, 6, 15)


def _patch_target(monkeypatch):
    monkeypatch.setattr(market, "latest_completed_trading_day", lambda *a, **k: TARGET)


def test_fetch_history_fresh_skips_recovery(monkeypatch):
    _patch_target(monkeypatch)
    fresh = _bars(["2026-06-12", "2026-06-15"])
    monkeypatch.setattr(market, "fetch_yf_history", lambda t, p="2y": fresh)
    called = []
    monkeypatch.setattr(market, "fetch_yf_recent", lambda t: called.append("recent") or pd.DataFrame())
    out = market.fetch_history("AAPL", "1y")
    assert market._last_date(out) == TARGET and called == []  # no recovery attempted


def test_fetch_history_recovers_via_alternate_path(monkeypatch):
    _patch_target(monkeypatch)
    stale = _bars(["2026-06-11", "2026-06-12"])
    recent = _bars(["2026-06-12", "2026-06-15"], close_start=200.0)
    monkeypatch.setattr(market, "fetch_yf_history", lambda t, p="2y": stale)
    monkeypatch.setattr(market, "fetch_yf_recent", lambda t: recent)
    tii = []
    monkeypatch.setattr(market, "fetch_tiingo_eod", lambda t, s: tii.append("tii") or pd.DataFrame())
    out = market.fetch_history("AAPL", "1y")
    assert market._last_date(out) == TARGET and tii == []  # tiingo not reached


def test_fetch_history_falls_back_to_tiingo(monkeypatch):
    _patch_target(monkeypatch)
    monkeypatch.setenv("TIINGO_API_KEY", "secret")
    stale = _bars(["2026-06-11", "2026-06-12"])
    monkeypatch.setattr(market, "fetch_yf_history", lambda t, p="2y": stale)
    monkeypatch.setattr(market, "fetch_yf_recent", lambda t: pd.DataFrame())
    monkeypatch.setattr(market, "fetch_tiingo_eod",
                        lambda t, s: _bars(["2026-06-15"], close_start=200.0))
    out = market.fetch_history("AAPL", "1y")
    assert market._last_date(out) == TARGET and out["Close"].iloc[-1] == 200.0


def test_fetch_history_returns_stale_without_key(monkeypatch):
    _patch_target(monkeypatch)
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    stale = _bars(["2026-06-11", "2026-06-12"])
    monkeypatch.setattr(market, "fetch_yf_history", lambda t, p="2y": stale)
    monkeypatch.setattr(market, "fetch_yf_recent", lambda t: pd.DataFrame())
    out = market.fetch_history("AAPL", "1y")
    assert market._last_date(out) == date(2026, 6, 12)  # still stale, no crash


def test_fetch_history_drops_intraday_bar_from_tiingo(monkeypatch):
    _patch_target(monkeypatch)
    monkeypatch.setenv("TIINGO_API_KEY", "secret")
    stale = _bars(["2026-06-11", "2026-06-12"])
    monkeypatch.setattr(market, "fetch_yf_history", lambda t, p="2y": stale)
    monkeypatch.setattr(market, "fetch_yf_recent", lambda t: pd.DataFrame())
    # Tiingo returns the finalized 06-15 AND today's in-progress 06-16
    monkeypatch.setattr(market, "fetch_tiingo_eod",
                        lambda t, s: _bars(["2026-06-15", "2026-06-16"], close_start=200.0))
    out = market.fetch_history("AAPL", "1y")
    dates = [pd.Timestamp(t).strftime("%Y-%m-%d") for t in out.index]
    assert "2026-06-16" not in dates and market._last_date(out) == TARGET
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: FAIL — `AttributeError: module 'app.data.market' has no attribute 'fetch_yf_history'`

- [ ] **Step 3: Implement — extract the raw fetch and write the orchestrator**

In `backend/app/data/market.py`, replace the current `fetch_history` (the 3 lines at ~22-24):

```python
def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    return drop_incomplete(df)
```

with:

```python
def fetch_yf_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """The primary source: a yfinance daily-history pull with the not-yet-closed bar dropped."""
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    return drop_incomplete(df)


def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Primary yfinance fetch with latest-finalized-bar recovery. When yfinance drops the latest
    completed trading day (NaN Close → drop_incomplete), recover it via an alternate yfinance path,
    then via Tiingo EOD. Only finalized bars are spliced (never today's in-progress bar), so the
    series stays safe to score and evaluate. Best-effort: returns the freshest series it can and
    never raises for a recovery failure (a still-stale series surfaces via the frontend badge)."""
    df = fetch_yf_history(ticker, period)
    target = latest_completed_trading_day()
    if _last_date(df) is not None and _last_date(df) >= target:
        return df

    df = _splice_tail(df, fetch_yf_recent(ticker), target)
    if _last_date(df) is not None and _last_date(df) >= target:
        return df

    if _tiingo_key():
        last = _last_date(df)
        start = (last + timedelta(days=1)) if last else (target - timedelta(days=7))
        df = _splice_tail(df, fetch_tiingo_eod(ticker, start), target)
    return df
```

Note: `fetch_tiingo_eod` re-checks `_tiingo_key()` internally, so the orchestrator's `if _tiingo_key()` guard is purely to skip the network call when unconfigured — both are intentional.

- [ ] **Step 4: Run the recovery tests, then the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: PASS (18 passed)

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — the full backend suite (existing `test_market.py` and everything that monkeypatches `market.fetch_history` still pass; no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_recovery.py
git commit -m "feat(backend): recover latest finalized bar in fetch_history"
```

---

### Task 6: Manual sanity check + wrap-up

**Files:** none (verification only).

- [ ] **Step 1: Confirm the public surface is unchanged**

Run: `.venv/Scripts/python.exe -c "from app.data.market import fetch_history, fetch_close_series, fetch_info; print('ok')"`
Expected: prints `ok` (no import errors; consumers unaffected).

- [ ] **Step 2: Confirm degradation with no key is silent**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: full suite green.

- [ ] **Step 3 (optional, networked): real-ticker smoke test**

Only if a network + (optionally) `TIINGO_API_KEY` is available. From `backend/`:
`.venv/Scripts/python.exe -c "from app.data.market import fetch_history; df = fetch_history('AAPL','1mo'); print(df.index[-1].date(), len(df))"`
Expected: the last date is the latest completed trading day (or today if mid-session and yfinance already has it); no exception. Skip in CI/offline.

- [ ] **Step 4: Final state**

No commit needed if Steps 1-3 changed nothing. The feature is complete on `feat/stale-bar-recovery`; integration to `master` is handled by the finishing-a-development-branch step after review.

---

## Self-Review

**Spec coverage:**
- "retry alternate yfinance path first" → Task 4 (`fetch_yf_recent`) + Task 5 orchestrator order. ✓
- "Tiingo EOD fallback, raw close, env key only" → Task 3. ✓
- "latest_completed_trading_day, ET, weekday-only, pandas tz" → Task 1. ✓
- "finalized-only invariant / no intraday bar" → Task 2 (`_splice_tail`) + Task 5 test `…drops_intraday_bar…`. ✓
- "tail-only splice, base wins on clash" → Task 2 tests. ✓
- "best-effort, no new exception, degrade without key" → Task 5 tests `…returns_stale_without_key`, internal try/except in Tasks 3-4. ✓
- "public API unchanged, consumers untouched, existing patches still work" → Task 5 full-suite run + Task 6 Step 1. ✓
- "no new dependency (pandas/httpx)" → imports in Task 1 Step 3; no pyproject change. ✓

**Placeholder scan:** none — every step has concrete code/commands and expected output.

**Type consistency:** `fetch_yf_history(ticker, period="2y")`, `fetch_yf_recent(ticker)`, `fetch_tiingo_eod(ticker, start_date: date)`, `_splice_tail(base, extra, target: date)`, `_last_date(df) -> date | None`, `latest_completed_trading_day(now=None) -> date` — names and signatures are used identically across Tasks 1-5 and the orchestrator. ✓
