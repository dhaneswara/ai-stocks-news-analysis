# Discover Board "Show" Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Show" dropdown (25 / 50 / 100 / All) to the Discover board that controls how many ranked rows are returned, with "All" = no cap.

**Architecture:** The `GET /api/screen` route already accepts `limit`; fix its handling so an omitted limit means `top_n` (unchanged) while `limit=0` means "all". Thread a `limit` through the `useScreen` hook and add a "Show" `<select>` to the Discover command bar.

**Tech Stack:** FastAPI + pytest (backend); React + TS + Vite + vitest + @tanstack/react-query (frontend).

---

**Spec:** [docs/superpowers/specs/2026-06-06-board-show-control-design.md](../specs/2026-06-06-board-show-control-design.md)

**Conventions (apply to every task):**
- Backend tests from `backend/`: `.venv\Scripts\python.exe -m pytest -q`.
- Commits use Conventional Commits.
- Frontend from `frontend/`: `npm run test` (vitest run) and `npm run build` (tsc + vite).

---

## File structure

**Backend (modify):** `backend/app/api/routes.py` (the `screen` route's final slice), `backend/tests/test_api_screen.py` (new limit=0 test).

**Frontend (modify):** `frontend/src/hooks/queries.ts` (`useScreen` gains `limit`), `frontend/src/api/client.test.ts` (limit=0 test), `frontend/src/pages/Discover.tsx` (the "Show" select). `client.ts` already supports `limit` — no change.

---

## Task 1: Backend — `limit=0` means "all"

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_screen.py`

- [ ] **Step 1: Write the failing test** (append to `backend/tests/test_api_screen.py`)

This test uses a store whose `top_n` is 2 so that "all" (limit=0) must beat the cap — proving
`limit=0` is not treated as falsy-and-defaulted (the old `limit or top_n` bug):

```python
def test_screen_limit_zero_returns_all_uncapped(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)  # 3 items

    class _SmallStore:
        def load(self):
            s = Settings()
            s.screener.top_n = 2
            return s

    app.dependency_overrides[routes.get_settings_store] = lambda: _SmallStore()
    app.dependency_overrides[routes.get_cache] = lambda: cache
    client = TestClient(app)
    capped = client.get("/api/screen").json()["items"]          # no limit -> top_n = 2
    all_items = client.get("/api/screen?limit=0").json()["items"]  # limit=0 -> uncapped
    app.dependency_overrides.clear()
    assert len(capped) == 2
    assert len(all_items) == 3
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api_screen.py::test_screen_limit_zero_returns_all_uncapped -q`
Expected: FAIL — `all_items` has length 2 (the old `limit or top_n` treats `0` as falsy → caps at 2).

- [ ] **Step 3: Fix the route's slice logic**

In `backend/app/api/routes.py`, in the `screen` function, replace the final return line:

```python
    return board.model_copy(update={"items": items[: (limit or settings.screener.top_n)]})
```

with:

```python
    n = settings.screener.top_n if limit is None else limit
    shown = items if n <= 0 else items[:n]
    return board.model_copy(update={"items": shown})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api_screen.py -q`
Expected: PASS — the new test plus the existing screen tests (the no-limit default still caps at
`top_n`, and `?limit=2` still returns 2).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_screen.py
git commit   # feat(backend): treat /screen?limit=0 as "all" (uncapped)
```

---

## Task 2: Frontend — `useScreen` limit param + client test

**Files:**
- Modify: `frontend/src/hooks/queries.ts`, `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing client test**

Paste this `it(...)` inside the existing `describe('api client', ...)` in
`frontend/src/api/client.test.ts`:

```ts
  it('getScreen sends limit=0 for "All"', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getScreen(undefined, undefined, 0);
    expect(fetchMock.mock.calls[0][0] as string).toContain('limit=0');
  });
```

- [ ] **Step 2: Run to verify it passes already (regression lock)**

Run (from `frontend/`): `npm run test -- client`
Expected: PASS — `client.ts`'s `getScreen` already sends `limit` when `!= null`, so `0` is
included. (This test locks that behavior so a future refactor can't silently drop `limit=0`.)

> Note: this is a regression-guard test for existing behavior, so it passes immediately — there is
> no red phase here. The behavioral change in this task is the hook signature in Step 3.

- [ ] **Step 3: Add the `limit` param to `useScreen`**

In `frontend/src/hooks/queries.ts`, replace the `useScreen` hook:

```ts
export function useScreen(sector?: string, direction?: string) {
  return useQuery({
    queryKey: ['screen', sector ?? '', direction ?? ''],
    queryFn: () => api.getScreen(sector, direction),
  });
}
```

with:

```ts
export function useScreen(sector?: string, direction?: string, limit?: number) {
  return useQuery({
    queryKey: ['screen', sector ?? '', direction ?? '', limit ?? ''],
    queryFn: () => api.getScreen(sector, direction, limit),
  });
}
```

- [ ] **Step 4: Typecheck + run tests**

Run (from `frontend/`): `npm run build && npm run test`
Expected: clean tsc (the existing `useScreen(sector || undefined, direction || undefined)` call in
`Discover.tsx` still type-checks — `limit` is optional); all vitest tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/queries.ts frontend/src/api/client.test.ts
git commit   # feat(frontend): useScreen limit param + limit=0 client test
```

---

## Task 3: Frontend — the "Show" select on Discover

**Files:**
- Modify: `frontend/src/pages/Discover.tsx`

- [ ] **Step 1: Add `show` state and pass it to `useScreen`**

In `frontend/src/pages/Discover.tsx`, add the state next to the existing `sector`/`direction`
state (after `const [direction, setDirection] = useState('');`):

```tsx
  const [show, setShow] = useState(25);
```

Then update the `useScreen` call to pass it:

```tsx
  const board = useScreen(sector || undefined, direction || undefined, show);
```

- [ ] **Step 2: Add the "Show" dropdown**

In the `.board-controls` block, add this `<label>` immediately **after** the "Call" `<label>` and
**before** the `<span className="spacer" />`:

```tsx
          <label>Show
            <select value={show} onChange={(e) => setShow(Number(e.target.value))}>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={0}>All</option>
            </select>
          </label>
```

- [ ] **Step 3: Typecheck, build, test**

Run (from `frontend/`): `npm run build && npm run test`
Expected: clean tsc; vite build succeeds; all vitest tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Discover.tsx
git commit   # feat(frontend): "Show" (25/50/100/All) control on the Discover board
```

---

## Self-review notes (coverage vs spec)

- **"Show" dropdown 25/50/100/All, default 25** → Task 3 (`<select>` with `value={show}`, default
  `useState(25)`). ✅
- **"All" = `limit=0`, omitted limit = `top_n`** → Task 1 (route `n = top_n if limit is None else
  limit; shown = items if n <= 0 else items[:n]`); proven by `test_screen_limit_zero_returns_all_uncapped`
  (top_n=2 store: default caps at 2, limit=0 returns all 3). ✅
- **Default unchanged for existing callers** → Task 1 (omitted `limit` still → `top_n`; existing
  `?limit=2` + no-limit tests still pass). ✅
- **`limit` threaded through the hook; key includes it so changes refetch** → Task 2
  (`useScreen(sector, direction, limit)`, queryKey `['screen', …, limit ?? '']`). ✅
- **Client already sends `limit` (incl. 0)** → Task 2 regression test (`getScreen(…, 0)` →
  `limit=0`). ✅
- **Session-local, no persistence / pagination (YAGNI)** → only local `show` state; nothing
  persisted. ✅

**Type/name consistency:** `useScreen(sector?, direction?, limit?)` (Task 2) is called as
`useScreen(sector || undefined, direction || undefined, show)` (Task 3); `show` is a `number`
(`useState(25)`, `Number(e.target.value)`), matching `getScreen`'s `limit?: number`. The route's
`limit: int | None` (Task 1) receives the `?limit=` query the client builds.
