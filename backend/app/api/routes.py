from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.config.cache import Cache
from app.config.settings_store import SettingsStore, mask_settings, merge_settings
from app.deps import get_cache, get_settings_store
from app.llm.base import LLMError
from app.llm.factory import build_provider
from app.models.schemas import (
    DEFAULT_MODELS,
    AnalysisResult,
    Settings,
    StockData,
)
from app.services.analysis_service import run_analysis
from app.services.stock_service import get_stock_data

router = APIRouter(prefix="/api")

_PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "ollama": "Ollama (local)",
}


@router.get("/stock/{ticker}", response_model=StockData)
def stock(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> StockData:
    settings = store.load()
    try:
        return get_stock_data(ticker, period, settings.indicator_params, cache)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/analyze/{ticker}", response_model=AnalysisResult)
def analyze_ticker(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> AnalysisResult:
    settings = store.load()
    try:
        return run_analysis(ticker, period, settings, cache)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/settings", response_model=Settings)
def read_settings(store: SettingsStore = Depends(get_settings_store)) -> Settings:
    return mask_settings(store.load())


@router.put("/settings", response_model=Settings)
def update_settings(
    incoming: Settings, store: SettingsStore = Depends(get_settings_store)
) -> Settings:
    merged = merge_settings(store.load(), incoming)
    store.save(merged)
    return mask_settings(merged)


@router.get("/providers")
def list_providers(store: SettingsStore = Depends(get_settings_store)) -> list[dict]:
    settings = store.load()
    out = []
    for pid, label in _PROVIDER_LABELS.items():
        cfg = settings.providers.get(pid)
        configured = bool(cfg and (cfg.api_key or pid == "ollama"))
        out.append(
            {
                "id": pid,
                "label": label,
                "configured": configured,
                "default_model": DEFAULT_MODELS[pid],
            }
        )
    return out


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: str, store: SettingsStore = Depends(get_settings_store)
) -> dict:
    settings = store.load()
    if provider_id not in settings.providers:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    settings.active_provider = provider_id  # type: ignore[assignment]
    try:
        provider = build_provider(settings)
        provider.complete("You are a connection test.", "Reply with the single word: ok")
        return {"ok": True, "message": "Connection succeeded."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}
