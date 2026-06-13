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
