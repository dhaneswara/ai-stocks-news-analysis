# Signal-Source Scoreboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track every CALL the app produces (fast LLM, deep LLM, technical, network) through one evaluation engine, surface a per-ticker SignalsStrip + per-source scoreboard, and feed the LLM its own track record.

**Architecture:** The existing `predictions`/`prediction_evals` SQLite tables gain a `source` column inside the PK (one-time rebuild migration). All recording paths funnel into the existing `PredictionStore`; a new `app/evaluation/signals.py` hosts deterministic recording + the signals summary; a new `AgentTraceStore` persists deep traces. The frontend adds a `SignalsStrip` (replacing `ScoreChip`), a Discover post-rescan snapshot call, and an Evaluation-page source scoreboard.

**Tech Stack:** FastAPI + pydantic v2 + sqlite3 + pytest (backend, venv at `backend/.venv`); React + TanStack Query + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-06-10-signal-source-scoreboard-design.md`

**Conventions:**
- Backend tests: `cd backend; .venv\Scripts\python -m pytest <paths> -v` (PowerShell).
- Frontend tests: `cd frontend; npx vitest run <paths>`; typecheck/build: `npm run build`.
- Commit style: `feat(scope): ...` / `test(scope): ...`. **Never add a Claude co-author trailer.**

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `backend/app/evaluation/store.py` | rewrite | source column, PK migration, source-aware CRUD, source constants |
| `backend/app/evaluation/service.py` | modify | source threading (record/evaluate/board/explain), by_source rollups |
| `backend/app/evaluation/signals.py` | create | deterministic pair recording, watchlist snapshot, signals summary, track-record block |
| `backend/app/analysis/scoring.py` | modify | extract `direction_for(net)` helper |
| `backend/app/analysis/network.py` | modify | reuse `direction_for` (DRY) |
| `backend/app/analysis/trace_store.py` | create | `AgentTraceStore` (deep-trace persistence) |
| `backend/app/deps.py` | modify | `get_trace_store` |
| `backend/app/models/schemas.py` | modify | `Source`, `PredictionRecord.source`, signals models, `by_source`/`sources`, `StockData.track_record` |
| `backend/app/analysis/analyzer.py` | modify | render track-record prompt section |
| `backend/app/services/analysis_service.py` | modify | `gather_stock_context(store=)`, pair recording |
| `backend/app/api/routes.py` | modify | deep recording + `/traces` + `/evaluation/snapshot` + `/signals` + explain `source` |
| `frontend/src/types.ts` | modify | Source/SignalsSummary/SourceTrack/etc. |
| `frontend/src/api/client.ts` | modify | getSignals, snapshotEvaluation, explain source |
| `frontend/src/hooks/queries.ts` | modify | useSignals, useSnapshotEvaluation, useExplainPrediction source, useAnalyze invalidation |
| `frontend/src/components/SignalsStrip.tsx` (+test) | create | per-source chips, crown, agreement |
| `frontend/src/components/ScoreChip.tsx` (+test) | delete | absorbed by SignalsStrip |
| `frontend/src/pages/Dashboard.tsx` | modify | render SignalsStrip |
| `frontend/src/pages/Discover.tsx` | modify | post-rescan snapshot + note |
| `frontend/src/pages/Evaluation.tsx` | rewrite | scoreboard cards, filter chips, source badges, explain source |
| `frontend/src/styles.css` | modify | strip/card/filter styles |

---

### Task 1: PredictionStore — `source` column + PK migration

**Files:**
- Modify: `backend/app/evaluation/store.py` (full rewrite below)
- Create: `backend/tests/test_evaluation_migration.py`

- [ ] **Step 1: Write the failing migration tests** — create `backend/tests/test_evaluation_migration.py`:

```python
import sqlite3

from app.evaluation.store import PredictionStore


def _legacy_db(path: str) -> None:
    """Build a pre-source database exactly as the old store created it."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE predictions ("
        "ticker TEXT, call_date TEXT, provider TEXT, model TEXT, recommendation TEXT, "
        "confidence REAL, sentiment TEXT, entry_price REAL, created_at REAL, "
        "PRIMARY KEY (ticker, call_date))"
    )
    conn.execute(
        "CREATE TABLE prediction_evals ("
        "ticker TEXT, call_date TEXT, horizon INTEGER, eval_date TEXT, exit_price REAL, "
        "return_pct REAL, hit INTEGER, score REAL, "
        "PRIMARY KEY (ticker, call_date, horizon))"
    )
    conn.execute(
        "INSERT INTO predictions VALUES ('AAPL', '2026-06-05', 'anthropic', 'm', 'buy', "
        "0.8, 'bullish', 204.0, 1.0)"
    )
    conn.execute(
        "INSERT INTO prediction_evals VALUES ('AAPL', '2026-06-05', 1, '2026-06-06', "
        "210.0, 2.9, 1, 79.4)"
    )
    conn.commit()
    conn.close()


def test_legacy_rows_migrate_tagged_llm_fast(tmp_path):
    path = str(tmp_path / "p.db")
    _legacy_db(path)
    store = PredictionStore(path)
    rows = store.all_predictions()
    assert len(rows) == 1 and rows[0].source == "llm_fast"
    assert rows[0].recommendation == "buy" and rows[0].entry_price == 204.0
    evals = store.evals_for("AAPL", "2026-06-05")
    assert len(evals) == 1 and evals[0].source == "llm_fast" and evals[0].score == 79.4


def test_fast_and_deep_coexist_same_day_after_migration(tmp_path):
    path = str(tmp_path / "p.db")
    _legacy_db(path)
    store = PredictionStore(path)
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="sell", confidence=0.6, sentiment="bearish",
                            entry_price=204.0, source="llm_deep")
    assert store.get_prediction("AAPL", "2026-06-05", "llm_fast").recommendation == "buy"
    assert store.get_prediction("AAPL", "2026-06-05", "llm_deep").recommendation == "sell"
    assert len(store.all_predictions()) == 2


def test_migration_is_idempotent_on_reopen(tmp_path):
    path = str(tmp_path / "p.db")
    _legacy_db(path)
    PredictionStore(path)
    store = PredictionStore(path)  # reopen — must not duplicate or fail
    assert len(store.all_predictions()) == 1


def test_fresh_db_gets_new_schema(tmp_path):
    store = PredictionStore(str(tmp_path / "new.db"))
    store.upsert_prediction(ticker="MSFT", call_date="2026-06-05", provider="rules", model="",
                            recommendation="hold", confidence=0.1, sentiment="neutral",
                            entry_price=100.0, source="technical")
    assert store.get_prediction("MSFT", "2026-06-05", "technical") is not None
    assert store.get_prediction("MSFT", "2026-06-05") is None  # default looks up llm_fast


def test_entry_price_change_invalidates_only_that_source(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    for src in ("llm_fast", "technical"):
        store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                                recommendation="buy", confidence=0.8, sentiment="bullish",
                                entry_price=200.0, source=src)
        store.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0, source=src)
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=201.0, source="llm_fast")  # changed price
    assert store.has_eval("AAPL", "2026-06-05", 1, "llm_fast") is False
    assert store.has_eval("AAPL", "2026-06-05", 1, "technical") is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_migration.py -v`
Expected: FAIL (`source` attribute / unexpected keyword `source`).

- [ ] **Step 3: Rewrite `backend/app/evaluation/store.py`** with this full content:

```python
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

# Every CALL the app produces is tracked under one of these sources, and all of them are
# scored by the same evaluation rules. llm_* rows come from the analyzers; technical is the
# screener's pre-network vote; network is the blended vote (recorded only when a network
# signal actually influenced the score).
SOURCE_LLM_FAST = "llm_fast"
SOURCE_LLM_DEEP = "llm_deep"
SOURCE_TECHNICAL = "technical"
SOURCE_NETWORK = "network"
SOURCES = (SOURCE_LLM_FAST, SOURCE_LLM_DEEP, SOURCE_TECHNICAL, SOURCE_NETWORK)
LLM_SOURCES = (SOURCE_LLM_FAST, SOURCE_LLM_DEEP)

_CREATE_PREDICTIONS = (
    "CREATE TABLE IF NOT EXISTS predictions ("
    "ticker TEXT, call_date TEXT, provider TEXT, model TEXT, recommendation TEXT, "
    "confidence REAL, sentiment TEXT, entry_price REAL, created_at REAL, "
    "source TEXT NOT NULL DEFAULT 'llm_fast', "
    "PRIMARY KEY (ticker, call_date, source))"
)
_CREATE_EVALS = (
    "CREATE TABLE IF NOT EXISTS prediction_evals ("
    "ticker TEXT, call_date TEXT, horizon INTEGER, eval_date TEXT, exit_price REAL, "
    "return_pct REAL, hit INTEGER, score REAL, "
    "source TEXT NOT NULL DEFAULT 'llm_fast', "
    "PRIMARY KEY (ticker, call_date, source, horizon))"
)
# Legacy column lists for the one-time rebuild. `source` is appended LAST everywhere so
# SELECT order keeps matching the dataclasses, whose `source` field sits last with a default.
_PRED_LEGACY_COLS = ("ticker, call_date, provider, model, recommendation, confidence, "
                     "sentiment, entry_price, created_at")
_EVAL_LEGACY_COLS = "ticker, call_date, horizon, eval_date, exit_price, return_pct, hit, score"

_PRED_SELECT = ("SELECT ticker, call_date, provider, model, recommendation, confidence, "
                "sentiment, entry_price, created_at, source FROM predictions")
_EVAL_SELECT = ("SELECT ticker, call_date, horizon, eval_date, exit_price, return_pct, "
                "hit, score, source FROM prediction_evals")


@dataclass
class PredictionRow:
    ticker: str
    call_date: str
    provider: str
    model: str
    recommendation: str
    confidence: float
    sentiment: str
    entry_price: float
    created_at: float
    source: str = SOURCE_LLM_FAST


@dataclass
class EvalRow:
    ticker: str
    call_date: str
    horizon: int
    eval_date: str
    exit_price: float
    return_pct: float
    hit: int
    score: float
    source: str = SOURCE_LLM_FAST


class PredictionStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        # get_prediction_store() is an @lru_cache singleton, so this one connection is
        # shared process-wide across FastAPI's threadpool (check_same_thread=False).
        # sqlite3 connections are not safe under concurrent use, so every access to
        # _conn is serialised through _lock (see app/config/cache.py for details).
        # Multi-statement methods hold the lock across all statements so the
        # read-modify-write stays atomic.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate_add_source()
        self._conn.execute(_CREATE_PREDICTIONS)
        self._conn.execute(_CREATE_EVALS)
        self._conn.commit()

    def _migrate_add_source(self) -> None:
        """One-time rebuild for pre-source databases. SQLite can't widen a PRIMARY KEY, so:
        rename -> create new shape -> copy rows tagged 'llm_fast' -> drop legacy, one
        transaction per table (`with self._conn` commits or rolls the table back wholesale,
        so a failure is retried cleanly on next startup). Fresh DBs (no tables yet) and
        already-migrated DBs skip straight through."""
        for table, create_sql, legacy_cols in (
            ("predictions", _CREATE_PREDICTIONS, _PRED_LEGACY_COLS),
            ("prediction_evals", _CREATE_EVALS, _EVAL_LEGACY_COLS),
        ):
            info = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            if not info or any(col[1] == "source" for col in info):
                continue
            with self._conn:
                self._conn.execute(f"ALTER TABLE {table} RENAME TO {table}_legacy")
                self._conn.execute(create_sql)
                self._conn.execute(
                    f"INSERT INTO {table} ({legacy_cols}, source) "
                    f"SELECT {legacy_cols}, 'llm_fast' FROM {table}_legacy"
                )
                self._conn.execute(f"DROP TABLE {table}_legacy")

    def upsert_prediction(self, *, ticker: str, call_date: str, provider: str, model: str,
                          recommendation: str, confidence: float, sentiment: str,
                          entry_price: float, source: str = SOURCE_LLM_FAST) -> None:
        ticker = ticker.upper().strip()
        with self._lock:
            existing = self._conn.execute(
                "SELECT entry_price FROM predictions "
                "WHERE ticker = ? AND call_date = ? AND source = ?",
                (ticker, call_date, source),
            ).fetchone()
            if existing is not None and existing[0] != entry_price:
                self._conn.execute(
                    "DELETE FROM prediction_evals "
                    "WHERE ticker = ? AND call_date = ? AND source = ?",
                    (ticker, call_date, source),
                )
            self._conn.execute(
                "INSERT OR REPLACE INTO predictions "
                "(ticker, call_date, provider, model, recommendation, confidence, sentiment, "
                "entry_price, created_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, call_date, provider, model, recommendation, confidence, sentiment,
                 entry_price, time.time(), source),
            )
            self._conn.commit()

    def get_prediction(self, ticker: str, call_date: str,
                       source: str = SOURCE_LLM_FAST) -> Optional[PredictionRow]:
        with self._lock:
            row = self._conn.execute(
                _PRED_SELECT + " WHERE ticker = ? AND call_date = ? AND source = ?",
                (ticker.upper().strip(), call_date, source),
            ).fetchone()
        return PredictionRow(*row) if row else None

    def all_predictions(self) -> list[PredictionRow]:
        with self._lock:
            rows = self._conn.execute(_PRED_SELECT).fetchall()
        return [PredictionRow(*r) for r in rows]

    def has_eval(self, ticker: str, call_date: str, horizon: int,
                 source: str = SOURCE_LLM_FAST) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM prediction_evals "
                "WHERE ticker = ? AND call_date = ? AND horizon = ? AND source = ?",
                (ticker.upper().strip(), call_date, horizon, source),
            ).fetchone()
        return row is not None

    def record_eval(self, ticker: str, call_date: str, horizon: int, eval_date: str,
                    exit_price: float, return_pct: float, hit: int, score: float,
                    source: str = SOURCE_LLM_FAST) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO prediction_evals "
                "(ticker, call_date, horizon, eval_date, exit_price, return_pct, hit, score, "
                "source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker.upper().strip(), call_date, horizon, eval_date, exit_price, return_pct,
                 int(hit), score, source),
            )
            self._conn.commit()

    def evals_for(self, ticker: str, call_date: str,
                  source: Optional[str] = None) -> list[EvalRow]:
        sql = _EVAL_SELECT + " WHERE ticker = ? AND call_date = ?"
        params: tuple = (ticker.upper().strip(), call_date)
        if source is not None:
            sql += " AND source = ?"
            params += (source,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [EvalRow(*r) for r in rows]

    def all_evals(self) -> list[EvalRow]:
        with self._lock:
            rows = self._conn.execute(_EVAL_SELECT).fetchall()
        return [EvalRow(*r) for r in rows]

    def delete_ticker(self, ticker: str) -> int:
        ticker = ticker.upper().strip()
        with self._lock:
            cur = self._conn.execute("DELETE FROM predictions WHERE ticker = ?", (ticker,))
            self._conn.execute("DELETE FROM prediction_evals WHERE ticker = ?", (ticker,))
            self._conn.commit()
            return cur.rowcount
```

- [ ] **Step 4: Run migration tests + the whole evaluation suite**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_migration.py tests/test_evaluation_store.py tests/test_store_concurrency.py tests/test_evaluation_record.py tests/test_evaluation_evaluate.py tests/test_evaluation_board.py tests/test_evaluation_explain.py -v`
Expected: ALL PASS (old call sites work via the `source` defaults).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/store.py backend/tests/test_evaluation_migration.py
git commit -m "feat(evaluation): source-tagged prediction store with one-time PK migration"
```

---

### Task 2: Thread `source` through the evaluation service + explain route

**Files:**
- Modify: `backend/app/evaluation/service.py`
- Modify: `backend/app/models/schemas.py` (Source alias + `PredictionRecord.source`)
- Modify: `backend/app/api/routes.py:416-431` (explain `source` query param)
- Test: extend `backend/tests/test_evaluation_evaluate.py`, `backend/tests/test_evaluation_board.py`, `backend/tests/test_evaluation_explain.py`, `backend/tests/test_api_evaluation.py`

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_evaluation_evaluate.py`:

```python
def _rising_series():
    from datetime import date, timedelta
    d0 = date(2026, 6, 1)
    return [((d0 + timedelta(days=i)).isoformat(), 100.0 + i) for i in range(30)]


def test_multi_source_rows_scored_independently(tmp_path, monkeypatch):
    from app.evaluation.service import evaluate_pending
    from app.evaluation.store import PredictionStore
    from app.models.schemas import Settings

    store = PredictionStore(str(tmp_path / "p.db"))
    base = dict(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                confidence=0.8, sentiment="bullish", entry_price=100.0)
    store.upsert_prediction(**base, recommendation="buy", source="llm_fast")
    store.upsert_prediction(**base, recommendation="sell", source="llm_deep")
    store.upsert_prediction(**base, recommendation="buy", source="technical")
    monkeypatch.setattr("app.evaluation.service.fetch_close_series",
                        lambda t, p: _rising_series())
    evaluate_pending(store, Settings())
    fast = store.evals_for("AAPL", "2026-06-01", "llm_fast")
    deep = store.evals_for("AAPL", "2026-06-01", "llm_deep")
    tech = store.evals_for("AAPL", "2026-06-01", "technical")
    assert len(fast) == len(deep) == len(tech) == 3  # horizons 1/5/20
    assert all(e.hit for e in fast) and all(e.hit for e in tech)   # buy in a rising series
    assert all(not e.hit for e in deep)                            # sell in a rising series
```

Append to `backend/tests/test_evaluation_board.py`:

```python
def test_board_threads_source_through_records(tmp_path):
    from app.evaluation.service import build_board
    from app.evaluation.store import PredictionStore
    from app.models.schemas import Settings

    store = PredictionStore(str(tmp_path / "p.db"))
    base = dict(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                confidence=0.8, sentiment="bullish", entry_price=100.0)
    store.upsert_prediction(**base, recommendation="buy", source="llm_fast")
    store.upsert_prediction(**base, recommendation="sell", source="technical")
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 104.5, 4.5, 1, 90.0)  # llm_fast only
    board = build_board(store, Settings())
    comp = board.companies[0]
    by = {(c.call_date, c.source): c for c in comp.calls}
    assert by[("2026-06-01", "llm_fast")].results[0].status == "final"
    assert by[("2026-06-01", "technical")].results[0].status == "pending"
    assert comp.rollup.n_calls == 2
```

Append to `backend/tests/test_evaluation_explain.py`:

```python
def test_explain_uses_source_specific_row(tmp_path, monkeypatch):
    import pytest
    from app.config.cache import Cache
    from app.evaluation.service import explain_prediction
    from app.evaluation.store import PredictionStore
    from app.models.schemas import Settings

    class _Prov:
        name = "fake"
        def __init__(self):
            self.user = ""
        def complete(self, system, user):
            self.user = user
            return "because reasons"

    prov = _Prov()
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="rules", model="",
                            recommendation="buy", confidence=0.4, sentiment="bullish",
                            entry_price=100.0, source="technical")
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 95.0, -5.0, 0, 10.0,
                      source="technical")

    def _no_stock(*a, **k):
        raise ValueError("offline")

    monkeypatch.setattr("app.evaluation.service.get_stock_data", _no_stock)
    monkeypatch.setattr("app.evaluation.service.build_provider", lambda s: prov)

    text = explain_prediction("AAPL", "2026-06-01", Settings(), cache, store,
                              source="technical")
    assert text == "because reasons"
    assert "deterministic technical screen" in prov.user
    with pytest.raises(ValueError):
        explain_prediction("AAPL", "2026-06-01", Settings(), cache, store, source="llm_deep")
```

Append to `backend/tests/test_api_evaluation.py`:

```python
def test_explain_route_passes_source(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import routes
    from app.main import app

    captured = {}

    def fake_explain(ticker, call_date, settings, cache, store, source="llm_fast"):
        captured["source"] = source
        return "ok"

    monkeypatch.setattr(routes, "explain_prediction", fake_explain)
    client = TestClient(app)
    resp = client.post("/api/evaluation/AAPL/2026-06-01/explain?source=technical")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert captured["source"] == "technical"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_evaluate.py tests/test_evaluation_board.py tests/test_evaluation_explain.py tests/test_api_evaluation.py -v`
Expected: the four new tests FAIL (no `source` kwarg / no source attribute on records).

- [ ] **Step 3: Add the `Source` alias + `PredictionRecord.source` to `backend/app/models/schemas.py`.** Directly above `class HorizonResult(BaseModel):` (line ~246) insert:

```python
# All CALL sources tracked by the evaluation engine (mirrors app/evaluation/store.py).
Source = Literal["llm_fast", "llm_deep", "technical", "network"]
```

Inside `PredictionRecord` (line ~255), after `entry_price: float` add:

```python
    source: Source = "llm_fast"
```

- [ ] **Step 4: Update `backend/app/evaluation/service.py`.**

Change the store import to:

```python
from app.evaluation.store import (
    LLM_SOURCES,
    SOURCE_LLM_DEEP,
    SOURCE_LLM_FAST,
    SOURCE_NETWORK,
    SOURCE_TECHNICAL,
    PredictionStore,
)
```

`record_prediction` — new signature + pass-through:

```python
def record_prediction(stock: StockData, result: AnalysisResult, store: PredictionStore,
                      source: str = SOURCE_LLM_FAST) -> None:
    """Persist one call, keyed by the last trading day in the stock data."""
    if not stock.candles:
        return
    last = stock.candles[-1]
    store.upsert_prediction(
        ticker=result.ticker,
        call_date=last.time,
        provider=result.provider,
        model=result.model,
        recommendation=result.current_recommendation,
        confidence=result.confidence,
        sentiment=result.sentiment,
        entry_price=last.close,
        source=source,
    )
```

In `evaluate_pending`, change the `missing` comprehension to:

```python
        missing = [
            (p, h) for p in preds for h in horizons
            if not store.has_eval(p.ticker, p.call_date, h, p.source)
        ]
```

and the persist call to:

```python
                if persist:
                    store.record_eval(p.ticker, p.call_date, h, exit_date, exit_price,
                                      return_pct, int(hit), sc, source=p.source)
```

In `build_board`:
- `eval_index = {(e.ticker, e.call_date, e.source, e.horizon): e for e in store.all_evals()}`
- `preds.sort(key=lambda p: (p.call_date, p.source), reverse=True)`
- `e = eval_index.get((p.ticker, p.call_date, p.source, h))`
- replace `(hit_confs if e.hit else miss_confs).append(p.confidence)` with:

```python
                if p.source in LLM_SOURCES:  # deterministic |net| proxies must not skew the flag
                    (hit_confs if e.hit else miss_confs).append(p.confidence)
```

- in the `records.append(PredictionRecord(...))` call add `source=p.source,` after `entry_price=p.entry_price,`.

`explain_prediction` — add the labels map above it and thread `source`:

```python
_SOURCE_LABELS = {
    SOURCE_LLM_FAST: "fast LLM analysis",
    SOURCE_LLM_DEEP: "deep (agentic) LLM analysis",
    SOURCE_TECHNICAL: "deterministic technical screen",
    SOURCE_NETWORK: "network-blended screen",
}


def explain_prediction(ticker: str, call_date: str, settings: Settings, cache: Cache,
                       store: PredictionStore, source: str = SOURCE_LLM_FAST) -> str:
    """One short LLM post-mortem on why a call was off. Cached so it runs once per call."""
    ticker = ticker.upper().strip()
    pred = store.get_prediction(ticker, call_date, source)
    if pred is None:
        raise ValueError(f"No tracked {source} prediction for {ticker} on {call_date}")

    key = f"prediction_explain:{ticker}:{call_date}:{source}"
```

then `evals = sorted(store.evals_for(ticker, call_date, source), key=lambda e: e.horizon)`, and in the `user` prompt insert after the call-date line:

```python
        f"Signal source: {_SOURCE_LABELS.get(source, source)}\n"
```

- [ ] **Step 5: Update the explain route** in `backend/app/api/routes.py` — add the param and pass it:

```python
@router.post("/evaluation/{ticker}/{call_date}/explain")
def explain_evaluation(
    ticker: str,
    call_date: str,
    source: str = "llm_fast",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    settings = store.load()
    try:
        text = explain_prediction(ticker, call_date, settings, cache, prediction_store,
                                  source=source)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"explanation": text}
```

- [ ] **Step 6: Run the touched suites**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_evaluate.py tests/test_evaluation_board.py tests/test_evaluation_explain.py tests/test_api_evaluation.py tests/test_evaluation_record.py tests/test_evaluation_runner.py -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/evaluation/service.py backend/app/models/schemas.py backend/app/api/routes.py backend/tests/test_evaluation_evaluate.py backend/tests/test_evaluation_board.py backend/tests/test_evaluation_explain.py backend/tests/test_api_evaluation.py
git commit -m "feat(evaluation): thread prediction source through scoring, board and explain"
```

---

### Task 3: `direction_for` helper + deterministic pair recording at analysis time

**Files:**
- Modify: `backend/app/analysis/scoring.py` (extract `direction_for`)
- Modify: `backend/app/analysis/network.py` (reuse it)
- Create: `backend/app/evaluation/signals.py`
- Modify: `backend/app/services/analysis_service.py`
- Test: extend `backend/tests/test_scoring.py`; create `backend/tests/test_evaluation_signals.py`; modify `backend/tests/test_evaluation_record.py`

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_scoring.py`:

```python
def test_direction_for_thresholds():
    from app.analysis.scoring import direction_for
    assert direction_for(0.2) == "buy"
    assert direction_for(-0.2) == "sell"
    assert direction_for(0.05) == "hold"
```

Create `backend/tests/test_evaluation_signals.py`:

```python
from app.config.cache import Cache
from app.evaluation import signals
from app.evaluation.signals import record_deterministic_pair
from app.evaluation.store import PredictionStore
from app.models.schemas import (
    Candle, Fundamentals, Indicators, NetworkSignal, PriceSummary, Settings, StockData,
    StockScore,
)


def _stock(ticker="AAPL"):
    return StockData(
        ticker=ticker, company_name="X", as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=204.0, change=1.0, change_pct=0.5),
        candles=[
            Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
            Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
        ],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def _score(ticker="AAPL", *, base_net=0.3, net=0.3, direction="buy", network=None):
    return StockScore(ticker=ticker, name="X", sector="", price=204.0, change_pct=0.5,
                      score=70.0, direction=direction, net=net, base_net=base_net,
                      base_score=70.0, as_of="t", network=network)


def test_pair_records_technical_and_network(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    cache = Cache(str(tmp_path / "c.db"))
    sig = NetworkSignal(ticker="AAPL", intensity=0.5, signed=-0.4)
    monkeypatch.setattr(signals, "score_one",
                        lambda t, s, c: _score(base_net=0.3, net=-0.2, direction="sell",
                                               network=sig))
    record_deterministic_pair(_stock(), Settings(), cache, store)

    tech = store.get_prediction("AAPL", "2026-06-05", "technical")
    assert tech is not None and tech.recommendation == "buy"      # from base_net 0.3
    assert tech.entry_price == 204.0 and tech.provider == "rules"
    assert abs(tech.confidence - 0.3) < 1e-9

    net = store.get_prediction("AAPL", "2026-06-05", "network")
    assert net is not None and net.recommendation == "sell"       # blended direction
    assert abs(net.confidence - 0.2) < 1e-9


def test_pair_skips_network_row_without_signal(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score(network=None))
    record_deterministic_pair(_stock(), Settings(), Cache(str(tmp_path / "c.db")), store)
    assert store.get_prediction("AAPL", "2026-06-05", "technical") is not None
    assert store.get_prediction("AAPL", "2026-06-05", "network") is None


def test_pair_noop_without_candles(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score())
    stock = _stock()
    stock.candles = []
    record_deterministic_pair(stock, Settings(), Cache(str(tmp_path / "c.db")), store)
    assert store.all_predictions() == []
```

Append to `backend/tests/test_evaluation_record.py`:

```python
def test_run_analysis_also_records_deterministic_pair(tmp_path, monkeypatch):
    import json as _json
    from app.evaluation import signals
    from app.models.schemas import StockScore

    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())

    class FakeProvider:
        name = "fake"
        def complete(self, system, user):
            return _json.dumps({"overall_summary": "ok", "news_analysis": "ok",
                                "sentiment": "bullish", "current_recommendation": "buy",
                                "confidence": 0.8, "signals": [], "risks": []})

    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(
        signals, "score_one",
        lambda t, s, c: StockScore(ticker="AAPL", name="Apple", sector="", price=204.0,
                                   change_pct=0.5, score=70.0, direction="buy", net=0.3,
                                   base_net=0.3, base_score=70.0, as_of="t"))
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)
    assert store.get_prediction("AAPL", "2026-06-05", "llm_fast") is not None
    assert store.get_prediction("AAPL", "2026-06-05", "technical") is not None
```

Also update the two existing `run_analysis` tests in that file (`test_run_analysis_records_when_store_passed`, `test_run_analysis_skips_recording_when_disabled`) — add this line right after their `build_provider` monkeypatch so they stay hermetic once the pair recording lands:

```python
    monkeypatch.setattr(analysis_service, "record_deterministic_pair", lambda *a, **k: None)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_scoring.py tests/test_evaluation_signals.py tests/test_evaluation_record.py -v`
Expected: new tests FAIL (`direction_for` / `app.evaluation.signals` missing).

- [ ] **Step 3: Extract `direction_for` in `backend/app/analysis/scoring.py`.** Below `_DIRECTION_THRESHOLD = 0.1` (line 134) add:

```python
def direction_for(net: float) -> str:
    """Map a signed directional vote to the CALL, using the shared threshold."""
    return "buy" if net > _DIRECTION_THRESHOLD else "sell" if net < -_DIRECTION_THRESHOLD else "hold"
```

In `score_stock`, replace the line
`direction = "buy" if net > _DIRECTION_THRESHOLD else "sell" if net < -_DIRECTION_THRESHOLD else "hold"`
with `direction = direction_for(net)`.

In `backend/app/analysis/network.py`, change the import `from app.analysis.scoring import _DIRECTION_THRESHOLD` to `from app.analysis.scoring import direction_for`, and in `blend_network_into_score` replace:

```python
    direction = (
        "buy" if final_net > _DIRECTION_THRESHOLD
        else "sell" if final_net < -_DIRECTION_THRESHOLD
        else "hold"
    )
```

with `direction = direction_for(final_net)`.

- [ ] **Step 4: Create `backend/app/evaluation/signals.py`:**

```python
"""Multi-source signal recording + per-ticker signal summaries.

The deterministic scorer's calls (technical / network) are recorded through the SAME
PredictionStore the LLM paths use, so the evaluation engine judges every source by
identical rules."""
from __future__ import annotations

import logging

from app.analysis.scoring import direction_for
from app.config.cache import Cache
from app.evaluation.store import (
    SOURCE_NETWORK,
    SOURCE_TECHNICAL,
    PredictionStore,
)
from app.models.schemas import Settings, StockData
from app.screener.service import score_one

logger = logging.getLogger("evaluation")

_SENTIMENT_FOR = {"buy": "bullish", "sell": "bearish", "hold": "neutral"}


def record_deterministic_pair(stock: StockData, settings: Settings, cache: Cache,
                              store: PredictionStore) -> None:
    """Record the technical call (pre-network base vote) and — when a network signal actually
    influenced the score — the network-blended call, keyed to the same last-candle
    call_date/entry convention record_prediction uses."""
    if not stock.candles:
        return
    score = score_one(stock.ticker, settings, cache)
    last = stock.candles[-1]
    tech = direction_for(score.base_net)
    store.upsert_prediction(
        ticker=stock.ticker, call_date=last.time, provider="rules", model="",
        recommendation=tech, confidence=min(1.0, abs(score.base_net)),
        sentiment=_SENTIMENT_FOR[tech], entry_price=last.close, source=SOURCE_TECHNICAL,
    )
    if score.network is not None:
        store.upsert_prediction(
            ticker=stock.ticker, call_date=last.time, provider="rules", model="",
            recommendation=score.direction, confidence=min(1.0, abs(score.net)),
            sentiment=_SENTIMENT_FOR[score.direction], entry_price=last.close,
            source=SOURCE_NETWORK,
        )
```

- [ ] **Step 5: Wire it into `backend/app/services/analysis_service.py`.** Add the import:

```python
from app.evaluation.signals import record_deterministic_pair
```

and extend the recording block at the end of `run_analysis`:

```python
    if prediction_store is not None and settings.evaluation.enabled:
        try:
            record_prediction(stock, result, prediction_store)
        except Exception:  # noqa: BLE001 — recording must never break analysis
            logger.warning("prediction recording failed for %s", ticker)
        try:
            record_deterministic_pair(stock, settings, cache, prediction_store)
        except Exception:  # noqa: BLE001 — recording must never break analysis
            logger.warning("deterministic pair recording failed for %s", ticker)
    return result
```

- [ ] **Step 6: Run the touched suites + the full suite**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_scoring.py tests/test_network.py tests/test_evaluation_signals.py tests/test_evaluation_record.py -v` then `cd backend; .venv\Scripts\python -m pytest -q`
Expected: ALL PASS. If `tests/test_analysis_service.py` or `tests/test_runner.py` fail because they pass a prediction store into `run_analysis` (network access via the real `score_one`), add the same hermetic line to those tests: `monkeypatch.setattr(analysis_service, "record_deterministic_pair", lambda *a, **k: None)`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/analysis/scoring.py backend/app/analysis/network.py backend/app/evaluation/signals.py backend/app/services/analysis_service.py backend/tests/test_scoring.py backend/tests/test_evaluation_signals.py backend/tests/test_evaluation_record.py
git commit -m "feat(evaluation): record technical/network calls alongside every LLM analysis"
```

---

### Task 4: Deep-analysis recording + `AgentTraceStore` + `GET /api/traces/{ticker}`

**Files:**
- Create: `backend/app/analysis/trace_store.py`
- Modify: `backend/app/deps.py`
- Modify: `backend/app/api/routes.py` (deep stream + traces route)
- Test: create `backend/tests/test_trace_store.py`; rewrite `backend/tests/test_api_deep_stream.py`

- [ ] **Step 1: Write the failing tests.** Create `backend/tests/test_trace_store.py`:

```python
from app.analysis.trace_store import AgentTraceStore


def test_upsert_and_recent_ordering(tmp_path):
    s = AgentTraceStore(str(tmp_path / "t.db"))
    s.upsert(ticker="aapl", call_date="2026-06-04", provider="a", model="m", trace_json='{"d":4}')
    s.upsert(ticker="AAPL", call_date="2026-06-05", provider="a", model="m", trace_json='{"d":5}')
    assert s.recent("AAPL") == ['{"d":5}', '{"d":4}']
    assert s.recent("AAPL", limit=1) == ['{"d":5}']


def test_upsert_replaces_same_day(tmp_path):
    s = AgentTraceStore(str(tmp_path / "t.db"))
    s.upsert(ticker="AAPL", call_date="2026-06-05", provider="a", model="m", trace_json='{"v":1}')
    s.upsert(ticker="AAPL", call_date="2026-06-05", provider="a", model="m", trace_json='{"v":2}')
    assert s.recent("AAPL") == ['{"v":2}']
```

Rewrite `backend/tests/test_api_deep_stream.py` with this full content (keeps the three existing behaviors, adds recording/trace/fallback/traces-endpoint coverage, and stops touching the real `data/app.db` by overriding all deps):

```python
import json

from fastapi.testclient import TestClient

from app.analysis.trace_store import AgentTraceStore
from app.api import routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store, get_trace_store
from app.evaluation import signals
from app.evaluation.store import PredictionStore
from app.main import app
from app.models.schemas import Candle, StockScore
from tests.test_analyzer import VALID_PAYLOAD, FakeProvider, _stock


def _stock_with_candles():
    s = _stock()
    s.candles = [
        Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
        Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
    ]
    return s


def _fake_score():
    return StockScore(ticker="AAPL", name="Apple", sector="", price=204.0, change_pct=0.5,
                      score=70.0, direction="buy", net=0.3, base_net=0.3, base_score=70.0,
                      as_of="t")


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    settings_store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "pred.db"))
    trace_store = AgentTraceStore(str(tmp_path / "trace.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: settings_store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store
    app.dependency_overrides[get_trace_store] = lambda: trace_store
    return TestClient(app), pred_store, trace_store


def teardown_function():
    app.dependency_overrides.clear()


def test_deep_stream_emits_steps_and_final(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context", lambda t, p, s, c, prov: _stock())
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider([f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}']),
    )
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: step" in resp.text
    assert "event: final" in resp.text
    assert '"current_recommendation":"buy"' in resp.text


def test_deep_stream_404_when_no_price_data(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path)

    def boom(*a, **k):
        raise ValueError("No price history for ticker 'ZZZZ'")
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "gather_stock_context", boom)
    resp = client.get("/api/analyze/ZZZZ/deep/stream")
    assert resp.status_code == 404


def test_deep_stream_emits_error_event_when_provider_fails(tmp_path, monkeypatch):
    from app.llm.base import LLMError

    class _Raising:
        name = "raise"

        def complete(self, system, user, json_mode=True, stop=None):
            raise LLMError("provider down")

    client, _, _ = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context", lambda t, p, s, c, prov: _stock())
    monkeypatch.setattr(routes, "build_provider", lambda settings: _Raising())
    resp = client.get("/api/analyze/AAPL/deep/stream")
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "provider down" in resp.text


def test_deep_final_records_llm_deep_pair_and_trace(tmp_path, monkeypatch):
    client, pred_store, trace_store = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context",
                        lambda t, p, s, c, prov: _stock_with_candles())
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider([f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}']),
    )
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _fake_score())
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    deep = pred_store.get_prediction("AAPL", "2026-06-05", "llm_deep")
    assert deep is not None and deep.recommendation == "buy" and deep.entry_price == 204.0
    assert pred_store.get_prediction("AAPL", "2026-06-05", "technical") is not None
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_fast") is None
    traces = trace_store.recent("AAPL")
    assert len(traces) == 1 and '"fell_back":false' in traces[0]


def test_deep_fallback_records_as_llm_fast(tmp_path, monkeypatch):
    client, pred_store, trace_store = _client(tmp_path)
    monkeypatch.setattr(routes, "gather_stock_context",
                        lambda t, p, s, c, prov: _stock_with_candles())
    # Two protocol-breaking turns exhaust the nudge -> agent fails -> single-shot fallback
    # consumes the third output as plain JSON.
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider(["nonsense", "still nonsense", json.dumps(VALID_PAYLOAD)]),
    )
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _fake_score())
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_fast") is not None
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_deep") is None
    assert '"fell_back":true' in trace_store.recent("AAPL")[0]


def test_get_traces_returns_recent(tmp_path):
    client, _, trace_store = _client(tmp_path)
    trace_store.upsert(ticker="AAPL", call_date="2026-06-05", provider="anthropic", model="m",
                       trace_json='{"ticker":"AAPL","provider":"anthropic","model":"m",'
                                  '"started_at":"t"}')
    resp = client.get("/api/traces/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1 and body[0]["ticker"] == "AAPL"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_trace_store.py tests/test_api_deep_stream.py -v`
Expected: FAIL (`app.analysis.trace_store` / `get_trace_store` missing).

- [ ] **Step 3: Create `backend/app/analysis/trace_store.py`:**

```python
from __future__ import annotations

import sqlite3
import threading
import time


class AgentTraceStore:
    """Deep-analysis trace history: one AgentTrace JSON blob per (ticker, call_date),
    last run of the day wins. Mirrors the PredictionStore singleton/locking pattern
    (see app/evaluation/store.py)."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_traces ("
            "ticker TEXT, call_date TEXT, provider TEXT, model TEXT, trace_json TEXT, "
            "created_at REAL, PRIMARY KEY (ticker, call_date))"
        )
        self._conn.commit()

    def upsert(self, *, ticker: str, call_date: str, provider: str, model: str,
               trace_json: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_traces "
                "(ticker, call_date, provider, model, trace_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticker.upper().strip(), call_date, provider, model, trace_json, time.time()),
            )
            self._conn.commit()

    def recent(self, ticker: str, limit: int = 5) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT trace_json FROM agent_traces WHERE ticker = ? "
                "ORDER BY call_date DESC LIMIT ?",
                (ticker.upper().strip(), max(1, limit)),
            ).fetchall()
        return [r[0] for r in rows]
```

- [ ] **Step 4: Add `get_trace_store` to `backend/app/deps.py`:**

```python
from app.analysis.trace_store import AgentTraceStore
```

(at the imports), and at the end of the file:

```python
@lru_cache
def get_trace_store() -> AgentTraceStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return AgentTraceStore(DB_PATH)
```

- [ ] **Step 5: Wire recording into `backend/app/api/routes.py`.**

Add/extend imports near the top:

```python
import logging
from app.analysis.agent import AgentEvent, AgentTrace, ReActAgent, ToolContext
from app.analysis.trace_store import AgentTraceStore
from app.deps import get_cache, get_prediction_store, get_settings_store, get_trace_store
from app.evaluation.service import build_board, evaluate_pending, explain_prediction, record_prediction
from app.evaluation.signals import record_deterministic_pair
from app.evaluation.store import SOURCE_LLM_DEEP, SOURCE_LLM_FAST, PredictionStore
```

Below `router = APIRouter(prefix="/api")` add:

```python
logger = logging.getLogger("api")
```

Add the persistence helper above `analyze_deep_stream` (next to `_sse`):

```python
def _persist_deep_final(event: AgentEvent, stock: StockData, settings: Settings, cache: Cache,
                        prediction_store: PredictionStore, trace_store: AgentTraceStore) -> None:
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
    if event.result is None or not settings.evaluation.enabled:
        return
    source = SOURCE_LLM_FAST if (trace is not None and trace.fell_back) else SOURCE_LLM_DEEP
    try:
        record_prediction(stock, event.result, prediction_store, source=source)
    except Exception:  # noqa: BLE001
        logger.warning("deep prediction recording failed for %s", stock.ticker)
    try:
        record_deterministic_pair(stock, settings, cache, prediction_store)
    except Exception:  # noqa: BLE001
        logger.warning("deterministic pair recording failed for %s", stock.ticker)
```

Update `analyze_deep_stream` — add the two store deps and call the helper on `final`:

```python
@router.get("/analyze/{ticker}/deep/stream")
def analyze_deep_stream(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
    trace_store: AgentTraceStore = Depends(get_trace_store),
) -> StreamingResponse:
```

(docstring unchanged), and inside `event_stream()`:

```python
    def event_stream():
        try:
            for event in agent.stream(provider, cfg.model, provider_id, ctx):
                if event.type == "final":
                    _persist_deep_final(event, stock, settings, cache, prediction_store,
                                        trace_store)
                yield _sse(event)
        except LLMError as exc:  # provider/LLM failure (e.g. missing key) -> usable in-stream error
            yield _sse(AgentEvent(type="error", message=str(exc)))
```

Add the traces route after the deep-stream route:

```python
@router.get("/traces/{ticker}", response_model=list[AgentTrace])
def get_traces(
    ticker: str,
    limit: int = 5,
    trace_store: AgentTraceStore = Depends(get_trace_store),
) -> list[AgentTrace]:
    """Most recent persisted deep-analysis traces for a ticker (newest first)."""
    return [AgentTrace.model_validate_json(j) for j in trace_store.recent(ticker, limit)]
```

- [ ] **Step 6: Run**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_trace_store.py tests/test_api_deep_stream.py -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/analysis/trace_store.py backend/app/deps.py backend/app/api/routes.py backend/tests/test_trace_store.py backend/tests/test_api_deep_stream.py
git commit -m "feat(deep-analysis): record deep runs in evaluation and persist agent traces"
```

---

### Task 5: Watchlist snapshot — `snapshot_watchlist` + `POST /api/evaluation/snapshot`

**Files:**
- Modify: `backend/app/evaluation/signals.py`
- Modify: `backend/app/api/routes.py`
- Test: extend `backend/tests/test_evaluation_signals.py`, `backend/tests/test_api_evaluation.py`

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_evaluation_signals.py`:

```python
def test_snapshot_watchlist_records_and_isolates_failures(tmp_path, monkeypatch):
    from app.evaluation.signals import snapshot_watchlist

    store = PredictionStore(str(tmp_path / "p.db"))
    cache = Cache(str(tmp_path / "c.db"))
    settings = Settings()  # default watchlist: ["AAPL", "MSFT"]

    def fake_stock(ticker, period, params, cache_):
        if ticker == "MSFT":
            raise ValueError("no data")
        return _stock(ticker)

    monkeypatch.setattr(signals, "get_stock_data", fake_stock)
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score(t))
    out = snapshot_watchlist(settings, cache, store)
    assert out["recorded"] == 1
    assert out["skipped"] == [{"ticker": "MSFT", "reason": "no data"}]
    assert store.get_prediction("AAPL", "2026-06-05", "technical") is not None
```

Append to `backend/tests/test_api_evaluation.py`:

```python
def test_snapshot_route_uses_settings_watchlist(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import routes
    from app.config.cache import Cache
    from app.config.settings_store import SettingsStore
    from app.deps import get_cache, get_prediction_store, get_settings_store
    from app.evaluation.store import PredictionStore
    from app.main import app

    cache = Cache(str(tmp_path / "cache.db"))
    settings_store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "pred.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: settings_store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store

    captured = {}

    def fake_snapshot(settings, cache_, store_):
        captured["watchlist"] = list(settings.watchlist)
        return {"recorded": 2, "skipped": []}

    monkeypatch.setattr(routes, "snapshot_watchlist", fake_snapshot)
    client = TestClient(app)
    resp = client.post("/api/evaluation/snapshot")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {"recorded": 2, "skipped": []}
    assert captured["watchlist"] == ["AAPL", "MSFT"]  # Settings default
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py tests/test_api_evaluation.py -v`
Expected: new tests FAIL (`snapshot_watchlist` missing).

- [ ] **Step 3: Add `snapshot_watchlist` to `backend/app/evaluation/signals.py`.** Add the import `from app.services.stock_service import get_stock_data` and `from app.screener.service import SCAN_PERIOD, score_one` (replacing the bare `score_one` import), then:

```python
def snapshot_watchlist(settings: Settings, cache: Cache, store: PredictionStore) -> dict:
    """Record today's technical/network calls for every watchlist ticker (the Discover page
    fires this after Rescan All). Per-ticker isolation: one bad ticker is skipped and
    reported, the rest record."""
    recorded, skipped = 0, []
    for raw in settings.watchlist:
        ticker = raw.upper().strip()
        try:
            stock = get_stock_data(ticker, SCAN_PERIOD, settings.indicator_params, cache)
            record_deterministic_pair(stock, settings, cache, store)
            recorded += 1
        except Exception as exc:  # noqa: BLE001 — isolate per-ticker failures
            logger.warning("signal snapshot failed for %s", ticker)
            skipped.append({"ticker": ticker, "reason": str(exc)})
    return {"recorded": recorded, "skipped": skipped}
```

- [ ] **Step 4: Add the route to `backend/app/api/routes.py`** (after `delete_tracked`; extend the signals import to `from app.evaluation.signals import record_deterministic_pair, snapshot_watchlist`):

```python
@router.post("/evaluation/snapshot")
def snapshot_evaluation(
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    """Snapshot the watchlist's technical/network calls as dated predictions (no body —
    the watchlist lives in settings)."""
    settings = store.load()
    if not settings.evaluation.enabled:
        return {"recorded": 0, "skipped": [], "disabled": True}
    return snapshot_watchlist(settings, cache, prediction_store)
```

**Route-order note:** FastAPI matches in registration order; `POST /evaluation/snapshot` only collides with `POST /evaluation/{ticker}/{call_date}/explain` if paths are ambiguous — they aren't (different segment counts). No reordering needed.

- [ ] **Step 5: Run**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py tests/test_api_evaluation.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/evaluation/signals.py backend/app/api/routes.py backend/tests/test_evaluation_signals.py backend/tests/test_api_evaluation.py
git commit -m "feat(evaluation): watchlist signal snapshot endpoint for Rescan All"
```

---

### Task 6: Track-record prompt block (both LLM paths)

**Files:**
- Modify: `backend/app/evaluation/signals.py` (`build_track_record_block`)
- Modify: `backend/app/models/schemas.py` (`StockData.track_record`)
- Modify: `backend/app/analysis/analyzer.py` (render the section)
- Modify: `backend/app/services/analysis_service.py` (`gather_stock_context(store=)`)
- Modify: `backend/app/api/routes.py` (deep route passes the store to gather)
- Test: extend `backend/tests/test_evaluation_signals.py`, `backend/tests/test_analyzer.py`; adjust lambdas in `backend/tests/test_api_deep_stream.py`

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_evaluation_signals.py`:

```python
def _seed_llm_history(store):
    base = dict(ticker="NVDA", provider="a", model="m", sentiment="bullish", entry_price=100.0)
    store.upsert_prediction(**base, call_date="2026-05-12", recommendation="buy",
                            confidence=0.8, source="llm_fast")
    store.record_eval("NVDA", "2026-05-12", 5, "2026-05-19", 101.2, 1.2, 1, 62.0,
                      source="llm_fast")
    store.upsert_prediction(**base, call_date="2026-05-20", recommendation="buy",
                            confidence=0.9, source="llm_deep")
    store.record_eval("NVDA", "2026-05-20", 5, "2026-05-27", 96.9, -3.1, 0, 19.0,
                      source="llm_deep")


def test_track_record_block_formats_history(tmp_path):
    from app.evaluation.signals import build_track_record_block

    store = PredictionStore(str(tmp_path / "p.db"))
    _seed_llm_history(store)
    block = build_track_record_block("nvda", store, Settings())
    assert "2026-05-20 [deep] BUY (conf 90%)" in block
    assert "2026-05-12 [fast] BUY (conf 80%)" in block
    assert "+1.2% @5d ✓" in block and "-3.1% @5d ✗" in block
    assert "you hit 50% at 5 trading days" in block
    assert "skew overconfident" in block          # miss conf 0.9 >= hit conf 0.8
    assert block.endswith("Calibrate this call's confidence accordingly.")


def test_track_record_block_gates(tmp_path):
    from app.evaluation.signals import build_track_record_block

    store = PredictionStore(str(tmp_path / "p.db"))
    assert build_track_record_block("NVDA", store, Settings()) is None  # no history

    store.upsert_prediction(ticker="NVDA", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0, source="llm_fast")
    assert build_track_record_block("NVDA", store, Settings()) is None  # nothing matured

    disabled = Settings()
    disabled.evaluation.enabled = False
    _seed_llm_history(store)
    assert build_track_record_block("NVDA", store, disabled) is None   # feature off

    # deterministic rows alone never produce a block
    store2 = PredictionStore(str(tmp_path / "p2.db"))
    store2.upsert_prediction(ticker="NVDA", call_date="2026-06-01", provider="rules", model="",
                             recommendation="buy", confidence=0.4, sentiment="bullish",
                             entry_price=100.0, source="technical")
    store2.record_eval("NVDA", "2026-06-01", 5, "2026-06-08", 105.0, 5.0, 1, 100.0,
                       source="technical")
    assert build_track_record_block("NVDA", store2, Settings()) is None
```

Append to `backend/tests/test_analyzer.py`:

```python
def test_build_user_prompt_renders_track_record_only_when_set():
    stock = _stock()
    base = build_user_prompt(stock)
    assert "YOUR TRACK RECORD" not in base
    stock.track_record = "- 2026-06-01 [fast] BUY (conf 80%): +1.2% @5d ✓"
    enriched = build_user_prompt(stock)
    assert "YOUR TRACK RECORD" in enriched
    assert "+1.2% @5d ✓" in enriched
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py tests/test_analyzer.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement.**

`backend/app/models/schemas.py` — in `StockData`, after `network: Optional[NetworkSignal] = None` add:

```python
    track_record: Optional[str] = None   # LLM's own scored history on this ticker (prompt block)
```

`backend/app/evaluation/signals.py` — add imports `from typing import Optional`, `from app.evaluation.scoring import is_overconfident`, and extend the store-constants import with `SOURCE_LLM_DEEP, SOURCE_LLM_FAST, LLM_SOURCES`. Then add:

```python
def build_track_record_block(ticker: str, store: PredictionStore,
                             settings: Settings) -> Optional[str]:
    """Compact 'your own history on this name' block for the LLM prompt, or None when there
    is nothing scored yet — the prompt must stay byte-identical for fresh tickers."""
    if not settings.evaluation.enabled:
        return None
    ticker = ticker.upper().strip()
    preds = sorted(
        (p for p in store.all_predictions()
         if p.ticker == ticker and p.source in LLM_SOURCES),
        key=lambda p: p.call_date, reverse=True,
    )
    if not preds:
        return None
    evals = [e for e in store.all_evals() if e.ticker == ticker and e.source in LLM_SOURCES]
    by_call: dict[tuple[str, str], list] = {}
    for e in evals:
        by_call.setdefault((e.call_date, e.source), []).append(e)
    matured = [(p, sorted(by_call[(p.call_date, p.source)], key=lambda e: e.horizon))
               for p in preds if (p.call_date, p.source) in by_call]
    if not matured:
        return None

    lines = []
    for p, es in matured[:5]:
        mode = "deep" if p.source == SOURCE_LLM_DEEP else "fast"
        outcomes = ", ".join(
            f"{e.return_pct:+.1f}% @{e.horizon}d {'✓' if e.hit else '✗'}" for e in es)
        lines.append(f"- {p.call_date} [{mode}] {p.recommendation.upper()} "
                     f"(conf {p.confidence:.0%}): {outcomes}")

    horizons = settings.evaluation.horizons
    mid = horizons[len(horizons) // 2] if horizons else 5
    conf_by_call = {(p.call_date, p.source): p.confidence for p, _ in matured}
    mid_evals = [e for e in evals
                 if e.horizon == mid and (e.call_date, e.source) in conf_by_call]
    summary = ""
    if mid_evals:
        rate = 100.0 * sum(1 for e in mid_evals if e.hit) / len(mid_evals)
        summary = f"\nAcross your scored calls you hit {rate:.0f}% at {mid} trading days."
        hit_confs = [conf_by_call[(e.call_date, e.source)] for e in mid_evals if e.hit]
        miss_confs = [conf_by_call[(e.call_date, e.source)] for e in mid_evals if not e.hit]
        if is_overconfident(hit_confs, miss_confs):
            summary += (
                f" Your average confidence on misses "
                f"({sum(miss_confs) / len(miss_confs):.2f}) is at least your confidence on "
                f"hits ({sum(hit_confs) / len(hit_confs):.2f}) — you skew overconfident.")
    return ("\n".join(lines) + summary +
            "\nCalibrate this call's confidence accordingly.")
```

`backend/app/analysis/analyzer.py` — in `build_user_prompt`, before the `return f"""Analyze ...` statement add:

```python
    track_block = ""
    if stock.track_record:
        track_block = (
            "YOUR TRACK RECORD ON THIS TICKER (your own past tracked calls, scored against "
            "actual prices):\n" + stock.track_record +
            "\nWeigh this as calibration evidence about your own judgement on this name.\n\n"
        )
```

and change the template tail from:

```
create dated buy/sell signals from it (it informs the current recommendation only).

{_JSON_SCHEMA_HINT}"""
```

to:

```
create dated buy/sell signals from it (it informs the current recommendation only).

{track_block}{_JSON_SCHEMA_HINT}"""
```

(The prompt is byte-identical when `track_record` is unset.)

`backend/app/services/analysis_service.py` — add import `from app.evaluation.signals import build_track_record_block, record_deterministic_pair` (extending the Task 3 import), change the signature to:

```python
def gather_stock_context(ticker, period, settings, cache, provider,
                         store: PredictionStore | None = None) -> StockData:
```

and just before its `return stock` add:

```python
    if store is not None:
        try:
            stock.track_record = build_track_record_block(ticker, store, settings)
        except Exception:  # noqa: BLE001 — prompt enrichment must never break analysis
            logger.warning("track-record block failed for %s", ticker)
```

In `run_analysis`, change the gather call to:

```python
    stock = gather_stock_context(ticker, period, settings, cache, provider,
                                 store=prediction_store)
```

`backend/app/api/routes.py` — in `analyze_deep_stream`, change the gather call to:

```python
        stock = gather_stock_context(ticker, period, settings, cache, provider,
                                     store=prediction_store)
```

`backend/tests/test_api_deep_stream.py` — the four `gather_stock_context` monkeypatch lambdas gain the new kwarg; change each `lambda t, p, s, c, prov:` to `lambda t, p, s, c, prov, store=None:` (the `boom(*a, **k)` def already absorbs it).

- [ ] **Step 4: Run**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py tests/test_analyzer.py tests/test_api_deep_stream.py tests/test_analysis_service.py tests/test_evaluation_record.py -v`
Expected: ALL PASS (any other caller of `gather_stock_context` surfacing in the full run gets the same `store=None`-tolerant lambda fix).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/signals.py backend/app/models/schemas.py backend/app/analysis/analyzer.py backend/app/services/analysis_service.py backend/app/api/routes.py backend/tests/test_evaluation_signals.py backend/tests/test_analyzer.py backend/tests/test_api_deep_stream.py
git commit -m "feat(analysis): inject the LLM's own track record into fast and deep prompts"
```

---

### Task 7: Signals summary — schemas + `build_signals` + `GET /api/signals/{ticker}`

**Files:**
- Modify: `backend/app/models/schemas.py` (signals models)
- Modify: `backend/app/evaluation/signals.py` (`build_signals`)
- Modify: `backend/app/api/routes.py` (route)
- Test: extend `backend/tests/test_evaluation_signals.py`; create `backend/tests/test_api_signals.py`

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_evaluation_signals.py`:

```python
def _signal_pred(store, source, call_date, rec, *, ticker="AAPL", conf=0.5):
    store.upsert_prediction(ticker=ticker, call_date=call_date, provider="x", model="",
                            recommendation=rec, confidence=conf, sentiment="neutral",
                            entry_price=100.0, source=source)


def _signal_eval(store, source, call_date, score, hit, *, ticker="AAPL", horizon=5):
    store.record_eval(ticker, call_date, horizon, "2026-06-09", 100.0, 1.0, hit, score,
                      source=source)


def test_build_signals_empty(tmp_path):
    from datetime import date
    from app.evaluation.signals import build_signals

    store = PredictionStore(str(tmp_path / "p.db"))
    out = build_signals("AAPL", store, today=date(2026, 6, 10))
    assert out.ticker == "AAPL" and out.winner is None
    assert out.agreement.counted == 0
    assert all(v is None for v in out.sources.values())


def test_build_signals_latest_tracks_winner_and_agreement(tmp_path):
    from datetime import date
    from app.evaluation.signals import build_signals

    store = PredictionStore(str(tmp_path / "p.db"))
    # technical: 3 matured, strong — qualifies and wins
    for i, d in enumerate(("2026-06-03", "2026-06-04", "2026-06-05")):
        _signal_pred(store, "technical", d, "buy")
        _signal_eval(store, "technical", d, 80.0, 1)
    # llm_fast: 2 matured only — does not qualify for the crown
    for d in ("2026-06-04", "2026-06-05"):
        _signal_pred(store, "llm_fast", d, "sell")
        _signal_eval(store, "llm_fast", d, 90.0, 1)
    # network: stale (outside the 7-day window) — recorded but must not vote
    _signal_pred(store, "network", "2026-05-20", "hold")

    out = build_signals("AAPL", store, today=date(2026, 6, 10))
    assert out.winner == "technical"
    tech = out.sources["technical"]
    assert tech.latest.call_date == "2026-06-05" and tech.latest.recommendation == "buy"
    assert tech.track.n_calls == 3 and tech.track.n_matured == 3
    assert tech.track.hit_rate == 100.0 and tech.track.grade == "Strong"
    assert out.sources["llm_deep"] is None
    assert out.agreement.counted == 2          # technical + llm_fast; network too old
    assert out.agreement.conflict is True
    assert out.agreement.agreeing == 1


def test_build_signals_winner_tie_yields_no_crown(tmp_path):
    from datetime import date
    from app.evaluation.signals import build_signals

    store = PredictionStore(str(tmp_path / "p.db"))
    for src in ("technical", "llm_fast"):
        for d in ("2026-06-03", "2026-06-04", "2026-06-05"):
            _signal_pred(store, src, d, "buy")
            _signal_eval(store, src, d, 70.0, 1)
    out = build_signals("AAPL", store, today=date(2026, 6, 10))
    assert out.winner is None
```

Create `backend/tests/test_api_signals.py`:

```python
from fastapi.testclient import TestClient

from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store
from app.evaluation.store import PredictionStore
from app.main import app


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    settings_store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "pred.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: settings_store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store
    return TestClient(app), pred_store


def teardown_function():
    app.dependency_overrides.clear()


def test_signals_endpoint_shape(tmp_path):
    client, store = _client(tmp_path)
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="rules", model="",
                            recommendation="buy", confidence=0.3, sentiment="bullish",
                            entry_price=204.0, source="technical")
    body = client.get("/api/signals/aapl").json()
    assert body["ticker"] == "AAPL"
    assert body["sources"]["technical"]["latest"]["recommendation"] == "buy"
    assert body["sources"]["llm_fast"] is None
    assert body["winner"] is None
    assert set(body["sources"].keys()) == {"llm_fast", "llm_deep", "technical", "network"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py tests/test_api_signals.py -v`
Expected: new tests FAIL (`build_signals` / models missing).

- [ ] **Step 3: Add the models to `backend/app/models/schemas.py`** — insert between `PredictionRecord` and `CompanyRollup` (so later tasks can reference `SourceTrack` from classes below):

```python
class SourceTrack(BaseModel):
    n_calls: int = 0
    n_matured: int = 0                 # one unit per matured horizon, like CompanyRollup
    hit_rate: Optional[float] = None
    avg_score: Optional[float] = None
    grade: Optional[Literal["Strong", "Mixed", "Weak"]] = None


class LatestCall(BaseModel):
    call_date: str
    recommendation: Literal["buy", "sell", "hold"]
    confidence: float = 0.0


class SourceSignal(BaseModel):
    latest: LatestCall
    track: SourceTrack = Field(default_factory=SourceTrack)


class SignalsAgreement(BaseModel):
    counted: int = 0
    agreeing: int = 0
    on: Optional[Literal["buy", "sell", "hold"]] = None
    conflict: bool = False


class SignalsSummary(BaseModel):
    ticker: str
    sources: dict[str, Optional[SourceSignal]] = Field(default_factory=dict)
    agreement: SignalsAgreement = Field(default_factory=SignalsAgreement)
    winner: Optional[Source] = None
```

- [ ] **Step 4: Add `build_signals` to `backend/app/evaluation/signals.py`.** Add imports:

```python
from collections import Counter
from datetime import date, timedelta

from app.evaluation.scoring import grade_for, is_overconfident
from app.evaluation.store import SOURCES
from app.models.schemas import LatestCall, SignalsAgreement, SignalsSummary, SourceSignal, SourceTrack
```

(merge with existing import lines), then:

```python
_MIN_MATURED_FOR_WINNER = 3
_AGREEMENT_WINDOW_DAYS = 7   # ~5 trading days, calendar-approximated


def build_signals(ticker: str, store: PredictionStore, *,
                  today: Optional[date] = None) -> SignalsSummary:
    """Latest call + track record per source for one ticker, plus the agreement summary and
    the historically best source (>=3 matured evals; full ties get no crown). Reads only
    already-scored evals — maturing happens on the Evaluation page / CLI runs."""
    ticker = ticker.upper().strip()
    preds = [p for p in store.all_predictions() if p.ticker == ticker]
    eval_rows = [e for e in store.all_evals() if e.ticker == ticker]

    sources: dict[str, Optional[SourceSignal]] = {}
    for src in SOURCES:
        sp = sorted((p for p in preds if p.source == src), key=lambda p: p.call_date)
        if not sp:
            sources[src] = None
            continue
        es = [e for e in eval_rows if e.source == src]
        hit_rate = avg = grade = None
        if es:
            avg = round(sum(e.score for e in es) / len(es), 1)
            hit_rate = round(100.0 * sum(1 for e in es if e.hit) / len(es), 1)
            grade = grade_for(avg)
        latest = sp[-1]
        sources[src] = SourceSignal(
            latest=LatestCall(call_date=latest.call_date,
                              recommendation=latest.recommendation,
                              confidence=latest.confidence),
            track=SourceTrack(n_calls=len(sp), n_matured=len(es), hit_rate=hit_rate,
                              avg_score=avg, grade=grade),
        )

    qualified = sorted(
        ((src, s.track) for src, s in sources.items()
         if s is not None and s.track.n_matured >= _MIN_MATURED_FOR_WINNER),
        key=lambda kv: (kv[1].avg_score, kv[1].n_matured), reverse=True,
    )
    winner = None
    if qualified and (len(qualified) == 1 or
                      (qualified[0][1].avg_score, qualified[0][1].n_matured)
                      != (qualified[1][1].avg_score, qualified[1][1].n_matured)):
        winner = qualified[0][0]

    cutoff = ((today or date.today()) - timedelta(days=_AGREEMENT_WINDOW_DAYS)).isoformat()
    votes = [s.latest.recommendation for s in sources.values()
             if s is not None and s.latest.call_date >= cutoff]
    agreement = SignalsAgreement()
    if votes:
        counts = Counter(votes)
        on, agreeing = counts.most_common(1)[0]
        agreement = SignalsAgreement(counted=len(votes), agreeing=agreeing, on=on,
                                     conflict=len(counts) > 1)
    return SignalsSummary(ticker=ticker, sources=sources, agreement=agreement, winner=winner)
```

- [ ] **Step 5: Add the route to `backend/app/api/routes.py`** (extend the signals import with `build_signals`, add `SignalsSummary` to the schemas import) — place it next to `get_score`:

```python
@router.get("/signals/{ticker}", response_model=SignalsSummary)
def get_signals(
    ticker: str,
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> SignalsSummary:
    """All recorded CALL sources for one ticker + per-source track records, agreement and
    the historically best source — the Dashboard SignalsStrip payload."""
    return build_signals(ticker, prediction_store)
```

- [ ] **Step 6: Run**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py tests/test_api_signals.py tests/test_schemas.py -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/schemas.py backend/app/evaluation/signals.py backend/app/api/routes.py backend/tests/test_evaluation_signals.py backend/tests/test_api_signals.py
git commit -m "feat(evaluation): per-ticker signals summary endpoint (latest calls, winner, agreement)"
```

---

### Task 8: Evaluation board — `by_source` rollups + overall `sources` scoreboard

**Files:**
- Modify: `backend/app/models/schemas.py` (`CompanyEvaluation.by_source`, `EvaluationBoard.sources`)
- Modify: `backend/app/evaluation/service.py` (`build_board`)
- Test: extend `backend/tests/test_evaluation_board.py`

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_evaluation_board.py`:

```python
def test_board_by_source_and_overall_scoreboard(tmp_path):
    from app.evaluation.service import build_board
    from app.evaluation.store import PredictionStore
    from app.models.schemas import Settings

    store = PredictionStore(str(tmp_path / "p.db"))
    base = dict(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                sentiment="bullish", entry_price=100.0)
    store.upsert_prediction(**base, recommendation="buy", confidence=0.5, source="llm_fast")
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 104.5, 4.5, 1, 90.0,
                      source="llm_fast")
    # deterministic miss with absurd confidence — must NOT flip the overconfidence flag
    store.upsert_prediction(**base, recommendation="sell", confidence=1.0, source="technical")
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 104.5, 4.5, 0, 5.0,
                      source="technical")

    board = build_board(store, Settings())
    comp = board.companies[0]
    assert comp.by_source["llm_fast"].n_matured == 1
    assert comp.by_source["llm_fast"].hit_rate == 100.0
    assert comp.by_source["technical"].hit_rate == 0.0
    assert comp.by_source["technical"].grade == "Weak"
    assert comp.rollup.overconfident is False           # technical conf excluded
    assert board.sources["llm_fast"].n_calls == 1
    assert board.sources["technical"].avg_score == 5.0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_board.py -v`
Expected: new test FAILS (`by_source` missing).

- [ ] **Step 3: Schemas** — in `backend/app/models/schemas.py` add to `CompanyEvaluation`:

```python
    by_source: dict[str, SourceTrack] = Field(default_factory=dict)
```

and to `EvaluationBoard`:

```python
    sources: dict[str, SourceTrack] = Field(default_factory=dict)
```

- [ ] **Step 4: Rework `build_board` aggregation in `backend/app/evaluation/service.py`.** Add a module-level helper above `build_board`:

```python
def _track_for(n_calls: int, scores: list[float], hits: int) -> SourceTrack:
    if not scores:
        return SourceTrack(n_calls=n_calls)
    avg = round(sum(scores) / len(scores), 1)
    return SourceTrack(n_calls=n_calls, n_matured=len(scores),
                       hit_rate=round(100.0 * hits / len(scores), 1),
                       avg_score=avg, grade=grade_for(avg))
```

(add `SourceTrack` to the schemas import). Inside `build_board`, add global accumulators after `eval_index`:

```python
    g_counts: dict[str, int] = {}
    g_scores: dict[str, list[float]] = {}
    g_hits: dict[str, int] = {}
```

Inside the per-company loop, alongside the existing `scores`/`hit_confs`/`miss_confs` accumulators add:

```python
        s_counts: dict[str, int] = {}
        s_scores: dict[str, list[float]] = {}
        s_hits: dict[str, int] = {}
```

In the per-prediction loop, after `for p in preds:` add `s_counts[p.source] = s_counts.get(p.source, 0) + 1`, and inside the matured-horizon branch (where `scores.append(e.score)` happens) add:

```python
                s_scores.setdefault(p.source, []).append(e.score)
                if e.hit:
                    s_hits[p.source] = s_hits.get(p.source, 0) + 1
```

After the rollup is built, attach the breakdown and merge globals:

```python
        by_source = {src: _track_for(s_counts[src], s_scores.get(src, []),
                                     s_hits.get(src, 0)) for src in s_counts}
        for src in s_counts:
            g_counts[src] = g_counts.get(src, 0) + s_counts[src]
            g_scores.setdefault(src, []).extend(s_scores.get(src, []))
            g_hits[src] = g_hits.get(src, 0) + s_hits.get(src, 0)
        companies.append(CompanyEvaluation(rollup=rollup, calls=records, by_source=by_source))
```

(replacing the existing `companies.append(...)` line), and build the board with the overall scoreboard:

```python
    board_sources = {src: _track_for(g_counts[src], g_scores.get(src, []),
                                     g_hits.get(src, 0)) for src in g_counts}
    return EvaluationBoard(as_of=datetime.now(timezone.utc).isoformat(),
                           companies=companies, sources=board_sources)
```

- [ ] **Step 5: Run**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_board.py tests/test_api_evaluation.py -v` then the full backend suite `cd backend; .venv\Scripts\python -m pytest -q`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schemas.py backend/app/evaluation/service.py backend/tests/test_evaluation_board.py
git commit -m "feat(evaluation): per-source rollups and overall source scoreboard on the board"
```

---

### Task 9: Frontend types + API client + hooks

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/hooks/queries.ts`
- Test: extend `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing tests.** Append to `frontend/src/api/client.test.ts` (self-contained block; reuse the file's existing fetch-mock helpers if they exist instead of redefining):

```ts
import { afterEach as _afterEach, expect as _expect, it as _it, vi as _vi } from 'vitest';
import { api as _api } from './client';

const _okJson = (body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

_afterEach(() => _vi.restoreAllMocks());

_it('getSignals hits /signals/{ticker}', async () => {
  const spy = _vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
    _okJson({ ticker: 'AAPL', sources: {}, agreement: { counted: 0, agreeing: 0, on: null, conflict: false }, winner: null }));
  await _api.getSignals('AAPL');
  _expect(String(spy.mock.calls[0][0])).toContain('/signals/AAPL');
});

_it('snapshotEvaluation POSTs /evaluation/snapshot', async () => {
  const spy = _vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
    _okJson({ recorded: 2, skipped: [] }));
  await _api.snapshotEvaluation();
  _expect(String(spy.mock.calls[0][0])).toContain('/evaluation/snapshot');
  _expect((spy.mock.calls[0][1] as RequestInit).method).toBe('POST');
});

_it('explainPrediction carries the source', async () => {
  const spy = _vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
    _okJson({ explanation: 'x' }));
  await _api.explainPrediction('AAPL', '2026-06-01', 'technical');
  _expect(String(spy.mock.calls[0][0])).toContain('/evaluation/AAPL/2026-06-01/explain?source=technical');
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend; npx vitest run src/api/client.test.ts`
Expected: FAIL (`getSignals` not a function / explain arity).

- [ ] **Step 3: `frontend/src/types.ts`** — add after the `Grade` type:

```ts
export type Source = 'llm_fast' | 'llm_deep' | 'technical' | 'network';

export interface SourceTrack {
  n_calls: number;
  n_matured: number;
  hit_rate: number | null;
  avg_score: number | null;
  grade: Grade | null;
}

export interface LatestCall {
  call_date: string;
  recommendation: Recommendation;
  confidence: number;
}

export interface SourceSignal {
  latest: LatestCall;
  track: SourceTrack;
}

export interface SignalsAgreement {
  counted: number;
  agreeing: number;
  on: Recommendation | null;
  conflict: boolean;
}

export interface SignalsSummary {
  ticker: string;
  sources: Partial<Record<Source, SourceSignal | null>>;
  agreement: SignalsAgreement;
  winner: Source | null;
}

export interface SnapshotResult {
  recorded: number;
  skipped: { ticker: string; reason: string }[];
}
```

In `PredictionRecord` add `source: Source;` after `entry_price: number;`. In `CompanyEvaluation` add `by_source: Partial<Record<Source, SourceTrack>>;`. In `EvaluationBoard` add `sources: Partial<Record<Source, SourceTrack>>;`.

- [ ] **Step 4: `frontend/src/api/client.ts`** — add `SignalsSummary, SnapshotResult, Source` to the type imports; add to the `api` object next to `getScore`:

```ts
  getSignals: (ticker: string) => http<SignalsSummary>(`/signals/${encodeURIComponent(ticker)}`),
  snapshotEvaluation: () => http<SnapshotResult>('/evaluation/snapshot', { method: 'POST' }),
```

and change `explainPrediction` to:

```ts
  explainPrediction: (ticker: string, callDate: string, source: Source) =>
    http<{ explanation: string }>(
      `/evaluation/${encodeURIComponent(ticker)}/${encodeURIComponent(callDate)}/explain?source=${encodeURIComponent(source)}`,
      { method: 'POST' },
    ),
```

- [ ] **Step 5: `frontend/src/hooks/queries.ts`** — add `Source` to the type import; add:

```ts
export function useSignals(ticker: string) {
  return useQuery({
    queryKey: ['signals', ticker],
    queryFn: () => api.getSignals(ticker),
    enabled: ticker.length > 0,
    retry: false,
  });
}

export function useSnapshotEvaluation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.snapshotEvaluation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
    onError: (e) => console.warn('signal snapshot failed:', e),
  });
}
```

Change `useAnalyze` so a fresh LLM call refreshes the strip:

```ts
export function useAnalyze(ticker: string, period = '5y') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.analyze(ticker, period),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['signals', ticker] }),
  });
}
```

Change `useExplainPrediction` to:

```ts
export function useExplainPrediction() {
  return useMutation({
    mutationFn: ({ ticker, callDate, source }: { ticker: string; callDate: string; source: Source }) =>
      api.explainPrediction(ticker, callDate, source),
  });
}
```

- [ ] **Step 6: Run**

Run: `cd frontend; npx vitest run src/api/client.test.ts` → PASS. `npx tsc -b` → expected to FAIL only in `Evaluation.tsx` (explain call sites now need `source`) — that's Task 12; if it fails anywhere else, fix here.

Note: `Evaluation.tsx` is reworked in Task 12; to keep the tree compiling between tasks, apply the minimal interim fix now — in `Evaluation.tsx`, change `runExplain(call.call_date)` calls to pass the record and source:

```ts
  const runExplain = (call: PredictionRecord) => {
    setOpenExplain(call.call_date);
    explain.mutate(
      { ticker: company.rollup.ticker, callDate: call.call_date, source: call.source },
      { onSuccess: (d) => setText((t) => ({ ...t, [call.call_date]: d.explanation })) },
    );
  };
```

and the button's `onClick={() => runExplain(call.call_date)}` to `onClick={() => runExplain(call)}`. Then `npx tsc -b` → clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/api/client.test.ts frontend/src/pages/Evaluation.tsx
git commit -m "feat(frontend): signals/snapshot API client, hooks and source-aware explain"
```

---

### Task 10: `SignalsStrip` component + Dashboard wiring (replaces ScoreChip)

**Files:**
- Create: `frontend/src/components/SignalsStrip.tsx`, `frontend/src/components/SignalsStrip.test.tsx`
- Delete: `frontend/src/components/ScoreChip.tsx`, `frontend/src/components/ScoreChip.test.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`, `frontend/src/styles.css`

- [ ] **Step 1: Write the failing tests** — create `frontend/src/components/SignalsStrip.test.tsx`:

```tsx
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SignalsStrip } from './SignalsStrip';
import type { SignalsSummary, StockScore } from '../types';

function score(extra: Partial<StockScore> = {}): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0,
    score: 72, direction: 'buy', net: 0.3, reasons: ['RSI 28 (oversold)'], components: {}, as_of: 't',
    ...extra,
  };
}

function signals(extra: Partial<SignalsSummary> = {}): SignalsSummary {
  return {
    ticker: 'AAPL',
    sources: {
      technical: {
        latest: { call_date: '2026-06-09', recommendation: 'buy', confidence: 0.4 },
        track: { n_calls: 4, n_matured: 3, hit_rate: 66.7, avg_score: 61.2, grade: 'Mixed' },
      },
      llm_fast: {
        latest: { call_date: '2026-06-09', recommendation: 'sell', confidence: 0.7 },
        track: { n_calls: 2, n_matured: 0, hit_rate: null, avg_score: null, grade: null },
      },
    },
    agreement: { counted: 2, agreeing: 1, on: 'buy', conflict: true },
    winner: 'technical',
    ...extra,
  };
}

it('renders the score, one chip per source, and dashes for absent sources', () => {
  render(<SignalsStrip score={score()} signals={signals()} />);
  expect(screen.getByText('72')).toBeInTheDocument();
  expect(screen.getByText(/TECH/)).toBeInTheDocument();
  expect(screen.getByText('▲ BUY')).toBeInTheDocument();
  expect(screen.getByText('▼ SELL')).toBeInTheDocument();
  expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2); // NET + DEEP absent
});

it('crowns the winner and flags conflict', () => {
  render(<SignalsStrip score={score()} signals={signals()} />);
  expect(screen.getByText(/👑/)).toBeInTheDocument();
  expect(screen.getByText(/1\/2 lean BUY/)).toBeInTheDocument();
});

it('shows the 🔗 network badge only when the score has a network signal', () => {
  const { rerender } = render(<SignalsStrip score={score()} signals={signals()} />);
  expect(screen.queryByText('🔗')).not.toBeInTheDocument();
  rerender(<SignalsStrip
    score={score({ network: { ticker: 'AAPL', intensity: 0.5, signed: 0.3, influences: [], reasons: ['partner MSFT (bullish)'] } })}
    signals={signals()}
  />);
  expect(screen.getByText('🔗')).toBeInTheDocument();
});

it('renders without signals data (score only)', () => {
  render(<SignalsStrip score={score()} />);
  expect(screen.getByText('72')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend; npx vitest run src/components/SignalsStrip.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `frontend/src/components/SignalsStrip.tsx`:**

```tsx
import type { Recommendation, SignalsSummary, Source, StockScore } from '../types';
import { ScoreBar } from './ScoreBar';

const ORDER: [Source, string][] = [
  ['technical', 'TECH'], ['network', 'NET'], ['llm_fast', 'FAST'], ['llm_deep', 'DEEP'],
];
const ARROW: Record<Recommendation, string> = { buy: '▲', sell: '▼', hold: '—' };

/** Every CALL source for the loaded ticker side by side: latest call per source, hit-rate
 * tooltips, a crown on the historically best source, and an agree/conflict badge. Replaces
 * the old ScoreChip — the score bar + reason chips live on. */
export function SignalsStrip({ score, signals }: { score?: StockScore; signals?: SignalsSummary }) {
  const a = signals?.agreement;
  return (
    <div className="signals-strip">
      <div className="signals-row">
        <span className="section-label">Signals</span>
        {score && (
          <div className="score-cell"><ScoreBar score={score.score} /><span>{score.score.toFixed(0)}</span></div>
        )}
        {ORDER.map(([key, label]) => {
          const s = signals?.sources?.[key];
          const crowned = signals?.winner === key;
          const title = s
            ? `${label}: ${s.latest.recommendation.toUpperCase()} on ${s.latest.call_date}` +
              (s.track.hit_rate != null
                ? ` · ${s.track.hit_rate}% hit rate over ${s.track.n_matured} scored`
                : ' · collecting data')
            : `${label}: no call recorded yet`;
          return (
            <span key={key} className={`signal-chip${crowned ? ' winner' : ''}`} title={title}>
              <span className="signal-src">{crowned ? '👑 ' : ''}{label}</span>
              {s ? (
                <span className={`badge ${s.latest.recommendation}`}>
                  {ARROW[s.latest.recommendation]} {s.latest.recommendation.toUpperCase()}
                </span>
              ) : (
                <span className="muted">—</span>
              )}
            </span>
          );
        })}
        {a && a.counted >= 2 && (
          <span className={`agree-badge${a.conflict ? ' conflict' : ''}`}>
            {a.conflict
              ? `${a.agreeing}/${a.counted} lean ${a.on?.toUpperCase() ?? ''}`
              : `${a.counted}/${a.counted} agree on ${a.on?.toUpperCase() ?? ''}`}
          </span>
        )}
      </div>
      {score && (
        <div className="reasons">
          {score.network && score.network.reasons.length > 0 && (
            <span className="reason-chip net" title={score.network.reasons.join(' · ')}>🔗</span>
          )}
          {score.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire the Dashboard** (`frontend/src/pages/Dashboard.tsx`):
- Replace `import { ScoreChip } from '../components/ScoreChip';` with `import { SignalsStrip } from '../components/SignalsStrip';`
- Change the hooks import to `import { useAnalyze, useScore, useSignals, useStock, useWatchlist } from '../hooks/queries';` and add `import { useQueryClient } from '@tanstack/react-query';`
- After `const score = useScore(ticker);` add `const signals = useSignals(ticker);` and `const qc = useQueryClient();`
- Replace the deep-result effect with one that also refreshes the strip:

```tsx
  useEffect(() => {
    if (deep.result) {
      setAnalysis(deep.result);
      qc.invalidateQueries({ queryKey: ['signals', ticker] });
    }
  }, [deep.result, setAnalysis, qc, ticker]);
```

- Replace `{score.data && <ScoreChip score={score.data} />}` with:

```tsx
              {(score.data || signals.data) && (
                <SignalsStrip score={score.data} signals={signals.data} />
              )}
```

- [ ] **Step 5: Delete the absorbed component**

```bash
git rm frontend/src/components/ScoreChip.tsx frontend/src/components/ScoreChip.test.tsx
```

- [ ] **Step 6: Add styles** to `frontend/src/styles.css` (next to the existing `.score-chip` block; leave `.score-chip` CSS in place or remove it — it is now unused, removing is cleaner):

```css
.signals-strip { display: flex; flex-direction: column; gap: 8px; align-items: flex-end; }
.signals-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.signal-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 9px; border: 1px solid var(--panel-brd); border-radius: 999px;
}
.signal-chip.winner { border-color: var(--gold-line); background: var(--gold-tint); }
.signal-src { font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em; color: var(--ink-faint); }
.agree-badge { font-family: var(--mono); font-size: 10.5px; color: var(--buy); }
.agree-badge.conflict { color: var(--sell); }
```

(remove the now-dead `.score-chip { ... }` rule.)

- [ ] **Step 7: Run**

Run: `cd frontend; npx vitest run src/components/SignalsStrip.test.tsx` → PASS. Then `npx tsc -b` → clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/SignalsStrip.tsx frontend/src/components/SignalsStrip.test.tsx frontend/src/pages/Dashboard.tsx frontend/src/styles.css
git commit -m "feat(frontend): SignalsStrip — all CALL sources side by side on the Dashboard"
```

---

### Task 11: Discover — snapshot after Rescan All

**Files:**
- Modify: `frontend/src/pages/Discover.tsx`

- [ ] **Step 1: Edit `frontend/src/pages/Discover.tsx`:**
- Import line becomes:

```ts
import { useRefreshUniverse, useRescan, useScreen, useSectors, useSnapshotEvaluation, useWatchlist } from '../hooks/queries';
```

- After `const refreshList = useRefreshUniverse();` add `const snapshot = useSnapshotEvaluation();`
- Change the rescan button's onClick to chain the snapshot:

```tsx
          <button onClick={() => rescan.mutate(sector || undefined, { onSuccess: () => snapshot.mutate() })} disabled={rescan.isPending}>
            {rescan.isPending ? 'Scanning…' : sector ? `Rescan ${sector}` : 'Rescan all'}
          </button>
```

- After the `{rescan.isError && ...}` line add:

```tsx
      {snapshot.data && (
        <p className="muted">
          ✓ Recorded {snapshot.data.recorded} watchlist signal{snapshot.data.recorded === 1 ? '' : 's'} for
          evaluation{snapshot.data.skipped.length ? ` (${snapshot.data.skipped.length} skipped)` : ''}.
        </p>
      )}
```

- [ ] **Step 2: Verify**

Run: `cd frontend; npx tsc -b` → clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Discover.tsx
git commit -m "feat(frontend): snapshot watchlist signals after Rescan All"
```

---

### Task 12: Evaluation page — scoreboard cards, source filter, badges

**Files:**
- Rewrite: `frontend/src/pages/Evaluation.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Replace `frontend/src/pages/Evaluation.tsx`** with this full content:

```tsx
import { useState } from 'react';
import { EvaluationBoard } from '../components/EvaluationBoard';
import { ScoreBar } from '../components/ScoreBar';
import { useDeleteTracked, useEvaluation, useExplainPrediction } from '../hooks/queries';
import type {
  CompanyEvaluation, HorizonResult, PredictionRecord, Source, SourceTrack,
} from '../types';

const SOURCE_ORDER: Source[] = ['technical', 'network', 'llm_fast', 'llm_deep'];
const SOURCE_LABEL: Record<Source, string> = {
  technical: 'Technical', network: 'Network', llm_fast: 'LLM fast', llm_deep: 'LLM deep',
};
const GRADE_CLASS: Record<string, string> = { Strong: 'buy', Mixed: 'hold', Weak: 'sell' };

function OutcomeChip({ r }: { r: HorizonResult }) {
  if (r.status !== 'final') return <span className="outcome pending">{r.horizon}d · pending</span>;
  const pct = r.return_pct ?? 0;
  const sign = pct >= 0 ? '+' : '';
  return (
    <span className={`outcome ${r.hit ? 'hit' : 'miss'}`}>
      {r.horizon}d {r.hit ? '✓' : '✗'} {sign}{pct.toFixed(1)}%
    </span>
  );
}

function hasMiss(call: PredictionRecord): boolean {
  return call.results.some((r) => r.status === 'final' && r.hit === false);
}

function SourceScoreboard({ sources }: { sources: Partial<Record<Source, SourceTrack>> }) {
  const entries = SOURCE_ORDER.filter((k) => sources[k]);
  if (!entries.length) return null;
  return (
    <div className="source-cards">
      {entries.map((k) => {
        const t = sources[k]!;
        return (
          <div className="source-card" key={k}>
            <span className="section-label">{SOURCE_LABEL[k]}</span>
            <span className="muted">{t.n_calls} calls · {t.n_matured} scored</span>
            <span className="mono">{t.hit_rate == null ? '— hit rate' : `${t.hit_rate.toFixed(1)}% hit rate`}</span>
            {t.avg_score != null ? (
              <div className="score-cell"><ScoreBar score={t.avg_score} /><span>{t.avg_score.toFixed(0)}</span></div>
            ) : (
              <span className="muted">no scored calls yet</span>
            )}
            {t.grade && <span className={`badge ${GRADE_CLASS[t.grade]}`}>{t.grade}</span>}
          </div>
        );
      })}
    </div>
  );
}

function CompanyDetail({ company, srcFilter }: { company: CompanyEvaluation; srcFilter: Source | null }) {
  const explain = useExplainPrediction();
  const remove = useDeleteTracked();
  const [openExplain, setOpenExplain] = useState<string | null>(null);
  const [text, setText] = useState<Record<string, string>>({});

  const runExplain = (call: PredictionRecord) => {
    const key = `${call.call_date}:${call.source}`;
    setOpenExplain(key);
    explain.mutate(
      { ticker: company.rollup.ticker, callDate: call.call_date, source: call.source },
      { onSuccess: (d) => setText((t) => ({ ...t, [key]: d.explanation })) },
    );
  };

  const calls = company.calls.filter((c) => !srcFilter || c.source === srcFilter);

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="section-label">{company.rollup.ticker} — calls</span>
        <button className="secondary" onClick={() => remove.mutate(company.rollup.ticker)} disabled={remove.isPending}>
          {remove.isPending ? 'Removing…' : 'Stop tracking'}
        </button>
      </div>
      <div className="src-filter">
        {SOURCE_ORDER.filter((k) => company.by_source[k]).map((k) => {
          const t = company.by_source[k]!;
          return (
            <span key={k} className="reason-chip">
              {SOURCE_LABEL[k]}: {t.hit_rate == null ? '—' : `${t.hit_rate.toFixed(0)}%`} over {t.n_matured}
            </span>
          );
        })}
      </div>
      {remove.isError && <p className="error">Couldn't remove: {(remove.error as Error).message}</p>}
      {!calls.length && <p className="muted">No calls from this source yet.</p>}
      <div className="calls">
        {calls.map((call) => {
          const key = `${call.call_date}:${call.source}`;
          return (
            <div className="call-row" key={key}>
              <span className="mono">{call.call_date}</span>
              <span className="reason-chip">{SOURCE_LABEL[call.source]}</span>
              <span className={`badge ${call.recommendation}`}>{call.recommendation.toUpperCase()}</span>
              <span className="muted">conf {(call.confidence * 100).toFixed(0)}%</span>
              <div className="outcomes">
                {call.results.map((r) => <OutcomeChip key={r.horizon} r={r} />)}
              </div>
              {hasMiss(call) && (
                <button className="secondary" onClick={() => runExplain(call)}
                        disabled={explain.isPending && openExplain === key}>
                  {explain.isPending && openExplain === key ? 'Analyzing…' : 'Explain miss'}
                </button>
              )}
              {openExplain === key && explain.isError && (
                <p className="error">Couldn't explain: {(explain.error as Error).message}</p>
              )}
              {text[key] && <p className="explain-box">{text[key]}</p>}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function Evaluation() {
  const board = useEvaluation();
  const [selected, setSelected] = useState<string | null>(null);
  const [srcFilter, setSrcFilter] = useState<Source | null>(null);

  const companies = board.data?.companies ?? [];
  const current = companies.find((c) => c.rollup.ticker === selected) ?? null;

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <span className="section-label">Call accuracy by source — click a company to see its calls</span>
          {board.data?.as_of && (
            <span className="muted board-asof">As of {new Date(board.data.as_of).toLocaleString()}</span>
          )}
        </div>
        {board.isLoading && <p className="muted">Loading evaluation…</p>}
        {board.isError && <p className="error">Could not load evaluation: {(board.error as Error).message}</p>}
        {board.data && (
          <>
            <SourceScoreboard sources={board.data.sources ?? {}} />
            <div className="src-filter">
              <button className={srcFilter == null ? '' : 'secondary'} onClick={() => setSrcFilter(null)}>All</button>
              {SOURCE_ORDER.map((k) => (
                <button key={k} className={srcFilter === k ? '' : 'secondary'} onClick={() => setSrcFilter(k)}>
                  {SOURCE_LABEL[k]}
                </button>
              ))}
            </div>
            <EvaluationBoard companies={companies} selected={selected} onSelect={setSelected} />
          </>
        )}
      </section>
      {current && <CompanyDetail company={current} srcFilter={srcFilter} />}
    </>
  );
}
```

- [ ] **Step 2: Add styles** to `frontend/src/styles.css` (next to the evaluation classes):

```css
.source-cards { display: flex; gap: 12px; flex-wrap: wrap; margin: 0 0 14px; }
.source-card {
  flex: 1 1 150px; display: flex; flex-direction: column; gap: 6px;
  border: 1px solid var(--panel-brd); border-radius: 8px; padding: 10px 12px;
  background: var(--panel);
}
.src-filter { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 10px; }
```

- [ ] **Step 3: Verify**

Run: `cd frontend; npx vitest run` (all frontend tests) and `npm run build`
Expected: tests PASS, build clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Evaluation.tsx frontend/src/styles.css
git commit -m "feat(frontend): evaluation source scoreboard, filter chips and source badges"
```

---

### Task 13: Full verification sweep

- [ ] **Step 1: Backend full suite**

Run: `cd backend; .venv\Scripts\python -m pytest -q`
Expected: ALL PASS, no network access during tests.

- [ ] **Step 2: Frontend full suite + production build**

Run: `cd frontend; npx vitest run` then `npm run build`
Expected: ALL PASS, clean build.

- [ ] **Step 3: CLI smoke (no DB yet — exercises migration + empty board)**

Run: `cd backend; $env:DATA_DIR = "$env:TEMP\mc-eval-smoke"; .venv\Scripts\python -m app.evaluation --dry-run; Remove-Item -Recurse -Force "$env:TEMP\mc-eval-smoke"`
Expected: exits 0, logs `Done: {...}`.

- [ ] **Step 4: Final commit if anything was touched during verification; otherwise done.**

---

## Self-review checklist (run after writing/executing)

- **Spec coverage:** schema+migration (Task 1), four recording paths (Tasks 2–5), traces + `/traces` (Task 4), snapshot endpoint + Discover hook (Tasks 5, 11), `/signals` + SignalsStrip (Tasks 7, 10), board scoreboard/filters (Tasks 8, 12), prompt block both paths (Task 6), explain source (Tasks 2, 9, 12).
- **Out of scope (per spec):** no blended verdict, no holdings/advisor, no scheduler, no trace-browser UI.
