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
