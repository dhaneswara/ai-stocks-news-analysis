from __future__ import annotations

from datetime import date

from app.analysis.analyzer import analyze
from app.config.cache import Cache
from app.llm.base import LLMError
from app.llm.factory import build_provider, resolve_config
from app.models.schemas import AnalysisResult, Settings
from app.services.stock_service import get_stock_data

ANALYSIS_TTL_SECONDS = 24 * 60 * 60  # 1 day


def run_analysis(ticker: str, period: str, settings: Settings, cache: Cache) -> AnalysisResult:
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

    stock = get_stock_data(ticker, period, settings.indicator_params, cache)
    provider = build_provider(settings)
    result = analyze(stock, provider, model=cfg.model, provider_name=provider_id)
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    return result
