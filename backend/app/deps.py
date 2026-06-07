from __future__ import annotations

import os
from functools import lru_cache

from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.evaluation.store import PredictionStore

DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "app.db")


@lru_cache
def get_cache() -> Cache:
    os.makedirs(DATA_DIR, exist_ok=True)
    return Cache(DB_PATH)


@lru_cache
def get_settings_store() -> SettingsStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return SettingsStore(DB_PATH)


@lru_cache
def get_prediction_store() -> PredictionStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return PredictionStore(DB_PATH)
