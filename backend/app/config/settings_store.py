from __future__ import annotations

import copy
import sqlite3
import threading

from app.models.schemas import Settings

MASK = "****"


class SettingsStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        # get_settings_store() is an @lru_cache singleton, so this one connection is
        # shared process-wide across FastAPI's threadpool (check_same_thread=False).
        # sqlite3 connections are not safe under concurrent use, so every access to
        # _conn is serialised through _lock (see app/config/cache.py for details).
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL)"
        )
        self._conn.commit()

    def load(self) -> Settings:
        with self._lock:
            row = self._conn.execute("SELECT json FROM settings WHERE id = 1").fetchone()
        if row is None:
            return Settings()
        return Settings.model_validate_json(row[0])

    def save(self, settings: Settings) -> None:
        payload = settings.model_dump_json()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (id, json) VALUES (1, ?)",
                (payload,),
            )
            self._conn.commit()


def mask_settings(settings: Settings) -> Settings:
    masked = copy.deepcopy(settings)
    for cfg in masked.providers.values():
        if cfg.api_key:
            cfg.api_key = MASK
    if masked.alerts.telegram_bot_token:
        masked.alerts.telegram_bot_token = MASK
    for cfg in masked.news.providers.values():
        if cfg.api_key:
            cfg.api_key = MASK
    return masked


def merge_settings(existing: Settings, incoming: Settings) -> Settings:
    merged = copy.deepcopy(incoming)
    for name, cfg in merged.providers.items():
        if cfg.api_key == MASK:
            cfg.api_key = existing.providers.get(name, type(cfg)()).api_key
    if merged.alerts.telegram_bot_token == MASK:
        merged.alerts.telegram_bot_token = existing.alerts.telegram_bot_token
    for name, cfg in merged.news.providers.items():
        if cfg.api_key == MASK:
            cfg.api_key = existing.news.providers.get(name, type(cfg)()).api_key
    return merged
