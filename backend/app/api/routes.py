from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.alerts.notifier import build_notifier
from app.config.cache import Cache
from app.config.settings_store import SettingsStore, mask_settings, merge_settings
from app.deps import get_cache, get_prediction_store, get_settings_store
from app.llm.base import LLMError
from app.llm.factory import build_provider
from app.models.schemas import (
    DEFAULT_MODELS,
    AnalysisResult,
    EvaluationBoard,
    KnowledgeGraph,
    SavedGraphSummary,
    SavedGraphVersion,
    ScreenBoard,
    Settings,
    StockData,
)
from app.analysis import political
from app.analysis.network import apply_network
from app.data import truth_social
from app.network.service import build_company_graph, build_graph
from app.network.store import (
    delete_saved_graph,
    list_saved_graphs,
    load_company_graph,
    load_graph,
    save_company_graph,
    save_graph,
)
from app.evaluation.service import build_board, evaluate_pending, explain_prediction
from app.evaluation.store import PredictionStore
from app.services.analysis_service import run_analysis
from app.services.stock_service import get_stock_data
from app.data import universe
from app.data.universe import list_sectors
from app.screener.service import run_scan
from app.screener.store import load_snapshot, merge_sector, save_snapshot

router = APIRouter(prefix="/api")

_PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "ollama": "Ollama (local)",
    "deepseek": "DeepSeek",
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
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> AnalysisResult:
    settings = store.load()
    try:
        return run_analysis(ticker, period, settings, cache, prediction_store)
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


@router.get("/providers/{provider_id}/models")
def list_provider_models(
    provider_id: str, store: SettingsStore = Depends(get_settings_store)
) -> dict:
    settings = store.load()
    if provider_id not in settings.providers:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    settings.active_provider = provider_id  # type: ignore[assignment]
    try:
        return {"models": build_provider(settings).list_models(), "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"models": [], "error": str(exc)}


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
    n = settings.screener.top_n if limit is None else limit
    shown = items if n <= 0 else items[:n]
    return board.model_copy(update={"items": shown})


@router.post("/screen/rescan", response_model=ScreenBoard)
def screen_rescan(
    sector: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    board = run_scan(sector, settings, cache)
    graph = load_graph(cache, "focus")
    if sector:
        full = load_snapshot(cache, "all")
        merged = merge_sector(full, board) if full else board
        if graph is not None:
            merged = apply_network(merged, graph, settings)
        save_snapshot(merged, cache)
    else:
        to_save = apply_network(board, graph, settings) if graph is not None else board
        save_snapshot(to_save, cache)
    return board


@router.get("/screen/sectors", response_model=list[str])
def screen_sectors() -> list[str]:
    return list_sectors()


@router.get("/graph", response_model=KnowledgeGraph)
def get_graph(scope: str = "focus", cache: Cache = Depends(get_cache)) -> KnowledgeGraph:
    graph = load_graph(cache, scope)
    return graph if graph is not None else KnowledgeGraph(scope=scope)


@router.post("/graph/rebuild", response_model=KnowledgeGraph)
def rebuild_graph(
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> KnowledgeGraph:
    settings = store.load()
    graph = build_graph(None, settings, cache)
    save_graph(graph, cache)
    board = load_snapshot(cache, "all")
    if board is not None:
        save_snapshot(apply_network(board, graph, settings), cache)
    return graph


@router.get("/graph/company/{ticker}", response_model=KnowledgeGraph)
def get_company_graph(
    ticker: str,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> KnowledgeGraph:
    """One-hop ego graph for a single ticker — powers both 'start from company' and 'expand'."""
    return build_company_graph(ticker, store.load(), cache)


@router.get("/graph/saved", response_model=list[SavedGraphSummary])
def list_saved(cache: Cache = Depends(get_cache)) -> list[SavedGraphSummary]:
    return list_saved_graphs(cache)


@router.post("/graph/saved", response_model=SavedGraphVersion)
def save_saved(payload: SavedGraphVersion, cache: Cache = Depends(get_cache)) -> SavedGraphVersion:
    stamped = payload.model_copy(update={"saved_at": datetime.now(timezone.utc).isoformat()})
    return save_company_graph(stamped, cache)


@router.get("/graph/saved/{root}", response_model=SavedGraphVersion)
def get_saved(
    root: str, version: str | None = None, cache: Cache = Depends(get_cache)
) -> SavedGraphVersion:
    found = load_company_graph(root, cache, version)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No saved graph for '{root}'")
    return found


@router.delete("/graph/saved/{root}")
def delete_saved(root: str, version: str | None = None, cache: Cache = Depends(get_cache)) -> dict:
    return {"deleted": delete_saved_graph(root, cache, version)}


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


@router.post("/universe/refresh")
def update_universe() -> dict:
    try:
        return universe.refresh_universe()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Could not update the S&P 500 list: {exc}"
        ) from exc


@router.get("/evaluation", response_model=EvaluationBoard)
def get_evaluation(
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> EvaluationBoard:
    settings = store.load()
    evaluate_pending(prediction_store, settings)
    return build_board(prediction_store, settings)


@router.post("/evaluation/{ticker}/{call_date}/explain")
def explain_evaluation(
    ticker: str,
    call_date: str,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    settings = store.load()
    try:
        text = explain_prediction(ticker, call_date, settings, cache, prediction_store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"explanation": text}


@router.delete("/evaluation/{ticker}")
def delete_tracked(
    ticker: str,
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    return {"deleted": prediction_store.delete_ticker(ticker)}
