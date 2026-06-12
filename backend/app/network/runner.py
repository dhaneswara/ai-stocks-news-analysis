from __future__ import annotations

import logging

from app.analysis.network import apply_network
from app.config.cache import Cache
from app.models.schemas import Settings
from app.network.store import active_graph, get_active_ontology
from app.screener.store import load_snapshot, save_snapshot

logger = logging.getLogger("network")


def run(settings: Settings, cache: Cache) -> dict:
    """Re-blend the board snapshot against the ACTIVE ontology (daily job after the screener).
    No LLM build anymore — the ontology is user-curated on the Graph page."""
    if not settings.network.enabled:
        logger.info("Network signal disabled; nothing to do.")
        return {"enabled": False, "baked": 0}
    board = load_snapshot(cache, "all")
    if board is None:
        logger.info("No board snapshot yet; nothing to bake.")
        return {"enabled": True, "baked": 0, "active": get_active_ontology(cache) or ""}
    graph = active_graph(cache)
    save_snapshot(apply_network(board, graph, settings), cache)
    logger.info("Baked: rows=%d edges=%d active=%s",
                len(board.items), len(graph.edges), get_active_ontology(cache) or "(none)")
    return {"enabled": True, "baked": len(board.items), "edges": len(graph.edges),
            "active": get_active_ontology(cache) or ""}
