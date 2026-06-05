# Update S&P 500 List — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click "Update S&P 500 list" action that scrapes the current S&P 500 constituents from Wikipedia and rewrites `backend/app/data/sp500.json` in place (validated, atomic, no server restart).

**Architecture:** A swappable fetcher + a pure `pandas.read_html` parser + a `refresh_universe` orchestrator in `app/data/universe.py` (validate → atomic write → clear the loader's `lru_cache`), exposed as `POST /api/universe/refresh`, driven by a secondary button on the Discover page that invalidates the sector dropdown on success.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pandas + **lxml** (new runtime dep), pytest (backend); React + TS + Vite + vitest, @tanstack/react-query (frontend).

---

**Spec:** [docs/superpowers/specs/2026-06-05-update-sp500-list-design.md](../specs/2026-06-05-update-sp500-list-design.md)

**Conventions (apply to every task):**
- Backend tests from `backend/`: `.venv\Scripts\python.exe -m pytest -q`. Single test: append `tests/test_x.py::test_name -v`.
- Commits use Conventional Commits and **end with** the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Frontend from `frontend/`: `npm run test` (vitest run) and `npm run build` (tsc + vite).

---

## File structure

**Backend (modify):**
- `backend/pyproject.toml` — add `lxml` to `[project].dependencies`.
- `backend/app/data/universe.py` — add `_fetch_sp500_html`, `parse_sp500`, `_dump_entries`, `refresh_universe`, and the `WIKI_SP500_URL` / `_MIN_SP500_ROWS` constants.
- `backend/app/api/routes.py` — `POST /api/universe/refresh`.
- `backend/tests/test_universe.py` — extend (parse + refresh tests + a cache-isolation fixture).
- `backend/tests/test_api_universe.py` — new (route success + 502).

**Frontend (modify):**
- `frontend/src/api/client.ts` (+ `client.test.ts`) — `refreshUniverse`.
- `frontend/src/hooks/queries.ts` — `useRefreshUniverse`.
- `frontend/src/pages/Discover.tsx` — the "Update S&P 500 list" button + result/error line.

---

## Task 1: Backend — fetch + parse (`parse_sp500`)

**Files:**
- Modify: `backend/pyproject.toml`, `backend/app/data/universe.py`
- Test: `backend/tests/test_universe.py`

- [ ] **Step 1: Add `lxml` to dependencies**

In `backend/pyproject.toml`, add `"lxml>=5.0",` to the `[project].dependencies` array, right after the `"pandas>=2.0",` line:

```toml
    "pandas>=2.0",
    "lxml>=5.0",
    "numpy>=1.26",
```

`lxml` is already installed in `backend\.venv` (added during the manual universe expansion), so no network install is needed here — just declare it. Verify it's importable (offline):

```
.venv\Scripts\python.exe -c "import lxml; print('lxml', lxml.__version__)"
```

Expected: prints a version (e.g. `lxml 5.x`). If it is somehow missing, install it with `.venv\Scripts\python.exe -m pip install lxml`.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_universe.py` (and add the imports `import pytest` at the top if not present):

```python
import pytest

from app.data import universe


@pytest.fixture(autouse=True)
def _clear_universe_cache():
    # Tests monkeypatch _DATA_FILE; clear the lru_cache before and after each
    # test so cached entries never leak across tests.
    universe._all_entries.cache_clear()
    yield
    universe._all_entries.cache_clear()


SAMPLE_HTML = """
<table>
  <thead><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th></tr></thead>
  <tbody>
    <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td><td>Tech Hardware</td></tr>
    <tr><td>MSFT</td><td>Microsoft</td><td>Information Technology</td><td>Software</td></tr>
    <tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td><td>Multi-Sector</td></tr>
  </tbody>
</table>
"""


def test_parse_sp500_extracts_and_normalizes_symbols():
    entries = universe.parse_sp500(SAMPLE_HTML)
    by = {e.ticker: e for e in entries}
    assert set(by) == {"AAPL", "MSFT", "BRK-B"}      # BRK.B -> BRK-B (yfinance form)
    assert by["AAPL"].sector == "Information Technology"
    assert by["BRK-B"].name == "Berkshire Hathaway"


def test_parse_sp500_dedupes_by_ticker():
    dup = SAMPLE_HTML.replace(
        "  </tbody>",
        "    <tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td><td>x</td></tr>\n  </tbody>",
    )
    entries = universe.parse_sp500(dup)
    assert sum(1 for e in entries if e.ticker == "AAPL") == 1


def test_parse_sp500_raises_when_table_missing():
    with pytest.raises(ValueError):
        universe.parse_sp500("<table><thead><tr><th>Foo</th></tr></thead><tbody><tr><td>bar</td></tr></tbody></table>")
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_universe.py -q`
Expected: FAIL — `AttributeError: module 'app.data.universe' has no attribute 'parse_sp500'`.

- [ ] **Step 4: Update imports + add the fetch/parse code**

In `backend/app/data/universe.py`, replace the import block:

```python
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models.schemas import UniverseEntry
```

with:

```python
from __future__ import annotations

import io
import json
import os
import urllib.request
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.models.schemas import UniverseEntry
```

Add the constants just after the `_DATA_FILE = ...` line:

```python
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_MIN_SP500_ROWS = 450  # module constant so tests can monkeypatch a smaller floor
```

Append the fetcher + parser at the end of the file:

```python
def _fetch_sp500_html(url: str = WIKI_SP500_URL) -> str:
    """Isolated network I/O (swappable in tests). Wikipedia 403s the default UA."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sp500-universe-refresh)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse_sp500(html: str) -> list[UniverseEntry]:
    """Parse the constituents table into UniverseEntry rows. Pure + deterministic."""
    tables = pd.read_html(io.StringIO(html))
    df = next(
        (t for t in tables if {"Symbol", "Security", "GICS Sector"}.issubset(set(map(str, t.columns)))),
        None,
    )
    if df is None:
        raise ValueError("S&P 500 constituents table not found in the page")
    seen: set[str] = set()
    out: list[UniverseEntry] = []
    for _, row in df.iterrows():
        ticker = str(row["Symbol"]).strip().replace(".", "-").upper()
        name = str(row["Security"]).strip()
        sector = str(row["GICS Sector"]).strip()
        if ticker and name and sector and ticker.lower() != "nan" and ticker not in seen:
            seen.add(ticker)
            out.append(UniverseEntry(ticker=ticker, name=name, sector=sector))
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_universe.py -q`
Expected: PASS (the original 3 + the 3 new = 6).

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/data/universe.py backend/tests/test_universe.py
git commit   # feat(backend): scrape + parse the Wikipedia S&P 500 table
```

---

## Task 2: Backend — `refresh_universe` (validate + atomic write + cache clear)

**Files:**
- Modify: `backend/app/data/universe.py`
- Test: `backend/tests/test_universe.py`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_universe.py`; reuses `SAMPLE_HTML`)

```python
def test_refresh_universe_writes_and_clears_cache(tmp_path, monkeypatch):
    out = tmp_path / "sp500.json"
    monkeypatch.setattr(universe, "_DATA_FILE", out)
    monkeypatch.setattr(universe, "_MIN_SP500_ROWS", 2)
    monkeypatch.setattr(universe, "_fetch_sp500_html", lambda url=universe.WIKI_SP500_URL: SAMPLE_HTML)

    summary = universe.refresh_universe()
    assert summary["count"] == 3
    assert summary["sectors"]["Information Technology"] == 2
    assert out.exists()
    # cache was cleared -> the loader now reflects the freshly written file
    tickers = {e.ticker for e in universe.load_universe()}
    assert {"AAPL", "MSFT", "BRK-B"} <= tickers


def test_refresh_universe_refuses_bad_parse_and_keeps_existing_file(tmp_path, monkeypatch):
    out = tmp_path / "sp500.json"
    out.write_text('[\n  { "ticker": "ZZZ", "name": "Sentinel", "sector": "Energy" }\n]\n', encoding="utf-8")
    monkeypatch.setattr(universe, "_DATA_FILE", out)
    # default _MIN_SP500_ROWS (450) > the 3 parsed rows -> must refuse
    monkeypatch.setattr(universe, "_fetch_sp500_html", lambda url=universe.WIKI_SP500_URL: SAMPLE_HTML)

    with pytest.raises(ValueError):
        universe.refresh_universe()
    assert "Sentinel" in out.read_text(encoding="utf-8")  # untouched, no partial write
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_universe.py -q`
Expected: FAIL — `AttributeError: module 'app.data.universe' has no attribute 'refresh_universe'`.

- [ ] **Step 3: Implement `_dump_entries` + `refresh_universe`** (append to `universe.py`)

```python
def _dump_entries(entries: list[UniverseEntry]) -> str:
    """Serialize in the committed one-object-per-line style (stable, diff-friendly)."""
    lines = ["["]
    for i, e in enumerate(entries):
        comma = "," if i < len(entries) - 1 else ""
        lines.append(
            f'  {{ "ticker": {json.dumps(e.ticker, ensure_ascii=False)}, '
            f'"name": {json.dumps(e.name, ensure_ascii=False)}, '
            f'"sector": {json.dumps(e.sector, ensure_ascii=False)} }}{comma}'
        )
    lines.append("]")
    return "\n".join(lines) + "\n"


def refresh_universe(url: str = WIKI_SP500_URL) -> dict:
    """Scrape the current S&P 500 list and rewrite the universe file atomically.

    Validates before writing and refuses (raises) on a short/garbage parse, so a bad
    scrape never clobbers the existing file. Clears the loader cache so the change takes
    effect without a server restart.
    """
    entries = parse_sp500(_fetch_sp500_html(url))
    has_anchor = any(e.ticker == "AAPL" and e.sector == "Information Technology" for e in entries)
    if len(entries) < _MIN_SP500_ROWS or not has_anchor:
        raise ValueError(
            f"refused to update universe: parsed {len(entries)} rows, anchor present={has_anchor}"
        )
    entries.sort(key=lambda e: (e.sector, e.ticker))

    tmp = _DATA_FILE.with_name(_DATA_FILE.name + ".tmp")
    tmp.write_text(_dump_entries(entries), encoding="utf-8")
    os.replace(tmp, _DATA_FILE)  # atomic swap
    _all_entries.cache_clear()

    return {
        "count": len(entries),
        "sectors": dict(sorted(Counter(e.sector for e in entries).items())),
        "source": url,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_universe.py -q`
Expected: PASS (8 total).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass (the autouse cache-clear fixture keeps the existing universe tests hermetic).

- [ ] **Step 6: Commit**

```bash
git add backend/app/data/universe.py backend/tests/test_universe.py
git commit   # feat(backend): refresh_universe — validated atomic universe rewrite
```

---

## Task 3: Backend — `POST /api/universe/refresh`

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_universe.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_universe.py`:

```python
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app


def test_refresh_route_success(monkeypatch):
    monkeypatch.setattr(
        routes.universe, "refresh_universe",
        lambda: {"count": 503, "sectors": {"Energy": 21}, "source": "wiki"},
    )
    body = TestClient(app).post("/api/universe/refresh").json()
    assert body["count"] == 503 and body["sectors"]["Energy"] == 21


def test_refresh_route_returns_502_on_failure(monkeypatch):
    def boom():
        raise ValueError("network down")

    monkeypatch.setattr(routes.universe, "refresh_universe", boom)
    resp = TestClient(app).post("/api/universe/refresh")
    assert resp.status_code == 502
    assert "network down" in resp.json()["detail"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api_universe.py -q`
Expected: FAIL — `AttributeError: module 'app.api.routes' has no attribute 'universe'` (and 404).

- [ ] **Step 3: Add the import + route**

In `backend/app/api/routes.py`, add this import next to the existing `from app.data.universe import list_sectors`:

```python
from app.data import universe
```

Append the route at the end of the file:

```python
@router.post("/universe/refresh")
def update_universe() -> dict:
    try:
        return universe.refresh_universe()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Could not update the S&P 500 list: {exc}"
        ) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api_universe.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full backend suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_universe.py
git commit   # feat(backend): POST /api/universe/refresh endpoint
```

---

## Task 4: Frontend — client method + hook

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`, `frontend/src/hooks/queries.ts`

- [ ] **Step 1: Write the failing client test**

Paste this `it(...)` block inside the existing `describe('api client', ...)` in `frontend/src/api/client.test.ts`:

```ts
  it('refreshUniverse POSTs /universe/refresh', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ count: 503, sectors: {}, source: 'x' }) });
    vi.stubGlobal('fetch', fetchMock);
    const body = await api.refreshUniverse();
    expect(body.count).toBe(503);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/universe/refresh');
    expect((init as RequestInit).method).toBe('POST');
  });
```

- [ ] **Step 2: Run to verify it fails**

Run (from `frontend/`): `npm run test -- client`
Expected: FAIL — `api.refreshUniverse is not a function`.

- [ ] **Step 3: Add the client method**

In `frontend/src/api/client.ts`, add to the `api` object (after `getSectors`):

```ts
  refreshUniverse: () =>
    http<{ count: number; sectors: Record<string, number>; source: string }>('/universe/refresh', {
      method: 'POST',
    }),
```

- [ ] **Step 4: Run the client test to verify it passes**

Run: `npm run test -- client`
Expected: PASS.

- [ ] **Step 5: Add the hook**

In `frontend/src/hooks/queries.ts`, append:

```ts
export function useRefreshUniverse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.refreshUniverse(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sectors'] }),
  });
}
```

- [ ] **Step 6: Typecheck**

Run (from `frontend/`): `npm run build`
Expected: clean tsc + vite build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/hooks/queries.ts
git commit   # feat(frontend): refreshUniverse client + hook
```

---

## Task 5: Frontend — "Update S&P 500 list" button on Discover

**Files:**
- Modify: `frontend/src/pages/Discover.tsx`

- [ ] **Step 1: Import + call the hook**

In `frontend/src/pages/Discover.tsx`, add `useRefreshUniverse` to the hooks import:

```ts
import { useRefreshUniverse, useRescan, useSaveSettings, useScreen, useSectors, useSettings } from '../hooks/queries';
```

Add the hook call next to the others (after `const saveSettings = useSaveSettings();`):

```tsx
  const refreshList = useRefreshUniverse();
```

- [ ] **Step 2: Add the button**

In the `.board-controls` block, add the secondary button immediately **before** the existing Rescan `<button>`:

```tsx
          <button className="secondary" onClick={() => refreshList.mutate()} disabled={refreshList.isPending}>
            {refreshList.isPending ? 'Updating…' : 'Update S&P 500 list'}
          </button>
```

- [ ] **Step 3: Add the result/error line**

Just after the existing `{rescan.isError && ...}` line, add:

```tsx
      {refreshList.isSuccess && (
        <p className="muted">S&amp;P 500 list updated — {refreshList.data.count} names. Hit Rescan to rebuild the board.</p>
      )}
      {refreshList.isError && <p className="error">Update failed: {(refreshList.error as Error).message}</p>}
```

- [ ] **Step 4: Typecheck, build, test**

Run (from `frontend/`): `npm run build && npm run test`
Expected: clean tsc; vite build succeeds; all vitest tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Discover.tsx
git commit   # feat(frontend): "Update S&P 500 list" button on the Discover page
```

---

## Self-review notes (coverage vs spec)

- **Scrape behind a swappable fetcher** → Task 1 (`_fetch_sp500_html` isolated; tests stub it). ✅
- **pandas.read_html + lxml; symbol normalization; dedupe** → Task 1 (`parse_sp500`, `BRK.B`→`BRK-B`); `lxml` added to deps (Step 1). ✅
- **Validate (≥ `_MIN_SP500_ROWS` AND AAPL/Information Technology) → atomic write → cache_clear** → Task 2 (`refresh_universe`); proven by `test_refresh_universe_writes_and_clears_cache` and `test_refresh_universe_refuses_bad_parse_and_keeps_existing_file`. ✅
- **POST /api/universe/refresh; 502 on failure, file untouched** → Task 3 (route + both tests). ✅
- **Frontend client + hook (invalidate `['sectors']`) + button + result/error line** → Tasks 4–5. ✅
- **No auto-rescan / no confirm dialog** → Task 5 (the button only refreshes the list; the result line nudges the user to Rescan). ✅

**Type/name consistency:** `refresh_universe()`/`parse_sp500()`/`_fetch_sp500_html()`/`_dump_entries()` and the constants `WIKI_SP500_URL`/`_MIN_SP500_ROWS` are referenced identically in Tasks 1–3. The route (`routes.universe.refresh_universe`) matches the module import added in Task 3. The client `refreshUniverse` (Task 4) → route path `/universe/refresh` (Task 3). The `{count, sectors, source}` shape matches between `refresh_universe` (Task 2), the route (Task 3), the client type (Task 4), and the UI (`refreshList.data.count`, Task 5).
```