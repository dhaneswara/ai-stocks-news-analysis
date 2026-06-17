# Tiingo API key in Settings — design

**Date:** 2026-06-16
**Status:** approved

## Problem

The stale-bar recovery feature (merged 2026-06-16, `5a61454`) added an independent Tiingo EOD
fallback in `backend/app/data/market.py`, but the Tiingo API key is configurable **only** via the
`TIINGO_API_KEY` environment variable. There is no way to set it from the app's Settings page, unlike
every LLM provider key and news provider key. Users expect to manage it in the UI alongside those.

## Goal & scope

Let the user set the Tiingo key on the Settings page — saved in the DB, masked on read-out, with a
"Test connection" button — exactly like the LLM and news provider keys. The environment variable
remains a fallback. Tiingo stays a *fallback data source only*; this changes only *where the key can
be set*.

- **In scope:** a new `MarketDataConfig` settings section holding `tiingo_api_key`; masking/merge for
  it; a settings-first/env-fallback resolver in `market.py`; a Tiingo test-connection endpoint; the
  Settings-page "Market data" section with a masked field + Test-connection button.
- **Out of scope (YAGNI):** no general "data sources" framework, no per-ticker source override, no
  removal of the env-var fallback, no change to the recovery logic itself or to `fetch_tiingo_eod`'s
  fetch behavior.

## Design

### 1. Schema — `backend/app/models/schemas.py`

New sub-model and one `Settings` field:

```python
class MarketDataConfig(BaseModel):
    tiingo_api_key: str = ""

class Settings(BaseModel):
    ...
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
```

Because `market_data` has a default factory, a legacy settings blob lacking the key deserializes
cleanly to the default — **no `@model_validator` change is needed** (the existing validator only
backfills the LLM/news provider *dicts*; a scalar default-factory sub-model auto-fills). `api_key`
defaults to `""` (never `None`), matching every other key field. Frontend type mirror in `types.ts`
(`MarketDataConfig { tiingo_api_key: string }`, optional `market_data?` on `Settings`).

### 2. Masking / merge — `backend/app/config/settings_store.py`

Treat `market_data.tiingo_api_key` exactly like the existing scalar `alerts.telegram_bot_token`
(not a provider-dict loop):

- `mask_settings()`: set `masked.market_data.tiingo_api_key = MASK` (`"****"`).
- `merge_settings()`: if `incoming.market_data.tiingo_api_key == MASK`, restore it from
  `existing.market_data.tiingo_api_key`.

This makes the saved key render as `****` and prevents the masked sentinel from overwriting the real
key on save. Both functions already `deepcopy`; the new lines follow the telegram-token precedent.

### 3. Resolver seam — `backend/app/data/market.py`

`_tiingo_key()` becomes settings-first, env-fallback:

```python
def _tiingo_key() -> str:
    from app.deps import get_settings_store  # function-local: no import-time coupling/cycle
    saved = get_settings_store().load().market_data.tiingo_api_key
    return saved or os.environ.get("TIINGO_API_KEY", "")
```

This is the **only** consumer change — `fetch_history`'s `if _tiingo_key():` guard and
`fetch_tiingo_eod`'s internal key read are untouched, and no `get_stock_data` call site (there are 15,
one with no `Settings`) needs threading. The function-local import avoids any import cycle (`deps.py`
imports cache/settings_store/prediction-store/trace-store/snapshot-store — never `market`). Env var
keeps working as the fallback when no key is saved.

**Resolver alternative considered & rejected:** threading a `tiingo_key` parameter from each caller
through `get_stock_data` → `fetch_history` → `fetch_tiingo_eod`. Cleaner layering, but 15 call sites
(one, `universe.py:97`, has no `Settings` at all) → high churn and incomplete. The singleton resolver
is one function, zero call-site churn, and preserves the monkeypatch test boundary.

### 4. Test connection — backend

- New `tiingo_test(api_key: str) -> tuple[bool, str]` in `market.py`: an authenticated `httpx.get`
  (`timeout=20`) to `https://api.tiingo.com/tiingo/daily/AAPL` (the same API/auth path
  `fetch_tiingo_eod` uses, so it tests real connectivity + entitlement). `200` → `(True, "Connected")`;
  non-200 → `(False, "<status>: <short body>")`; any exception → `(False, str(exc))`. Best-effort,
  never raises.
- New route `POST /api/market/tiingo/test` in `routes.py`: resolves the saved key via `_tiingo_key()`;
  empty → `{"ok": False, "message": "No Tiingo API key configured"}`; else returns
  `tiingo_test(key)` as `{"ok": bool, "message": str}`. Never 500 (mirrors the resilient
  `test_news_provider`). No key is sent in the request body — the frontend saves first, then this
  endpoint reads the persisted key (same as the LLM `POST /providers/{id}/test`).

### 5. Frontend — Settings page (`frontend/src/pages/Settings.tsx`, `types.ts`, `api/client.ts`)

- A new **"Market data"** `.settings-card` `<section>` after the News card: a masked password input
  bound to `market_data.tiingo_api_key` (`type="password"`, placeholder `****`, note "(leave as ****
  to keep the saved key)"), an `updateMarketData(patch)` helper mirroring `updateAlerts`, and a
  **Test connection** `className="secondary"` button.
- The button follows the established **save-first** flow: `await save.mutateAsync(form)` then
  `api.testTiingo()`, with the result shown inline as a `.note` ✓/✗ — identical to `onTest`/`onTestNews`.
- `api.testTiingo()` in `client.ts`: `http<TestResult>('/market/tiingo/test', { method: 'POST' })`.
- `types.ts`: `MarketDataConfig { tiingo_api_key: string }`; `Settings.market_data?: MarketDataConfig`;
  a `DEFAULT_MARKET_DATA` fallback in `Settings.tsx` (mirrors `DEFAULT_NEWS`) so the form renders
  before the field exists on an older saved blob.

### 6. Error handling / degradation

Every new path is best-effort: an unset key → recovery silently skips Tiingo (unchanged);
`tiingo_test` and the route never raise; a network failure in the test surfaces as `{ok: False}` with
a message, not a 500. Saving with the masked `****` value preserves the stored key.

## Testing (TDD)

- **Backend**
  - schema: `Settings().market_data.tiingo_api_key == ""`; a legacy JSON blob without `market_data`
    deserializes with the default (no error).
  - `settings_store`: `mask_settings` replaces `market_data.tiingo_api_key` with `****` (original
    untouched); `merge_settings` restores it from existing when incoming `== "****"`, and keeps a real
    new value otherwise.
  - `market._tiingo_key`: settings-first — monkeypatch `app.deps.get_settings_store` to a fake whose
    `load().market_data.tiingo_api_key` is set → returned even with env unset; env-fallback — fake
    store empty + `monkeypatch.setenv` → env value. (Uses a fake store, so the real sandboxed DB is
    untouched and recovery tests can't be affected.)
  - `tiingo_test`: monkeypatch `market.httpx.get` → 200 `(True, "Connected")`; non-200 `(False, …)`;
    raised exception `(False, …)`.
  - route `POST /api/market/tiingo/test`: no key → `{ok: False, "No Tiingo API key configured"}`; with
    key (monkeypatch `_tiingo_key`/`tiingo_test`) → passes through `{ok, message}`.
  - regression: the existing `test_market_recovery.py` suite stays green (empty sandboxed settings →
    env fallback; `setenv`-based tests unaffected).
- **Frontend**
  - Settings renders the Market-data field + Test-connection button; the field is masked; the button
    triggers save-then-test (mock `api.testTiingo`); inline ✓/✗ shows.

## Non-goals

No general data-sources framework, no per-ticker source override, no env-var removal, no change to
`fetch_tiingo_eod`/recovery behavior, no new dependency (reuses `httpx`).
