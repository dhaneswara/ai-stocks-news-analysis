from __future__ import annotations

import logging
from datetime import date

from app.analysis import political
from app.analysis.analyzer import analyze
from app.analysis.network import compute_network_signal, incident_edges
from app.config.cache import Cache
from app.data import truth_social
from app.evaluation.service import record_prediction
from app.evaluation.signals import build_track_record_block, record_deterministic_pair
from app.evaluation.store import PredictionStore
from app.llm.base import LLMError
from app.llm.factory import build_provider, resolve_config
from app.models.schemas import AnalysisResult, Settings, StockData
from app.network.store import effective_graph
from app.screener.store import load_snapshot
from app.services.stock_service import get_stock_data

ANALYSIS_TTL_SECONDS = 24 * 60 * 60  # 1 day

logger = logging.getLogger("analysis")


def gather_stock_context(ticker, period, settings, cache, provider,
                         store: PredictionStore | None = None) -> StockData:
    """Build the StockData the analyzers consume: price/indicators/news + the company-network
    signal + the truth-social mood. Shared by the fast (run_analysis) and deep (agent) paths."""
    ticker = ticker.upper().strip()
    stock = get_stock_data(ticker, period, settings.indicator_params, cache)

    ncfg = settings.network
    if ncfg.enabled:
        graph = effective_graph(cache, "focus")
        if graph.edges:
            board = load_snapshot(cache, "all")
            base_index = {s.ticker: s for s in (board.items if board else [])}
            edges = incident_edges(ticker, graph.edges, set(ncfg.symmetric_types))
            if edges:
                stock.network = compute_network_signal(ticker, edges, base_index, ncfg)

    ts = settings.truth_signal
    if ts.enabled:
        posts = truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
        stock.trump_mentions = political.find_mentions(posts, ticker, stock.company_name)
        cfg = settings.providers[settings.active_provider]
        stock.market_mood = political.summarize_market_mood(
            posts, provider, cfg.model, settings.active_provider, cache
        )
    if store is not None:
        try:
            stock.track_record = build_track_record_block(ticker, store, settings)
        except Exception:  # noqa: BLE001 — prompt enrichment must never break analysis
            logger.warning("track-record block failed for %s", ticker)
    return stock


def run_analysis(
    ticker: str,
    period: str,
    settings: Settings,
    cache: Cache,
    prediction_store: PredictionStore | None = None,
) -> AnalysisResult:
    ticker = ticker.upper().strip()
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise LLMError(f"No configuration for provider '{provider_id}'")
    effective = resolve_config(provider_id, cfg)
    if provider_id != "ollama" and not effective.api_key:
        raise LLMError(
            f"Missing API key for provider '{provider_id}'. "
            "Set it in Settings or via environment variable."
        )

    cache_key = f"analysis:{ticker}:{provider_id}:{cfg.model}:{period}:{date.today().isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return AnalysisResult.model_validate_json(cached)

    provider = build_provider(settings)
    stock = gather_stock_context(ticker, period, settings, cache, provider,
                                 store=prediction_store)

    result = analyze(stock, provider, model=cfg.model, provider_name=provider_id)
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    if prediction_store is not None and settings.evaluation.enabled:
        try:
            record_prediction(stock, result, prediction_store)
        except Exception:  # noqa: BLE001 — recording must never break analysis
            logger.warning("prediction recording failed for %s", ticker)
        try:
            record_deterministic_pair(stock, settings, cache, prediction_store)
        except Exception:  # noqa: BLE001 — recording must never break analysis
            logger.warning("deterministic pair recording failed for %s", ticker)
    return result
