from __future__ import annotations

import os
from functools import lru_cache

from app.analysis.trace_store import AgentTraceStore
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.evaluation.store import PredictionStore
from app.services.analysis_snapshot_store import AnalysisSnapshotStore

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


@lru_cache
def get_trace_store() -> AgentTraceStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return AgentTraceStore(DB_PATH)


@lru_cache
def get_analysis_snapshot_store() -> AnalysisSnapshotStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return AnalysisSnapshotStore(os.path.join(DATA_DIR, "analysis_snapshots.db"))
