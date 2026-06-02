from __future__ import annotations

import sqlite3
import time


class AlertState:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS alert_log "
            "(ticker TEXT, rule_id TEXT, candle_date TEXT, sent_at REAL, "
            "PRIMARY KEY (ticker, rule_id, candle_date))"
        )
        self._conn.commit()

    def was_alerted(self, ticker: str, rule_id: str, candle_date: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alert_log WHERE ticker = ? AND rule_id = ? AND candle_date = ?",
            (ticker, rule_id, candle_date),
        ).fetchone()
        return row is not None

    def mark(self, ticker: str, rule_id: str, candle_date: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO alert_log (ticker, rule_id, candle_date, sent_at) VALUES (?, ?, ?, ?)",
            (ticker, rule_id, candle_date, time.time()),
        )
        self._conn.commit()
