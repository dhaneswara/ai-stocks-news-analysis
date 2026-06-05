"""Persist the latest ranked board in the existing Cache (SQLite KV).

Keyed `screen_snapshot:<scope>` with a long TTL; the daily job refreshes it well within that, so
expiry only ever yields the empty state. No new table — reuses the cache injected via get_cache.
"""
from __future__ import annotations

from app.config.cache import Cache
from app.models.schemas import ScreenBoard

_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _key(scope: str) -> str:
    return f"screen_snapshot:{scope}"


def save_snapshot(board: ScreenBoard, cache: Cache) -> None:
    cache.set(_key(board.scope), board.model_dump_json(), _SNAPSHOT_TTL_SECONDS)


def load_snapshot(cache: Cache, scope: str = "all") -> ScreenBoard | None:
    raw = cache.get(_key(scope))
    return ScreenBoard.model_validate_json(raw) if raw is not None else None


def merge_sector(full: ScreenBoard, fresh: ScreenBoard) -> ScreenBoard:
    """Replace the rows belonging to fresh.scope inside the full board, then re-rank by score.

    Recompute ``scanned``/``skipped`` so they describe the merged board rather than carrying the
    full board's stale counts (otherwise a sector rescan leaves e.g. "30 scanned" on a board that
    now holds far more names). ``scanned`` counts the names on the board plus this rescan's
    failures; ``skipped`` reflects the freshly rescanned sector.
    """
    kept = [i for i in full.items if i.sector != fresh.scope]
    items = kept + list(fresh.items)
    items.sort(key=lambda s: s.score, reverse=True)
    return full.model_copy(
        update={"items": items, "scanned": len(items) + fresh.skipped, "skipped": fresh.skipped}
    )
