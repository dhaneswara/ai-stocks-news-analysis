"""One-hop company relationship extraction powering the graph explorer (start/expand)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.relationships import TickerResolver, extract_relationships
from app.config.cache import Cache
from app.data.universe import load_universe
from app.llm.factory import build_provider
from app.models.schemas import KnowledgeGraph, Settings
from app.news.factory import build_news_provider
from app.services.stock_service import get_stock_data

NETWORK_PERIOD = "1y"
NEWS_LIMIT = 10


def build_company_graph(
    ticker: str, settings: Settings, cache: Cache, *, now: datetime | None = None, refresh: bool = False
) -> KnowledgeGraph:
    """One-hop ego graph for a single ticker. Powers both 'start from company' and 'expand a node'.

    Degrades gracefully: any provider/settings/universe/data failure returns a graph
    containing just the (lone) root node — never raises — so the explorer always has something
    to show.
    """
    now = now or datetime.now(timezone.utc)
    t = (ticker or "").upper().strip()
    scope = f"company:{t}"
    ncfg = settings.network
    if not t or not ncfg.enabled:
        return KnowledgeGraph(as_of=now.isoformat(), scope=scope, nodes=[t] if t else [])

    try:
        provider = build_provider(settings)
        provider_id = settings.active_provider
        model = settings.providers[provider_id].model
        resolver = TickerResolver(load_universe(cache=cache))  # include custom (non-S&P) companies as edge targets
    except Exception:  # noqa: BLE001 — bad provider/settings/universe -> degrade, don't crash
        return KnowledgeGraph(as_of=now.isoformat(), scope=scope, nodes=[t])

    try:
        stock = get_stock_data(t, NETWORK_PERIOD, settings.indicator_params, cache)
        query = f"{stock.company_name} ({t}) stock"
        stock.news = build_news_provider(settings).search(
            query, limit=NEWS_LIMIT, recency_days=settings.news.news_recency_days
        )
        edges = extract_relationships(stock, resolver, provider, model, provider_id, cache, ncfg, now=now, refresh=refresh)
    except Exception:  # noqa: BLE001 — no data / provider / extraction error -> lone node
        return KnowledgeGraph(as_of=now.isoformat(), scope=scope, nodes=[t])

    nodes = {t}
    for e in edges:
        nodes.add(e.target)
    return KnowledgeGraph(
        as_of=now.isoformat(), scope=scope, nodes=sorted(nodes), edges=edges, built=1, skipped=0
    )
