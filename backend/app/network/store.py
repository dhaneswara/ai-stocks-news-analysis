"""Persist the latest knowledge graph in the existing Cache (SQLite KV), keyed
`graph_snapshot:<scope>` with a long TTL — mirrors `screener/store.py`."""
from __future__ import annotations

from app.config.cache import Cache
from app.models.schemas import KnowledgeGraph

_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _key(scope: str) -> str:
    return f"graph_snapshot:{scope}"


def save_graph(graph: KnowledgeGraph, cache: Cache) -> None:
    cache.set(_key(graph.scope), graph.model_dump_json(), _SNAPSHOT_TTL_SECONDS)


def load_graph(cache: Cache, scope: str = "focus") -> KnowledgeGraph | None:
    raw = cache.get(_key(scope))
    return KnowledgeGraph.model_validate_json(raw) if raw else None
