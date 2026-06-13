# Dashboard Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reword the NET signal tooltip, make the watchlist a collapsible searchable menu, make the Deep Analysis button gold, and durably persist + auto-restore the last analysis (panel + signal reasoning + chart markers) so it survives an app restart without re-running and without affecting evaluation.

**Architecture:** Frontend-only for items #1–#3. Item #4 adds a new `AnalysisSnapshotStore` (its own SQLite file, separate from the eval store), a `GET /api/analysis/{ticker}` read endpoint, best-effort snapshot writes on the fast + deep analysis paths, and a `useLastAnalysis` query the Dashboard falls back to when no in-session analysis exists. A related footgun fix makes a prediction immutable once it has a matured eval.

**Tech Stack:** FastAPI + SQLite (backend), React + TanStack Query + Vitest/Testing-Library (frontend), pytest (backend tests).

**Conventions:**
- Backend tests: from `backend/`, run `.venv/Scripts/python.exe -m pytest <args>`.
- Frontend tests: from `frontend/`, run `npx vitest run <path>`.
- Commits: Conventional Commits, one per task, **no `Co-Authored-By` trailer**.

---

### Task 1: NET wording — distinguish "recorded, not scored" from "no data"

**Files:**
- Modify: `frontend/src/components/SignalsStrip.tsx:24-29`
- Test: `frontend/src/components/SignalsStrip.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/SignalsStrip.test.tsx`:

```tsx
it('shows scored-vs-recorded counts instead of "collecting data" for an unmatured source', () => {
  render(<SignalsStrip score={score()} signals={signals({
    sources: {
      network: {
        latest: { call_date: '2026-06-12', recommendation: 'hold', confidence: 0.1 },
        track: { n_calls: 1, n_matured: 0, hit_rate: null, avg_score: null, grade: null },
      },
    },
  })} />);
  const chip = screen.getByText('NET').closest('.signal-chip') as HTMLElement;
  expect(chip).toHaveAttribute(
    'title',
    'NET: HOLD on 2026-06-12 · 0 of 1 scored — awaiting maturity',
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/SignalsStrip.test.tsx`
Expected: FAIL — the title still ends with `· collecting data`.

- [ ] **Step 3: Implement the reword**

In `frontend/src/components/SignalsStrip.tsx`, replace the `title` expression (lines 24-29):

```tsx
          const title = s
            ? `${label}: ${s.latest.recommendation.toUpperCase()} on ${s.latest.call_date}` +
              (s.track.hit_rate != null
                ? ` · ${s.track.hit_rate}% hit rate over ${s.track.n_matured} scored`
                : ` · ${s.track.n_matured} of ${s.track.n_calls} scored — awaiting maturity`)
            : `${label}: no call recorded yet`;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/SignalsStrip.test.tsx`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SignalsStrip.tsx frontend/src/components/SignalsStrip.test.tsx
git commit -m "fix(frontend): NET tooltip shows scored/recorded counts instead of 'collecting data'"
```

---

### Task 2: Gold Deep Analysis button

**Files:**
- Modify: `frontend/src/components/TickerBar.tsx:77-85`
- Test: `frontend/src/components/TickerBar.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/TickerBar.test.tsx`:

```tsx
it('renders the Deep Analysis button as a solid-gold (non-secondary) button', () => {
  setup();
  const deep = screen.getByRole('button', { name: /deep analysis/i });
  expect(deep).not.toHaveClass('secondary');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/TickerBar.test.tsx`
Expected: FAIL — the button currently has class `secondary`.

- [ ] **Step 3: Drop the `secondary` class**

In `frontend/src/components/TickerBar.tsx`, change the Deep Analysis button (remove `className="secondary"`):

```tsx
      <button
        type="button"
        onClick={onDeepAnalyze}
        disabled={!canAnalyze || deepAnalyzing}
        title="Agentic analysis — the LLM pulls data step-by-step; slower, streamed live"
      >
        {deepAnalyzing ? 'Deep analyzing…' : 'Deep Analysis'}
      </button>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/TickerBar.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/TickerBar.tsx frontend/src/components/TickerBar.test.tsx
git commit -m "style(frontend): make the Deep Analysis button solid gold like the primary"
```

---

### Task 3: Footgun fix — a prediction is immutable once it has a matured eval

**Files:**
- Modify: `backend/app/evaluation/store.py:114-137`
- Test: `backend/tests/test_evaluation_migration.py:73-84` (rewrite), `backend/tests/test_evaluation_record.py` (add)

- [ ] **Step 1: Rewrite the now-obsolete behavior test**

Replace `test_entry_price_change_invalidates_only_that_source` in `backend/tests/test_evaluation_migration.py` (lines 73-84) with:

```python
def test_scored_prediction_is_immutable_on_rerecord(tmp_path):
    """Once a call has a matured eval, re-recording it (e.g. an intraday Analyze re-run at a
    different price) is a no-op: the scored history and the original entry are preserved."""
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=200.0, source="llm_fast")
    store.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0, source="llm_fast")
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="sell", confidence=0.2, sentiment="bearish",
                            entry_price=201.0, source="llm_fast")  # re-run at a new price
    row = store.get_prediction("AAPL", "2026-06-05", "llm_fast")
    assert row.entry_price == 200.0 and row.recommendation == "buy"  # unchanged
    assert store.has_eval("AAPL", "2026-06-05", 1, "llm_fast") is True  # eval preserved


def test_unscored_prediction_still_updates_on_rerecord(tmp_path):
    """Before any eval matures, re-recording the same call still refreshes it (intraday updates)."""
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=200.0, source="llm_fast")
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="sell", confidence=0.3, sentiment="bearish",
                            entry_price=205.0, source="llm_fast")
    row = store.get_prediction("AAPL", "2026-06-05", "llm_fast")
    assert row.entry_price == 205.0 and row.recommendation == "sell"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_migration.py::test_scored_prediction_is_immutable_on_rerecord -v`
Expected: FAIL — current code deletes the eval and overwrites the entry, so `has_eval` is False and `entry_price` is 201.0.

- [ ] **Step 3: Make `upsert_prediction` immutable-once-scored**

In `backend/app/evaluation/store.py`, replace the body of `upsert_prediction` (lines 117-137) with:

```python
        ticker = ticker.upper().strip()
        with self._lock:
            # Immutable once scored: if this call already has a matured eval, re-recording is a
            # no-op. Re-running analysis must never move the recorded entry/recommendation or
            # destroy scored history. Before anything matures, a re-record still refreshes the
            # row (intraday updates), so INSERT OR REPLACE runs only when no eval exists.
            scored = self._conn.execute(
                "SELECT 1 FROM prediction_evals "
                "WHERE ticker = ? AND call_date = ? AND source = ? LIMIT 1",
                (ticker, call_date, source),
            ).fetchone()
            if scored is not None:
                return
            self._conn.execute(
                "INSERT OR REPLACE INTO predictions "
                "(ticker, call_date, provider, model, recommendation, confidence, sentiment, "
                "entry_price, created_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, call_date, provider, model, recommendation, confidence, sentiment,
                 entry_price, time.time(), source),
            )
            self._conn.commit()
```

- [ ] **Step 4: Run the full evaluation test set to verify pass + no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_migration.py tests/test_evaluation_record.py -q`
Expected: PASS (both new tests pass; existing cache-hit tests unaffected — they rely on `_record_if_missing` skipping when a prediction exists).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/store.py backend/tests/test_evaluation_migration.py
git commit -m "fix(backend): a prediction becomes immutable once scored — re-running never wipes evals"
```

---

### Task 4: AnalysisSnapshotStore + dependency

**Files:**
- Create: `backend/app/services/analysis_snapshot_store.py`
- Modify: `backend/app/deps.py`
- Test: `backend/tests/test_analysis_snapshot_store.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_analysis_snapshot_store.py`:

```python
from app.services.analysis_snapshot_store import AnalysisSnapshotStore


def test_upsert_and_latest_roundtrip(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    store.upsert(ticker="aapl", source="llm_fast", call_date="2026-06-12", period="1y",
                 provider="anthropic", model="m", result_json='{"x": 1}')
    row = store.latest("AAPL")
    assert row is not None
    assert row.source == "llm_fast" and row.call_date == "2026-06-12"
    assert row.result_json == '{"x": 1}'


def test_latest_returns_most_recent_across_sources(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    store.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                 provider="p", model="m", result_json='{"who": "fast"}')
    store.upsert(ticker="AAPL", source="llm_deep", call_date="2026-06-12", period="1y",
                 provider="p", model="m", result_json='{"who": "deep"}')
    assert store.latest("AAPL").result_json == '{"who": "deep"}'  # newer created_at wins


def test_latest_none_for_unknown_ticker(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    assert store.latest("ZZZZ") is None


def test_upsert_replaces_same_ticker_source(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    store.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-11", period="1y",
                 provider="p", model="m", result_json='{"v": 1}')
    store.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                 provider="p", model="m", result_json='{"v": 2}')
    row = store.latest("AAPL")
    assert row.call_date == "2026-06-12" and row.result_json == '{"v": 2}'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analysis_snapshot_store.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.analysis_snapshot_store`.

- [ ] **Step 3: Implement the store**

Create `backend/app/services/analysis_snapshot_store.py`:

```python
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

# The full last AnalysisResult per (ticker, source), kept so the Dashboard can restore a past
# analysis (panel + signal reasoning + chart markers) without re-running it. Deliberately a
# SEPARATE store from the evaluation predictions/evals: viewing must never touch scoring.
_CREATE = (
    "CREATE TABLE IF NOT EXISTS analysis_snapshots ("
    "ticker TEXT, source TEXT, call_date TEXT, period TEXT, provider TEXT, model TEXT, "
    "created_at REAL, result_json TEXT, "
    "PRIMARY KEY (ticker, source))"
)
_SELECT = ("SELECT ticker, source, call_date, period, provider, model, created_at, result_json "
           "FROM analysis_snapshots")


@dataclass
class SnapshotRow:
    ticker: str
    source: str
    call_date: str
    period: str
    provider: str
    model: str
    created_at: float
    result_json: str


class AnalysisSnapshotStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(_CREATE)
        self._conn.commit()

    def upsert(self, *, ticker: str, source: str, call_date: str, period: str, provider: str,
               model: str, result_json: str) -> None:
        ticker = ticker.upper().strip()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO analysis_snapshots "
                "(ticker, source, call_date, period, provider, model, created_at, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, source, call_date, period, provider, model, time.time(), result_json),
            )
            self._conn.commit()

    def latest(self, ticker: str) -> Optional[SnapshotRow]:
        with self._lock:
            row = self._conn.execute(
                _SELECT + " WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
                (ticker.upper().strip(),),
            ).fetchone()
        return SnapshotRow(*row) if row else None
```

- [ ] **Step 4: Add the dependency**

In `backend/app/deps.py`, add the import and accessor:

```python
from app.services.analysis_snapshot_store import AnalysisSnapshotStore
```

```python
@lru_cache
def get_analysis_snapshot_store() -> AnalysisSnapshotStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return AnalysisSnapshotStore(os.path.join(DATA_DIR, "analysis_snapshots.db"))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analysis_snapshot_store.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/analysis_snapshot_store.py backend/app/deps.py backend/tests/test_analysis_snapshot_store.py
git commit -m "feat(backend): AnalysisSnapshotStore for durable per-ticker last-analysis"
```

---

### Task 5: `LastAnalysis` schema + `GET /api/analysis/{ticker}` read endpoint

**Files:**
- Modify: `backend/app/models/schemas.py` (add `LastAnalysis`)
- Modify: `backend/app/api/routes.py` (imports + new route)
- Test: `backend/tests/test_api_last_analysis.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_last_analysis.py`:

```python
from fastapi.testclient import TestClient

from app.deps import get_analysis_snapshot_store
from app.main import app
from app.services.analysis_snapshot_store import AnalysisSnapshotStore


def _client(tmp_path):
    snap = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    app.dependency_overrides[get_analysis_snapshot_store] = lambda: snap
    return TestClient(app), snap


def teardown_function():
    app.dependency_overrides.clear()


_RESULT_JSON = (
    '{"ticker":"AAPL","provider":"anthropic","model":"m","generated_at":"2026-06-12",'
    '"overall_summary":"hello","news_analysis":"n","sentiment":"bullish",'
    '"current_recommendation":"buy","confidence":0.8,"key_factors":[],"signals":[],'
    '"risks":[],"disclaimer":"Not financial advice"}'
)


def test_returns_null_when_no_snapshot(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/api/analysis/AAPL").json() is None


def test_returns_latest_snapshot(tmp_path):
    client, snap = _client(tmp_path)
    snap.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                provider="anthropic", model="m", result_json=_RESULT_JSON)
    body = client.get("/api/analysis/aapl").json()
    assert body["source"] == "llm_fast"
    assert body["call_date"] == "2026-06-12"
    assert body["result"]["overall_summary"] == "hello"


def test_corrupt_snapshot_returns_null(tmp_path):
    client, snap = _client(tmp_path)
    snap.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                provider="anthropic", model="m", result_json="{not valid json")
    assert client.get("/api/analysis/AAPL").json() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_last_analysis.py -v`
Expected: FAIL — route does not exist (404).

- [ ] **Step 3: Add the `LastAnalysis` schema**

In `backend/app/models/schemas.py`, add near `AnalysisResult` (it is a `pydantic.BaseModel` subclass like the others in the file):

```python
class LastAnalysis(BaseModel):
    """The most recent persisted analysis for a ticker, restored read-only on the Dashboard."""
    result: AnalysisResult
    source: str
    call_date: str
    created_at: float
```

- [ ] **Step 4: Add the route**

In `backend/app/api/routes.py`:

Add `Optional` to the typing import:

```python
from typing import Literal, Optional
```

Add to the deps import line:

```python
from app.deps import (
    get_analysis_snapshot_store,
    get_cache,
    get_prediction_store,
    get_settings_store,
    get_trace_store,
)
```

Add `AnalysisSnapshotStore` import:

```python
from app.services.analysis_snapshot_store import AnalysisSnapshotStore
```

Add `LastAnalysis` to the `app.models.schemas` import block.

Add the route (place it right after `analyze_ticker`, before `_sse`):

```python
@router.get("/analysis/{ticker}", response_model=Optional[LastAnalysis])
def get_last_analysis(
    ticker: str,
    snapshot_store: AnalysisSnapshotStore = Depends(get_analysis_snapshot_store),
) -> Optional[LastAnalysis]:
    """The most recent persisted analysis for a ticker — read-only Dashboard restore. Pure read:
    no compute, no recording, no evaluation impact. Returns null when none exists or the stored
    JSON is unreadable (never a 500)."""
    row = snapshot_store.latest(ticker)
    if row is None:
        return None
    try:
        result = AnalysisResult.model_validate_json(row.result_json)
    except Exception:  # noqa: BLE001 — a corrupt snapshot is "no snapshot", not an error
        logger.warning("corrupt analysis snapshot for %s", ticker)
        return None
    return LastAnalysis(result=result, source=row.source, call_date=row.call_date,
                        created_at=row.created_at)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_last_analysis.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/routes.py backend/tests/test_api_last_analysis.py
git commit -m "feat(backend): GET /api/analysis/{ticker} returns the last persisted analysis"
```

---

### Task 6: Write snapshots on the fast + deep analysis paths

**Files:**
- Modify: `backend/app/services/analysis_service.py` (run_analysis + helper)
- Modify: `backend/app/api/routes.py` (`_persist_deep_final` + 3 routes pass the store)
- Test: `backend/tests/test_evaluation_record.py` (add), `backend/tests/test_api_deep_stream.py` (add)

- [ ] **Step 1: Write the failing test (fast path)**

Add to `backend/tests/test_evaluation_record.py` (it already imports `analysis_service`, `Cache`, `PredictionStore`, and has `_stock_with_candles`, `_seed_analysis_cache`, `_no_provider` helpers — reuse them):

```python
def test_run_analysis_writes_snapshot_on_cache_hit(tmp_path, monkeypatch):
    from app.services.analysis_snapshot_store import AnalysisSnapshotStore

    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())
    monkeypatch.setattr(analysis_service, "record_deterministic_pair", lambda *a, **k: None)
    _no_provider(monkeypatch)
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    snap = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    _seed_analysis_cache(cache, settings)

    analysis_service.run_analysis("AAPL", "2y", settings, cache, store, snapshot_store=snap)

    row = snap.latest("AAPL")
    assert row is not None and row.source == "llm_fast" and row.call_date == "2026-06-05"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_record.py::test_run_analysis_writes_snapshot_on_cache_hit -v`
Expected: FAIL — `run_analysis` has no `snapshot_store` parameter (`TypeError`).

- [ ] **Step 3: Add the snapshot write to `run_analysis`**

In `backend/app/services/analysis_service.py`:

Add the import near the top:

```python
from app.services.analysis_snapshot_store import AnalysisSnapshotStore
```

Add the helper (after `_record_if_missing`, before `run_analysis`):

```python
def _write_snapshot_fast(ticker: str, period: str, result: AnalysisResult, settings: Settings,
                         cache: Cache, snapshot_store: AnalysisSnapshotStore | None) -> None:
    """Best-effort: persist the full fast-analysis result so the Dashboard can restore it later
    without re-running. INDEPENDENT of the evaluation gate — viewing must work even if recording
    is off. call_date matches the prediction convention (the last candle); the stock fetch is a
    same-day cache read."""
    if snapshot_store is None:
        return
    try:
        stock = get_stock_data(ticker, period, settings.indicator_params, cache)
        call_date = stock.candles[-1].time if stock.candles else ""
        snapshot_store.upsert(ticker=ticker, source=SOURCE_LLM_FAST, call_date=call_date,
                              period=period, provider=result.provider, model=result.model,
                              result_json=result.model_dump_json())
    except Exception:  # noqa: BLE001 — snapshotting must never break analysis
        logger.warning("analysis snapshot write failed for %s", ticker)
```

Change the `run_analysis` signature to accept the store:

```python
def run_analysis(
    ticker: str,
    period: str,
    settings: Settings,
    cache: Cache,
    prediction_store: PredictionStore | None = None,
    snapshot_store: AnalysisSnapshotStore | None = None,
) -> AnalysisResult:
```

In the cache-hit branch, add the snapshot write before `return result`:

```python
    cached = cache.get(cache_key)
    if cached is not None:
        result = AnalysisResult.model_validate_json(cached)
        _record_if_missing(ticker, period, result, settings, cache, prediction_store)
        _write_snapshot_fast(ticker, period, result, settings, cache, snapshot_store)
        return result
```

In the fresh-compute branch, add the snapshot write before `return result`:

```python
    result = analyze(stock, provider, model=cfg.model, provider_name=provider_id)
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    _record_calls(stock, result, settings, cache, prediction_store)
    _write_snapshot_fast(ticker, period, result, settings, cache, snapshot_store)
    return result
```

- [ ] **Step 4: Run the fast-path test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_record.py::test_run_analysis_writes_snapshot_on_cache_hit -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test (deep path)**

Add to `backend/tests/test_api_deep_stream.py` a focused unit test of the persistence helper (it lives in `app.api.routes`):

```python
def test_persist_deep_final_writes_deep_snapshot(tmp_path):
    from app.analysis.agent import AgentEvent, AgentTrace
    from app.analysis.trace_store import AgentTraceStore
    from app.api.routes import _persist_deep_final
    from app.config.cache import Cache
    from app.evaluation.store import PredictionStore
    from app.models.schemas import AnalysisResult, Candle, Settings, StockData
    from app.services.analysis_snapshot_store import AnalysisSnapshotStore

    stock = StockData(ticker="AAPL", company_name="Apple", as_of="2026-06-12",
                      price={"current": 1, "change": 0, "change_pct": 0, "currency": "USD"},
                      candles=[Candle(time="2026-06-12", open=1, high=1, low=1, close=1, volume=1)],
                      fundamentals={}, indicators={}, news=[])
    result = AnalysisResult(ticker="AAPL", provider="anthropic", model="m",
                            generated_at="2026-06-12", overall_summary="deep!", news_analysis="n",
                            sentiment="bullish", current_recommendation="buy", confidence=0.7,
                            key_factors=[], signals=[], risks=[], disclaimer="Not financial advice")
    trace = AgentTrace(ticker="AAPL", provider="anthropic", model="m", started_at="t",
                       elapsed_ms=1, stopped_reason="final", fell_back=False, steps=[], final=result)
    settings = Settings()
    cache = Cache(str(tmp_path / "c.db"))
    pred = PredictionStore(str(tmp_path / "p.db"))
    traces = AgentTraceStore(str(tmp_path / "t.db"))
    snap = AnalysisSnapshotStore(str(tmp_path / "snap.db"))

    _persist_deep_final(AgentEvent(type="final", result=result, trace=trace), stock, settings,
                        cache, pred, traces, snapshot_store=snap)

    row = snap.latest("AAPL")
    assert row is not None and row.source == "llm_deep" and row.call_date == "2026-06-12"
```

(If `Candle`/`StockData` constructors in this repo require different fields, copy the construction style already used elsewhere in `test_api_deep_stream.py`.)

- [ ] **Step 6: Run the deep-path test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_deep_stream.py::test_persist_deep_final_writes_deep_snapshot -v`
Expected: FAIL — `_persist_deep_final` has no `snapshot_store` parameter.

- [ ] **Step 7: Wire the snapshot into `_persist_deep_final` + routes**

In `backend/app/api/routes.py`, change `_persist_deep_final` to write the snapshot before the evaluation gate (so it runs even when recording is off). Replace its body (lines 142-167) with:

```python
def _persist_deep_final(event: AgentEvent, stock: StockData, settings: Settings, cache: Cache,
                        prediction_store: PredictionStore, trace_store: AgentTraceStore,
                        snapshot_store: AnalysisSnapshotStore | None = None) -> None:
    """Persist the trace + predictions when a deep run completes. Each persistence concern is
    isolated — a failure must never break the SSE stream. A run that degraded to the
    single-shot fallback is recorded as llm_fast (that path produced the answer), keeping the
    fast-vs-deep comparison honest."""
    trace = event.trace
    call_date = stock.candles[-1].time if stock.candles else ""
    if trace is not None and call_date:
        try:
            trace_store.upsert(ticker=trace.ticker, call_date=call_date, provider=trace.provider,
                               model=trace.model, trace_json=trace.model_dump_json())
        except Exception:  # noqa: BLE001
            logger.warning("trace persistence failed for %s", stock.ticker)
    # No trace = can't prove it was a real agent run -> conservatively label llm_fast.
    source = SOURCE_LLM_FAST if (trace is None or trace.fell_back) else SOURCE_LLM_DEEP
    # Snapshot the result for Dashboard restore, independent of the evaluation gate.
    if event.result is not None and snapshot_store is not None:
        try:
            snapshot_store.upsert(ticker=event.result.ticker, source=source, call_date=call_date,
                                  period="", provider=event.result.provider,
                                  model=event.result.model,
                                  result_json=event.result.model_dump_json())
        except Exception:  # noqa: BLE001
            logger.warning("deep analysis snapshot write failed for %s", stock.ticker)
    if event.result is None or not settings.evaluation.enabled:
        return
    try:
        record_prediction(stock, event.result, prediction_store, source=source)
    except Exception:  # noqa: BLE001
        logger.warning("deep prediction recording failed for %s", stock.ticker)
    try:
        record_deterministic_pair(stock, settings, cache, prediction_store)
    except Exception:  # noqa: BLE001
        logger.warning("deterministic pair recording failed for %s", stock.ticker)
```

Wire the snapshot store into the three routes that produce analyses:

`analyze_ticker` — add the dep and pass it:

```python
@router.post("/analyze/{ticker}", response_model=AnalysisResult)
def analyze_ticker(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
    snapshot_store: AnalysisSnapshotStore = Depends(get_analysis_snapshot_store),
) -> AnalysisResult:
    settings = store.load()
    try:
        return run_analysis(ticker, period, settings, cache, prediction_store,
                            snapshot_store=snapshot_store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

`analyze_deep_stream` — add the dep, and pass it to `_persist_deep_final`:

```python
def analyze_deep_stream(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
    trace_store: AgentTraceStore = Depends(get_trace_store),
    snapshot_store: AnalysisSnapshotStore = Depends(get_analysis_snapshot_store),
) -> StreamingResponse:
```

```python
                if event.type == "final":
                    _persist_deep_final(event, stock, settings, cache, prediction_store,
                                        trace_store, snapshot_store=snapshot_store)
```

`analyze_watchlist_stream` — add the dep, pass to both paths:

```python
def analyze_watchlist_stream(
    mode: Literal["fast", "deep"] = "fast",
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
    trace_store: AgentTraceStore = Depends(get_trace_store),
    snapshot_store: AnalysisSnapshotStore = Depends(get_analysis_snapshot_store),
) -> StreamingResponse:
```

```python
                if mode == "fast":
                    result = run_analysis(ticker, period, settings, cache, prediction_store,
                                          snapshot_store=snapshot_store)
                else:
                    deep_stock = gather_stock_context(ticker, period, settings, cache,
                                                      provider, store=prediction_store)
                    ctx = ToolContext(stock=deep_stock, settings=settings, cache=cache)
                    result, trace = ReActAgent().run(provider, cfg.model, provider_id, ctx)
                    if result is None:
                        raise LLMError("agent produced no result")
                    _persist_deep_final(AgentEvent(type="final", result=result, trace=trace),
                                        deep_stock, settings, cache, prediction_store,
                                        trace_store, snapshot_store=snapshot_store)
                    fell_back = trace.fell_back if trace else True
```

- [ ] **Step 8: Run the deep-path test + the existing deep-stream + record suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_deep_stream.py tests/test_evaluation_record.py -q`
Expected: PASS (new tests + no regressions).

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/analysis_service.py backend/app/api/routes.py backend/tests/test_evaluation_record.py backend/tests/test_api_deep_stream.py
git commit -m "feat(backend): persist a last-analysis snapshot on the fast and deep paths"
```

---

### Task 7: Frontend — `LastAnalysis` type, API client, `useLastAnalysis` hook + invalidation

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/hooks/queries.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/api/client.test.ts` (it tests `api` against a mocked `fetch` — match the file's existing style; the snippet below assumes `vi.stubGlobal('fetch', ...)` patterns already used there):

```tsx
it('getLastAnalysis GETs the analysis endpoint and returns the body', async () => {
  const body = { result: { overall_summary: 'hi' }, source: 'llm_fast', call_date: '2026-06-12', created_at: 1 };
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => body })) as unknown as typeof fetch);
  const { api } = await import('./client');
  const got = await api.getLastAnalysis('aapl');
  expect((got as { source: string }).source).toBe('llm_fast');
  expect((globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0])
    .toContain('/analysis/aapl');
});
```

(If `client.test.ts` uses a different fetch-mock helper, follow that file's convention instead — the assertion that matters is that the request path contains `/analysis/aapl` and the parsed body is returned.)

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/api/client.test.ts`
Expected: FAIL — `api.getLastAnalysis` is undefined.

- [ ] **Step 3: Add the `LastAnalysis` type**

In `frontend/src/types.ts`, after `AnalysisResult` (and after `Source` is defined — place it near the other signal types, below the `Source` type on line 129):

```ts
export interface LastAnalysis {
  result: AnalysisResult;
  source: Source;
  call_date: string;
  created_at: number;
}
```

- [ ] **Step 4: Add the API client method**

In `frontend/src/api/client.ts`, add `LastAnalysis` to the type import block, and add to the `api` object (after `analyze`):

```ts
  getLastAnalysis: (ticker: string) =>
    http<LastAnalysis | null>(`/analysis/${encodeURIComponent(ticker)}`),
```

- [ ] **Step 5: Add the hook + invalidation**

In `frontend/src/hooks/queries.ts`:

Add the hook (next to `useSignals`):

```ts
export function useLastAnalysis(ticker: string) {
  return useQuery({
    queryKey: ['analysis', ticker],
    queryFn: () => api.getLastAnalysis(ticker),
    enabled: ticker.length > 0,
    retry: false,
  });
}
```

Extend `useAnalyze`'s `onSuccess` so a fresh run refreshes the snapshot:

```ts
export function useAnalyze(ticker: string, period = '5y') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.analyze(ticker, period),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['signals', ticker] });
      qc.invalidateQueries({ queryKey: ['evaluation'] });
      qc.invalidateQueries({ queryKey: ['analysis', ticker] });
    },
  });
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npx vitest run src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/api/client.test.ts
git commit -m "feat(frontend): useLastAnalysis hook + api.getLastAnalysis for restore"
```

---

### Task 8: Dashboard auto-restore + "as of" badge

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/pages/Dashboard.test.tsx`

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/Dashboard.test.tsx`:

Add `getLastAnalysis: vi.fn()` to the mocked `api` object (line 11-24 block), and a default in `beforeEach`:

```tsx
  vi.mocked(api.getLastAnalysis).mockResolvedValue(null);
```

Then add the restore test:

```tsx
describe('Dashboard analysis restore', () => {
  it('restores the last saved analysis on load without clicking Analyze', async () => {
    vi.mocked(api.getLastAnalysis).mockResolvedValue({
      result: ANALYSIS, source: 'llm_fast', call_date: '2026-06-05', created_at: 1,
    });
    renderApp();
    // The persisted summary shows with no Analyze click.
    expect(await screen.findByText('PERSIST-ME-SUMMARY')).toBeInTheDocument();
    expect(screen.getByText(/as of 2026-06-05/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/pages/Dashboard.test.tsx`
Expected: FAIL — without restore wiring, the summary only appears after clicking Analyze; the "as of" badge does not exist.

- [ ] **Step 3: Wire restore into the Dashboard**

In `frontend/src/pages/Dashboard.tsx`:

Add `useLastAnalysis` to the hooks import:

```tsx
import { useAnalyze, useLastAnalysis, useScore, useSignals, useStock, useWatchlist } from '../hooks/queries';
```

After the existing query hooks (near line 38), derive the shown analysis:

```tsx
  const lastAnalysis = useLastAnalysis(ticker);
  // In-session analysis (fresh run) wins; otherwise restore the last persisted one read-only.
  const restored = analysis ? null : lastAnalysis.data ?? null;
  const shown = analysis ?? restored?.result ?? null;
```

In the deep-result effect, also refresh the snapshot query:

```tsx
  useEffect(() => {
    if (deep.result) {
      setAnalysis(deep.result);
      qc.invalidateQueries({ queryKey: ['signals', ticker] });
      qc.invalidateQueries({ queryKey: ['analysis', ticker] });
    }
  }, [deep.result, setAnalysis, qc, ticker]);
```

Replace the chart `signals` prop and the hint (lines 154-155):

```tsx
              <PriceChart data={d} signals={shown?.signals ?? []} range={range} onSelectSignal={setSelected} />
              {shown && <p className="hint">Click a marker — or a signal in Analysis — to read its reasoning.</p>}
```

Replace the Analysis panel body (lines 165-169) to render `shown` and a restore badge:

```tsx
              {shown ? (
                <div className="analysis-scroll">
                  {!analysis && restored && (
                    <p className="hint restored-badge">
                      Last analysis · as of {restored.call_date} ·{' '}
                      {restored.source === 'llm_deep' ? 'deep' : 'fast'}
                    </p>
                  )}
                  <ReasoningPanel result={shown} />
                </div>
              ) : !deep.running && deep.steps.length === 0 ? (
                <p className="muted">Click “Analyze with LLM” for a fast call, or “Deep Analysis” to watch the agent pull data step-by-step.</p>
              ) : null}
```

Replace the side-col SignalList block (lines 177-183) to read `shown`:

```tsx
                {shown ? (
                  <div className="signals-scroll">
                    <SignalList signals={shown.signals} selected={selected} onSelect={setSelected} />
                  </div>
                ) : (
                  <p className="muted">Run an analysis to see buy/sell signals here.</p>
                )}
```

- [ ] **Step 4: Run test to verify it passes (and existing Dashboard tests still pass)**

Run: `npx vitest run src/pages/Dashboard.test.tsx`
Expected: PASS — restore test passes; the "keeps the LLM analysis after navigating" test still passes (default `getLastAnalysis` is null, so behavior is unchanged when there is no snapshot).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.test.tsx
git commit -m "feat(frontend): auto-restore the last analysis (panel, signal reasoning, chart markers) with an 'as of' badge"
```

---

### Task 9: Watchlist collapsible searchable dropdown

**Files:**
- Create: `frontend/src/components/WatchlistMenu.tsx`
- Create: `frontend/src/components/WatchlistMenu.test.tsx`
- Modify: `frontend/src/components/TickerBar.tsx` (replace inline `.watch` block)
- Modify: `frontend/src/components/TickerBar.test.tsx` (update 3 affected cases)
- Modify: `frontend/src/styles.css` (menu styles)

- [ ] **Step 1: Write the failing test for the new component**

Create `frontend/src/components/WatchlistMenu.test.tsx`:

```tsx
import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WatchlistMenu } from './WatchlistMenu';

function setup(over: { watchlist?: string[]; current?: string } = {}) {
  const onSelect = vi.fn();
  const onRemove = vi.fn();
  render(
    <WatchlistMenu
      watchlist={over.watchlist ?? ['AAPL', 'MSFT', 'NVDA']}
      current={over.current ?? 'AAPL'}
      onSelect={onSelect}
      onRemove={onRemove}
    />,
  );
  return { onSelect, onRemove };
}

const toggle = () => screen.getByRole('button', { name: /watchlist \(/i });

it('shows the count and is closed by default', () => {
  setup();
  expect(toggle()).toHaveTextContent('Watchlist (3)');
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it('opens, filters, and selects a ticker (closing the menu)', () => {
  const { onSelect } = setup();
  fireEvent.click(toggle());
  fireEvent.change(screen.getByPlaceholderText(/filter/i), { target: { value: 'nv' } });
  expect(screen.queryByRole('option', { name: /AAPL/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('option', { name: /NVDA/ }));
  expect(onSelect).toHaveBeenCalledWith('NVDA');
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it('removes a ticker via × without selecting or closing', () => {
  const { onSelect, onRemove } = setup();
  fireEvent.click(toggle());
  fireEvent.click(screen.getByRole('button', { name: /remove MSFT/i }));
  expect(onRemove).toHaveBeenCalledWith('MSFT');
  expect(onSelect).not.toHaveBeenCalled();
  expect(screen.getByRole('listbox')).toBeInTheDocument();
});

it('closes on Escape', () => {
  setup();
  fireEvent.click(toggle());
  expect(screen.getByRole('listbox')).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

it('disables the toggle when the watchlist is empty', () => {
  setup({ watchlist: [] });
  expect(screen.getByRole('button', { name: /watchlist \(0\)/i })).toBeDisabled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/WatchlistMenu.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `WatchlistMenu`**

Create `frontend/src/components/WatchlistMenu.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';

/** Collapsible, searchable watchlist. Replaces the inline chip row so a long watchlist stays
 *  one line. Click the toggle to open a filterable popover; pick a ticker to select (and close)
 *  or × to remove (stays open). Closes on Escape / outside-click. */
export function WatchlistMenu({ watchlist, current, onSelect, onRemove }: {
  watchlist: string[];
  current: string;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const shown = watchlist.filter((t) => t.toUpperCase().includes(filter.trim().toUpperCase()));
  const select = (t: string) => { onSelect(t); setOpen(false); };

  return (
    <div className="watch-menu" ref={ref}>
      <button
        type="button"
        className="secondary watch-toggle"
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={watchlist.length === 0}
        onClick={() => setOpen((o) => !o)}
      >
        Watchlist ({watchlist.length}) {open ? '▴' : '▾'}
      </button>
      {open && (
        <div className="watch-pop" role="listbox">
          <input
            autoFocus
            className="watch-filter"
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="watch-list">
            {shown.length === 0 && <p className="muted watch-empty">No matches</p>}
            {shown.map((t) => (
              <div
                key={t}
                role="option"
                aria-selected={t === current}
                className={`watch-item${t === current ? ' current' : ''}`}
                onClick={() => select(t)}
              >
                <span className="watch-item-label">{t}</span>
                <button
                  type="button"
                  className="chip-x"
                  aria-label={`Remove ${t}`}
                  onClick={(e) => { e.stopPropagation(); onRemove(t); }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the component test to verify it passes**

Run: `npx vitest run src/components/WatchlistMenu.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Add the menu styles**

In `frontend/src/styles.css`, add after the existing `.watch` / `.chip` rules (around line 441, in the command-bar section):

```css
/* Collapsible watchlist menu (replaces the inline chip row when the list grows long) */
.watch-menu { position: relative; }
.watch-toggle { white-space: nowrap; }
.watch-pop {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 30;
  width: 230px;
  max-height: 340px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  background: var(--bg-2);
  border: 1px solid var(--panel-brd);
  border-radius: 10px;
  box-shadow: 0 14px 34px -12px rgba(0, 0, 0, 0.6);
}
.watch-filter { width: 100%; }
.watch-list { overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.watch-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.06em;
}
.watch-item:hover { background: var(--gold-tint); color: var(--gold); }
.watch-item.current { border: 1px solid var(--gold-line); color: var(--gold); }
.watch-empty { padding: 6px 8px; }
```

- [ ] **Step 6: Update the failing TickerBar test cases**

In `frontend/src/components/TickerBar.test.tsx`, the inline chips no longer render — they live in the popover. Update:

Remove the two now-obsolete inline-chip cases (`'removes a chip via its × without also selecting it'` and `'selects a ticker when its chip body is clicked'`) — they are now covered by `WatchlistMenu.test.tsx`.

Replace the `'shows no star when no ticker is loaded'` case (its `/watchlist/i` regex now also matches the menu toggle) with a star-specific query:

```tsx
it('shows no star when no ticker is loaded', () => {
  setup({ current: '' });
  expect(
    screen.queryByRole('button', { name: /add to watchlist|remove from watchlist/i }),
  ).not.toBeInTheDocument();
});

it('renders the collapsible watchlist toggle with a count', () => {
  setup({ watchlist: ['AAPL', 'MSFT'], current: 'AAPL' });
  expect(screen.getByRole('button', { name: /watchlist \(2\)/i })).toBeInTheDocument();
});
```

- [ ] **Step 7: Swap the inline watch block for `WatchlistMenu` in `TickerBar`**

In `frontend/src/components/TickerBar.tsx`, add the import:

```tsx
import { WatchlistMenu } from './WatchlistMenu';
```

Replace the inline `.watch` block (current lines 55-72) with:

```tsx
      {watchlist.length > 0 && (
        <WatchlistMenu
          watchlist={watchlist}
          current={current}
          onSelect={onSelect}
          onRemove={onRemove}
        />
      )}
```

- [ ] **Step 8: Run the TickerBar + WatchlistMenu tests to verify all pass**

Run: `npx vitest run src/components/TickerBar.test.tsx src/components/WatchlistMenu.test.tsx`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/WatchlistMenu.tsx frontend/src/components/WatchlistMenu.test.tsx frontend/src/components/TickerBar.tsx frontend/src/components/TickerBar.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): collapsible searchable watchlist menu"
```

---

### Task 10: Full-suite verification

- [ ] **Step 1: Backend suite**

Run: from `backend/`, `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (previously ~442 + the new tests).

- [ ] **Step 2: Frontend suite**

Run: from `frontend/`, `npx vitest run`
Expected: all pass (previously ~217 + the new tests).

- [ ] **Step 3: Manual smoke (optional, dev servers run with HMR)**

- Load a ticker → click Analyze → confirm the chart arrows + Analysis + Signals list appear.
- Reload the app (fresh) → same ticker auto-shows the analysis with a "Last analysis · as of <date> · fast" badge, no Analyze click, no token spend.
- Hover the NET chip → tooltip reads "… · 0 of 1 scored — awaiting maturity".
- Open the Watchlist (N) ▾ menu → filter, select, remove.
- Confirm the Deep Analysis button is gold.

---

## Self-Review notes

- **Spec coverage:** #1 → Task 1; #2 → Task 9; #3 → Task 2; #4 read store → Task 4, schema/endpoint → Task 5, writes → Task 6, frontend hook → Task 7, restore UI → Task 8; footgun → Task 3. All covered.
- **Type consistency:** `AnalysisSnapshotStore.upsert(...)` keyword args (`ticker, source, call_date, period, provider, model, result_json`) match every call site (Tasks 5–6). `LastAnalysis` fields (`result, source, call_date, created_at`) match the backend schema (Task 5) and the frontend type (Task 7) and the Dashboard usage (`restored.result`, `restored.source`, `restored.call_date`) in Task 8. `run_analysis(..., snapshot_store=)` and `_persist_deep_final(..., snapshot_store=)` signatures match all call sites.
- **No placeholders:** every code step shows the full code; commands include expected outcomes.
