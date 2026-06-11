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
        # Construction runs before the instance is shared, so these _conn accesses
        # need no lock; all public methods below take _lock.
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

    def clear_all(self) -> dict[str, int]:
        """Start over: wipe every recorded call and verdict across all tickers."""
        with self._lock:
            preds = self._conn.execute("DELETE FROM predictions").rowcount
            evals = self._conn.execute("DELETE FROM prediction_evals").rowcount
            self._conn.commit()
        return {"predictions": preds, "evals": evals}
