from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional


class Cache:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        # get_cache() is an @lru_cache singleton, so this one connection is shared
        # process-wide across FastAPI's threadpool (hence check_same_thread=False).
        # sqlite3 connections are not safe under concurrent use, so every access to
        # _conn is serialised through _lock. Without it, interleaved threads corrupt
        # the shared cursor/transaction state ("bad parameter or other API misuse",
        # "no more rows available", "cannot commit - no transaction is active", ...).
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value, expires_at = row
            if expires_at <= time.time():
                self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                self._conn.commit()
                return None
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, value, expires_at),
            )
            self._conn.commit()
