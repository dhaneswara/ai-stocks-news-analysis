"""Build the knowledge graph over the focus set (watchlist ∪ top board names).

Mirrors `screener/service.run_scan`: per-company try/except so one bad name never aborts the
build; reuses cached `get_stock_data` (news included). Only edge extraction costs an LLM call.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.relationships import TickerResolver, extract_relationships
from app.config.cache import Cache
from app.data.universe import load_universe
from app.llm.base import LLMError
from app.llm.factory import build_provider
from app.models.schemas import KnowledgeGraph, Settings
from app.screener.store import load_snapshot
from app.services.stock_service import get_stock_data

NETWORK_PERIOD = "1y"


def _focus_set(settings: Settings, cache: Cache) -> list[str]:
    board = load_snapshot(cache, "all")
    top = [i.ticker for i in board.items[: settings.network.focus_top_n]] if board else []
    seen: set[str] = set()
    focus: list[str] = []
    for t in list(settings.watchlist) + top:
        tu = (t or "").upper().strip()
        if tu and tu not in seen:
            seen.add(tu)
            focus.append(tu)
    return focus


def build_graph(scope: str | None, settings: Settings, cache: Cache, *, now: datetime | None = None) -> KnowledgeGraph:
    now = now or datetime.now(timezone.utc)
    out_scope = scope or "focus"
    ncfg = settings.network
    if not ncfg.enabled:
        return KnowledgeGraph(as_of=now.isoformat(), scope=out_scope)

    try:
        provider = build_provider(settings)
    except LLMError:
        return KnowledgeGraph(as_of=now.isoformat(), scope=out_scope)  # no usable provider -> empty
    provider_id = settings.active_provider
    model = settings.providers[provider_id].model
    resolver = TickerResolver(load_universe())

    edges = []
    nodes: set[str] = set()
    built = skipped = 0
    for ticker in _focus_set(settings, cache):
        try:
            stock = get_stock_data(ticker, NETWORK_PERIOD, settings.indicator_params, cache)
            es = extract_relationships(stock, resolver, provider, model, provider_id, cache, ncfg, now=now)
            edges.extend(es)
            nodes.add(ticker)
            for e in es:
                nodes.add(e.target)
            built += 1
        except Exception:  # noqa: BLE001 — one bad name must not abort the build
            skipped += 1
            continue

    return KnowledgeGraph(
        as_of=now.isoformat(), scope=out_scope, nodes=sorted(nodes),
        edges=edges, built=built, skipped=skipped,
    )
