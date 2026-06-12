"""Run the scorer across the universe and return a ranked board (no persistence here)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from app.analysis import political
from app.analysis.scoring import score_stock
from app.config.cache import Cache
from app.data import truth_social
from app.data.universe import load_universe
from app.analysis.network import blend_network_into_score, compute_network_signal, incident_edges
from app.models.schemas import ScreenBoard, Settings, StockScore
from app.network.store import effective_graph
from app.screener.store import load_snapshot
from app.services.stock_service import get_stock_data

SCAN_PERIOD = "1y"  # enough history for SMA200, RSI, 1-month momentum, 52-wk extremes


@dataclass(frozen=True)
class ScanProgress:
    """One in-flight scan step: `ticker` is about to be fetched, counts are completed-so-far."""
    ticker: str
    scanned: int
    total: int
    skipped: int


def iter_scan(scope: str | None, settings: Settings, cache: Cache) -> Iterator[ScanProgress | ScreenBoard]:
    """Scan the universe, yielding a ScanProgress per ticker and the finished board last.

    Progress is emitted BEFORE each fetch so a stalled ticker is identifiable by name."""
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
        yield ScanProgress(ticker=entry.ticker, scanned=scanned, total=len(entries), skipped=skipped)
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
    yield ScreenBoard(
        as_of=datetime.now(timezone.utc).isoformat(),
        scope=scope or "all",
        scanned=scanned,
        skipped=skipped,
        items=items,
    )


def run_scan(scope: str | None, settings: Settings, cache: Cache) -> ScreenBoard:
    """Blocking variant of iter_scan — the CLI, the scheduled runner and the POST route."""
    board: ScreenBoard | None = None
    for step in iter_scan(scope, settings, cache):
        if isinstance(step, ScreenBoard):
            board = step
    assert board is not None  # iter_scan always ends with the board
    return board


def score_one(ticker: str, settings: Settings, cache: Cache) -> StockScore:
    """Score a single ticker on-demand (no LLM), network-blended to match the Discover board.

    Raises ValueError (via get_stock_data) when the ticker has no data — the route maps that to 404.
    The network block is best-effort: any failure degrades to the base technical score.
    """
    stock = get_stock_data(ticker, SCAN_PERIOD, settings.indicator_params, cache)
    ts = settings.truth_signal
    posts = (
        truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
        if ts.enabled else []
    )
    mentions = political.find_mentions(posts, ticker, stock.company_name)
    score = score_stock(stock, mentions, settings.screener)
    score.sector = next((e.sector for e in load_universe() if e.ticker == ticker), "")

    if settings.network.enabled:
        try:
            graph = effective_graph(cache, "focus")
            board = load_snapshot(cache, "all")
            base_index = {s.ticker: s for s in (board.items if board else [])}
            edges = incident_edges(ticker, graph.edges, set(settings.network.symmetric_types))
            if edges:
                sig = compute_network_signal(ticker, edges, base_index, settings.network)
                score = blend_network_into_score(score, sig, settings)
        except Exception:  # noqa: BLE001 — network is best-effort; base score on any failure
            pass
    return score
