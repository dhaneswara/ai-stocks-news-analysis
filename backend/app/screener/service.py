"""Run the scorer across the universe and return a ranked board (no persistence here)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.analysis import political
from app.analysis.scoring import score_stock
from app.config.cache import Cache
from app.data import truth_social
from app.data.universe import load_universe
from app.models.schemas import ScreenBoard, Settings
from app.services.stock_service import get_stock_data

SCAN_PERIOD = "1y"  # enough history for SMA200, RSI, 1-month momentum, 52-wk extremes


def run_scan(scope: str | None, settings: Settings, cache: Cache) -> ScreenBoard:
    entries = load_universe(scope)
    ts = settings.truth_signal
    posts = (
        truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
        if ts.enabled else []
    )

    items = []
    scanned = 0
    skipped = 0
    for entry in entries:
        scanned += 1
        try:
            stock = get_stock_data(entry.ticker, SCAN_PERIOD, settings.indicator_params, cache)
            mentions = political.find_mentions(posts, entry.ticker, stock.company_name)
            score = score_stock(stock, mentions, settings.screener)
            score.sector = entry.sector
            items.append(score)
        except Exception:  # noqa: BLE001 — a bad ticker must never abort the whole scan
            skipped += 1
            continue

    items.sort(key=lambda s: s.score, reverse=True)
    return ScreenBoard(
        as_of=datetime.now(timezone.utc).isoformat(),
        scope=scope or "all",
        scanned=scanned,
        skipped=skipped,
        items=items,
    )
