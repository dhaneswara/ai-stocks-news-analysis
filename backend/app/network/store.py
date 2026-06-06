"""Persist knowledge graphs in the existing Cache (SQLite KV).

Two namespaces:
- `graph_snapshot:<scope>`  — the auto/daily focus snapshot (7-day TTL), unchanged.
- `graph_user_saved:<ROOT>` — user-saved explored subgraphs (≈10y TTL, history capped to 5).
"""
from __future__ import annotations

import json

from app.config.cache import Cache
from app.models.schemas import KnowledgeGraph, SavedGraphSummary, SavedGraphVersion

_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
_USER_SAVE_TTL_SECONDS = 3650 * 24 * 60 * 60  # ~10 years (effectively permanent)
_MAX_VERSIONS = 5
_INDEX_KEY = "graph_user_saved:__index__"


def _key(scope: str) -> str:
    return f"graph_snapshot:{scope}"


def save_graph(graph: KnowledgeGraph, cache: Cache) -> None:
    cache.set(_key(graph.scope), graph.model_dump_json(), _SNAPSHOT_TTL_SECONDS)


def load_graph(cache: Cache, scope: str = "focus") -> KnowledgeGraph | None:
    raw = cache.get(_key(scope))
    return KnowledgeGraph.model_validate_json(raw) if raw else None


def _saved_key(root: str) -> str:
    return f"graph_user_saved:{root.upper().strip()}"


def _load_index(cache: Cache) -> list[str]:
    raw = cache.get(_INDEX_KEY)
    try:
        return json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 — corrupt index -> empty
        return []


def _save_index(roots: list[str], cache: Cache) -> None:
    cache.set(_INDEX_KEY, json.dumps(roots), _USER_SAVE_TTL_SECONDS)


def _load_versions(root: str, cache: Cache) -> list[SavedGraphVersion]:
    raw = cache.get(_saved_key(root))
    if not raw:
        return []
    try:
        return [SavedGraphVersion.model_validate(v) for v in json.loads(raw)]
    except Exception:  # noqa: BLE001 — corrupt entry -> none
        return []


def _store_versions(root: str, versions: list[SavedGraphVersion], cache: Cache) -> None:
    cache.set(_saved_key(root), json.dumps([v.model_dump() for v in versions]), _USER_SAVE_TTL_SECONDS)


def save_company_graph(version: SavedGraphVersion, cache: Cache) -> SavedGraphVersion:
    root = version.root.upper().strip()
    version = version.model_copy(update={"root": root})
    versions = ([version] + _load_versions(root, cache))[:_MAX_VERSIONS]  # newest first, capped
    _store_versions(root, versions, cache)
    idx = _load_index(cache)
    if root not in idx:
        idx.append(root)
        _save_index(idx, cache)
    return version


def load_company_graph(root: str, cache: Cache, version: str | None = None) -> SavedGraphVersion | None:
    versions = _load_versions(root, cache)
    if not versions:
        return None
    if version is None:
        return versions[0]  # latest
    return next((v for v in versions if v.saved_at == version), None)


def list_saved_graphs(cache: Cache) -> list[SavedGraphSummary]:
    out: list[SavedGraphSummary] = []
    for root in _load_index(cache):
        versions = _load_versions(root, cache)
        if versions:
            out.append(SavedGraphSummary(root=root, versions=[v.saved_at for v in versions]))
    return out


def delete_saved_graph(root: str, cache: Cache, version: str | None = None) -> bool:
    root = root.upper().strip()
    versions = _load_versions(root, cache)
    if not versions:
        return False
    if version is None:
        remaining: list[SavedGraphVersion] = []
    else:
        remaining = [v for v in versions if v.saved_at != version]
        if len(remaining) == len(versions):
            return False  # version not found
    if remaining:
        _store_versions(root, remaining, cache)
    else:
        _store_versions(root, [], cache)  # Cache has no delete; store empty
        _save_index([r for r in _load_index(cache) if r != root], cache)
    return True
