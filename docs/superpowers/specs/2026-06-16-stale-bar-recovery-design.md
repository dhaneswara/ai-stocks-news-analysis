# Stale-bar recovery (latest finalized daily bar) — design

**Date:** 2026-06-16
**Status:** approved

## Problem

Technical and network analysis run on the candle series from
`app/data/market.py::fetch_history()` (yfinance). yfinance intermittently returns the latest
*completed* trading day's daily bar with a `NaN` Close; `drop_incomplete()` correctly discards the
unusable row, so the series ends on the **prior** trading day. The scan then scores indicators, the
network blend, and the Discover/Portfolio board on a day-old candle, and
`app/evaluation/signals.py::record_deterministic_pair()` records the technical/network calls keyed to
that stale `candles[-1]` (`call_date` + `entry_price`). Reported live: ~46 of 57 portfolio tickers
showed June-12 data after a June-16 rescan, because yfinance failed to return the finalized June-15
bar (the documented yfinance NaN-Close / `drop_incomplete` self-healing gotcha).

This is **not** the same as "today's bar isn't finalized yet." The missing bar is a *completed,
finalized* session that genuinely exists at other vendors — yfinance simply failed to serve it.
Recovering that real bar and analysing on it is correct, not an estimate.

### The pollution distinction (why this is safe)

`record_deterministic_pair` keys eval rows off `candles[-1].time` / `.close`. Two ways to "update"
that last candle differ sharply:

| Last candle | call_date / entry | Pollutes eval? |
|---|---|---|
| The **real finalized** bar yfinance dropped | finalized date, real close | **No** — the correct official close, recovered. |
| A **synthetic intraday** estimate (live quote) | today, a guess | **Yes** — later scored against a price that was never a real close. |

This design recovers only the **first** kind. The load-bearing invariant is that the scored series
must end on a **finalized** trading day; an unfinished/intraday bar is never appended.

## Goal & scope

Make `fetch_history` resilient: when yfinance drops the latest finalized bar, recover it so technical
& network analysis (and everything downstream of `fetch_history`) run on current finalized data.
Recovery order (user choice "C"): **retry an alternate yfinance path first, then fall back to an
independent EOD vendor (Tiingo).**

- **In scope:** `backend/app/data/market.py` only. New orchestrator + two new network-boundary
  functions + one date helper. No consumer edits (public `fetch_history` signature unchanged).
- **Out of scope:** No intraday/live-quote display feature (that was a separate idea, deferred). No
  Settings UI for the Tiingo key (env var only). No change to `drop_incomplete`, scoring, the
  evaluation store, or the frontend staleness badge (the badge remains the correct signal when
  recovery cannot fill the gap). No backfill/repair of historical bars — tail only.

## Design

### Components (all in `app/data/market.py`)

| Function | Role |
|---|---|
| `fetch_yf_history(ticker, period)` | Today's `fetch_history` body verbatim: `yf.Ticker(t).history(period, interval="1d", auto_adjust=False)` → `drop_incomplete`. The primary source; independently patchable. |
| `fetch_yf_recent(ticker)` | Alternate-path best-effort fetch of a short recent window via `yf.download(ticker, period="5d", interval="1d", auto_adjust=False)` → `drop_incomplete`. A genuinely different request than the long `Ticker.history`, so it can dodge a transient NaN. Returns empty on error. |
| `fetch_tiingo_eod(ticker, start_date)` | New independent vendor. `httpx.get("https://api.tiingo.com/tiingo/daily/{ticker}/prices", params={startDate, token}, timeout=20)` → DataFrame of **raw** OHLCV (Tiingo `open/high/low/close/volume`, **not** `adjClose`). Returns empty when no key / HTTP error / empty payload. (`httpx` is already the app's HTTP client — `data/news.py`, `data/truth_social.py`, `alerts/notifier.py`, `llm/ollama_provider.py`.) |
| `latest_completed_trading_day(now=None)` | The most recent weekday **strictly before** today's date in **US Eastern**, as a `date`. Uses pandas' tz conversion (`pd.Timestamp(...).tz_convert("America/New_York")`) — **not** stdlib `zoneinfo`, which needs `tzdata` on Windows; pandas resolves NY via `pytz` (already vendored by yfinance, and already how the candle index is NY-tz). Weekday-only; holidays not modeled (same accepted trade-off as the frontend `marketClock.ts`). `now` injectable for deterministic tests. |
| `fetch_history(ticker, period)` | New orchestrator (public API unchanged). |

### Orchestrator algorithm

```
df = fetch_yf_history(ticker, period)
target = latest_completed_trading_day()
if df is non-empty and last_bar_date(df) >= target:
    return df                                  # fresh — status quo, no extra I/O

# stale: yfinance dropped one or more finalized bars
alt = fetch_yf_recent(ticker)                  # A — alternate yfinance path (cheap, best-effort)
df = _splice_tail(df, alt, target)             # fill dates in (last_bar_date(df), target]
if last_bar_date(df) >= target:
    return df

if tiingo_key_present():                        # B — independent fallback
    tii = fetch_tiingo_eod(ticker, start_date=last_bar_date(df) + 1 day)
    df = _splice_tail(df, tii, target)

return df                                       # may still be stale → frontend badge shows; no crash
```

`_splice_tail(base, extra, target)` (pure, unit-tested): append only `extra` rows whose date is
**strictly after** `base`'s last date **and** `<= target`; never replace an existing row; keep the
index sorted and unique; use raw OHLCV columns only. This is the single enforcement point of the
finalized-only invariant — any source's today/in-progress row is filtered out here.

### Error handling / degradation

Recovery is best-effort, mirroring the network block in `score_one`: a failure in
`fetch_yf_recent` or `fetch_tiingo_eod` (network, parse, missing key) is swallowed and the function
returns the best series it has. The only externally-visible effect of total failure is the status
quo: a stale series and the existing "Data lagging" badge. `fetch_history` never raises a new
exception type; `get_stock_data` still raises its existing `ValueError` when the *primary* fetch
yields nothing.

### Config

- **`TIINGO_API_KEY` environment variable only.** Read inside `market.py` (e.g. via a small
  `_tiingo_key() -> str` reading `os.environ`), mirroring `app/news/factory.py`'s env-key fallback.
  No Settings schema field, no Settings UI (YAGNI; can graduate later).
- When unset, branch B is skipped entirely — the feature degrades to A-only with zero configuration.

### Test boundary

Existing tests that monkeypatch `market.fetch_history` to return a fixed DataFrame keep working —
they bypass the orchestrator. New orchestrator tests patch `fetch_yf_history`, `fetch_yf_recent`,
and `fetch_tiingo_eod` (and `latest_completed_trading_day` via injected `now`).

## Correctness caveats (designed-for, not incidental)

- **Tail-only splice** — historical bars are never replaced; only the 1–2 day gap at the end is
  filled, so no source-mixing in the body and no split/dividend-adjustment mismatch (no corporate
  action intervenes in the tail).
- **Raw close only** — Tiingo `close` (not `adjClose`) to stay consistent with `auto_adjust=False`.
  For the recent tail, vendors' raw closes for a given finalized day agree to the cent.
- **Finalized-only** — `_splice_tail`'s `<= target` filter guarantees no intraday bar enters the
  scored series, keeping `record_deterministic_pair` rows clean.
- **Volume / single-venue** — a spliced Tiingo bar's volume may differ slightly from Yahoo's; the
  price-based indicators and the score are unaffected materially. (Alpaca's IEX-only daily close was
  rejected for exactly this reason — it is not the official consolidated close.)
- **Tiingo rate limit** — free tier is 1,000 req/day but 50/hr. Recovery only fires for *stale*
  tickers, so a single rescan (even ~46 stale) is fine; many rescans within one hour could brush the
  hourly cap. Accepted and noted; not engineered around (YAGNI).

## Testing (TDD)

- `latest_completed_trading_day(now=…)` — weekday→prior weekday; Monday→prior Friday; Saturday/Sunday
  → prior Friday; an ET-boundary instant.
- `_splice_tail` — fills only the post-last-date tail; drops rows `> target` (the intraday guard);
  never replaces an existing row; sorted/unique index; empty `extra` is a no-op.
- `fetch_history` orchestrator — (a) fresh → no recovery, unchanged DataFrame; (b) stale → alternate
  yfinance path recovers; (c) stale → alternate fails, Tiingo recovers; (d) stale → no Tiingo key →
  returns stale, no crash; (e) a source returns today's unfinished bar → filtered out.
- `fetch_tiingo_eod` — parses a mocked JSON payload to raw OHLCV; empty DataFrame on error/no-key
  (HTTP mocked).

## Non-goals

No live-quote display feature. No Settings UI for Tiingo. No holiday calendar. No historical-bar
repair. No change to `drop_incomplete`, scoring, the evaluation store, or the staleness badge. No new
dependency — reuses the already-vendored `httpx` and pandas' pytz-backed tz conversion (no
`tzdata`/`zoneinfo`).
