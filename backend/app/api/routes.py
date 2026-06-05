from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from app.alerts.notifier import build_notifier
from app.config.cache import Cache
from app.config.settings_store import SettingsStore, mask_settings, merge_settings
from app.deps import get_cache, get_settings_store
from app.llm.base import LLMError
from app.llm.factory import build_provider
from app.models.schemas import (
    DEFAULT_MODELS,
    AnalysisResult,
    ScreenBoard,
    Settings,
    StockData,
)
from app.analysis import political
from app.data import truth_social
from app.services.analysis_service import run_analysis
from app.services.stock_service import get_stock_data
from app.data.universe import list_sectors
from app.screener.service import run_scan
from app.screener.store import load_snapshot, merge_sector, save_snapshot

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


@router.get("/truth/mood")
def truth_mood(
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> dict:
    settings = store.load()
    ts = settings.truth_signal
    if not ts.enabled:
        return {"enabled": False, "post_count": 0, "mood": None}
    posts = truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
    try:
        provider = build_provider(settings)
        cfg = settings.providers[settings.active_provider]
        mood = political.summarize_market_mood(
            posts, provider, cfg.model, settings.active_provider, cache
        )
        return {"enabled": True, "post_count": len(posts), "mood": mood.model_dump()}
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "post_count": len(posts), "mood": None, "error": str(exc)}


@router.get("/screen", response_model=ScreenBoard)
def screen(
    sector: str | None = None,
    direction: str | None = None,
    limit: int | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    board = load_snapshot(cache, "all")
    if board is None:
        return ScreenBoard()  # empty -> frontend prompts a first scan
    items = board.items
    if sector:
        items = [i for i in items if i.sector == sector]
    if direction:
        items = [i for i in items if i.direction == direction]
    return board.model_copy(update={"items": items[: (limit or settings.screener.top_n)]})


@router.post("/screen/rescan", response_model=ScreenBoard)
def screen_rescan(
    sector: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    board = run_scan(sector, settings, cache)
    if sector:
        full = load_snapshot(cache, "all")
        # Merge fresh sector rows into the full board if one exists; else persist as-is.
        save_snapshot(merge_sector(full, board) if full else board, cache)
    else:
        save_snapshot(board, cache)
    return board


@router.get("/screen/sectors", response_model=list[str])
def screen_sectors() -> list[str]:
    return list_sectors()


@router.post("/alerts/test")
def test_alert(store: SettingsStore = Depends(get_settings_store)) -> dict:
    cfg = store.load().alerts
    token = cfg.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if cfg.channel == "telegram" and not (token and chat_id):
        return {"ok": False, "message": "Telegram bot token and chat id are required."}
    try:
        build_notifier(cfg).send("Test alert", "Alerts are configured correctly. (Not financial advice.)")
        return {"ok": True, "message": "Test alert sent."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}
