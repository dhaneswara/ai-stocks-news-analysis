"""Validate + normalize an externally-authored ontology model into a KnowledgeGraph fragment.

Pure: no I/O, no LLM. Resolves entities to universe tickers via TickerResolver (hybrid: a match
becomes a ticker node; a miss becomes an ``ext:<slug>`` node with a node_meta entry). Maps relation
types onto the six canonical types or ``other``. Tags every edge ``origin="imported"``. Degrades
leniently: malformed nodes/edges are skipped and counted, never raised.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.analysis.relationships import TickerResolver
from app.models.schemas import GraphEdge, ImportReport, KnowledgeGraph, NodeMeta

MAX_IMPORT_EDGES = 1000

_CANONICAL = {"supplier", "customer", "partner", "competitor", "owner", "subsidiary"}

_SYNONYMS = {
    "invests_in": "owner", "investor": "owner", "stake": "owner", "owns": "owner",
    "acquired": "owner", "acquires": "owner", "acquisition": "owner", "parent": "owner",
    "owned_by": "subsidiary", "unit": "subsidiary", "division": "subsidiary",
    "licenses": "partner", "licensee": "partner", "licensor": "partner", "alliance": "partner",
    "collaborates": "partner", "collaboration": "partner", "partners": "partner",
    "jv": "partner", "joint_venture": "partner",
    "vendor": "supplier", "supplies": "supplier", "supplier_of": "supplier",
    "buys_from": "customer", "client": "customer", "buyer": "customer",
    "rival": "competitor", "competes": "competitor", "competes_with": "competitor",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def map_relation_type(raw: Any) -> str:
    t = str(raw or "").strip().lower()
    if t in _CANONICAL:
        return t
    return _SYNONYMS.get(t, "other")


def _clamp01(x: Any, default: float = 0.5) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


def normalize_import(
    payload: Any, resolver: TickerResolver, *, now: datetime | None = None
) -> tuple[KnowledgeGraph, ImportReport]:
    now = now or datetime.now(timezone.utc)
    report = ImportReport()
    if not isinstance(payload, dict):
        report.warnings.append("Payload is not a JSON object; nothing imported.")
        return KnowledgeGraph(scope="imported", as_of=now.isoformat()), report

    as_of = str(payload.get("as_of") or now.isoformat())
    id_map: dict[str, str] = {}
    node_meta: dict[str, NodeMeta] = {}

    def resolve_entity(raw_id: Any, label: str = "", kind: str = "") -> str:
        rid = str(raw_id or "").strip()
        lbl = str(label or rid).strip()
        if not rid:
            return ""
        if rid in id_map:
            return id_map[rid]
        ticker = resolver.resolve(lbl, rid)
        if ticker:
            id_map[rid] = ticker
            return ticker
        ext = f"ext:{_slug(lbl or rid)}"
        id_map[rid] = ext
        if ext not in node_meta:  # first-seen label wins on slug collision (deterministic)
            node_meta[ext] = NodeMeta(label=lbl or rid, kind=str(kind or ""), source="imported")
        return ext

    for n in payload.get("nodes", []) or []:
        if isinstance(n, dict) and (n.get("id") or n.get("label")):
            resolve_entity(n.get("id") or n.get("label"), n.get("label", ""), n.get("kind", ""))

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    dropped = 0
    for e in payload.get("edges", []) or []:
        if not isinstance(e, dict):
            dropped += 1
            continue
        src = resolve_entity(e.get("source", ""))
        tgt = resolve_entity(e.get("target", ""))
        if not src or not tgt or src == tgt:
            dropped += 1
            continue
        rel = map_relation_type(e.get("type"))
        sent = e.get("sentiment", "neutral")
        if sent not in ("positive", "negative", "neutral"):
            sent = "neutral"
        key = (src, tgt, rel)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        edges.append(GraphEdge(
            source=src, target=tgt, type=rel, sentiment=sent,
            weight=_clamp01(e.get("weight")), confidence=_clamp01(e.get("confidence")),
            evidence=str(e.get("evidence", ""))[:200], url=str(e.get("url", ""))[:2048],
            as_of=as_of, origin="imported",
        ))

    edges.sort(key=lambda x: x.weight * x.confidence, reverse=True)
    if len(edges) > MAX_IMPORT_EDGES:
        report.warnings.append(
            f"Import capped at {MAX_IMPORT_EDGES} edges; {len(edges) - MAX_IMPORT_EDGES} dropped."
        )
        dropped += len(edges) - MAX_IMPORT_EDGES
        edges = edges[:MAX_IMPORT_EDGES]

    nodes = sorted({e.source for e in edges} | {e.target for e in edges})
    node_set = set(nodes)
    node_meta = {k: v for k, v in node_meta.items() if k in node_set}

    report.nodes_added = len(nodes)
    report.edges_added = len(edges)
    report.dropped = dropped
    graph = KnowledgeGraph(
        scope="imported", as_of=as_of, nodes=nodes, edges=edges, node_meta=node_meta, built=1
    )
    return graph, report
