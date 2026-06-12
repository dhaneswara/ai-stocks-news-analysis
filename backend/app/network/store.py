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
from app.models.schemas import ImportSetSummary, KnowledgeGraph, OntologySummary, OntologyVersion, SavedGraphSummary, SavedGraphVersion

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


def load_import_graph(set_id: str, cache: Cache) -> KnowledgeGraph | None:
    """The graph of one import set, for merging into a working graph; None if unknown."""
    loaded = _load_import_set(set_id, cache)
    return loaded[1] if loaded else None


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


# --- named ontologies (the user-curated graphs behind scoring) ---------------------------------

_ONTOLOGY_INDEX_KEY = "ontology:__index__"
_ONTOLOGY_ACTIVE_KEY = "ontology:__active__"


def _ontology_key(name: str) -> str:
    return f"ontology:{name}"


def _load_ontology_index(cache: Cache) -> list[str]:
    raw = cache.get(_ONTOLOGY_INDEX_KEY)
    try:
        return json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 — corrupt index -> empty
        return []


def _save_ontology_index(names: list[str], cache: Cache) -> None:
    cache.set(_ONTOLOGY_INDEX_KEY, json.dumps(names), _USER_SAVE_TTL_SECONDS)


def canonical_ontology_name(name: str, cache: Cache) -> str | None:
    """The stored spelling of `name`, matched case-insensitively; None when unknown."""
    want = (name or "").strip().lower()
    return next((n for n in _load_ontology_index(cache) if n.lower() == want), None)


def _load_ontology_versions(name: str, cache: Cache) -> list[OntologyVersion]:
    raw = cache.get(_ontology_key(name))
    if not raw:
        return []
    try:
        return [OntologyVersion.model_validate(v) for v in json.loads(raw)]
    except Exception:  # noqa: BLE001 — corrupt entry -> none
        return []


def _store_ontology_versions(name: str, versions: list[OntologyVersion], cache: Cache) -> None:
    cache.set(_ontology_key(name), json.dumps([v.model_dump() for v in versions]),
              _USER_SAVE_TTL_SECONDS)


def save_ontology(version: OntologyVersion, cache: Cache) -> OntologyVersion:
    """Create-or-update under a case-insensitively unique name; newest first, capped at 5."""
    name = canonical_ontology_name(version.name, cache) or version.name.strip()
    version = version.model_copy(update={"name": name})
    versions = ([version] + _load_ontology_versions(name, cache))[:_MAX_VERSIONS]
    _store_ontology_versions(name, versions, cache)
    idx = _load_ontology_index(cache)
    if name not in idx:
        idx.append(name)
        _save_ontology_index(idx, cache)
    return version


def load_ontology(name: str, cache: Cache, version: str | None = None) -> OntologyVersion | None:
    canon = canonical_ontology_name(name, cache)
    if canon is None:
        return None
    versions = _load_ontology_versions(canon, cache)
    if not versions:
        return None
    if version is None:
        return versions[0]  # latest
    return next((v for v in versions if v.saved_at == version), None)


def list_ontologies(cache: Cache) -> list[OntologySummary]:
    active = get_active_ontology(cache)
    out: list[OntologySummary] = []
    for name in _load_ontology_index(cache):
        versions = _load_ontology_versions(name, cache)
        if versions:
            latest = versions[0].graph
            out.append(OntologySummary(
                name=name, versions=[v.saved_at for v in versions],
                node_count=len(latest.nodes), edge_count=len(latest.edges),
                active=name == active,
            ))
    return out


def delete_ontology(name: str, cache: Cache, version: str | None = None) -> bool:
    canon = canonical_ontology_name(name, cache)
    if canon is None:
        return False
    versions = _load_ontology_versions(canon, cache)
    if not versions:
        return False
    remaining = [] if version is None else [v for v in versions if v.saved_at != version]
    if version is not None and len(remaining) == len(versions):
        return False  # version not found
    if remaining:
        _store_ontology_versions(canon, remaining, cache)
    else:
        _store_ontology_versions(canon, [], cache)  # Cache has no delete; store empty
        _save_ontology_index([n for n in _load_ontology_index(cache) if n != canon], cache)
        if get_active_ontology(cache) == canon:
            set_active_ontology(None, cache)        # the master pointer must never dangle
    return True


def get_active_ontology(cache: Cache) -> str | None:
    raw = cache.get(_ONTOLOGY_ACTIVE_KEY)
    return raw or None


def set_active_ontology(name: str | None, cache: Cache) -> bool:
    """Point scoring at `name` (case-insensitive; canonical spelling stored). None clears."""
    if name is None:
        cache.set(_ONTOLOGY_ACTIVE_KEY, "", _USER_SAVE_TTL_SECONDS)
        return True
    canon = canonical_ontology_name(name, cache)
    if canon is None:
        return False
    cache.set(_ONTOLOGY_ACTIVE_KEY, canon, _USER_SAVE_TTL_SECONDS)
    return True


def active_graph(cache: Cache) -> KnowledgeGraph:
    """The graph every scoring path consumes: the active ontology's latest revision, or an
    empty graph when none is active (=> no network signal, by design)."""
    name = get_active_ontology(cache)
    if not name:
        return KnowledgeGraph(scope="active")
    found = load_ontology(name, cache)
    return found.graph if found else KnowledgeGraph(scope="active")
