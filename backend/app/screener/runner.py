from __future__ import annotations

import logging

from app.config.cache import Cache
from app.models.schemas import Settings
from app.screener.service import run_scan
from app.screener.store import save_snapshot

logger = logging.getLogger("screener")


def run(settings: Settings, cache: Cache, scope: str | None = None) -> dict:
    if not settings.screener.enabled:
        logger.info("Screener disabled; nothing to do.")
        return {"enabled": False, "scanned": 0}
    board = run_scan(scope, settings, cache)
    save_snapshot(board, cache)
    logger.info("Scan complete: scope=%s scanned=%d skipped=%d",
                board.scope, board.scanned, board.skipped)
    return {"enabled": True, "scope": board.scope, "scanned": board.scanned, "skipped": board.skipped}
