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
