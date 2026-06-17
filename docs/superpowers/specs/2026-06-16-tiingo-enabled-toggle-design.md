# Tiingo enable/disable toggle — design

**Date:** 2026-06-16
**Status:** approved

## Problem

The Tiingo EOD fallback (stale-bar recovery) is used whenever a Tiingo key is configured — there is
no way to keep the key saved but temporarily stop using Tiingo. Users want a toggle: **off → Yahoo
only; on → use Tiingo when a key is set.**

## Goal & scope

Add a boolean `tiingo_enabled` to the Market-data settings, surfaced as a checkbox in the Settings
"Market data" section. When off, `fetch_history`'s recovery skips Tiingo entirely (the alternate
yfinance path still runs); when on (default), behavior is exactly as today. The toggle is independent
of the key: the key field and Test-connection stay usable while the toggle is off.

- **In scope:** `MarketDataConfig.tiingo_enabled`; an `_tiingo_enabled()` gate in `market.py`; the
  checkbox in the Settings UI; tests.
- **Out of scope (YAGNI):** no env-var override for the toggle (settings-only; the key keeps its
  `TIINGO_API_KEY` env fallback), no per-ticker toggle, no change to `fetch_tiingo_eod`, the
  test-connection route, masking/merge, or recovery behavior beyond the gate.

## Design

### 1. Schema — `backend/app/models/schemas.py`

`MarketDataConfig` gains a second field:

```python
class MarketDataConfig(BaseModel):
    tiingo_api_key: str = ""
    tiingo_enabled: bool = True
```

`default = True` preserves today's behavior and migrates cleanly: a settings blob persisted before
this change (which has `market_data` but no `tiingo_enabled`, or no `market_data` at all) deserializes
with `tiingo_enabled = True` — so anyone who already saved a key keeps Tiingo on. No
`@model_validator` change needed. Frontend type mirror: `MarketDataConfig { tiingo_api_key: string;
tiingo_enabled: boolean; }`.

### 2. Gate — `backend/app/data/market.py`

New resolver mirroring `_tiingo_key()` (function-local `from app.deps import get_settings_store`,
cycle-safe):

```python
def _tiingo_enabled() -> bool:
    from app.deps import get_settings_store
    return get_settings_store().load().market_data.tiingo_enabled
```

`fetch_history`'s Tiingo branch changes from `if _tiingo_key():` to:

```python
    if _tiingo_enabled() and _tiingo_key():
        ...
```

So **off → recovery is Yahoo-only** (primary `fetch_yf_history` + the `fetch_yf_recent` alternate
path still run; Tiingo is skipped); **on + key set → Tiingo fallback** as today. The gate
short-circuits: when disabled, `_tiingo_key()` isn't called, so there's no extra settings read. The
gate at the orchestrator is the single enforcement point — `fetch_tiingo_eod` is unchanged and never
reached when disabled.

(Settings is loaded once by `_tiingo_enabled()` and, when enabled, once by `_tiingo_key()` — two small
SQLite reads, only on the stale recovery path. Not worth combining; YAGNI.)

### 3. Test-connection & key resolution — unchanged

`POST /api/market/tiingo/test` and `_tiingo_key()` are untouched and toggle-independent. The user can
save and Test a key while the toggle is off, then enable it.

### 4. Frontend — `frontend/src/pages/Settings.tsx` (+ `types.ts`)

In the "Market data" section, add a checkbox (mirroring the Alerts / Truth-Social `enabled`
checkboxes — `<div className="field check">` → `<label>` → `<input type="checkbox">`):

> **Use Tiingo as a fallback when Yahoo data lags** (off = Yahoo only)

bound to `marketData.tiingo_enabled` via the existing `updateMarketData` helper
(`updateMarketData({ tiingo_enabled: e.target.checked })`). Placed at the top of the section, above
the key field. The key field and Test-connection button stay always-enabled regardless of the
checkbox. `DEFAULT_MARKET_DATA` gains `tiingo_enabled: true`.

### 5. Masking / merge — no change

`tiingo_enabled` is a boolean (not a secret), so `mask_settings`/`merge_settings` need no change; it
round-trips through the existing deep-copy in `merge_settings`.

## Error handling

`_tiingo_enabled()` does a settings load like `_tiingo_key()`; both are on the best-effort recovery
path. If the load somehow raised it would propagate the same way `_tiingo_key()`'s already does — no
new failure mode. No user-facing error path changes.

## Testing (TDD)

- **Backend**
  - schema: `Settings().market_data.tiingo_enabled is True`; a legacy blob (`{"market_data":
    {"tiingo_api_key": "x"}}` and `{}`) deserializes with `tiingo_enabled is True`.
  - `_tiingo_enabled()`: monkeypatch `app.deps.get_settings_store` to a fake store with
    `tiingo_enabled` True/False → returns it.
  - `fetch_history` gate: with a saved key + stale series, `tiingo_enabled = False` → `fetch_tiingo_eod`
    is NOT called and the series stays stale; `tiingo_enabled = True` → Tiingo is used (the existing
    `test_fetch_history_falls_back_to_tiingo` still passes because the autouse store defaults to
    `True`). Add a disabled-path test that asserts `fetch_tiingo_eod` is not invoked (spy).
  - regression: full recovery suite + full backend suite green (default `True` keeps existing
    behavior).
- **Frontend**
  - the Market-data checkbox renders, reflects `market_data.tiingo_enabled`, toggling it updates the
    form, and it persists via save (mock `api.saveSettings`).

## Non-goals

No env-var toggle, no per-ticker override, no change to the key field / Test-connection / masking /
`fetch_tiingo_eod` / recovery beyond the single gate. No new dependency.
