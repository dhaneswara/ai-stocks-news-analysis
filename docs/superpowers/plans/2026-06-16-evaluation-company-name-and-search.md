# Evaluation page: company name + search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each tracked company's name in a "Company" column on the Evaluation board (and in the detail header), and add a search box to filter the board by ticker or name.

**Architecture:** Backend resolves ticker→name from `load_universe` and sets a new `CompanyRollup.name` in `build_board` (optional `cache` param; the route passes the request cache). Frontend adds the Company column, the detail-header name, and a client-side search filter.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2; React + Vite + TS + vitest.

**Spec:** `docs/superpowers/specs/2026-06-16-evaluation-company-name-and-search-design.md`
**Branch:** `feat/eval-company-name-search` (already checked out).
**Test harness:** backend — from `backend/`, `.venv/Scripts/python.exe -m pytest -q`. frontend — from `frontend/`, `npm test -- --run`.

---

## File Structure
- **Modify** `backend/app/models/schemas.py` — `CompanyRollup.name`.
- **Modify** `backend/app/evaluation/service.py` — `build_board` resolves names (optional `cache`).
- **Modify** `backend/app/api/routes.py` — `get_evaluation` passes the cache.
- **Modify** `frontend/src/types.ts`, `frontend/src/components/EvaluationBoard.tsx`, `frontend/src/pages/Evaluation.tsx`.
- **Tests:** `backend/tests/test_evaluation_board.py`, `frontend/src/components/EvaluationBoard.test.tsx`, `frontend/src/pages/Evaluation.test.tsx`.

---

### Task 1: Backend — `name` on the rollup, resolved in `build_board`

**Files:** Modify `backend/app/models/schemas.py`, `backend/app/evaluation/service.py`, `backend/app/api/routes.py`; Test `backend/tests/test_evaluation_board.py`.

- [ ] **Step 1: Failing test** — append to `backend/tests/test_evaluation_board.py`:

```python
def test_build_board_resolves_company_name(tmp_path):
    from app.evaluation.service import build_board
    from app.evaluation.store import PredictionStore
    from app.models.schemas import Settings
    store = PredictionStore(str(tmp_path / "p.db"))
    base = dict(call_date="2026-06-01", provider="rules", model="", recommendation="buy",
                confidence=0.5, sentiment="bullish", entry_price=100.0, source="technical")
    store.upsert_prediction(ticker="AAPL", **base)
    store.upsert_prediction(ticker="ZZZZ", **base)
    board = build_board(store, Settings())  # cache defaults None -> S&P names resolve from sp500.json
    by_ticker = {c.rollup.ticker: c.rollup for c in board.companies}
    assert by_ticker["AAPL"].name != ""    # known S&P ticker -> resolved name
    assert by_ticker["ZZZZ"].name == ""    # unknown ticker -> empty
```

- [ ] **Step 2: Run → fail**: `cd backend; .venv/Scripts/python.exe -m pytest tests/test_evaluation_board.py::test_build_board_resolves_company_name -q` → FAIL (`'CompanyRollup' object has no attribute 'name'` / name is "").

- [ ] **Step 3: Implement**

(a) `backend/app/models/schemas.py` — add `name` to `CompanyRollup` (it currently starts `class CompanyRollup(BaseModel):` / `ticker: str` / `n_calls: int = 0` …). Insert the field right after `ticker`:
```python
class CompanyRollup(BaseModel):
    ticker: str
    name: str = ""
    n_calls: int = 0
```

(b) `backend/app/evaluation/service.py`:
- Add the import near the other `from app.*` imports at the top:
  ```python
  from app.data.universe import load_universe
  ```
- Change the signature `def build_board(store: PredictionStore, settings: Settings) -> EvaluationBoard:` to:
  ```python
  def build_board(store: PredictionStore, settings: Settings, cache=None) -> EvaluationBoard:
  ```
- Immediately after the `eval_index = {...}` line (≈ line 119), add the name index:
  ```python
      names = {e.ticker: e.name for e in load_universe(cache=cache)}
  ```
- In the `rollup = CompanyRollup(...)` constructor, add `name=names.get(ticker, "")`:
  ```python
          rollup = CompanyRollup(
              ticker=ticker, name=names.get(ticker, ""), n_calls=len(preds), n_matured=n_matured,
              hit_rate=hit_rate, avg_score=avg_score, grade=grade,
              overconfident=is_overconfident(hit_confs, miss_confs),
              latest_recommendation=preds[0].recommendation, latest_call_date=preds[0].call_date,
          )
  ```

(c) `backend/app/api/routes.py` — the `get_evaluation` route (≈ line 862). Add a cache dependency and pass it (`Cache` and `get_cache` are already imported and used by other routes):
```python
@router.get("/evaluation", response_model=EvaluationBoard)
def get_evaluation(
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
    cache: Cache = Depends(get_cache),
) -> EvaluationBoard:
    settings = store.load()
    evaluate_pending(prediction_store, settings)
    return build_board(prediction_store, settings, cache)
```

- [ ] **Step 4: Run → pass** then full suite:
  - `cd backend; .venv/Scripts/python.exe -m pytest tests/test_evaluation_board.py -q` → PASS (new test + existing board tests; the existing `build_board(store, Settings())` calls still work via the default `cache=None`, and none assert on `name`).
  - `cd backend; .venv/Scripts/python.exe -m pytest -q` → all green.

- [ ] **Step 5: Commit**:
```bash
git add backend/app/models/schemas.py backend/app/evaluation/service.py backend/app/api/routes.py backend/tests/test_evaluation_board.py
git commit -m "feat(backend): resolve company name onto evaluation rollup"
```

---

### Task 2: Frontend — Company column + detail-header name

**Files:** Modify `frontend/src/types.ts`, `frontend/src/components/EvaluationBoard.tsx`, `frontend/src/pages/Evaluation.tsx`; Test `frontend/src/components/EvaluationBoard.test.tsx`.

- [ ] **Step 1: Failing test** — append to `frontend/src/components/EvaluationBoard.test.tsx`, inside the existing `describe('EvaluationBoard', ...)`:

```tsx
  it('renders the Company column with the name', () => {
    const withName: CompanyEvaluation[] = [{
      rollup: {
        ticker: 'AAPL', name: 'Apple Inc.', n_calls: 1, n_matured: 0, hit_rate: null,
        avg_score: null, grade: null, overconfident: false, latest_recommendation: 'buy',
        latest_call_date: '2026-06-05',
      },
      by_source: {}, calls: [],
    }];
    render(<EvaluationBoard companies={withName} selected={null} onSelect={() => {}} />);
    expect(screen.getByText('Company')).toBeInTheDocument();      // new column header
    expect(screen.getByText('Apple Inc.')).toBeInTheDocument();   // name cell
  });
```

- [ ] **Step 2: Run → fail**: `cd frontend; npm test -- --run src/components/EvaluationBoard.test.tsx` → FAIL (no "Company" header / "Apple Inc." text; and the `name` field is a TS error on the fixture).

- [ ] **Step 3: Implement**

(a) `frontend/src/types.ts` — add `name?: string` to `CompanyRollup` (right after `ticker: string;`). It's optional so existing partial fixtures keep compiling; the API always sends it.
```ts
export interface CompanyRollup {
  ticker: string;
  name?: string;
  n_calls: number;
  n_matured: number;
```

(b) `frontend/src/components/EvaluationBoard.tsx`:
- In `<thead>`, insert a Company header right after the Ticker header:
  ```tsx
            <th>Ticker</th><th>Company</th><th>Calls</th><th>Scored</th><th>Hit rate</th>
  ```
- In the row, insert a name cell right after the ticker `<td>`:
  ```tsx
                  <td className="mono">{r.ticker}</td>
                  <td className="muted">{r.name}</td>
  ```
- The detail row spans all columns — change `colSpan={7}` to `colSpan={8}`:
  ```tsx
                    <td colSpan={8}>{renderDetail(c)}</td>
  ```

(c) `frontend/src/pages/Evaluation.tsx` — in `CompanyDetail`, the panel-head label currently reads `{company.rollup.ticker} — calls`. Show the name when present:
```tsx
        <span className="section-label">
          {company.rollup.ticker}{company.rollup.name ? ` · ${company.rollup.name}` : ''} — calls
        </span>
```

- [ ] **Step 4: Run → pass** then full suite + typecheck:
  - `cd frontend; npm test -- --run src/components/EvaluationBoard.test.tsx` → PASS.
  - `cd frontend; npm test -- --run` → all green. Run the build/typecheck script if present (`npm run build`) to catch TS errors.

- [ ] **Step 5: Commit**:
```bash
git add frontend/src/types.ts frontend/src/components/EvaluationBoard.tsx frontend/src/pages/Evaluation.tsx
git commit -m "feat(frontend): company-name column on the Evaluation board"
```

---

### Task 3: Frontend — search box on the Evaluation page

**Files:** Modify `frontend/src/pages/Evaluation.tsx`; Test `frontend/src/pages/Evaluation.test.tsx`.

- [ ] **Step 1: Failing test** — append to `frontend/src/pages/Evaluation.test.tsx`, matching the file's existing setup (it `vi.mock('../api/client')`, wraps in `QueryClientProvider` + `MemoryRouter` + `WatchlistRunProvider`, and mocks `api.getEvaluation`). Use a board with two NAMED companies so both the ticker and name filters can be exercised. A self-contained test:

```tsx
it('filters the board by ticker or company name', async () => {
  const board: EvaluationBoard = {
    as_of: '2026-06-07T00:00:00Z',
    sources: {},
    companies: [
      { rollup: { ticker: 'AAPL', name: 'Apple Inc.', n_calls: 1, n_matured: 0, hit_rate: null,
        avg_score: null, grade: null, overconfident: false, latest_recommendation: 'buy',
        latest_call_date: '2026-06-05' }, by_source: {}, calls: [] },
      { rollup: { ticker: 'MSFT', name: 'Microsoft Corp.', n_calls: 1, n_matured: 0, hit_rate: null,
        avg_score: null, grade: null, overconfident: false, latest_recommendation: 'sell',
        latest_call_date: '2026-06-06' }, by_source: {}, calls: [] },
    ],
  };
  vi.mocked(api.getEvaluation).mockResolvedValue(board);
  renderEvaluation();                                  // use the file's existing render helper/setup
  await screen.findByText('AAPL');
  const box = screen.getByPlaceholderText(/Filter by ticker or company/i);

  fireEvent.change(box, { target: { value: 'micro' } });   // matches MSFT by name
  expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
  expect(screen.getByText('MSFT')).toBeInTheDocument();

  fireEvent.change(box, { target: { value: 'aapl' } });     // matches AAPL by ticker (case-insensitive)
  expect(screen.getByText('AAPL')).toBeInTheDocument();
  expect(screen.queryByText('MSFT')).not.toBeInTheDocument();

  fireEvent.change(box, { target: { value: '' } });         // cleared -> both
  expect(screen.getByText('AAPL')).toBeInTheDocument();
  expect(screen.getByText('MSFT')).toBeInTheDocument();
});
```

If the file has no shared `renderEvaluation` helper, render inline exactly like the existing tests do (QueryClientProvider + MemoryRouter + WatchlistRunProvider around `<Evaluation/>`), and set the other `api.*` mocks the existing tests set (e.g. `getPortfolioTickers`, `getSettings`) to benign resolved values so the page mounts.

- [ ] **Step 2: Run → fail**: `cd frontend; npm test -- --run src/pages/Evaluation.test.tsx` → FAIL (no search box).

- [ ] **Step 3: Implement** — in `frontend/src/pages/Evaluation.tsx`:
- Add a query state near the other `useState`s in `Evaluation()`:
  ```ts
  const [query, setQuery] = useState('');
  ```
- Derive the filtered list from `companies`:
  ```ts
  const q = query.trim().toLowerCase();
  const shown = q
    ? companies.filter((c) =>
        c.rollup.ticker.toLowerCase().includes(q) ||
        (c.rollup.name ?? '').toLowerCase().includes(q))
    : companies;
  ```
- Render a search input just before `<EvaluationBoard .../>` (inside the `board.data` block):
  ```tsx
            <input
              className="eval-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by ticker or company…"
            />
  ```
- Pass the filtered list to the board: change `companies={companies}` to `companies={shown}`.

- [ ] **Step 4: Run → pass** then full suite:
  - `cd frontend; npm test -- --run src/pages/Evaluation.test.tsx` → PASS.
  - `cd frontend; npm test -- --run` → all green. (`npm run build` if present.)

- [ ] **Step 5: Commit**:
```bash
git add frontend/src/pages/Evaluation.tsx frontend/src/pages/Evaluation.test.tsx
git commit -m "feat(frontend): search box to filter the Evaluation board"
```

---

### Task 4: Full verification + final review

**Files:** none (verification only).

- [ ] **Step 1: Backend** — `cd backend; .venv/Scripts/python.exe -m pytest -q` → all green.
- [ ] **Step 2: Frontend** — `cd frontend; npm test -- --run` → all green.
- [ ] **Step 3: Final whole-implementation review** (controller dispatches via subagent-driven-development).

---

## Self-Review

**Spec coverage:** `CompanyRollup.name` + resolution from `load_universe` in `build_board` (optional cache) + route passes cache → Task 1 ✓; Company column (8 cols, detail colSpan 8) + detail-header name → Task 2 ✓; search box filtering by ticker/name, empty=all → Task 3 ✓; unknown ticker → "" (ticker-only) → Task 1 test ✓; existing build_board calls/tests + partial frontend fixtures unaffected (optional cache, optional `name?`) → Tasks 1/2 ✓.

**Placeholder scan:** none — concrete code/commands throughout. (The "match the file's render helper" notes in the frontend tests are deliberate reuse of the existing harness.)

**Type consistency:** `CompanyRollup.name` (py `str=""` / ts `name?: string`), `build_board(store, settings, cache=None)`, route `build_board(prediction_store, settings, cache)`, `r.name` in the board cell + `company.rollup.name` in the detail header + the search filter — consistent across backend, API, and UI. The Company column and `colSpan={8}` agree on 8 columns.
