# Tiingo enable/disable toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `tiingo_enabled` toggle (default on) to the Market-data settings + a checkbox in the Settings UI; when off, `fetch_history`'s recovery skips Tiingo (Yahoo-only) while keeping the saved key and Test-connection usable.

**Architecture:** `MarketDataConfig` gains `tiingo_enabled: bool = True`. `market.py` gains `_tiingo_enabled()` (settings-read, mirroring `_tiingo_key()`), and `fetch_history`'s Tiingo branch becomes `if _tiingo_enabled() and _tiingo_key():`. A checkbox in the Settings "Market data" section binds to `market_data.tiingo_enabled`.

**Tech Stack:** Python 3.13, pydantic v2; React + Vite + TS + vitest.

**Spec:** `docs/superpowers/specs/2026-06-16-tiingo-enabled-toggle-design.md`
**Branch:** `feat/tiingo-toggle` (already checked out).
**Test harness:** backend — from `backend/`, `.venv/Scripts/python.exe -m pytest -q`. frontend — from `frontend/`, `npm test -- --run`.

---

## File Structure
- **Modify** `backend/app/models/schemas.py` — add `tiingo_enabled` to `MarketDataConfig`.
- **Modify** `backend/app/data/market.py` — add `_tiingo_enabled()`; gate the Tiingo branch.
- **Modify** `frontend/src/types.ts`, `frontend/src/pages/Settings.tsx` — type + `DEFAULT_MARKET_DATA` + checkbox.
- **Tests:** `backend/tests/test_schemas.py`, `backend/tests/test_market_recovery.py`, `frontend/src/pages/Settings.test.tsx`.

---

### Task 1: Schema — `tiingo_enabled`

**Files:** Modify `backend/app/models/schemas.py`; Test `backend/tests/test_schemas.py`.

- [ ] **Step 1: Failing test** — append to `backend/tests/test_schemas.py`:

```python
def test_market_data_tiingo_enabled_defaults_true():
    from app.models.schemas import Settings
    assert Settings().market_data.tiingo_enabled is True
    # legacy blobs (market_data without the field, and no market_data) deserialize to True
    assert Settings.model_validate_json('{"market_data": {"tiingo_api_key": "x"}}').market_data.tiingo_enabled is True
    assert Settings.model_validate_json('{}').market_data.tiingo_enabled is True
```

- [ ] **Step 2: Run → fail**: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_schemas.py::test_market_data_tiingo_enabled_defaults_true -q` → FAIL (`'MarketDataConfig' object has no attribute 'tiingo_enabled'`).

- [ ] **Step 3: Implement** — in `backend/app/models/schemas.py`, the current class is:
```python
class MarketDataConfig(BaseModel):
    """Market-data source settings. Today: the Tiingo EOD fallback key used by the stale-bar
    recovery in app/data/market.py (env var TIINGO_API_KEY remains the fallback)."""
    tiingo_api_key: str = ""
```
Add the field:
```python
class MarketDataConfig(BaseModel):
    """Market-data source settings. Today: the Tiingo EOD fallback key used by the stale-bar
    recovery in app/data/market.py (env var TIINGO_API_KEY remains the fallback)."""
    tiingo_api_key: str = ""
    tiingo_enabled: bool = True
```

- [ ] **Step 4: Run → pass**: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_schemas.py -q` → PASS.

- [ ] **Step 5: Commit**:
```bash
git add backend/app/models/schemas.py backend/tests/test_schemas.py
git commit -m "feat(backend): add tiingo_enabled toggle to MarketDataConfig"
```

---

### Task 2: Gate — `_tiingo_enabled()` + `fetch_history` branch

**Files:** Modify `backend/app/data/market.py`; Test `backend/tests/test_market_recovery.py`.

- [ ] **Step 1: Failing tests** — append to `backend/tests/test_market_recovery.py` (`Settings`, `market`, `pd`, `date`, `_bars`, `_patch_target` already available; the autouse `_isolate_tiingo_settings` fixture defaults the store to `Settings()` → `tiingo_enabled True`):

```python
def test_tiingo_enabled_reads_settings(monkeypatch):
    import app.deps as deps

    class _Store:
        def __init__(self, enabled):
            self._enabled = enabled

        def load(self):
            s = Settings()
            s.market_data.tiingo_enabled = self._enabled
            return s

    monkeypatch.setattr(deps, "get_settings_store", lambda: _Store(False))
    assert market._tiingo_enabled() is False
    monkeypatch.setattr(deps, "get_settings_store", lambda: _Store(True))
    assert market._tiingo_enabled() is True


def test_fetch_history_skips_tiingo_when_disabled(monkeypatch):
    _patch_target(monkeypatch)
    monkeypatch.setenv("TIINGO_API_KEY", "secret")          # key present...
    monkeypatch.setattr(market, "_tiingo_enabled", lambda: False)  # ...but toggle off
    stale = _bars(["2026-06-11", "2026-06-12"])
    monkeypatch.setattr(market, "fetch_yf_history", lambda t, p="2y": stale)
    monkeypatch.setattr(market, "fetch_yf_recent", lambda t: pd.DataFrame())
    called = []
    monkeypatch.setattr(market, "fetch_tiingo_eod",
                        lambda t, s: called.append("x") or _bars(["2026-06-15"], close_start=200.0))
    out = market.fetch_history("AAPL", "1y")
    assert called == []                                     # Tiingo NOT used when disabled
    assert market._last_date(out) == date(2026, 6, 12)      # stays stale (Yahoo-only)
```

- [ ] **Step 2: Run → fail**: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q` → FAIL (`market._tiingo_enabled` missing; and the disabled test fails because the current gate ignores the toggle).

- [ ] **Step 3: Implement** — in `backend/app/data/market.py`:

(a) Add immediately AFTER `_tiingo_key()` (after its `return saved or os.environ.get(...)` line):
```python
def _tiingo_enabled() -> bool:
    """Whether the Tiingo EOD fallback is enabled in settings (default True). Settings-only —
    the toggle gates *usage* in recovery; the key keeps its TIINGO_API_KEY env fallback."""
    from app.deps import get_settings_store
    return get_settings_store().load().market_data.tiingo_enabled
```

(b) In `fetch_history`, change the Tiingo guard line from:
```python
    if _tiingo_key():
```
to:
```python
    if _tiingo_enabled() and _tiingo_key():
```

- [ ] **Step 4: Run → pass** then full suite:
  - `cd backend; .venv/Scripts/python.exe -m pytest tests/test_market_recovery.py -q` → PASS (new tests + existing recovery tests; the existing `test_fetch_history_falls_back_to_tiingo` etc. still pass because the autouse store defaults `tiingo_enabled` to True).
  - `cd backend; .venv/Scripts/python.exe -m pytest -q` → all green.

- [ ] **Step 5: Commit**:
```bash
git add backend/app/data/market.py backend/tests/test_market_recovery.py
git commit -m "feat(backend): gate Tiingo recovery on tiingo_enabled toggle"
```

---

### Task 3: Frontend — type + checkbox

**Files:** Modify `frontend/src/types.ts`, `frontend/src/pages/Settings.tsx`; Test `frontend/src/pages/Settings.test.tsx`.

- [ ] **Step 1: Failing test** — append to `frontend/src/pages/Settings.test.tsx`, matching the file's existing render helper + `api` mock + save-button query (inspect a couple of existing tests first). Target:

```tsx
it('toggles Tiingo enabled off and persists it on save', async () => {
  const saveSettings = vi.spyOn(api, 'saveSettings').mockResolvedValue(SETTINGS as never);
  renderSettings();                                    // use the file's existing render helper
  const checkbox = await screen.findByLabelText(/Use Tiingo as a fallback/i);
  expect(checkbox).toBeChecked();                      // default true (DEFAULT_MARKET_DATA fallback)
  fireEvent.click(checkbox);                           // turn off
  fireEvent.click(screen.getByRole('button', { name: /^Save$/ }));
  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  const saved = saveSettings.mock.calls[0][0] as any;
  expect(saved.market_data.tiingo_enabled).toBe(false);
});
```

Adapt the render-helper name, the `api` mock style (`vi.spyOn` vs `vi.mock` factory), and the Save-button matcher to the file's conventions; keep the behavior (checkbox starts checked, toggling off then Save sends `market_data.tiingo_enabled === false`).

- [ ] **Step 2: Run → fail**: `cd frontend; npm test -- --run src/pages/Settings.test.tsx` → FAIL (no checkbox with that label).

- [ ] **Step 3: Implement**

(a) `frontend/src/types.ts` line 261 — extend the interface:
```ts
export interface MarketDataConfig { tiingo_api_key: string; tiingo_enabled: boolean; }
```

(b) `frontend/src/pages/Settings.tsx` line 7 — extend the default:
```ts
const DEFAULT_MARKET_DATA: MarketDataConfig = { tiingo_api_key: '', tiingo_enabled: true };
```

(c) `frontend/src/pages/Settings.tsx` — in the "Market data" `<section>`, add the checkbox immediately AFTER `<h3>Market data</h3>` and BEFORE the `<div className="field">` that holds the key input:
```tsx
        <div className="field check">
          <label>
            <input type="checkbox" checked={marketData.tiingo_enabled}
                   onChange={(e) => updateMarketData({ tiingo_enabled: e.target.checked })} />
            Use Tiingo as a fallback when Yahoo data lags (off = Yahoo only)
          </label>
        </div>
```
(Leave the key field and Test-connection button as-is — always enabled.)

- [ ] **Step 4: Run → pass** then full suite:
  - `cd frontend; npm test -- --run src/pages/Settings.test.tsx` → PASS.
  - `cd frontend; npm test -- --run` → all green. (Run the project's typecheck/build if one exists, e.g. `npm run build`, to catch TS errors; skip if no such script.)

- [ ] **Step 5: Commit**:
```bash
git add frontend/src/types.ts frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(frontend): Tiingo enable/disable checkbox in Settings"
```

---

### Task 4: Full verification + final review

**Files:** none (verification only).

- [ ] **Step 1: Backend** — `cd backend; .venv/Scripts/python.exe -m pytest -q` → all green.
- [ ] **Step 2: Frontend** — `cd frontend; npm test -- --run` → all green.
- [ ] **Step 3: Gate sanity** — `cd backend; .venv/Scripts/python.exe -c "from app.data.market import _tiingo_enabled; from app.models.schemas import Settings; print('default on:', Settings().market_data.tiingo_enabled is True)"` → prints `default on: True`.
- [ ] **Step 4: Final whole-implementation review** (controller dispatches via subagent-driven-development).

---

## Self-Review

**Spec coverage:** `tiingo_enabled: bool = True` (T1) ✓; `_tiingo_enabled()` + gate `if _tiingo_enabled() and _tiingo_key():` (T2) ✓; checkbox + type + default, key/Test stay enabled (T3) ✓; default-True migration + existing-tests-stay-green (T1/T2) ✓; no masking change, no env toggle, no per-ticker (non-goals respected) ✓.

**Placeholder scan:** none — concrete code/commands throughout. (The "match the file's render helper/save matcher" note in T3 is intentional reuse of the existing harness.)

**Type consistency:** `MarketDataConfig.tiingo_enabled` (py `bool` / ts `boolean`), `_tiingo_enabled() -> bool`, `DEFAULT_MARKET_DATA.tiingo_enabled`, `updateMarketData({ tiingo_enabled })` — consistent across schema, gate, and UI.
