# Single-ticker Rescan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-row ⟳ button to the shared board that re-scores a single ticker, persists it durably into the saved snapshot, patches that row in place (re-sorted, no full refetch), and records the ticker's technical/network signal for evaluation.

**Architecture:** Reuse the existing single-ticker primitives — `score_one` (network-blended) and `record_deterministic_pair` (eval recording) — behind a new synchronous `POST /api/screen/rescan/{ticker}?scope=`. A small `store.upsert_score` helper writes the fresh row back into the scope's snapshot. The frontend adds an `api.rescanTicker` call, a `useRescanTicker` mutation that patches the `['screen']` query cache, and a ⟳ button on `ScoreBoard` wired into Discover and Portfolio.

**Tech Stack:** Python 3.13 / FastAPI / pytest (backend); React 18 / TypeScript / TanStack Query / Vitest + Testing Library (frontend).

**Spec:** [docs/superpowers/specs/2026-06-14-single-ticker-rescan-design.md](../specs/2026-06-14-single-ticker-rescan-design.md)

**Conventions:**
- Backend tests run from `backend/`: `.venv/Scripts/python.exe -m pytest -q` (venv activation does not persist between tool calls — always call the interpreter explicitly).
- Frontend tests run from `frontend/`: `npm test` (alias for `vitest run`); a single file: `npm test -- src/path/to/file.test.tsx`.
- Conventional Commits, one per task. **No `Co-Authored-By: Claude` trailer.**

---

## File Structure

**Backend**
- Modify `backend/app/screener/store.py` — add `upsert_score(score, scope, cache) -> ScreenBoard`.
- Modify `backend/app/evaluation/signals.py` — add optional `score=` param to `record_deterministic_pair`.
- Modify `backend/app/api/routes.py` — add `POST /screen/rescan/{ticker}` route + two imports.
- Test `backend/tests/test_screener_service.py` — `upsert_score` unit tests.
- Test `backend/tests/test_evaluation_signals.py` — precomputed-score test.
- Test `backend/tests/test_api_screen.py` — route tests.

**Frontend**
- Modify `frontend/src/api/client.ts` — add `rescanTicker`.
- Modify `frontend/src/hooks/queries.ts` — add `useRescanTicker(scope?)`.
- Modify `frontend/src/components/ScoreBoard.tsx` — add `onRescan` / `rescanning` props + ⟳ button.
- Modify `frontend/src/styles.css` — add `.rescan-btn` + spin animation.
- Modify `frontend/src/pages/Discover.tsx` — wire the hook (scope `all`).
- Modify `frontend/src/pages/Portfolio.tsx` — wire the hook (scope `portfolio`) into both boards.
- Test `frontend/src/api/client.test.ts` — `rescanTicker` URL.
- Test `frontend/src/hooks/queries` — new `frontend/src/hooks/useRescanTicker.test.tsx`.
- Test `frontend/src/components/ScoreBoard.test.tsx` — ⟳ rendering + behavior.

---

## Task 1: `upsert_score` store helper

Writes one fresh row into the scope's saved snapshot (replace-or-append, re-sorted). Mirrors the existing `merge_sector` helper.

**Files:**
- Modify: `backend/app/screener/store.py`
- Test: `backend/tests/test_screener_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_screener_service.py`. Note this file already imports `from app.screener.store import save_snapshot, load_snapshot` — extend that import line to include `upsert_score` (the existing import is near the top of the file alongside `merge_sector`; if `upsert_score` is not yet importable the test will fail at import, which is fine for Step 2).

```python
def test_upsert_score_appends_when_absent_and_sorts(tmp_path):
    from app.screener.store import upsert_score, load_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=50, direction="hold"),
    ]), cache)
    fresh = StockScore(ticker="BBB", name="B", sector="Energy", price=1, change_pct=0, score=90, direction="buy")
    board = upsert_score(fresh, None, cache)
    assert [i.ticker for i in board.items] == ["BBB", "AAA"]            # re-sorted by score desc
    assert [i.ticker for i in load_snapshot(cache, "all").items] == ["BBB", "AAA"]  # persisted


def test_upsert_score_replaces_existing_case_insensitively(tmp_path):
    from app.screener.store import upsert_score, load_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=90, direction="buy"),
        StockScore(ticker="BBB", name="B", sector="Energy", price=1, change_pct=0, score=80, direction="sell"),
    ]), cache)
    fresh = StockScore(ticker="aaa", name="A", sector="Tech", price=2, change_pct=1, score=10, direction="sell")
    board = upsert_score(fresh, None, cache)
    assert [i.ticker for i in board.items] == ["BBB", "aaa"]           # AAA re-scored to 10, sinks below BBB
    assert len([i for i in board.items if i.ticker.upper() == "AAA"]) == 1  # no duplicate


def test_upsert_score_routes_portfolio_scope_to_portfolio_snapshot(tmp_path):
    from app.screener.store import upsert_score, load_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    fresh = StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=50, direction="hold")
    upsert_score(fresh, "portfolio", cache)
    assert load_snapshot(cache, "portfolio").items[0].ticker == "AAA"  # created under portfolio
    assert load_snapshot(cache, "all") is None                          # all untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_screener_service.py -q -k upsert_score`
Expected: FAIL — `ImportError: cannot import name 'upsert_score'`.

- [ ] **Step 3: Implement `upsert_score`**

Append to `backend/app/screener/store.py` (after `merge_sector`):

```python
def upsert_score(score: StockScore, scope: str | None, cache: Cache) -> ScreenBoard:
    """Write one freshly re-scored row into the scope's saved snapshot, then re-rank.

    Replaces the row with a matching ticker (case-insensitive) or appends it; the board-level
    as_of/scanned/skipped are left untouched because only one row was rescanned. Creates a fresh
    empty board when no snapshot exists. `scope="portfolio"` targets the portfolio snapshot; any
    other scope (a sector name or None) targets the broad "all" snapshot, matching how the rescan
    stream persists.
    """
    snap_scope = "portfolio" if scope == "portfolio" else "all"
    board = load_snapshot(cache, snap_scope) or ScreenBoard(scope=snap_scope)
    kept = [i for i in board.items if i.ticker.upper() != score.ticker.upper()]
    items = kept + [score]
    items.sort(key=lambda s: s.score, reverse=True)
    board = board.model_copy(update={"items": items})
    save_snapshot(board, cache)
    return board
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_screener_service.py -q -k upsert_score`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/store.py backend/tests/test_screener_service.py
git commit -m "feat(backend): upsert_score — write one fresh row into the board snapshot"
```

---

## Task 2: Optional precomputed `score` for `record_deterministic_pair`

So the new route can record the eval signal without scoring the ticker a second time.

**Files:**
- Modify: `backend/app/evaluation/signals.py:42-63`
- Test: `backend/tests/test_evaluation_signals.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_evaluation_signals.py` (the `_stock`, `_score` helpers and `signals` import already exist at the top of the file):

```python
def test_pair_uses_precomputed_score_without_rescoring(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))

    def boom(*a, **k):  # score_one must NOT be called when a score is supplied
        raise AssertionError("score_one should not be called when score= is given")

    monkeypatch.setattr(signals, "score_one", boom)
    record_deterministic_pair(_stock(), Settings(), Cache(str(tmp_path / "c.db")), store,
                              score=_score(base_net=0.3, net=0.3, direction="buy"))
    assert store.get_prediction("AAPL", "2026-06-05", "technical") is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_evaluation_signals.py -q -k precomputed`
Expected: FAIL — `TypeError: record_deterministic_pair() got an unexpected keyword argument 'score'`.

- [ ] **Step 3: Add the optional parameter**

In `backend/app/evaluation/signals.py`, change the signature and first body line of `record_deterministic_pair`.

Replace:

```python
def record_deterministic_pair(stock: StockData, settings: Settings, cache: Cache,
                              store: PredictionStore) -> None:
    """Record the technical call (pre-network base vote) and — when a network signal actually
    influenced the score — the network-blended call, keyed to the same last-candle
    call_date/entry convention record_prediction uses."""
    if not stock.candles:
        return
    score = score_one(stock.ticker, settings, cache)
```

With:

```python
def record_deterministic_pair(stock: StockData, settings: Settings, cache: Cache,
                              store: PredictionStore, *, score: StockScore | None = None) -> None:
    """Record the technical call (pre-network base vote) and — when a network signal actually
    influenced the score — the network-blended call, keyed to the same last-candle
    call_date/entry convention record_prediction uses.

    Pass a precomputed `score` (e.g. from the single-ticker rescan) to avoid re-running
    score_one; otherwise it is computed here as before."""
    if not stock.candles:
        return
    score = score if score is not None else score_one(stock.ticker, settings, cache)
```

(`StockScore` is already imported in this module.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_evaluation_signals.py -q`
Expected: PASS (all existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/signals.py backend/tests/test_evaluation_signals.py
git commit -m "feat(backend): record_deterministic_pair accepts a precomputed score"
```

---

## Task 3: `POST /api/screen/rescan/{ticker}` route

**Files:**
- Modify: `backend/app/api/routes.py:78-79` (imports) and after the `screen_rescan_stream` route (~line 610)
- Test: `backend/tests/test_api_screen.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_screen.py`. This file already imports `routes`, `Cache`, `app`, `ScreenBoard`, `Settings`, `StockScore`, `save_snapshot`, and defines `_client(cache)` / `_board()`. Add `PredictionStore` and `load_snapshot` imports at the top, plus a `_stock` helper.

```python
from app.evaluation.store import PredictionStore
from app.models.schemas import Candle, Fundamentals, Indicators, PriceSummary, StockData
from app.screener.store import load_snapshot


def _stock(ticker="BBB"):
    return StockData(
        ticker=ticker, company_name="B", as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=10.0, change=1.0, change_pct=1.0),
        candles=[Candle(time="2026-06-05", open=1, high=1, low=1, close=10.0, volume=1)],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def _fresh(ticker="BBB", score=99.0):
    return StockScore(ticker=ticker, name="B", sector="Energy", price=10.0, change_pct=1.0,
                      score=score, direction="buy", net=0.4, base_net=0.4, base_score=score, as_of="new")


def test_rescan_ticker_persists_and_returns_fresh_score(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)  # AAA 90, BBB 80, CCC 70
    pstore = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(routes, "get_stock_data", lambda *a, **k: _stock("BBB"))
    monkeypatch.setattr(routes, "score_one", lambda *a, **k: _fresh("BBB", 99.0))
    app.dependency_overrides[routes.get_prediction_store] = lambda: pstore
    client = _client(cache)
    body = client.post("/api/screen/rescan/BBB").json()
    app.dependency_overrides.clear()

    assert body["ticker"] == "BBB" and body["score"] == 99.0
    items = load_snapshot(cache, "all").items
    assert [i.ticker for i in items] == ["BBB", "AAA", "CCC"]          # BBB re-scored to 99, re-sorted
    assert pstore.get_prediction("BBB", "2026-06-05", "technical") is not None  # eval recorded


def test_rescan_ticker_skips_eval_when_disabled(tmp_path, monkeypatch):
    class _OffStore:
        def load(self):
            s = Settings()
            s.evaluation.enabled = False
            return s

    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    pstore = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(routes, "get_stock_data", lambda *a, **k: _stock("BBB"))
    monkeypatch.setattr(routes, "score_one", lambda *a, **k: _fresh("BBB", 99.0))
    app.dependency_overrides[routes.get_settings_store] = lambda: _OffStore()
    app.dependency_overrides[routes.get_cache] = lambda: cache
    app.dependency_overrides[routes.get_prediction_store] = lambda: pstore
    client = TestClient(app)
    client.post("/api/screen/rescan/BBB")
    app.dependency_overrides.clear()
    assert pstore.all_predictions() == []                              # nothing recorded


def test_rescan_ticker_404_on_no_data(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    pstore = PredictionStore(str(tmp_path / "p.db"))

    def boom(*a, **k):
        raise ValueError("no price history")

    monkeypatch.setattr(routes, "get_stock_data", boom)
    app.dependency_overrides[routes.get_prediction_store] = lambda: pstore
    client = _client(cache)
    resp = client.post("/api/screen/rescan/NOPE")
    app.dependency_overrides.clear()
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_screen.py -q -k rescan_ticker`
Expected: FAIL — 404 for all three (route not registered yet).

- [ ] **Step 3: Add the imports and the route**

In `backend/app/api/routes.py`, extend the two existing screener imports:

Replace line 78:
```python
from app.screener.service import iter_scan, portfolio_universe, run_scan, score_one
```
with:
```python
from app.screener.service import SCAN_PERIOD, iter_scan, portfolio_universe, run_scan, score_one
```

Replace line 79:
```python
from app.screener.store import load_snapshot, merge_sector, save_snapshot
```
with:
```python
from app.screener.store import load_snapshot, merge_sector, save_snapshot, upsert_score
```

Then add the route immediately after the `screen_rescan_stream` function (after its `return StreamingResponse(...)`, ~line 610):

```python
@router.post("/screen/rescan/{ticker}", response_model=StockScore)
def rescan_ticker(
    ticker: str,
    scope: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> StockScore:
    """Re-score one ticker (no LLM), persist it into the scope's saved snapshot, and record its
    technical/network signal for evaluation. Returns the fresh score so the board patches the
    single row in place. 404 when the ticker has no data, matching GET /score/{ticker}."""
    settings = store.load()
    sym = ticker.upper().strip()
    try:
        stock = get_stock_data(sym, SCAN_PERIOD, settings.indicator_params, cache)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    score = score_one(sym, settings, cache)
    upsert_score(score, scope, cache)
    if settings.evaluation.enabled and stock.candles:
        try:
            record_deterministic_pair(stock, settings, cache, prediction_store, score=score)
        except Exception:  # noqa: BLE001 — eval recording is best-effort
            logger.warning("single-rescan eval recording failed for %s", sym)
    return score
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api_screen.py -q -k rescan_ticker`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_screen.py
git commit -m "feat(backend): POST /screen/rescan/{ticker} — single-row rescan + persist + eval"
```

---

## Task 4: `api.rescanTicker` client method

**Files:**
- Modify: `frontend/src/api/client.ts` (in the `api` object, near `getScore`)
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test**

Append inside the `describe('api client', ...)` block in `frontend/src/api/client.test.ts`:

```ts
it('rescanTicker POSTs and includes the scope query when given', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticker: 'BBB' }) });
  vi.stubGlobal('fetch', fetchMock);
  await api.rescanTicker('BBB', 'portfolio');
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toContain('/screen/rescan/BBB');
  expect(url).toContain('scope=portfolio');
  expect(init).toMatchObject({ method: 'POST' });
});

it('rescanTicker omits the scope query when not given', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticker: 'BBB' }) });
  vi.stubGlobal('fetch', fetchMock);
  await api.rescanTicker('BBB');
  expect(fetchMock.mock.calls[0][0]).not.toContain('scope=');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- src/api/client.test.ts`
Expected: FAIL — `api.rescanTicker is not a function`.

- [ ] **Step 3: Add the client method**

In `frontend/src/api/client.ts`, add after the `getScore` line:

```ts
  rescanTicker: (ticker: string, scope?: string) =>
    http<StockScore>(
      `/screen/rescan/${encodeURIComponent(ticker)}${scope ? `?scope=${encodeURIComponent(scope)}` : ''}`,
      { method: 'POST' },
    ),
```

(`StockScore` is already imported in this file.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(frontend): api.rescanTicker client method"
```

---

## Task 5: `useRescanTicker` hook

A mutation that patches every cached `['screen', …]` board in place (replace the row, re-sort) and exposes the in-flight ticker.

**Files:**
- Modify: `frontend/src/hooks/queries.ts` (add the hook; `useQueryClient`/`useMutation` are already imported there)
- Test: `frontend/src/hooks/useRescanTicker.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useRescanTicker.test.tsx`:

```tsx
import { expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { ScreenBoard, StockScore } from '../types';

vi.mock('../api/client', () => ({ api: { rescanTicker: vi.fn() } }));
import { api } from '../api/client';
import { useRescanTicker } from './queries';

function row(ticker: string, score: number): StockScore {
  return {
    ticker, name: ticker, sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
    price: 1, change_pct: 0, score, direction: 'hold', net: 0,
    reasons: [], components: {}, as_of: 't',
  };
}

const KEY = ['screen', '', '', '', ''];

it('replaces the matching row in the screen cache and re-sorts by score', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData<ScreenBoard>(KEY, {
    as_of: 't', scope: 'all', scanned: 2, skipped: 0, items: [row('AAA', 90), row('BBB', 80)],
  });
  vi.mocked(api.rescanTicker).mockResolvedValue(row('BBB', 99));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useRescanTicker(), { wrapper });
  await act(async () => { await result.current.mutateAsync('BBB'); });

  const board = qc.getQueryData<ScreenBoard>(KEY)!;
  expect(board.items.map((i) => i.ticker)).toEqual(['BBB', 'AAA']);   // re-sorted
  expect(board.items[0].score).toBe(99);                              // patched
});

it('passes the scope through to the API', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(api.rescanTicker).mockResolvedValue(row('BBB', 99));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useRescanTicker('portfolio'), { wrapper });
  await act(async () => { await result.current.mutateAsync('BBB'); });
  await waitFor(() => expect(api.rescanTicker).toHaveBeenCalledWith('BBB', 'portfolio'));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- src/hooks/useRescanTicker.test.tsx`
Expected: FAIL — `useRescanTicker` is not exported.

- [ ] **Step 3: Implement the hook**

In `frontend/src/hooks/queries.ts`, first extend the type import (line 3) — it currently reads `import type { OntologyVersion, Settings, Source } from '../types';` — to add `ScreenBoard` (needed for the `setQueriesData<ScreenBoard>` generic; `fresh`'s `StockScore` type is inferred from `api.rescanTicker`, so do not import it — an unused import fails `npm run lint`):

```ts
import type { OntologyVersion, ScreenBoard, Settings, Source } from '../types';
```

Then add the hook after `useScore`:

```ts
export function useRescanTicker(scope?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.rescanTicker(ticker, scope),
    onSuccess: (fresh) => {
      // Patch the one row in every cached board view (no refetch); re-sort to match the server.
      qc.setQueriesData<ScreenBoard>({ queryKey: ['screen'] }, (board) => {
        if (!board) return board;
        const i = board.items.findIndex(
          (s) => s.ticker.toUpperCase() === fresh.ticker.toUpperCase(),
        );
        if (i === -1) return board;
        const items = [...board.items];
        items[i] = fresh;
        items.sort((a, b) => b.score - a.score);
        return { ...board, items };
      });
    },
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- src/hooks/useRescanTicker.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/queries.ts frontend/src/hooks/useRescanTicker.test.tsx
git commit -m "feat(frontend): useRescanTicker hook patches the board row in place"
```

---

## Task 6: `ScoreBoard` per-row ⟳ button

**Files:**
- Modify: `frontend/src/components/ScoreBoard.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/components/ScoreBoard.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/ScoreBoard.test.tsx` (the `row` helper and imports exist):

```tsx
it('renders a ⟳ rescan button per row only when onRescan is given', () => {
  const items = [row({})];
  const { rerender } = render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.queryByTitle(/rescan AAPL/i)).not.toBeInTheDocument();
  rerender(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} onRescan={() => {}} /></MemoryRouter>);
  expect(screen.getByTitle(/rescan AAPL/i)).toBeInTheDocument();
});

it('calls onRescan with the ticker when ⟳ is clicked', () => {
  const onRescan = vi.fn();
  render(<MemoryRouter><ScoreBoard items={[row({})]} onAdd={() => {}} onRescan={onRescan} /></MemoryRouter>);
  fireEvent.click(screen.getByTitle(/rescan AAPL/i));
  expect(onRescan).toHaveBeenCalledWith('AAPL');
});

it('disables the ⟳ for the row currently being rescanned', () => {
  render(
    <MemoryRouter>
      <ScoreBoard items={[row({})]} onAdd={() => {}} onRescan={() => {}} rescanning="AAPL" />
    </MemoryRouter>,
  );
  expect(screen.getByTitle(/rescanning AAPL/i)).toBeDisabled();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm test -- src/components/ScoreBoard.test.tsx`
Expected: FAIL — the ⟳ button / `onRescan` prop do not exist.

- [ ] **Step 3: Add the props and the button**

In `frontend/src/components/ScoreBoard.tsx`:

Extend the `Props` interface (after `onRemove`):

```ts
  /** Re-score a single row. Omit to hide the per-row ⟳ button. */
  onRescan?: (t: string) => void;
  /** Ticker currently being rescanned — that row's ⟳ spins and is disabled. */
  rescanning?: string | null;
```

Update the destructure:

```ts
export function ScoreBoard({ items, onAdd, watched, onUnwatch, onRemove, onRescan, rescanning }: Props) {
```

In the actions `<td>`, add the ⟳ button before the `onRemove` block (so order is ★, ⟳, ×):

```tsx
                    {onRescan && (
                      <button
                        type="button"
                        className={`rescan-btn${rescanning === s.ticker ? ' spinning' : ''}`}
                        disabled={rescanning === s.ticker}
                        aria-label={rescanning === s.ticker ? `Rescanning ${s.ticker}` : `Rescan ${s.ticker}`}
                        title={rescanning === s.ticker ? `Rescanning ${s.ticker}…` : `Rescan ${s.ticker} — re-score this one company`}
                        onClick={(e) => { e.stopPropagation(); onRescan(s.ticker); }}
                      >
                        ⟳
                      </button>
                    )}
```

- [ ] **Step 4: Add the styles**

In `frontend/src/styles.css`, after the `.star-btn:hover` rule (~line 438):

```css
.rescan-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 2px;
  font-size: 15px;
  line-height: 1;
  color: var(--muted);
  box-shadow: none;
}
.rescan-btn:hover:not(:disabled) { filter: brightness(1.4); transform: none; box-shadow: none; }
.rescan-btn:disabled { cursor: default; opacity: 0.8; }
.rescan-btn.spinning { display: inline-block; animation: rescan-spin 0.8s linear infinite; }
@keyframes rescan-spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm test -- src/components/ScoreBoard.test.tsx`
Expected: PASS (existing tests + 3 new ones).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ScoreBoard.tsx frontend/src/components/ScoreBoard.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): per-row ⟳ rescan button on the ScoreBoard"
```

---

## Task 7: Wire the ⟳ into Discover and Portfolio

**Files:**
- Modify: `frontend/src/pages/Discover.tsx`
- Modify: `frontend/src/pages/Portfolio.tsx`

- [ ] **Step 1: Wire Discover (scope `all`)**

In `frontend/src/pages/Discover.tsx`:

Add `useRescanTicker` to the existing `../hooks/queries` import line:

```ts
import { useRefreshUniverse, useScreen, useSectors, useWatchlist, useDeleteCustomCompany, useRescanTicker } from '../hooks/queries';
```

Add the hook near the other hooks (after `const delCustom = useDeleteCustomCompany();`):

```ts
  const rescanOne = useRescanTicker(); // scope "all"
```

Pass the props to `<ScoreBoard>` (extend the existing element):

```tsx
          <ScoreBoard
            items={data.items}
            onAdd={watch.add}
            watched={watch.list}
            onUnwatch={watch.remove}
            onRemove={(t) => delCustom.mutate(t)}
            onRescan={(t) => rescanOne.mutate(t)}
            rescanning={rescanOne.isPending ? rescanOne.variables ?? null : null}
          />
```

- [ ] **Step 2: Wire Portfolio (scope `portfolio`, both boards)**

In `frontend/src/pages/Portfolio.tsx`:

Add `useRescanTicker` to the existing `../hooks/queries` import line:

```ts
import { usePortfolioTickers, useScreen, useWatchlist, useRescanTicker } from '../hooks/queries';
```

Add the hook (after `const watch = useWatchlist();`):

```ts
  const rescanOne = useRescanTicker('portfolio');
  const rescanning = rescanOne.isPending ? rescanOne.variables ?? null : null;
```

Pass the props to **both** `<ScoreBoard>` elements (the Watchlist board and the Extended board):

```tsx
          <ScoreBoard items={mine} onAdd={watch.add} watched={watch.list} onUnwatch={watch.remove}
                      onRescan={(t) => rescanOne.mutate(t)} rescanning={rescanning} />
```

```tsx
          <ScoreBoard items={extended} onAdd={watch.add} watched={watch.list} onUnwatch={watch.remove}
                      onRescan={(t) => rescanOne.mutate(t)} rescanning={rescanning} />
```

- [ ] **Step 3: Run the existing Portfolio page test**

Run: `cd frontend && npm test -- src/pages/Portfolio.test.tsx`
Expected: PASS (no test asserts ⟳; the wiring is exercised by the ScoreBoard/hook tests, so the existing page test must stay green). There is no `Discover.test.tsx`; the Discover wiring is covered by Task 5/6 and the full-suite run in Step 4.

- [ ] **Step 4: Run the full frontend suite (no regressions)**

Run: `cd frontend && npm test`
Expected: PASS (all green).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Discover.tsx frontend/src/pages/Portfolio.tsx
git commit -m "feat(frontend): wire per-row rescan into Discover and Portfolio"
```

---

## Task 8: Docs + manual verification

**Files:**
- Modify: `backend/README.md` (the endpoint table / screener section)

- [ ] **Step 1: Document the endpoint**

In `backend/README.md`, in the screener/endpoints section (near the existing `POST /api/screen/rescan` and `GET /api/screen/rescan/stream` entries), add a line:

```
- `POST /api/screen/rescan/{ticker}?scope=` — re-score ONE ticker (no LLM), upsert it into the scope's saved board snapshot (`all` default, or `portfolio`), and record its technical/network signal for evaluation; returns the fresh `StockScore`. Backs the per-row ⟳ on the Discover/Portfolio boards.
```

- [ ] **Step 2: Manual verification (dev servers are running with HMR)**

The user's backend (uvicorn `--reload`) and frontend (Vite HMR) pick up edits live. Verify with the preview tools:
1. Open the Discover board; confirm each row shows a ⟳ button next to ★.
2. Click ⟳ on one row → it spins/disables, then the row updates and the board re-sorts; the rest of the board is unchanged.
3. Confirm via `GET /api/screen` (or a board refetch/navigation) that the new score persisted.
4. Confirm on the Evaluation page that a technical (and, if a network edge exists, network) signal was recorded for that ticker.
5. Repeat one click on the Portfolio board (scope `portfolio`).

Note: per the project gotcha, verify interactive UI with coordinate-based `preview_click` (not `element.click()`), and confirm state changed (row score/order, network call), not just that the click fired.

- [ ] **Step 3: Commit the docs**

```bash
git add backend/README.md
git commit -m "docs: document POST /screen/rescan/{ticker} single-ticker rescan"
```

---

## Self-Review Notes

- **Spec coverage:** per-row ⟳ (T6) on both pages (T7); patch-row-and-re-sort (T5); durable persistence (T1, T3); eval recording with no double-score (T2, T3); 404 parity, network best-effort, untouched board-level `as_of` (T1, T3); non-goals respected (no streaming, no whole-board re-blend, no eval toast).
- **Type consistency:** `upsert_score(score, scope, cache)`, `record_deterministic_pair(..., *, score=None)`, `api.rescanTicker(ticker, scope?)`, `useRescanTicker(scope?)`, `ScoreBoard` props `onRescan`/`rescanning` — names match across backend, client, hook, component, and pages.
- **No placeholders:** every code/command step has concrete content.
