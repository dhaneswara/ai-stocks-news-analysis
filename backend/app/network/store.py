"""Persist knowledge graphs in the existing Cache (SQLite KV).

Namespaces:
- `graph_snapshot:<scope>`   — the auto/daily focus snapshot (7-day TTL), unchanged.
- `graph_user_saved:<ROOT>`  — user-saved explored subgraphs (≈10y TTL, history capped to 5).
- `graph_imported:<id>`      — imported external-ontology overlay sets (≈10y TTL, keyed by created_at).
- `graph_imported:__index__` — the overlay index (list of set ids).
"""
from __future__ import annotations

import json

from app.config.cache import Cache
from app.models.schemas import ImportSetSummary, KnowledgeGraph, SavedGraphSummary, SavedGraphVersion

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


# --- imported overlay (external ontology models) ----------------------------------------------

_IMPORT_TTL_SECONDS = _USER_SAVE_TTL_SECONDS  # ~10y; survives rebuilds and the daily job
_IMPORT_INDEX_KEY = "graph_imported:__index__"


def _imported_key(set_id: str) -> str:
    return f"graph_imported:{set_id}"


def merge_graphs(a: KnowledgeGraph, b: KnowledgeGraph) -> KnowledgeGraph:
    """Union two graphs: nodes unioned, edges deduped by (source,target,type), node_meta merged
    (b wins on key clash). Returns a copy of `a` with the merged fields (keeps a's scope/as_of)."""
    nodes = sorted(set(a.nodes) | set(b.nodes))
    seen = {(e.source, e.target, e.type) for e in a.edges}
    edges = list(a.edges)
    for e in b.edges:
        k = (e.source, e.target, e.type)
        if k not in seen:
            seen.add(k)
            edges.append(e)
    node_meta = {**a.node_meta, **b.node_meta}
    return a.model_copy(update={"nodes": nodes, "edges": edges, "node_meta": node_meta})


def _load_import_index(cache: Cache) -> list[str]:
    raw = cache.get(_IMPORT_INDEX_KEY)
    try:
        return json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 — corrupt index -> empty
        return []


def _save_import_index(ids: list[str], cache: Cache) -> None:
    cache.set(_IMPORT_INDEX_KEY, json.dumps(ids), _IMPORT_TTL_SECONDS)


def add_import_set(name: str, graph: KnowledgeGraph, cache: Cache, *, created_at: str) -> ImportSetSummary:
    summary = ImportSetSummary(
        id=created_at, name=name or "", as_of=graph.as_of, created_at=created_at,
        node_count=len(graph.nodes), edge_count=len(graph.edges),
    )
    cache.set(
        _imported_key(created_at),
        json.dumps({"summary": summary.model_dump(), "graph": graph.model_dump()}),
        _IMPORT_TTL_SECONDS,
    )
    idx = _load_import_index(cache)
    if created_at not in idx:
        idx.append(created_at)
        _save_import_index(idx, cache)
    return summary


def _load_import_set(set_id: str, cache: Cache) -> tuple[ImportSetSummary, KnowledgeGraph] | None:
    raw = cache.get(_imported_key(set_id))
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return (
            ImportSetSummary.model_validate(obj["summary"]),
            KnowledgeGraph.model_validate(obj["graph"]),
        )
    except Exception:  # noqa: BLE001 — corrupt entry -> skip
        return None


def list_import_sets(cache: Cache) -> list[ImportSetSummary]:
    out: list[ImportSetSummary] = []
    for sid in _load_import_index(cache):
        loaded = _load_import_set(sid, cache)
        if loaded:
            out.append(loaded[0])
    return out


def delete_import_set(set_id: str, cache: Cache) -> bool:
    idx = _load_import_index(cache)
    if set_id not in idx:
        return False
    cache.set(_imported_key(set_id), "", 1)  # Cache has no delete; empty value -> treated as absent
    _save_import_index([s for s in idx if s != set_id], cache)
    return True


def load_overlay(cache: Cache) -> KnowledgeGraph:
    overlay = KnowledgeGraph(scope="imported")
    for sid in _load_import_index(cache):
        loaded = _load_import_set(sid, cache)
        if loaded:
            overlay = merge_graphs(overlay, loaded[1])
    return overlay


def effective_graph(cache: Cache, scope: str = "focus") -> KnowledgeGraph:
    """The graph scoring/display should consume: the saved snapshot unioned with the overlay.
    The saved snapshot itself is never mutated, so rebuilds stay idempotent."""
    base = load_graph(cache, scope)
    overlay = load_overlay(cache)
    if base is None:
        return overlay
    if not overlay.edges and not overlay.nodes:
        return base
    return merge_graphs(base, overlay)
