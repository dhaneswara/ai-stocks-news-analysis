from __future__ import annotations

import logging

from app.analysis.network import apply_network
from app.config.cache import Cache
from app.models.schemas import Settings
from app.network.service import build_graph
from app.network.store import effective_graph, save_graph
from app.screener.store import load_snapshot, save_snapshot

logger = logging.getLogger("network")


def run(settings: Settings, cache: Cache, scope: str | None = None) -> dict:
    if not settings.network.enabled:
        logger.info("Network signal disabled; nothing to do.")
        return {"enabled": False, "built": 0}
    graph = build_graph(scope, settings, cache)
    save_graph(graph, cache)
    board = load_snapshot(cache, "all")
    if board is not None:
        save_snapshot(apply_network(board, effective_graph(cache), settings), cache)  # bake influence in
    logger.info("Graph built: built=%d skipped=%d edges=%d", graph.built, graph.skipped, len(graph.edges))
    return {"enabled": True, "built": graph.built, "skipped": graph.skipped, "edges": len(graph.edges)}
