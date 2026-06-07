# LLM Recommendation Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every LLM "Analyze with LLM" recommendation, score it against actual price moves at 1/5/20 trading days, and surface per-company accuracy on a new Evaluation page with an on-demand "why was this wrong?" post-mortem.

**Architecture:** A new `backend/app/evaluation/` package (mirroring `app/alerts/`) adds two SQLite tables via a `PredictionStore`, pure scoring functions, a service (`record_prediction` / `evaluate_pending` / `build_board` / `explain_prediction`), a CLI runner, and three API endpoints. Recording is a side-effect of the existing `/analyze` route. The frontend adds an `/evaluation` page (summary board + expandable per-company calls) reusing existing board/badge/score-bar styles.

**Tech Stack:** Backend — FastAPI, Pydantic v2, raw `sqlite3`, pytest, yfinance/pandas (price history). Frontend — React 18 + TS, @tanstack/react-query v5, vitest + @testing-library/react.

**Conventions (Windows / PowerShell):**
- Backend tests: `cd backend; .venv\Scripts\python.exe -m pytest -q` (add a path to scope).
- Frontend: `cd frontend; npx vitest run <file>` (targeted), `npx tsc --noEmit` (types), `npm run build` (full gate).
- Conventional Commits, one per task. **Never** add a `Co-Authored-By: Claude` trailer.
- Work happens on branch `feat/llm-recommendation-evaluation` (already created; the spec is committed there).

---

## File Structure

**Backend (new `app/evaluation/` package):**
- `backend/app/evaluation/__init__.py` — empty package marker.
- `backend/app/evaluation/store.py` — `PredictionStore` + `PredictionRow`/`EvalRow` dataclasses (the two tables, raw sqlite, mirrors `app/alerts/state.py`).
- `backend/app/evaluation/scoring.py` — pure `is_hit` / `score_call` / `grade_for` / `is_overconfident` + grade constants.
- `backend/app/evaluation/service.py` — `record_prediction`, `evaluate_pending`, `build_board`, `explain_prediction`.
- `backend/app/evaluation/runner.py` — `run_evaluation` (thin wrapper used by CLI).
- `backend/app/evaluation/__main__.py` — `python -m app.evaluation [--dry-run]`.

**Backend (modified):**
- `backend/app/models/schemas.py` — `EvaluationConfig`, response models, `Settings.evaluation`.
- `backend/app/data/market.py` — `fetch_close_series` helper.
- `backend/app/services/analysis_service.py` — optional `prediction_store` param + record on fresh path.
- `backend/app/deps.py` — `get_prediction_store()` singleton.
- `backend/app/api/routes.py` — three endpoints + wire store into `/analyze`.

**Frontend (new):**
- `frontend/src/components/EvaluationBoard.tsx` (+ `.test.tsx`) — summary table.
- `frontend/src/pages/Evaluation.tsx` (+ `.test.tsx`) — page: fetch, select, per-company detail + explain.

**Frontend (modified):**
- `frontend/src/types.ts` — evaluation types + `Settings.evaluation`.
- `frontend/src/api/client.ts` — `getEvaluation` / `explainPrediction` / `deleteTracked`.
- `frontend/src/hooks/queries.ts` — `useEvaluation` / `useExplainPrediction` / `useDeleteTracked`.
- `frontend/src/App.tsx` — route + nav link.
- `frontend/src/styles.css` — outcome chips + call-row styles.
- `frontend/src/pages/Dashboard.test.tsx`, `frontend/src/hooks/useWatchlist.test.tsx` — add `evaluation` to their `Settings` fixtures.

---

## Task 1: Schemas — EvaluationConfig + response models + Settings.evaluation

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_evaluation_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_schema.py`:

```python
from app.models.schemas import (
    CompanyEvaluation,
    CompanyRollup,
    EvaluationBoard,
    EvaluationConfig,
    HorizonResult,
    PredictionRecord,
    Settings,
)


def test_evaluation_config_defaults():
    cfg = EvaluationConfig()
    assert cfg.enabled is True
    assert cfg.horizons == [1, 5, 20]
    assert cfg.hold_band_pct == 2.0
    assert cfg.score_scale_pct == 5.0


def test_settings_includes_evaluation_and_round_trips():
    s = Settings()
    assert s.evaluation.enabled is True
    again = Settings.model_validate_json(s.model_dump_json())
    assert again.evaluation.horizons == [1, 5, 20]


def test_response_models_construct():
    hr = HorizonResult(horizon=5, status="final", eval_date="2026-06-12",
                       return_pct=3.0, hit=True, score=80.0)
    rec = PredictionRecord(ticker="AAPL", call_date="2026-06-05", provider="anthropic",
                           model="m", recommendation="buy", confidence=0.8,
                           sentiment="bullish", entry_price=200.0, results=[hr])
    roll = CompanyRollup(ticker="AAPL", n_calls=1, n_matured=1, hit_rate=100.0,
                         avg_score=80.0, grade="Strong", overconfident=False,
                         latest_recommendation="buy", latest_call_date="2026-06-05")
    board = EvaluationBoard(as_of="t", companies=[CompanyEvaluation(rollup=roll, calls=[rec])])
    assert board.companies[0].rollup.grade == "Strong"
    assert board.companies[0].calls[0].results[0].hit is True


def test_horizon_result_pending_defaults():
    hr = HorizonResult(horizon=1)
    assert hr.status == "pending" and hr.return_pct is None and hr.hit is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_schema.py -q`
Expected: FAIL with `ImportError: cannot import name 'EvaluationConfig'`.

- [ ] **Step 3: Add the models**

In `backend/app/models/schemas.py`, add these classes immediately **after** the `AnalysisResult` class (after line 203, before `class ProviderConfig`):

```python
class HorizonResult(BaseModel):
    horizon: int
    status: Literal["pending", "final"] = "pending"
    eval_date: Optional[str] = None
    return_pct: Optional[float] = None
    hit: Optional[bool] = None
    score: Optional[float] = None


class PredictionRecord(BaseModel):
    ticker: str
    call_date: str
    provider: str = ""
    model: str = ""
    recommendation: Literal["buy", "sell", "hold"]
    confidence: float = 0.0
    sentiment: Literal["bullish", "neutral", "bearish"] = "neutral"
    entry_price: float
    results: list[HorizonResult] = Field(default_factory=list)


class CompanyRollup(BaseModel):
    ticker: str
    n_calls: int = 0
    n_matured: int = 0
    hit_rate: Optional[float] = None
    avg_score: Optional[float] = None
    grade: Optional[Literal["Strong", "Mixed", "Weak"]] = None
    overconfident: bool = False
    latest_recommendation: Optional[Literal["buy", "sell", "hold"]] = None
    latest_call_date: Optional[str] = None


class CompanyEvaluation(BaseModel):
    rollup: CompanyRollup
    calls: list[PredictionRecord] = Field(default_factory=list)


class EvaluationBoard(BaseModel):
    as_of: str = ""
    companies: list[CompanyEvaluation] = Field(default_factory=list)
```

In the same file, add this config class immediately **after** `class NetworkConfig` (after line 163, before `class StockData`):

```python
class EvaluationConfig(BaseModel):
    enabled: bool = True
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 20])
    hold_band_pct: float = 2.0     # |return %| <= this counts as "flat" (the hold target)
    score_scale_pct: float = 5.0   # the move size (in %) that maps to a full 0 or 100 score
```

Then add the field to `Settings` (after the `network:` line, currently line 297):

```python
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_schema.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_evaluation_schema.py
git commit -m "feat(evaluation): add EvaluationConfig, response models, Settings.evaluation"
```

---

## Task 2: PredictionStore (two tables + dataclasses)

**Files:**
- Create: `backend/app/evaluation/__init__.py`
- Create: `backend/app/evaluation/store.py`
- Test: `backend/tests/test_evaluation_store.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_store.py`:

```python
from app.evaluation.store import PredictionStore


def _store(tmp_path):
    return PredictionStore(str(tmp_path / "p.db"))


def test_upsert_and_get(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="aapl", call_date="2026-06-05", provider="anthropic",
                        model="m", recommendation="buy", confidence=0.8,
                        sentiment="bullish", entry_price=200.0)
    row = s.get_prediction("AAPL", "2026-06-05")
    assert row is not None
    assert row.ticker == "AAPL" and row.recommendation == "buy" and row.entry_price == 200.0


def test_upsert_replaces_latest_wins(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="sell", confidence=0.6, sentiment="bearish", entry_price=200.0)
    assert len(s.all_predictions()) == 1
    assert s.get_prediction("AAPL", "2026-06-05").recommendation == "sell"


def test_changing_entry_price_clears_child_evals(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0)
    assert s.has_eval("AAPL", "2026-06-05", 1) is True
    # Re-record with a different entry price -> stale evals are dropped
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=201.0)
    assert s.has_eval("AAPL", "2026-06-05", 1) is False


def test_record_and_read_evals(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.record_eval("AAPL", "2026-06-05", 5, "2026-06-12", 206.0, 3.0, 1, 80.0)
    evals = s.evals_for("AAPL", "2026-06-05")
    assert len(evals) == 1 and evals[0].horizon == 5 and evals[0].score == 80.0
    assert len(s.all_evals()) == 1


def test_delete_ticker_removes_rows(tmp_path):
    s = _store(tmp_path)
    s.upsert_prediction(ticker="AAPL", call_date="2026-06-05", provider="a", model="m",
                        recommendation="buy", confidence=0.8, sentiment="bullish", entry_price=200.0)
    s.record_eval("AAPL", "2026-06-05", 1, "2026-06-06", 210.0, 5.0, 1, 100.0)
    deleted = s.delete_ticker("aapl")
    assert deleted == 1
    assert s.all_predictions() == [] and s.all_evals() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation'`.

- [ ] **Step 3: Create the package + store**

Create `backend/app/evaluation/__init__.py` (empty file):

```python
```

Create `backend/app/evaluation/store.py`:

```python
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Optional


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


class PredictionStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS predictions ("
            "ticker TEXT, call_date TEXT, provider TEXT, model TEXT, recommendation TEXT, "
            "confidence REAL, sentiment TEXT, entry_price REAL, created_at REAL, "
            "PRIMARY KEY (ticker, call_date))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS prediction_evals ("
            "ticker TEXT, call_date TEXT, horizon INTEGER, eval_date TEXT, exit_price REAL, "
            "return_pct REAL, hit INTEGER, score REAL, "
            "PRIMARY KEY (ticker, call_date, horizon))"
        )
        self._conn.commit()

    def upsert_prediction(self, *, ticker: str, call_date: str, provider: str, model: str,
                          recommendation: str, confidence: float, sentiment: str,
                          entry_price: float) -> None:
        ticker = ticker.upper().strip()
        existing = self._conn.execute(
            "SELECT entry_price FROM predictions WHERE ticker = ? AND call_date = ?",
            (ticker, call_date),
        ).fetchone()
        if existing is not None and existing[0] != entry_price:
            self._conn.execute(
                "DELETE FROM prediction_evals WHERE ticker = ? AND call_date = ?",
                (ticker, call_date),
            )
        self._conn.execute(
            "INSERT OR REPLACE INTO predictions "
            "(ticker, call_date, provider, model, recommendation, confidence, sentiment, "
            "entry_price, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, call_date, provider, model, recommendation, confidence, sentiment,
             entry_price, time.time()),
        )
        self._conn.commit()

    def get_prediction(self, ticker: str, call_date: str) -> Optional[PredictionRow]:
        row = self._conn.execute(
            "SELECT ticker, call_date, provider, model, recommendation, confidence, sentiment, "
            "entry_price, created_at FROM predictions WHERE ticker = ? AND call_date = ?",
            (ticker.upper().strip(), call_date),
        ).fetchone()
        return PredictionRow(*row) if row else None

    def all_predictions(self) -> list[PredictionRow]:
        rows = self._conn.execute(
            "SELECT ticker, call_date, provider, model, recommendation, confidence, sentiment, "
            "entry_price, created_at FROM predictions"
        ).fetchall()
        return [PredictionRow(*r) for r in rows]

    def has_eval(self, ticker: str, call_date: str, horizon: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM prediction_evals WHERE ticker = ? AND call_date = ? AND horizon = ?",
            (ticker.upper().strip(), call_date, horizon),
        ).fetchone()
        return row is not None

    def record_eval(self, ticker: str, call_date: str, horizon: int, eval_date: str,
                    exit_price: float, return_pct: float, hit: int, score: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO prediction_evals "
            "(ticker, call_date, horizon, eval_date, exit_price, return_pct, hit, score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker.upper().strip(), call_date, horizon, eval_date, exit_price, return_pct,
             int(hit), score),
        )
        self._conn.commit()

    def evals_for(self, ticker: str, call_date: str) -> list[EvalRow]:
        rows = self._conn.execute(
            "SELECT ticker, call_date, horizon, eval_date, exit_price, return_pct, hit, score "
            "FROM prediction_evals WHERE ticker = ? AND call_date = ?",
            (ticker.upper().strip(), call_date),
        ).fetchall()
        return [EvalRow(*r) for r in rows]

    def all_evals(self) -> list[EvalRow]:
        rows = self._conn.execute(
            "SELECT ticker, call_date, horizon, eval_date, exit_price, return_pct, hit, score "
            "FROM prediction_evals"
        ).fetchall()
        return [EvalRow(*r) for r in rows]

    def delete_ticker(self, ticker: str) -> int:
        ticker = ticker.upper().strip()
        cur = self._conn.execute("DELETE FROM predictions WHERE ticker = ?", (ticker,))
        self._conn.execute("DELETE FROM prediction_evals WHERE ticker = ?", (ticker,))
        self._conn.commit()
        return cur.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_store.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/__init__.py backend/app/evaluation/store.py backend/tests/test_evaluation_store.py
git commit -m "feat(evaluation): add PredictionStore with predictions + prediction_evals tables"
```

---

## Task 3: Scoring (pure functions)

**Files:**
- Create: `backend/app/evaluation/scoring.py`
- Test: `backend/tests/test_evaluation_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_scoring.py`:

```python
from app.evaluation.scoring import grade_for, is_hit, is_overconfident, score_call

BAND = 2.0   # hold_band_pct
SCALE = 5.0  # score_scale_pct


def test_is_hit_directional():
    assert is_hit("buy", 3.0, BAND) is True
    assert is_hit("buy", -3.0, BAND) is False
    assert is_hit("sell", -3.0, BAND) is True
    assert is_hit("sell", 3.0, BAND) is False


def test_is_hit_hold_band():
    assert is_hit("hold", 1.0, BAND) is True
    assert is_hit("hold", 2.0, BAND) is True     # edge counts as a hit
    assert is_hit("hold", 3.0, BAND) is False


def test_score_directional_maps_neutral_full_and_zero():
    assert score_call("buy", 0.0, BAND, SCALE) == 50.0
    assert score_call("buy", 5.0, BAND, SCALE) == 100.0    # correct move of one scale -> 100
    assert score_call("buy", -5.0, BAND, SCALE) == 0.0     # wrong move of one scale -> 0
    assert score_call("sell", -5.0, BAND, SCALE) == 100.0
    assert score_call("buy", 50.0, BAND, SCALE) == 100.0   # clamped


def test_score_hold_rewards_flat():
    assert score_call("hold", 0.0, BAND, SCALE) == 100.0
    assert score_call("hold", 2.0, BAND, SCALE) == 50.0    # at the band edge
    assert score_call("hold", 4.0, BAND, SCALE) == 0.0


def test_grade_thresholds():
    assert grade_for(75.0) == "Strong"
    assert grade_for(60.0) == "Strong"
    assert grade_for(50.0) == "Mixed"
    assert grade_for(40.0) == "Weak"
    assert grade_for(10.0) == "Weak"


def test_overconfident_flag():
    # misses are on average MORE confident than hits -> overconfident
    assert is_overconfident([0.5], [0.9]) is True
    assert is_overconfident([0.9], [0.5]) is False
    assert is_overconfident([], [0.9]) is False   # needs at least one of each
    assert is_overconfident([0.5], []) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_scoring.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation.scoring'`.

- [ ] **Step 3: Implement scoring**

Create `backend/app/evaluation/scoring.py`:

```python
from __future__ import annotations

from typing import Literal

GRADE_STRONG_MIN = 60.0
GRADE_WEAK_MAX = 40.0


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def is_hit(recommendation: str, return_pct: float, hold_band_pct: float) -> bool:
    """buy is right if price rose, sell if it fell, hold if it stayed within the band."""
    if recommendation == "buy":
        return return_pct > 0
    if recommendation == "sell":
        return return_pct < 0
    return abs(return_pct) <= hold_band_pct


def score_call(recommendation: str, return_pct: float, hold_band_pct: float,
               score_scale_pct: float) -> float:
    """0..100, magnitude-aware. 50 = neutral / at the hit boundary."""
    if recommendation == "hold":
        band = hold_band_pct if hold_band_pct > 0 else 1e-9
        closeness = (band - abs(return_pct)) / band
        return _clamp(50.0 + 50.0 * closeness)
    scale = score_scale_pct if score_scale_pct > 0 else 1e-9
    direction = 1.0 if recommendation == "buy" else -1.0
    aligned = direction * return_pct
    return _clamp(50.0 + 50.0 * (aligned / scale))


def grade_for(avg_score: float) -> Literal["Strong", "Mixed", "Weak"]:
    if avg_score >= GRADE_STRONG_MIN:
        return "Strong"
    if avg_score <= GRADE_WEAK_MAX:
        return "Weak"
    return "Mixed"


def is_overconfident(hit_confs: list[float], miss_confs: list[float]) -> bool:
    """True when, on average, missed calls were at least as confident as correct ones."""
    if not hit_confs or not miss_confs:
        return False
    return (sum(miss_confs) / len(miss_confs)) >= (sum(hit_confs) / len(hit_confs))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_scoring.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/scoring.py backend/tests/test_evaluation_scoring.py
git commit -m "feat(evaluation): add pure scoring (hit, score, grade, calibration)"
```

---

## Task 4: `fetch_close_series` price helper

**Files:**
- Modify: `backend/app/data/market.py`
- Test: `backend/tests/test_market.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_market.py`:

```python
def test_fetch_close_series_returns_ordered_pairs(monkeypatch):
    import pandas as pd
    from app.data import market

    df = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
    )
    monkeypatch.setattr(market, "fetch_history", lambda ticker, period="2y": df)

    series = market.fetch_close_series("AAPL", "1y")
    assert series == [("2026-06-01", 100.0), ("2026-06-02", 101.0), ("2026-06-03", 102.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_market.py::test_fetch_close_series_returns_ordered_pairs -q`
Expected: FAIL with `AttributeError: module 'app.data.market' has no attribute 'fetch_close_series'`.

- [ ] **Step 3: Implement the helper**

In `backend/app/data/market.py`, add this function immediately after `fetch_history` (after line 12):

```python
def fetch_close_series(ticker: str, period: str = "2y") -> list[tuple[str, float]]:
    """Ordered (YYYY-MM-DD, close) pairs for the period — trading days only."""
    df = fetch_history(ticker, period)
    closes = df["Close"].astype("float64")
    return [(pd.Timestamp(ts).strftime("%Y-%m-%d"), float(v)) for ts, v in closes.items()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_market.py -q`
Expected: PASS (all market tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market.py
git commit -m "feat(evaluation): add fetch_close_series price helper"
```

---

## Task 5: `record_prediction` + capture wiring (deps + run_analysis)

**Files:**
- Create: `backend/app/evaluation/service.py` (first function only)
- Modify: `backend/app/deps.py`
- Modify: `backend/app/services/analysis_service.py`
- Test: `backend/tests/test_evaluation_record.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_record.py`:

```python
from app.config.cache import Cache
from app.evaluation.service import record_prediction
from app.evaluation.store import PredictionStore
from app.models.schemas import (
    AnalysisResult,
    Candle,
    Fundamentals,
    Indicators,
    PriceSummary,
    Settings,
    StockData,
)
from app.services import analysis_service


def _stock_with_candles():
    return StockData(
        ticker="AAPL", company_name="Apple Inc.", as_of="2026-06-07T00:00:00Z",
        price=PriceSummary(current=205.0, change=1.0, change_pct=0.5),
        candles=[
            Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
            Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
        ],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def _result():
    return AnalysisResult(
        ticker="AAPL", provider="anthropic", model="m", generated_at="t",
        overall_summary="", news_analysis="", sentiment="bullish",
        current_recommendation="buy", confidence=0.8,
    )


def test_record_prediction_uses_last_candle(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    record_prediction(_stock_with_candles(), _result(), store)
    row = store.get_prediction("AAPL", "2026-06-05")
    assert row is not None
    assert row.call_date == "2026-06-05" and row.entry_price == 204.0
    assert row.recommendation == "buy" and row.confidence == 0.8


def test_record_prediction_no_candles_is_noop(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    stock = _stock_with_candles()
    stock.candles = []
    record_prediction(stock, _result(), store)
    assert store.all_predictions() == []


def test_run_analysis_records_when_store_passed(tmp_path, monkeypatch):
    settings = Settings()
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())

    class FakeProvider:
        name = "fake"
        def complete(self, system, user):
            import json
            return json.dumps({"overall_summary": "ok", "news_analysis": "ok",
                               "sentiment": "bullish", "current_recommendation": "buy",
                               "confidence": 0.8, "signals": [], "risks": []})

    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))

    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)
    assert store.get_prediction("AAPL", "2026-06-05") is not None


def test_run_analysis_skips_recording_when_disabled(tmp_path, monkeypatch):
    settings = Settings()
    settings.evaluation.enabled = False
    settings.providers["anthropic"].api_key = "k"
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock_with_candles())

    class FakeProvider:
        name = "fake"
        def complete(self, system, user):
            import json
            return json.dumps({"overall_summary": "ok", "news_analysis": "ok",
                               "sentiment": "bullish", "current_recommendation": "buy",
                               "confidence": 0.8, "signals": [], "risks": []})

    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))

    analysis_service.run_analysis("AAPL", "2y", settings, cache, store)
    assert store.all_predictions() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_record.py -q`
Expected: FAIL with `ImportError: cannot import name 'record_prediction' from 'app.evaluation.service'` (module does not exist yet).

- [ ] **Step 3: Create the service with `record_prediction`**

Create `backend/app/evaluation/service.py`:

```python
from __future__ import annotations

import logging

from app.evaluation.store import PredictionStore
from app.models.schemas import AnalysisResult, StockData

logger = logging.getLogger("evaluation")


def record_prediction(stock: StockData, result: AnalysisResult, store: PredictionStore) -> None:
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
    )
```

- [ ] **Step 4: Add the deps singleton**

In `backend/app/deps.py`, add the import and the singleton (after `get_settings_store`):

```python
from app.evaluation.store import PredictionStore
```

```python
@lru_cache
def get_prediction_store() -> PredictionStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return PredictionStore(DB_PATH)
```

- [ ] **Step 5: Wire recording into `run_analysis`**

In `backend/app/services/analysis_service.py`:

Add near the top imports (after the existing imports, around line 15):

```python
import logging

from app.evaluation.service import record_prediction
from app.evaluation.store import PredictionStore

logger = logging.getLogger("analysis")
```

Change the `run_analysis` signature (line 20) to add the optional store:

```python
def run_analysis(
    ticker: str,
    period: str,
    settings: Settings,
    cache: Cache,
    prediction_store: PredictionStore | None = None,
) -> AnalysisResult:
```

Replace the final two lines of the function (currently lines 60-61):

```python
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    return result
```

with:

```python
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    if prediction_store is not None and settings.evaluation.enabled:
        try:
            record_prediction(stock, result, prediction_store)
        except Exception:  # noqa: BLE001 — recording must never break analysis
            logger.warning("prediction recording failed for %s", ticker)
    return result
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_record.py tests/test_analysis_service.py -q`
Expected: PASS (new tests + the existing analysis_service tests still green — they call `run_analysis` with 4 args, which is valid since `prediction_store` defaults to `None`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/evaluation/service.py backend/app/deps.py backend/app/services/analysis_service.py backend/tests/test_evaluation_record.py
git commit -m "feat(evaluation): record predictions on analyze (run_analysis + deps)"
```

---

## Task 6: `evaluate_pending` (maturity + scoring loop)

**Files:**
- Modify: `backend/app/evaluation/service.py`
- Test: `backend/tests/test_evaluation_evaluate.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_evaluate.py`:

```python
from app.evaluation import service
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings


def _seed(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0)
    return store


# 6 trading days starting at the call date: +1d and +5d exist, +20d does not yet.
SERIES = [
    ("2026-06-01", 100.0),
    ("2026-06-02", 101.0),  # +1d -> +1.0%
    ("2026-06-03", 102.0),
    ("2026-06-04", 103.0),
    ("2026-06-05", 104.0),
    ("2026-06-08", 106.0),  # +5d -> +6.0%
]


def test_matures_only_available_horizons(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(service, "fetch_close_series", lambda ticker, period="2y": SERIES)
    summary = service.evaluate_pending(store, Settings())
    assert summary["evaluated"] == 2          # 1d and 5d matured
    assert summary["pending"] == 1            # 20d not yet
    assert store.has_eval("AAPL", "2026-06-01", 1) is True
    assert store.has_eval("AAPL", "2026-06-01", 5) is True
    assert store.has_eval("AAPL", "2026-06-01", 20) is False
    e1 = next(e for e in store.evals_for("AAPL", "2026-06-01") if e.horizon == 1)
    assert round(e1.return_pct, 4) == 1.0 and e1.hit == 1


def test_idempotent_on_rerun(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(service, "fetch_close_series", lambda ticker, period="2y": SERIES)
    service.evaluate_pending(store, Settings())
    summary = service.evaluate_pending(store, Settings())
    assert summary["evaluated"] == 0          # nothing new to do
    assert summary["pending"] == 1


def test_dry_run_does_not_persist(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(service, "fetch_close_series", lambda ticker, period="2y": SERIES)
    summary = service.evaluate_pending(store, Settings(), persist=False)
    assert summary["evaluated"] == 2
    assert store.all_evals() == []            # nothing written


def test_fetch_failure_skips_ticker(tmp_path, monkeypatch):
    store = _seed(tmp_path)

    def boom(ticker, period="2y"):
        raise RuntimeError("no network")

    monkeypatch.setattr(service, "fetch_close_series", boom)
    summary = service.evaluate_pending(store, Settings())
    assert summary["evaluated"] == 0 and store.all_evals() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_evaluate.py -q`
Expected: FAIL with `AttributeError: module 'app.evaluation.service' has no attribute 'evaluate_pending'`.

- [ ] **Step 3: Implement `evaluate_pending`**

In `backend/app/evaluation/service.py`, extend the imports at the top:

```python
from app.data.market import fetch_close_series
from app.evaluation.scoring import is_hit, score_call
from app.models.schemas import AnalysisResult, Settings, StockData
```

(The existing `from app.models.schemas import AnalysisResult, StockData` line should be replaced by the line above so all three names are imported.)

Add the module constant under the logger:

```python
EVAL_PERIOD = "2y"
```

Add the function:

```python
def evaluate_pending(store: PredictionStore, settings: Settings, *, persist: bool = True) -> dict:
    """Score every matured-but-unscored horizon. Fetches price history once per ticker,
    only for tickers that still have an unresolved horizon. Idempotent: already-final
    horizons are skipped. A per-ticker fetch failure is logged and retried next run."""
    horizons = settings.evaluation.horizons
    by_ticker: dict[str, list] = {}
    for p in store.all_predictions():
        by_ticker.setdefault(p.ticker, []).append(p)

    summary = {"tickers": 0, "evaluated": 0, "pending": 0}
    for ticker, preds in by_ticker.items():
        missing = [
            (p, h) for p in preds for h in horizons
            if not store.has_eval(p.ticker, p.call_date, h)
        ]
        if not missing:
            continue
        summary["tickers"] += 1
        try:
            series = fetch_close_series(ticker, EVAL_PERIOD)
        except Exception:  # noqa: BLE001
            logger.warning("evaluation: could not fetch history for %s", ticker)
            summary["pending"] += len(missing)
            continue

        dates = [d for d, _ in series]
        close_by_date = dict(series)
        index_of = {d: i for i, d in enumerate(dates)}

        for p, h in missing:
            i = index_of.get(p.call_date)
            if i is None or i + h >= len(dates):
                summary["pending"] += 1
                continue
            exit_date = dates[i + h]
            exit_price = close_by_date[exit_date]
            return_pct = ((exit_price - p.entry_price) / p.entry_price * 100.0
                          if p.entry_price else 0.0)
            hit = is_hit(p.recommendation, return_pct, settings.evaluation.hold_band_pct)
            sc = score_call(p.recommendation, return_pct,
                            settings.evaluation.hold_band_pct, settings.evaluation.score_scale_pct)
            if persist:
                store.record_eval(p.ticker, p.call_date, h, exit_date, exit_price,
                                  return_pct, int(hit), sc)
            summary["evaluated"] += 1
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_evaluate.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/service.py backend/tests/test_evaluation_evaluate.py
git commit -m "feat(evaluation): add evaluate_pending maturity + scoring loop"
```

---

## Task 7: `build_board` (rollups)

**Files:**
- Modify: `backend/app/evaluation/service.py`
- Test: `backend/tests/test_evaluation_board.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_board.py`:

```python
from app.evaluation import service
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings


def test_empty_board(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    board = service.build_board(store, Settings())
    assert board.companies == []


def test_company_rollup_with_mixed_results(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.9, sentiment="bullish",
                            entry_price=100.0)
    # 1d hit (score 90), 5d miss (score 10); 20d still pending (no eval row)
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 104.5, 4.5, 1, 90.0)
    store.record_eval("AAPL", "2026-06-01", 5, "2026-06-08", 96.0, -4.0, 0, 10.0)

    board = service.build_board(store, Settings())
    assert len(board.companies) == 1
    comp = board.companies[0]
    assert comp.rollup.ticker == "AAPL"
    assert comp.rollup.n_calls == 1
    assert comp.rollup.n_matured == 2
    assert comp.rollup.hit_rate == 50.0
    assert comp.rollup.avg_score == 50.0
    assert comp.rollup.grade == "Mixed"
    assert comp.rollup.latest_recommendation == "buy"
    # the call carries three horizon results, one of them pending
    statuses = {r.horizon: r.status for r in comp.calls[0].results}
    assert statuses == {1: "final", 5: "final", 20: "pending"}


def test_rollup_none_until_matured(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="MSFT", call_date="2026-06-06", provider="a", model="m",
                            recommendation="hold", confidence=0.5, sentiment="neutral",
                            entry_price=400.0)
    comp = service.build_board(store, Settings()).companies[0]
    assert comp.rollup.n_matured == 0
    assert comp.rollup.hit_rate is None and comp.rollup.avg_score is None
    assert comp.rollup.grade is None


def test_overconfident_when_misses_more_confident(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    # A confident SELL that was wrong, and a low-confidence BUY that was right.
    store.upsert_prediction(ticker="NVDA", call_date="2026-06-01", provider="a", model="m",
                            recommendation="sell", confidence=0.95, sentiment="bearish",
                            entry_price=100.0)
    store.record_eval("NVDA", "2026-06-01", 1, "2026-06-02", 105.0, 5.0, 0, 0.0)  # miss, conf .95
    store.upsert_prediction(ticker="NVDA", call_date="2026-06-02", provider="a", model="m",
                            recommendation="buy", confidence=0.40, sentiment="bullish",
                            entry_price=105.0)
    store.record_eval("NVDA", "2026-06-02", 1, "2026-06-03", 110.0, 4.76, 1, 95.0)  # hit, conf .40
    comp = service.build_board(store, Settings()).companies[0]
    assert comp.rollup.overconfident is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_board.py -q`
Expected: FAIL with `AttributeError: module 'app.evaluation.service' has no attribute 'build_board'`.

- [ ] **Step 3: Implement `build_board`**

In `backend/app/evaluation/service.py`, extend imports:

```python
from datetime import datetime, timezone

from app.evaluation.scoring import grade_for, is_hit, is_overconfident, score_call
from app.models.schemas import (
    AnalysisResult,
    CompanyEvaluation,
    CompanyRollup,
    EvaluationBoard,
    HorizonResult,
    PredictionRecord,
    Settings,
    StockData,
)
```

(Merge with the existing scoring/schemas imports — the final scoring import line should read `from app.evaluation.scoring import grade_for, is_hit, is_overconfident, score_call`, and the schemas import should include all the names above.)

Add the function:

```python
def build_board(store: PredictionStore, settings: Settings) -> EvaluationBoard:
    horizons = settings.evaluation.horizons
    eval_index = {(e.ticker, e.call_date, e.horizon): e for e in store.all_evals()}

    by_ticker: dict[str, list] = {}
    for p in store.all_predictions():
        by_ticker.setdefault(p.ticker, []).append(p)

    companies: list[CompanyEvaluation] = []
    for ticker, preds in by_ticker.items():
        preds.sort(key=lambda p: p.call_date, reverse=True)  # newest call first
        records: list[PredictionRecord] = []
        scores: list[float] = []
        hit_confs: list[float] = []
        miss_confs: list[float] = []

        for p in preds:
            results: list[HorizonResult] = []
            for h in horizons:
                e = eval_index.get((p.ticker, p.call_date, h))
                if e is None:
                    results.append(HorizonResult(horizon=h, status="pending"))
                    continue
                results.append(HorizonResult(
                    horizon=h, status="final", eval_date=e.eval_date,
                    return_pct=e.return_pct, hit=bool(e.hit), score=e.score,
                ))
                scores.append(e.score)
                (hit_confs if e.hit else miss_confs).append(p.confidence)
            records.append(PredictionRecord(
                ticker=p.ticker, call_date=p.call_date, provider=p.provider, model=p.model,
                recommendation=p.recommendation, confidence=p.confidence, sentiment=p.sentiment,
                entry_price=p.entry_price, results=results,
            ))

        n_matured = len(scores)
        n_hits = len(hit_confs)
        if n_matured:
            hit_rate: float | None = round(n_hits / n_matured * 100.0, 1)
            avg_score: float | None = round(sum(scores) / n_matured, 1)
            grade = grade_for(avg_score)
        else:
            hit_rate = avg_score = grade = None

        rollup = CompanyRollup(
            ticker=ticker, n_calls=len(preds), n_matured=n_matured,
            hit_rate=hit_rate, avg_score=avg_score, grade=grade,
            overconfident=is_overconfident(hit_confs, miss_confs),
            latest_recommendation=preds[0].recommendation, latest_call_date=preds[0].call_date,
        )
        companies.append(CompanyEvaluation(rollup=rollup, calls=records))

    companies.sort(key=lambda c: c.rollup.latest_call_date or "", reverse=True)
    return EvaluationBoard(as_of=datetime.now(timezone.utc).isoformat(), companies=companies)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_board.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/service.py backend/tests/test_evaluation_board.py
git commit -m "feat(evaluation): add build_board company rollups"
```

---

## Task 8: `explain_prediction` (LLM post-mortem, cached)

**Files:**
- Modify: `backend/app/evaluation/service.py`
- Test: `backend/tests/test_evaluation_explain.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_explain.py`:

```python
import pytest

from app.config.cache import Cache
from app.evaluation import service
from app.evaluation.store import PredictionStore
from app.models.schemas import (
    Fundamentals,
    Indicators,
    NewsItem,
    PriceSummary,
    Settings,
    StockData,
)


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return "The call missed an earnings surprise that reversed the trend."


def _seed(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="sell", confidence=0.9, sentiment="bearish",
                            entry_price=100.0)
    store.record_eval("AAPL", "2026-06-01", 1, "2026-06-02", 105.0, 5.0, 0, 0.0)
    return store


def _stock():
    return StockData(
        ticker="AAPL", company_name="Apple Inc.", as_of="t",
        price=PriceSummary(current=105.0, change=0.0, change_pct=0.0),
        candles=[], fundamentals=Fundamentals(), indicators=Indicators(),
        news=[NewsItem(title="Apple beats earnings")],
    )


def test_explain_returns_and_caches(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    cache = Cache(str(tmp_path / "c.db"))
    fake = FakeProvider()
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(service, "build_provider", lambda s: fake)

    text = service.explain_prediction("AAPL", "2026-06-01", Settings(), cache, store)
    assert "earnings" in text and fake.calls == 1

    # Second call is served from cache (provider not invoked again).
    again = service.explain_prediction("AAPL", "2026-06-01", Settings(), cache, store)
    assert again == text and fake.calls == 1


def test_explain_missing_prediction_raises(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    cache = Cache(str(tmp_path / "c.db"))
    with pytest.raises(ValueError):
        service.explain_prediction("ZZZ", "2026-06-01", Settings(), cache, store)


def test_explain_survives_news_fetch_failure(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    cache = Cache(str(tmp_path / "c.db"))
    fake = FakeProvider()

    def boom(*a, **k):
        raise RuntimeError("no data")

    monkeypatch.setattr(service, "get_stock_data", boom)
    monkeypatch.setattr(service, "build_provider", lambda s: fake)
    text = service.explain_prediction("AAPL", "2026-06-01", Settings(), cache, store)
    assert text and fake.calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_explain.py -q`
Expected: FAIL with `AttributeError: module 'app.evaluation.service' has no attribute 'explain_prediction'`.

- [ ] **Step 3: Implement `explain_prediction`**

In `backend/app/evaluation/service.py`, extend imports:

```python
from app.config.cache import Cache
from app.llm.factory import build_provider
from app.services.stock_service import get_stock_data
```

Add the constant under `EVAL_PERIOD`:

```python
EXPLAIN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
```

Add the function:

```python
def explain_prediction(ticker: str, call_date: str, settings: Settings, cache: Cache,
                       store: PredictionStore) -> str:
    """One short LLM post-mortem on why a call was off. Cached so it runs once per call."""
    ticker = ticker.upper().strip()
    pred = store.get_prediction(ticker, call_date)
    if pred is None:
        raise ValueError(f"No tracked prediction for {ticker} on {call_date}")

    key = f"prediction_explain:{ticker}:{call_date}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    evals = sorted(store.evals_for(ticker, call_date), key=lambda e: e.horizon)
    outcome_lines = [
        f"- {e.horizon} trading days later: {e.return_pct:+.2f}% "
        f"({'correct' if e.hit else 'wrong'})"
        for e in evals
    ] or ["- no matured horizons yet"]

    headlines: list[str] = []
    try:
        stock = get_stock_data(ticker, "1y", settings.indicator_params, cache)
        headlines = [n.title for n in stock.news[:8]]
    except Exception:  # noqa: BLE001
        logger.info("explain: news unavailable for %s", ticker)
    news_block = "\n".join(f"- {h}" for h in headlines) or "- (no recent headlines available)"

    system = (
        "You are a trading-analysis reviewer. In 3-4 sentences, explain why a past stock "
        "recommendation turned out to be inaccurate. Be concrete and concise. "
        "Not financial advice."
    )
    user = (
        f"Ticker: {ticker}\n"
        f"Call date: {call_date}\n"
        f"Recommendation: {pred.recommendation.upper()} (confidence {pred.confidence:.0%})\n"
        f"Entry price: {pred.entry_price:.2f}\n"
        "What actually happened:\n" + "\n".join(outcome_lines) + "\n\n"
        "Recent headlines:\n" + news_block + "\n\n"
        "Explain the most likely reasons the call was off, and what signal may have been missed."
    )
    provider = build_provider(settings)
    text = provider.complete(system, user).strip()
    cache.set(key, text, EXPLAIN_TTL_SECONDS)
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_explain.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/service.py backend/tests/test_evaluation_explain.py
git commit -m "feat(evaluation): add on-demand LLM post-mortem (explain_prediction)"
```

---

## Task 9: API endpoints + wire `/analyze`

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_evaluation.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_evaluation.py`:

```python
import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.config.cache import Cache
from app.deps import get_cache, get_prediction_store
from app.evaluation.store import PredictionStore
from app.main import app


@pytest.fixture
def client(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    store = PredictionStore(str(tmp_path / "p.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_prediction_store] = lambda: store
    try:
        yield TestClient(app), cache, store
    finally:
        app.dependency_overrides.pop(get_cache, None)
        app.dependency_overrides.pop(get_prediction_store, None)


def test_get_evaluation_empty(client):
    tc, _, _ = client
    r = tc.get("/api/evaluation")
    assert r.status_code == 200 and r.json()["companies"] == []


def test_get_evaluation_runs_lazy_eval(client, monkeypatch):
    tc, _, store = client
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0)
    monkeypatch.setattr(routes, "evaluate_pending",
                        lambda s, settings: store.record_eval("AAPL", "2026-06-01", 1,
                                                              "2026-06-02", 102.0, 2.0, 1, 70.0))
    r = tc.get("/api/evaluation")
    assert r.status_code == 200
    body = r.json()
    assert body["companies"][0]["rollup"]["ticker"] == "AAPL"
    assert body["companies"][0]["calls"][0]["results"][0]["status"] == "final"


def test_explain_endpoint(client, monkeypatch):
    tc, _, store = client
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="sell", confidence=0.9, sentiment="bearish",
                            entry_price=100.0)
    monkeypatch.setattr(routes, "explain_prediction",
                        lambda ticker, call_date, settings, cache, store: "because reasons")
    r = tc.post("/api/evaluation/AAPL/2026-06-01/explain")
    assert r.status_code == 200 and r.json()["explanation"] == "because reasons"


def test_explain_missing_is_404(client, monkeypatch):
    tc, _, _ = client

    def boom(*a, **k):
        raise ValueError("nope")

    monkeypatch.setattr(routes, "explain_prediction", boom)
    r = tc.post("/api/evaluation/ZZZ/2026-06-01/explain")
    assert r.status_code == 404


def test_delete_tracked(client):
    tc, _, store = client
    store.upsert_prediction(ticker="AAPL", call_date="2026-06-01", provider="a", model="m",
                            recommendation="buy", confidence=0.8, sentiment="bullish",
                            entry_price=100.0)
    r = tc.delete("/api/evaluation/AAPL")
    assert r.status_code == 200 and r.json()["deleted"] == 1
    assert store.all_predictions() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_evaluation.py -q`
Expected: FAIL (404s / import errors — the routes don't exist yet).

- [ ] **Step 3: Add imports to routes.py**

In `backend/app/api/routes.py`, update the `from app.deps import ...` line (line 11) to:

```python
from app.deps import get_cache, get_prediction_store, get_settings_store
```

Add to the schemas import block (inside the `from app.models.schemas import (...)` group, lines 14-23):

```python
    EvaluationBoard,
```

Add these imports after the existing `from app.services...` imports (around line 37):

```python
from app.evaluation.service import build_board, evaluate_pending, explain_prediction
from app.evaluation.store import PredictionStore
```

- [ ] **Step 4: Wire the store into the analyze route**

Replace the `analyze_ticker` function (lines 67-80) with:

```python
@router.post("/analyze/{ticker}", response_model=AnalysisResult)
def analyze_ticker(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> AnalysisResult:
    settings = store.load()
    try:
        return run_analysis(ticker, period, settings, cache, prediction_store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 5: Add the three evaluation endpoints**

Append to the end of `backend/app/api/routes.py`:

```python
@router.get("/evaluation", response_model=EvaluationBoard)
def get_evaluation(
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> EvaluationBoard:
    settings = store.load()
    evaluate_pending(prediction_store, settings)
    return build_board(prediction_store, settings)


@router.post("/evaluation/{ticker}/{call_date}/explain")
def explain_evaluation(
    ticker: str,
    call_date: str,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    settings = store.load()
    try:
        text = explain_prediction(ticker, call_date, settings, cache, prediction_store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"explanation": text}


@router.delete("/evaluation/{ticker}")
def delete_tracked(
    ticker: str,
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    return {"deleted": prediction_store.delete_ticker(ticker)}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_evaluation.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_evaluation.py
git commit -m "feat(evaluation): add /evaluation endpoints and wire analyze recording"
```

---

## Task 10: CLI runner

**Files:**
- Create: `backend/app/evaluation/runner.py`
- Create: `backend/app/evaluation/__main__.py`
- Test: `backend/tests/test_evaluation_runner.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_runner.py`:

```python
from app.evaluation import runner
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings


def test_disabled_returns_early(tmp_path):
    store = PredictionStore(str(tmp_path / "p.db"))
    settings = Settings()
    settings.evaluation.enabled = False
    summary = runner.run_evaluation(store, settings)
    assert summary == {"enabled": False, "tickers": 0, "evaluated": 0, "pending": 0}


def test_enabled_delegates_to_evaluate_pending(tmp_path, monkeypatch):
    store = PredictionStore(str(tmp_path / "p.db"))
    captured = {}

    def fake_eval(s, settings, *, persist=True):
        captured["persist"] = persist
        return {"tickers": 1, "evaluated": 2, "pending": 1}

    monkeypatch.setattr(runner, "evaluate_pending", fake_eval)
    summary = runner.run_evaluation(store, Settings(), dry_run=True)
    assert summary["enabled"] is True and summary["evaluated"] == 2
    assert captured["persist"] is False  # dry-run disables persistence
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation.runner'`.

- [ ] **Step 3: Implement runner + CLI**

Create `backend/app/evaluation/runner.py`:

```python
from __future__ import annotations

import logging

from app.evaluation.service import evaluate_pending
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings

logger = logging.getLogger("evaluation")


def run_evaluation(store: PredictionStore, settings: Settings, dry_run: bool = False) -> dict:
    if not settings.evaluation.enabled:
        logger.info("Evaluation is disabled; nothing to do.")
        return {"enabled": False, "tickers": 0, "evaluated": 0, "pending": 0}
    summary = evaluate_pending(store, settings, persist=not dry_run)
    summary["enabled"] = True
    return summary
```

Create `backend/app/evaluation/__main__.py`:

```python
from __future__ import annotations

import argparse
import logging
import os
import sys

from app.deps import DATA_DIR, get_prediction_store, get_settings_store
from app.evaluation.runner import run_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation",
        description="Score matured LLM recommendations against actual price moves.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute scores without persisting them.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)

    settings = get_settings_store().load()
    store = get_prediction_store()
    summary = run_evaluation(store, settings, dry_run=args.dry_run)
    logging.getLogger("evaluation").info("Done: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_evaluation_runner.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend; .venv\Scripts\python.exe -m pytest -q`
Expected: PASS (all prior tests + the new evaluation tests, ~220 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/evaluation/runner.py backend/app/evaluation/__main__.py backend/tests/test_evaluation_runner.py
git commit -m "feat(evaluation): add python -m app.evaluation CLI runner"
```

---

## Task 11: Frontend types + fix Settings fixtures

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/pages/Dashboard.test.tsx`
- Modify: `frontend/src/hooks/useWatchlist.test.tsx`

- [ ] **Step 1: Add the evaluation types**

In `frontend/src/types.ts`, add after the `AnalysisResult` interface (after line 106):

```typescript
export type Grade = 'Strong' | 'Mixed' | 'Weak';
export interface HorizonResult {
  horizon: number;
  status: 'pending' | 'final';
  eval_date?: string | null;
  return_pct?: number | null;
  hit?: boolean | null;
  score?: number | null;
}
export interface PredictionRecord {
  ticker: string;
  call_date: string;
  provider: string;
  model: string;
  recommendation: Recommendation;
  confidence: number;
  sentiment: Sentiment;
  entry_price: number;
  results: HorizonResult[];
}
export interface CompanyRollup {
  ticker: string;
  n_calls: number;
  n_matured: number;
  hit_rate: number | null;
  avg_score: number | null;
  grade: Grade | null;
  overconfident: boolean;
  latest_recommendation: Recommendation | null;
  latest_call_date: string | null;
}
export interface CompanyEvaluation {
  rollup: CompanyRollup;
  calls: PredictionRecord[];
}
export interface EvaluationBoard {
  as_of: string;
  companies: CompanyEvaluation[];
}
export interface EvaluationConfig {
  enabled: boolean;
  horizons: number[];
  hold_band_pct: number;
  score_scale_pct: number;
}
```

In the `Settings` interface (after the `network: NetworkConfig;` line, line 134), add:

```typescript
  evaluation: EvaluationConfig;
```

- [ ] **Step 2: Update the two Settings test fixtures**

In `frontend/src/pages/Dashboard.test.tsx`, in the `SETTINGS` object, add this line after the `network: { ... }` line (line 36):

```typescript
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
```

In `frontend/src/hooks/useWatchlist.test.tsx`, in the `SETTINGS` object, add the same line after its `network: { ... }` line (line 19):

```typescript
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
```

- [ ] **Step 3: Verify types compile and existing tests pass**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

Run: `cd frontend; npx vitest run src/pages/Dashboard.test.tsx src/hooks/useWatchlist.test.tsx`
Expected: PASS (fixtures now satisfy the `Settings` type).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/pages/Dashboard.test.tsx frontend/src/hooks/useWatchlist.test.tsx
git commit -m "feat(evaluation): add frontend evaluation types + Settings.evaluation"
```

---

## Task 12: API client methods

**Files:**
- Modify: `frontend/src/api/client.ts`

> Note: this repo does not unit-test `client.ts` directly (api is mocked in page/component tests). The gate here is `tsc` + no regressions; behavior is covered by Tasks 14-15.

- [ ] **Step 1: Add the imports**

In `frontend/src/api/client.ts`, add to the type import block (lines 1-12):

```typescript
  EvaluationBoard,
```

- [ ] **Step 2: Add the methods**

In `frontend/src/api/client.ts`, add inside the `api` object, after the `refreshUniverse` method (before the closing `};` at line 80):

```typescript
  getEvaluation: () => http<EvaluationBoard>('/evaluation'),
  explainPrediction: (ticker: string, callDate: string) =>
    http<{ explanation: string }>(
      `/evaluation/${encodeURIComponent(ticker)}/${encodeURIComponent(callDate)}/explain`,
      { method: 'POST' },
    ),
  deleteTracked: (ticker: string) =>
    http<{ deleted: number }>(`/evaluation/${encodeURIComponent(ticker)}`, { method: 'DELETE' }),
```

- [ ] **Step 3: Verify it compiles**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(evaluation): add evaluation API client methods"
```

---

## Task 13: Query hooks

**Files:**
- Modify: `frontend/src/hooks/queries.ts`

> Note: hooks are exercised through the page test (Task 15). Gate here is `tsc` + no regressions.

- [ ] **Step 1: Add the hooks**

In `frontend/src/hooks/queries.ts`, append:

```typescript
export function useEvaluation() {
  return useQuery({ queryKey: ['evaluation'], queryFn: api.getEvaluation });
}

export function useExplainPrediction() {
  return useMutation({
    mutationFn: ({ ticker, callDate }: { ticker: string; callDate: string }) =>
      api.explainPrediction(ticker, callDate),
  });
}

export function useDeleteTracked() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.deleteTracked(ticker),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
  });
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/queries.ts
git commit -m "feat(evaluation): add useEvaluation/useExplainPrediction/useDeleteTracked hooks"
```

---

## Task 14: EvaluationBoard summary component

**Files:**
- Create: `frontend/src/components/EvaluationBoard.tsx`
- Test: `frontend/src/components/EvaluationBoard.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/EvaluationBoard.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { EvaluationBoard } from './EvaluationBoard';
import type { CompanyEvaluation } from '../types';

const COMPANIES: CompanyEvaluation[] = [
  {
    rollup: {
      ticker: 'AAPL', n_calls: 3, n_matured: 6, hit_rate: 66.7, avg_score: 72.0,
      grade: 'Strong', overconfident: false, latest_recommendation: 'buy',
      latest_call_date: '2026-06-05',
    },
    calls: [],
  },
  {
    rollup: {
      ticker: 'TSLA', n_calls: 1, n_matured: 0, hit_rate: null, avg_score: null,
      grade: null, overconfident: false, latest_recommendation: 'sell',
      latest_call_date: '2026-06-06',
    },
    calls: [],
  },
];

describe('EvaluationBoard', () => {
  it('renders a row per company with grade and hit-rate', () => {
    render(<EvaluationBoard companies={COMPANIES} selected={null} onSelect={() => {}} />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('Strong')).toBeInTheDocument();
    expect(screen.getByText('66.7%')).toBeInTheDocument();
  });

  it('shows a dash for companies with no matured calls', () => {
    render(<EvaluationBoard companies={COMPANIES} selected={null} onSelect={() => {}} />);
    // TSLA row has no hit-rate yet
    const cells = screen.getAllByText('—');
    expect(cells.length).toBeGreaterThan(0);
  });

  it('calls onSelect when a row is clicked', () => {
    const onSelect = vi.fn();
    render(<EvaluationBoard companies={COMPANIES} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('AAPL'));
    expect(onSelect).toHaveBeenCalledWith('AAPL');
  });

  it('renders an empty hint when there are no companies', () => {
    render(<EvaluationBoard companies={[]} selected={null} onSelect={() => {}} />);
    expect(screen.getByText(/no tracked calls yet/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend; npx vitest run src/components/EvaluationBoard.test.tsx`
Expected: FAIL — cannot resolve `./EvaluationBoard`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/EvaluationBoard.tsx`:

```tsx
import type { CompanyEvaluation, Grade } from '../types';

const GRADE_CLASS: Record<Grade, string> = { Strong: 'buy', Mixed: 'hold', Weak: 'sell' };

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="score-bar" title={`${score.toFixed(0)} / 100`}>
      <span style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
    </div>
  );
}

export function EvaluationBoard({
  companies,
  selected,
  onSelect,
}: {
  companies: CompanyEvaluation[];
  selected: string | null;
  onSelect: (ticker: string) => void;
}) {
  if (!companies.length) {
    return <p className="muted">No tracked calls yet — analyze a company on the Dashboard to start.</p>;
  }
  return (
    <div className="board-wrap">
      <table className="board">
        <thead>
          <tr>
            <th>Ticker</th><th>Calls</th><th>Scored</th><th>Hit rate</th>
            <th>Avg score</th><th>Grade</th><th>Latest</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((c) => {
            const r = c.rollup;
            return (
              <tr
                key={r.ticker}
                className={`board-row${selected === r.ticker ? ' selected' : ''}`}
                onClick={() => onSelect(r.ticker)}
              >
                <td className="mono">{r.ticker}</td>
                <td className="muted">{r.n_calls}</td>
                <td className="muted">{r.n_matured}</td>
                <td className="mono">{r.hit_rate == null ? '—' : `${r.hit_rate.toFixed(1)}%`}</td>
                <td>
                  {r.avg_score == null ? (
                    <span className="muted">—</span>
                  ) : (
                    <div className="score-cell"><ScoreBar score={r.avg_score} /><span>{r.avg_score.toFixed(0)}</span></div>
                  )}
                </td>
                <td>
                  {r.grade ? (
                    <span className={`badge ${GRADE_CLASS[r.grade]}`}>{r.grade}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                  {r.overconfident && <span className="overconf" title="Missed calls were as confident as correct ones"> ⚠ overconfident</span>}
                </td>
                <td>
                  {r.latest_recommendation && (
                    <span className={`badge ${r.latest_recommendation}`}>{r.latest_recommendation.toUpperCase()}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend; npx vitest run src/components/EvaluationBoard.test.tsx`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EvaluationBoard.tsx frontend/src/components/EvaluationBoard.test.tsx
git commit -m "feat(evaluation): add EvaluationBoard summary table component"
```

---

## Task 15: Evaluation page + route + nav + styles

**Files:**
- Create: `frontend/src/pages/Evaluation.tsx`
- Test: `frontend/src/pages/Evaluation.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/Evaluation.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import Evaluation from './Evaluation';
import type { EvaluationBoard } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getEvaluation: vi.fn(),
    explainPrediction: vi.fn(),
    deleteTracked: vi.fn(),
  },
}));

import { api } from '../api/client';

const BOARD: EvaluationBoard = {
  as_of: '2026-06-07T00:00:00Z',
  companies: [
    {
      rollup: {
        ticker: 'AAPL', n_calls: 1, n_matured: 2, hit_rate: 50.0, avg_score: 45.0,
        grade: 'Mixed', overconfident: true, latest_recommendation: 'sell',
        latest_call_date: '2026-06-01',
      },
      calls: [
        {
          ticker: 'AAPL', call_date: '2026-06-01', provider: 'anthropic', model: 'm',
          recommendation: 'sell', confidence: 0.9, sentiment: 'bearish', entry_price: 100,
          results: [
            { horizon: 1, status: 'final', eval_date: '2026-06-02', return_pct: 5.0, hit: false, score: 0 },
            { horizon: 5, status: 'final', eval_date: '2026-06-08', return_pct: -3.0, hit: true, score: 80 },
            { horizon: 20, status: 'pending' },
          ],
        },
      ],
    },
  ],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Evaluation />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.getEvaluation).mockResolvedValue(BOARD);
  vi.mocked(api.explainPrediction).mockResolvedValue({ explanation: 'Missed an earnings beat.' });
  vi.mocked(api.deleteTracked).mockResolvedValue({ deleted: 1 });
});

describe('Evaluation page', () => {
  it('shows the board and expands a company to reveal calls', async () => {
    renderPage();
    const row = await screen.findByText('AAPL');
    fireEvent.click(row);
    // The call's horizon chips appear once expanded
    expect(await screen.findByText(/1d/)).toBeInTheDocument();
    expect(screen.getByText(/5d/)).toBeInTheDocument();
    expect(screen.getByText(/20d/)).toBeInTheDocument();
  });

  it('runs an LLM post-mortem on a missed call', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('AAPL'));
    const explainBtn = await screen.findByRole('button', { name: /explain miss/i });
    fireEvent.click(explainBtn);
    expect(await screen.findByText(/missed an earnings beat/i)).toBeInTheDocument();
    expect(api.explainPrediction).toHaveBeenCalledWith('AAPL', '2026-06-01');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend; npx vitest run src/pages/Evaluation.test.tsx`
Expected: FAIL — cannot resolve `./Evaluation`.

- [ ] **Step 3: Implement the page**

Create `frontend/src/pages/Evaluation.tsx`:

```tsx
import { useState } from 'react';
import { EvaluationBoard } from '../components/EvaluationBoard';
import { useDeleteTracked, useEvaluation, useExplainPrediction } from '../hooks/queries';
import type { CompanyEvaluation, HorizonResult, PredictionRecord } from '../types';

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

function CompanyDetail({ company }: { company: CompanyEvaluation }) {
  const explain = useExplainPrediction();
  const remove = useDeleteTracked();
  const [openExplain, setOpenExplain] = useState<string | null>(null);
  const [text, setText] = useState<Record<string, string>>({});

  const runExplain = (callDate: string) => {
    setOpenExplain(callDate);
    explain.mutate(
      { ticker: company.rollup.ticker, callDate },
      { onSuccess: (d) => setText((t) => ({ ...t, [callDate]: d.explanation })) },
    );
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="section-label">{company.rollup.ticker} — calls</span>
        <button className="secondary" onClick={() => remove.mutate(company.rollup.ticker)} disabled={remove.isPending}>
          {remove.isPending ? 'Removing…' : 'Stop tracking'}
        </button>
      </div>
      {remove.isError && <p className="error">Couldn't remove: {(remove.error as Error).message}</p>}
      <div className="calls">
        {company.calls.map((call) => (
          <div className="call-row" key={call.call_date}>
            <span className="mono">{call.call_date}</span>
            <span className={`badge ${call.recommendation}`}>{call.recommendation.toUpperCase()}</span>
            <span className="muted">conf {(call.confidence * 100).toFixed(0)}%</span>
            <div className="outcomes">
              {call.results.map((r) => <OutcomeChip key={r.horizon} r={r} />)}
            </div>
            {hasMiss(call) && (
              <button className="secondary" onClick={() => runExplain(call.call_date)}
                      disabled={explain.isPending && openExplain === call.call_date}>
                {explain.isPending && openExplain === call.call_date ? 'Analyzing…' : 'Explain miss'}
              </button>
            )}
            {openExplain === call.call_date && explain.isError && (
              <p className="error">Couldn't explain: {(explain.error as Error).message}</p>
            )}
            {text[call.call_date] && <p className="explain-box">{text[call.call_date]}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Evaluation() {
  const board = useEvaluation();
  const [selected, setSelected] = useState<string | null>(null);

  const companies = board.data?.companies ?? [];
  const current = companies.find((c) => c.rollup.ticker === selected) ?? null;

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <span className="section-label">LLM call accuracy — click a company to see its calls</span>
          {board.data?.as_of && (
            <span className="muted board-asof">As of {new Date(board.data.as_of).toLocaleString()}</span>
          )}
        </div>
        {board.isLoading && <p className="muted">Loading evaluation…</p>}
        {board.isError && <p className="error">Could not load evaluation: {(board.error as Error).message}</p>}
        {board.data && <EvaluationBoard companies={companies} selected={selected} onSelect={setSelected} />}
      </section>
      {current && <CompanyDetail company={current} />}
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend; npx vitest run src/pages/Evaluation.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Add the route + nav link**

In `frontend/src/App.tsx`:

Add the import after the `Settings` import (line 5):

```tsx
import Evaluation from './pages/Evaluation';
```

Add the nav link after the Graph `NavLink` (line 27):

```tsx
            <NavLink to="/evaluation" className={navClass}>Evaluation</NavLink>
```

Add the route after the `/graph` route (line 36):

```tsx
            <Route path="/evaluation" element={<Evaluation />} />
```

- [ ] **Step 6: Add styles**

Append to `frontend/src/styles.css`:

```css
/* --- Evaluation page --- */
.board-row.selected { background: var(--gold-tint); }
.calls { display: flex; flex-direction: column; gap: 4px; }
.call-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 9px 0; border-bottom: 1px solid var(--hairline); }
.call-row:last-child { border-bottom: 0; }
.outcomes { display: flex; gap: 6px; flex-wrap: wrap; }
.outcome {
  font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.02em;
  border: 1px solid var(--panel-brd); border-radius: 999px; padding: 2px 9px; white-space: nowrap;
}
.outcome.hit { color: var(--buy); background: var(--buy-tint); border-color: rgba(95, 211, 155, 0.3); }
.outcome.miss { color: var(--sell); background: var(--sell-tint); border-color: rgba(240, 129, 124, 0.3); }
.outcome.pending { color: var(--ink-faint); }
.overconf { font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: #cf6f6a; }
.explain-box { flex-basis: 100%; margin: 4px 0 0; color: var(--ink-soft); font-size: 13px; line-height: 1.5; }
```

- [ ] **Step 7: Verify build + types + page test**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

Run: `cd frontend; npx vitest run src/pages/Evaluation.test.tsx src/pages/Dashboard.test.tsx`
Expected: PASS (the new page test + the App-level Dashboard test, which now also mounts the Evaluation route definition without error).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/Evaluation.tsx frontend/src/pages/Evaluation.test.tsx frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat(evaluation): add Evaluation page, route, nav, and styles"
```

---

## Task 16: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run: `cd backend; .venv\Scripts\python.exe -m pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 2: Frontend types**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Frontend tests**

Run: `cd frontend; npx vitest run`
Expected: PASS (all suites, including the new EvaluationBoard + Evaluation tests).

- [ ] **Step 4: Frontend build**

Run: `cd frontend; npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 5: Smoke the CLI (optional, no network needed for the disabled path)**

Run: `cd backend; .venv\Scripts\python.exe -m app.evaluation --dry-run`
Expected: logs a `Done: {...}` summary line and exits 0 (it will fetch live prices for any tracked tickers; with none tracked it does nothing).

- [ ] **Step 6: Finish the branch**

Use superpowers:finishing-a-development-branch to present completion options (merge locally / PR / keep / discard).

---

## Notes for the implementer

- **No circular imports:** `app.evaluation.service` imports `store`, `scoring`, `data.market`, `llm.factory`, `services.stock_service`, `config.cache`, `models.schemas` — none of which import `app.evaluation`. `app.services.analysis_service` importing `app.evaluation.service` is therefore safe.
- **Recording happens only via the `/analyze` route**, which is the only caller that passes a `prediction_store`. The alerts runner calls `run_analysis` without a store (its `_reasoning` helper), so alerts never record predictions.
- **`call_date` is the last candle date** (a real trading day), not `StockData.as_of` (which is a UTC timestamp). Horizons are trading-day offsets into the candle/close series, so weekends and holidays are handled implicitly.
- **Verdicts are final once stored.** `evaluate_pending` only computes horizons with no existing eval row, so re-running (lazy on every page load, or via CLI) never recomputes or drifts a settled verdict.
- **Degrade-safe everywhere:** recording is wrapped in try/except; per-ticker price fetches in `evaluate_pending` are isolated; news fetch in `explain_prediction` is optional.
```
