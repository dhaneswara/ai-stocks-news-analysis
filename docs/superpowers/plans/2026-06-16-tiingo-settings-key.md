# Tiingo API key in Settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user set the Tiingo API key on the Settings page (DB-saved, masked, with a Test-connection button), mirroring the LLM/news provider keys; the `TIINGO_API_KEY` env var stays as fallback.

**Architecture:** A new `MarketDataConfig` settings sub-model holds `tiingo_api_key`, masked/merged like `alerts.telegram_bot_token`. `market.py::_tiingo_key()` resolves settings-first (via the `deps` settings-store singleton, function-local import — no cycle, no call-site churn) then env. A best-effort `tiingo_test()` + `POST /api/market/tiingo/test` powers a save-first "Test connection" button in a new Settings "Market data" section.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, `httpx` (vendored); React + Vite + TS + vitest.

**Spec:** `docs/superpowers/specs/2026-06-16-tiingo-settings-key-design.md`
**Branch:** `feat/tiingo-settings-key` (already checked out).
**Test harness:** backend — from `backend/`, `.venv/Scripts/python.exe -m pytest -q` (invoke interpreter by path; venv activation doesn't persist). frontend — from `frontend/`, `npm test -- --run`.

---

## File Structure

- **Modify** `backend/app/models/schemas.py` — add `MarketDataConfig`, add `Settings.market_data` field.
- **Modify** `backend/app/config/settings_store.py` — mask + merge `market_data.tiingo_api_key`.
- **Modify** `backend/app/data/market.py` — `_tiingo_key()` settings-first/env; add `tiingo_test()`.
- **Modify** `backend/app/api/routes.py` — add `POST /market/tiingo/test`.
- **Modify** `backend/tests/test_market_recovery.py`, `backend/tests/test_settings_store.py`, `backend/tests/test_api.py` — tests.
- **Modify** `frontend/src/types.ts`, `frontend/src/api/client.ts`, `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Settings.test.tsx` — type, API call, UI section, test.

---

### Task 1: Schema — `MarketDataConfig` + `Settings.market_data`

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_schemas.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_schemas.py`:

```python
def test_market_data_default_and_legacy_blob():
    from app.models.schemas import Settings
    # default present
    assert Settings().market_data.tiingo_api_key == ""
    # a legacy settings blob lacking `market_data` deserializes with the default (no error)
    s = Settings.model_validate_json('{"active_provider": "anthropic"}')
    assert s.market_data.tiingo_api_key == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_schemas.py::test_market_data_default_and_legacy_blob -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'market_data'`

- [ ] **Step 3: Implement** — in `backend/app/models/schemas.py`, add this class immediately **before** `class Settings(BaseModel):` (just after the `_default_providers` function, line ~496):

```python
class MarketDataConfig(BaseModel):
    """Market-data source settings. Today: the Tiingo EOD fallback key used by the stale-bar
    recovery in app/data/market.py (env var TIINGO_API_KEY remains the fallback)."""
    tiingo_api_key: str = ""
```

Then add the field to `Settings` (after the `news:` line, ~508):

```python
    news: NewsConfig = Field(default_factory=NewsConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
```

(No `@model_validator` change: a default-factory sub-model auto-fills when absent from a saved blob — the validator only backfills the provider *dicts*.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_schemas.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_schemas.py
git commit -m "feat(backend): add MarketDataConfig (tiingo_api_key) to Settings"
```

---

### Task 2: Mask + merge `market_data.tiingo_api_key`

**Files:**
- Modify: `backend/app/config/settings_store.py`
- Test: `backend/tests/test_settings_store.py`

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_settings_store.py` (it already imports `Settings`, `MASK`, `mask_settings`, `merge_settings`; if any import is missing, add `from app.config.settings_store import MASK, mask_settings, merge_settings` and `from app.models.schemas import Settings`):

```python
def test_mask_hides_market_data_key():
    s = Settings()
    s.market_data.tiingo_api_key = "secret"
    masked = mask_settings(s)
    assert masked.market_data.tiingo_api_key == MASK
    assert s.market_data.tiingo_api_key == "secret"  # original untouched


def test_merge_restores_masked_market_data_key():
    existing = Settings()
    existing.market_data.tiingo_api_key = "real-key"
    incoming = Settings()
    incoming.market_data.tiingo_api_key = MASK
    merged = merge_settings(existing, incoming)
    assert merged.market_data.tiingo_api_key == "real-key"


def test_merge_keeps_new_market_data_key():
    existing = Settings()
    existing.market_data.tiingo_api_key = "old"
    incoming = Settings()
    incoming.market_data.tiingo_api_key = "new"
    merged = merge_settings(existing, incoming)
    assert merged.market_data.tiingo_api_key == "new"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_settings_store.py -q`
Expected: FAIL (the new market_data assertions fail — the key isn't masked/restored yet)

- [ ] **Step 3: Implement** — in `backend/app/config/settings_store.py`:

In `mask_settings`, add before `return masked` (after the news loop, line ~53):

```python
    if masked.market_data.tiingo_api_key:
        masked.market_data.tiingo_api_key = MASK
```

In `merge_settings`, add before `return merged` (after the news loop, line ~66):

```python
    if merged.market_data.tiingo_api_key == MASK:
        merged.market_data.tiingo_api_key = existing.market_data.tiingo_api_key
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_settings_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config/settings_store.py backend/tests/test_settings_store.py
git commit -m "feat(backend): mask/merge market_data.tiingo_api_key in settings store"
```

---

### Task 3: `market.py` — settings-first `_tiingo_key()` + `tiingo_test()`

**Files:**
- Modify: `backend/app/data/market.py`
- Test: `backend/tests/test_market_recovery.py`

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_market_recovery.py`. Add `from app.models.schemas import Settings` near the top imports if not present (the `_FakeResp` class already exists in this file from the recovery work):

```python
def test_tiingo_key_prefers_saved_settings(monkeypatch):
    import app.deps as deps

    class _Store:
        def load(self):
            s = Settings()
            s.market_data.tiingo_api_key = "from-settings"
            return s

    monkeypatch.setattr(deps, "get_settings_store", lambda: _Store())
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    assert market._tiingo_key() == "from-settings"


def test_tiingo_key_falls_back_to_env(monkeypatch):
    import app.deps as deps

    class _Empty:
        def load(self):
            return Settings()

    monkeypatch.setattr(deps, "get_settings_store", lambda: _Empty())
    monkeypatch.setenv("TIINGO_API_KEY", "from-env")
    assert market._tiingo_key() == "from-env"


def test_tiingo_test_ok(monkeypatch):
    monkeypatch.setattr(market.httpx, "get", lambda *a, **k: _FakeResp({"ticker": "AAPL"}))
    ok, msg = market.tiingo_test("any-key")
    assert ok is True and msg == "Connected"


def test_tiingo_test_reports_failure(monkeypatch):
    monkeypatch.setattr(market.httpx, "get", lambda *a, **k: _FakeResp({}, status_ok=False))
    ok, msg = market.tiingo_test("any-key")
    assert ok is False and msg  # non-empty message
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: FAIL — `_tiingo_key` ignores settings; `market.tiingo_test` doesn't exist.

- [ ] **Step 3: Implement** — in `backend/app/data/market.py`, replace `_tiingo_key` (lines ~73-75) and add `tiingo_test` after it:

```python
def _tiingo_key() -> str:
    """Tiingo API key, settings-first then env. Reads the saved Settings via the deps
    singleton (function-local import — no import cycle; deps never imports market), falling
    back to the TIINGO_API_KEY env var, mirroring the news/LLM settings-first-then-env pattern."""
    from app.deps import get_settings_store
    saved = get_settings_store().load().market_data.tiingo_api_key
    return saved or os.environ.get("TIINGO_API_KEY", "")


def tiingo_test(api_key: str) -> tuple[bool, str]:
    """Best-effort connectivity/entitlement check for a Tiingo key: an authenticated GET to the
    same daily-metadata endpoint the EOD fallback uses. Never raises."""
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
```

- [ ] **Step 4: Run the recovery suite, then the full backend suite**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q`
Expected: PASS (new + existing recovery tests green — existing `setenv`-based tests still work: when settings has no key, env is used)

Run: `cd backend; .venv/Scripts/python.exe -m pytest -q`
Expected: PASS (full suite; no regression)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_recovery.py
git commit -m "feat(backend): resolve Tiingo key settings-first + add tiingo_test"
```

---

### Task 4: Route — `POST /api/market/tiingo/test`

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_api.py`, using the SAME `TestClient`/client fixture the other tests in that file use (inspect the top of the file for the fixture name, e.g. `client`). The route depends only on the module-level `_tiingo_key`/`tiingo_test` (monkeypatchable on `app.api.routes`), no `Depends`:

```python
def test_market_tiingo_test_no_key(client, monkeypatch):
    import app.api.routes as routes
    monkeypatch.setattr(routes, "_tiingo_key", lambda: "")
    r = client.post("/api/market/tiingo/test")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "No Tiingo API key configured"}


def test_market_tiingo_test_passes_through(client, monkeypatch):
    import app.api.routes as routes
    monkeypatch.setattr(routes, "_tiingo_key", lambda: "k")
    monkeypatch.setattr(routes, "tiingo_test", lambda key: (True, "Connected"))
    r = client.post("/api/market/tiingo/test")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "Connected"}
```

(If the file's client fixture has a different name/shape, match it — the assertions stay the same.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_api.py -q -k tiingo`
Expected: FAIL — route 404 (not registered yet).

- [ ] **Step 3: Implement** — in `backend/app/api/routes.py`:

Add the import near the other `app.*` imports at the top (if `app.data.market` is already imported, extend that line instead):

```python
from app.data.market import _tiingo_key, tiingo_test
```

Add the route next to the other test endpoints (after `test_news_provider`, ~line 500):

```python
@router.post("/market/tiingo/test")
def test_tiingo_connection() -> dict:
    key = _tiingo_key()
    if not key:
        return {"ok": False, "message": "No Tiingo API key configured"}
    ok, message = tiingo_test(key)
    return {"ok": ok, "message": message}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_api.py -q -k tiingo`
Expected: PASS
Run: `cd backend; .venv/Scripts/python.exe -m pytest -q`
Expected: PASS (full suite)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(backend): POST /api/market/tiingo/test connection check"
```

---

### Task 5: Frontend — type, API call, Settings section + test

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Settings.tsx`
- Test: `frontend/src/pages/Settings.test.tsx`

- [ ] **Step 1: Write the failing test** — append to `frontend/src/pages/Settings.test.tsx`, mirroring the existing render/test-flow tests in that file (reuse its existing render helper, query-client wrapper, and `api` mock). The test must render Settings, find the Tiingo field, and assert the Test-connection button triggers a save-then-`testTiingo` call:

```tsx
it('tests the Tiingo connection (save-first)', async () => {
  // mock api.saveSettings + api.testTiingo on the same `api` mock the other tests use
  const testTiingo = vi.spyOn(api, 'testTiingo').mockResolvedValue({ ok: true, message: 'Connected' });
  vi.spyOn(api, 'saveSettings').mockResolvedValue({} as never);
  renderSettings();                                  // use the file's existing render helper
  const key = await screen.findByLabelText(/Tiingo API key/i);
  fireEvent.change(key, { target: { value: 'tok' } });
  fireEvent.click(screen.getByRole('button', { name: /Test connection/i, }));  // the Market-data one
  await waitFor(() => expect(testTiingo).toHaveBeenCalled());
});
```

If multiple "Test connection" buttons make the query ambiguous, scope the query to the Market-data `<section>` (e.g. `within(screen.getByText('Market data').closest('section')!)`).

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/pages/Settings.test.tsx`
Expected: FAIL — no Tiingo field / `api.testTiingo` undefined.

- [ ] **Step 3: Implement**

(a) `frontend/src/types.ts` — add the interface after `ProviderConfig` (line ~261) and the field to `Settings` (after `news?`):

```ts
export interface MarketDataConfig { tiingo_api_key: string; }
```
```ts
  news?: NewsConfig;
  market_data?: MarketDataConfig;
```

(b) `frontend/src/api/client.ts` — add after `testNews` (line ~67):

```ts
  testTiingo: () => http<TestResult>('/market/tiingo/test', { method: 'POST' }),
```

(c) `frontend/src/pages/Settings.tsx`:

Add to the type import (line 5) `MarketDataConfig`:
```ts
import type { AlertConfig, MarketDataConfig, NewsConfig, NewsProviderId, ProviderId, Settings as SettingsT, TestResult, TruthSignalConfig } from '../types';
```

Add a default constant near `DEFAULT_NEWS` (line ~11):
```ts
const DEFAULT_MARKET_DATA: MarketDataConfig = { tiingo_api_key: '' };
```

Add state near the other test states (line ~28):
```ts
  const [tiingoTest, setTiingoTest] = useState<TestResult | null>(null);
```

Add the derived config + updater near `updateNews` (line ~67):
```ts
  const marketData = form.market_data ?? DEFAULT_MARKET_DATA;
  const updateMarketData = (patch: Partial<MarketDataConfig>) =>
    update({ market_data: { ...marketData, ...patch } });
```

Add the handler near `onTestNews` (line ~85):
```ts
  const onTestTiingo = async () => {
    setTiingoTest(null);
    await save.mutateAsync(form);
    setTiingoTest(await api.testTiingo());
  };
```

Add the new section after the News `</section>` (line ~285), before `<div className="settings-actions">`:
```tsx
      <section className="panel settings-card">
      <h3>Market data</h3>
      <div className="field">
        <label htmlFor="tiingo-key">Tiingo API key (leave as **** to keep the saved key)</label>
        <input id="tiingo-key" type="password"
               value={marketData.tiingo_api_key}
               onChange={(e) => updateMarketData({ tiingo_api_key: e.target.value })}
               placeholder="****" />
        <p className="muted">Optional fallback for fresh daily prices when Yahoo lags. Free key at tiingo.com; the TIINGO_API_KEY env var also works.</p>
      </div>
      <button className="secondary" onClick={onTestTiingo} disabled={save.isPending}>Test connection</button>
      {tiingoTest && <span className={`note ${tiingoTest.ok ? 'muted' : 'error'}`} style={{ marginLeft: 8 }}>{tiingoTest.ok ? '✓ ' : '✗ '}{tiingoTest.message}</span>}
      </section>
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend; npm test -- --run src/pages/Settings.test.tsx`
Expected: PASS
Run: `cd frontend; npm test -- --run`
Expected: PASS (full frontend suite — no regression)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(frontend): Tiingo API key + Test connection in Settings"
```

---

### Task 6: Full verification + final review

**Files:** none (verification only).

- [ ] **Step 1: Backend full suite** — `cd backend; .venv/Scripts/python.exe -m pytest -q` → all green.
- [ ] **Step 2: Frontend full suite** — `cd frontend; npm test -- --run` → all green.
- [ ] **Step 3: Import sanity** — `cd backend; .venv/Scripts/python.exe -c "from app.api.routes import test_tiingo_connection; from app.data.market import _tiingo_key, tiingo_test; from app.models.schemas import Settings; print(Settings().market_data.tiingo_api_key == '' and 'ok')"` → prints `ok`.
- [ ] **Step 4: Final whole-implementation code review** (handled by the controller via subagent-driven-development).

---

## Self-Review

**Spec coverage:**
- `MarketDataConfig` + `Settings.market_data`, no validator change → Task 1. ✓
- mask/merge like telegram token → Task 2. ✓
- `_tiingo_key` settings-first/env via deps singleton, function-local import → Task 3. ✓
- `tiingo_test` (daily/AAPL, best-effort) → Task 3. ✓
- `POST /api/market/tiingo/test` (no-key message; passthrough; never 500) → Task 4. ✓
- Frontend type + `api.testTiingo` + Market-data section (masked field, save-first Test button, inline ✓/✗) → Task 5. ✓
- Regression safety (recovery tests, full suites) → Tasks 3, 4, 6. ✓
- No new dependency; env var preserved as fallback → Tasks 1/3. ✓

**Placeholder scan:** none — every step has concrete code/commands/expected output. (The two "match the existing fixture/helper name" notes in Tasks 4-5 are deliberate: reuse the file's existing test harness rather than invent a parallel one.)

**Type consistency:** `MarketDataConfig.tiingo_api_key` (py + ts), `Settings.market_data`, `_tiingo_key() -> str`, `tiingo_test(api_key: str) -> tuple[bool, str]`, `api.testTiingo() -> TestResult`, route returns `{ok, message}` — names/shapes consistent across backend, route, and frontend.
