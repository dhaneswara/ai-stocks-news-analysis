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
from app.evaluation.store import SOURCE_LLM_FAST, PredictionStore
from app.llm.base import LLMError
from app.llm.factory import build_provider, resolve_config
from app.models.schemas import AnalysisResult, Settings, StockData
from app.network.store import active_graph
from app.screener.store import combined_base_index
from app.services.analysis_snapshot_store import AnalysisSnapshotStore
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
        graph = active_graph(cache)
        if graph.edges:
            base_index = combined_base_index(cache)  # portfolio-preferred, like score_one
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


def _record_calls(stock: StockData, result: AnalysisResult, settings: Settings, cache: Cache,
                  prediction_store: PredictionStore | None) -> None:
    """Best-effort persistence of the llm_fast call + its technical/network pair."""
    if prediction_store is None or not settings.evaluation.enabled:
        return
    try:
        record_prediction(stock, result, prediction_store)
    except Exception:  # noqa: BLE001 — recording must never break analysis
        logger.warning("prediction recording failed for %s", stock.ticker)
    try:
        record_deterministic_pair(stock, settings, cache, prediction_store)
    except Exception:  # noqa: BLE001 — recording must never break analysis
        logger.warning("deterministic pair recording failed for %s", stock.ticker)


def _record_if_missing(ticker: str, period: str, result: AnalysisResult, settings: Settings,
                       cache: Cache, prediction_store: PredictionStore | None) -> None:
    """Recording rides the fresh-compute path, so a cache-hit result was either recorded when
    first computed or never will be (analysis cached while evaluation was off, or its row
    deleted since — e.g. Clear all results). If the latest candle has no llm_fast row, record
    the cached result now; otherwise every same-day re-run keeps serving the cache, the call
    never reaches the evaluation store, and skip-already-done never engages."""
    if prediction_store is None or not settings.evaluation.enabled:
        return
    try:
        stock = get_stock_data(ticker, period, settings.indicator_params, cache)
    except Exception:  # noqa: BLE001 — recording must never break analysis
        logger.warning("recording skipped for %s: stock fetch failed", ticker)
        return
    if not stock.candles or prediction_store.get_prediction(
            ticker, stock.candles[-1].time, SOURCE_LLM_FAST):
        return
    _record_calls(stock, result, settings, cache, prediction_store)


def _write_snapshot_fast(ticker: str, period: str, result: AnalysisResult, settings: Settings,
                         cache: Cache, snapshot_store: AnalysisSnapshotStore | None) -> None:
    """Best-effort: persist the full fast-analysis result so the Dashboard can restore it later
    without re-running. INDEPENDENT of the evaluation gate — viewing must work even if recording
    is off. call_date matches the prediction convention (the last candle); the stock fetch is a
    same-day cache read."""
    if snapshot_store is None:
        return
    try:
        stock = get_stock_data(ticker, period, settings.indicator_params, cache)
        call_date = stock.candles[-1].time if stock.candles else ""
        snapshot_store.upsert(ticker=ticker, source=SOURCE_LLM_FAST, call_date=call_date,
                              period=period, provider=result.provider, model=result.model,
                              result_json=result.model_dump_json())
    except Exception:  # noqa: BLE001 — snapshotting must never break analysis
        logger.warning("analysis snapshot write failed for %s", ticker)


def run_analysis(
    ticker: str,
    period: str,
    settings: Settings,
    cache: Cache,
    prediction_store: PredictionStore | None = None,
    snapshot_store: AnalysisSnapshotStore | None = None,
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
        result = AnalysisResult.model_validate_json(cached)
        _record_if_missing(ticker, period, result, settings, cache, prediction_store)
        _write_snapshot_fast(ticker, period, result, settings, cache, snapshot_store)
        return result

    provider = build_provider(settings)
    stock = gather_stock_context(ticker, period, settings, cache, provider,
                                 store=prediction_store)

    result = analyze(stock, provider, model=cfg.model, provider_name=provider_id)
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    _record_calls(stock, result, settings, cache, prediction_store)
    _write_snapshot_fast(ticker, period, result, settings, cache, snapshot_store)
    return result
