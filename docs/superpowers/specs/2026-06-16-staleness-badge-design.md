# Staleness badge ("Data lagging") — design

**Date:** 2026-06-16
**Status:** approved

## Problem

After a **Rescan portfolio**, tickers whose latest daily bar the data provider (yfinance)
hasn't finalized show their *previous* trading day silently. Reported live for **SPCX** and
**JBL** (and ~46 of 57 portfolio tickers on 2026-06-16): yfinance returned Monday 2026-06-15
with a `NaN` Close, `app/data/market.py::drop_incomplete()` correctly drops the unusable bar,
and the scan re-scores on the 2026-06-12 candle. The Dashboard then shows June 12 prices and the
Evaluation page shows a June 12 `call_date` with **no indication that the data is stale** — it
reads as silently wrong rather than "the provider is lagging."

This is upstream data lag, not an app bug. The fix is purely informational: surface *when* a
ticker's latest bar is behind the most recent completed trading day. The data-dropping logic is
correct and stays unchanged.

## Scope

Frontend-only. No backend, schema, or API change. No change to `drop_incomplete`.
Badge appears on the **Dashboard** summary header and the **Evaluation** board rows.

## Design

### 1. Staleness rule — extend `frontend/src/lib/marketClock.ts` (reuse, don't reinvent)

`marketClock.ts` already centralizes US-market ET logic (`nyParts`, `WEEKDAYS`, DST handling) and
its header already documents the "weekdays only, holidays not modeled" trade-off. Add there rather
than a new module:

- `latestTradingDay(now = new Date()): string` — the most recent weekday **strictly before**
  today's calendar date in **US Eastern** (the candle timezone). Steps back a day at a time via
  the existing `nyParts`, skipping Sat/Sun. Returns `YYYY-MM-DD`.
- `isStale(lastBar: string | null | undefined, now = new Date()): boolean`
  — `!!lastBar && lastBar < latestTradingDay(now)` (lexicographic `YYYY-MM-DD` compare).

**Why "strictly before today":** flags a ticker missing a *completed* trading day (SPCX missing
Mon Jun 15 → flagged) but does NOT nag when today's bar merely isn't published yet (normal pre-/
intra-day) or on weekends. `now` is injectable so the logic is deterministically testable.

**Known trade-off:** on a US market **holiday** the rule can mildly false-positive (it expects a
bar the market never produced). Accepted — holidays are rare and this is an info badge. No
holiday calendar (YAGNI).

### 2. Shared component — `frontend/src/components/StaleBadge.tsx`

`StaleBadge({ lastDate }: { lastDate: string | null | undefined })`. Uses `isStale` from
`marketClock`. Renders `null` when fresh or `lastDate` is missing. When stale, renders a small
amber pill **"⚠ Data lagging"** with a tooltip: *"Latest price bar is Jun 12, 2026 — the data
provider hasn't published a newer close yet. Re-scan later."* (date formatted from `lastDate`).

### 3. Wiring

- **Dashboard** (`pages/Dashboard.tsx`) — in the summary header, after the
  `{ticker} · {currency} · {as_of}` line: `<StaleBadge lastDate={d.candles.at(-1)?.time ?? null} />`.
- **Evaluation board** (`components/EvaluationBoard.tsx`) — in the existing "Latest" column,
  next to `latest_recommendation`: `<StaleBadge lastDate={r.latest_call_date} />`.

### 4. Styles

One `.stale-badge` rule in `frontend/src/styles.css`, amber, matching existing `.badge` /
`.overconf` styling.

### 5. Tests (TDD)

- `lib/marketClock.test.ts` — new cases for `latestTradingDay`/`isStale`: weekday→prior weekday,
  Monday→prior Friday, weekend, fresh (== expected), stale (< expected), null, and one ET-boundary
  case. Injected `now`.
- `components/StaleBadge.test.tsx` — renders the pill when stale, `null` when fresh/missing
  (clock fixed via `vi.setSystemTime`).
- Assertion added to `pages/Dashboard.test.tsx` and `pages/Evaluation.test.tsx`.

## Non-goals

- No holiday calendar. No backend staleness flag. No badge on Portfolio/Discover board rows
  (they show scores, not dates). No change to data fetching or `drop_incomplete`.
