"""Persist the latest ranked board in the existing Cache (SQLite KV).

Keyed `screen_snapshot:<scope>` with a long TTL; the daily job refreshes it well within that, so
expiry only ever yields the empty state. No new table — reuses the cache injected via get_cache.
"""
from __future__ import annotations

from app.config.cache import Cache
from app.models.schemas import ScreenBoard, StockScore

_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _key(scope: str) -> str:
    return f"screen_snapshot:{scope}"


def save_snapshot(board: ScreenBoard, cache: Cache) -> None:
    cache.set(_key(board.scope), board.model_dump_json(), _SNAPSHOT_TTL_SECONDS)


def load_snapshot(cache: Cache, scope: str = "all") -> ScreenBoard | None:
    raw = cache.get(_key(scope))
    return ScreenBoard.model_validate_json(raw) if raw is not None else None


def combined_base_index(cache: Cache) -> dict[str, StockScore]:
    """Ticker -> base StockScore, the `all` board overlaid by the `portfolio` board (portfolio
    wins). The neighbour-state source for single-ticker scoring: prefer the focused portfolio
    data, fall back to the broad Discover scan."""
    out: dict[str, StockScore] = {}
    all_board = load_snapshot(cache, "all")
    if all_board:
        out.update({s.ticker: s for s in all_board.items})
    pf = load_snapshot(cache, "portfolio")
    if pf:
        out.update({s.ticker: s for s in pf.items})
    return out


def upsert_score(score: StockScore, scope: str | None, cache: Cache) -> ScreenBoard:
    """Write one freshly re-scored row into the scope's saved snapshot, then re-rank.

    Replaces the row with a matching ticker (case-insensitive) or appends it; the board-level
    as_of/scanned/skipped are left untouched because only one row was rescanned. Creates a fresh
    empty board when no snapshot exists. `scope="portfolio"` targets the portfolio snapshot; any
    other scope (a sector name or None) targets the broad "all" snapshot, matching how the rescan
    stream persists.
    """
    snap_scope = "portfolio" if scope == "portfolio" else "all"
    board = load_snapshot(cache, snap_scope) or ScreenBoard(scope=snap_scope)
    kept = [i for i in board.items if i.ticker.upper() != score.ticker.upper()]
    items = sorted(kept + [score], key=lambda s: s.score, reverse=True)
    board = board.model_copy(update={"items": items})
    save_snapshot(board, cache)
    return board


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
