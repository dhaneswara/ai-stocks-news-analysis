from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.alerts.notifier import build_notifier
from app.config.cache import Cache
from app.config.settings_store import SettingsStore, mask_settings, merge_settings
from app.deps import get_cache, get_prediction_store, get_settings_store, get_trace_store
from app.llm.base import LLMError
from app.llm.factory import build_provider, resolve_config
from app.models.schemas import (
    DEFAULT_MODELS,
    AnalysisResult,
    EvaluationBoard,
    ImportReport,
    ImportSetSummary,
    KnowledgeGraph,
    SavedGraphSummary,
    SavedGraphVersion,
    ScreenBoard,
    Settings,
    SignalsSummary,
    Source,
    StockData,
    StockScore,
    WatchlistRunEvent,
)
from app.analysis import political
from app.analysis.network import apply_network
from app.data import truth_social
from app.network.service import build_company_graph, build_graph
from app.network.store import (
    add_import_set,
    delete_import_set,
    delete_saved_graph,
    effective_graph,
    list_import_sets,
    list_saved_graphs,
    load_company_graph,
    load_graph,
    load_import_graph,
    load_overlay,
    save_company_graph,
    save_graph,
)
from app.evaluation.service import build_board, evaluate_pending, explain_prediction, record_prediction
from app.evaluation.signals import build_signals, record_deterministic_pair, snapshot_watchlist
from app.evaluation.store import SOURCE_LLM_DEEP, SOURCE_LLM_FAST, PredictionStore
from app.analysis.agent import AgentEvent, AgentTrace, ReActAgent, ToolContext
from app.analysis.trace_store import AgentTraceStore
from app.services.analysis_service import gather_stock_context, run_analysis
from app.services.stock_service import get_stock_data
from app.analysis.relationships import TickerResolver
from app.network.import_model import normalize_import
from app.data import universe
from app.data.universe import list_sectors
from app.screener.service import run_scan, score_one
from app.screener.store import load_snapshot, merge_sector, save_snapshot

router = APIRouter(prefix="/api")

logger = logging.getLogger("api")

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


@router.get("/score/{ticker}", response_model=StockScore)
def get_score(
    ticker: str,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> StockScore:
    """No-LLM opportunity score for a single ticker (Discover parity, network-blended)."""
    try:
        return score_one(ticker.upper().strip(), store.load(), cache)
    except ValueError as exc:   # no data for ticker -> 404, same convention as GET /stock/{ticker}
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/signals/{ticker}", response_model=SignalsSummary)
def get_signals(
    ticker: str,
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> SignalsSummary:
    """All recorded CALL sources for one ticker + per-source track records, agreement and
    the historically best source — the Dashboard SignalsStrip payload."""
    return build_signals(ticker, prediction_store)


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


def _sse(event: AgentEvent | WatchlistRunEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


def _persist_deep_final(event: AgentEvent, stock: StockData, settings: Settings, cache: Cache,
                        prediction_store: PredictionStore, trace_store: AgentTraceStore) -> None:
    """Persist the trace + predictions when a deep run completes. Each persistence concern is
    isolated — a failure must never break the SSE stream. A run that degraded to the
    single-shot fallback is recorded as llm_fast (that path produced the answer), keeping the
    fast-vs-deep comparison honest."""
    trace = event.trace
    call_date = stock.candles[-1].time if stock.candles else ""
    if trace is not None and call_date:
        try:
            trace_store.upsert(ticker=trace.ticker, call_date=call_date, provider=trace.provider,
                               model=trace.model, trace_json=trace.model_dump_json())
        except Exception:  # noqa: BLE001
            logger.warning("trace persistence failed for %s", stock.ticker)
    if event.result is None or not settings.evaluation.enabled:
        return
    # No trace = can't prove it was a real agent run -> conservatively label llm_fast.
    source = SOURCE_LLM_FAST if (trace is None or trace.fell_back) else SOURCE_LLM_DEEP
    try:
        record_prediction(stock, event.result, prediction_store, source=source)
    except Exception:  # noqa: BLE001
        logger.warning("deep prediction recording failed for %s", stock.ticker)
    try:
        record_deterministic_pair(stock, settings, cache, prediction_store)
    except Exception:  # noqa: BLE001
        logger.warning("deterministic pair recording failed for %s", stock.ticker)


@router.get("/analyze/{ticker}/deep/stream")
def analyze_deep_stream(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
    trace_store: AgentTraceStore = Depends(get_trace_store),
) -> StreamingResponse:
    """Agentic (ReAct) deep analysis, streamed step-by-step as Server-Sent Events. Failures that
    prevent starting (no price data -> 404, no provider config -> 502) are normal HTTP errors;
    provider/LLM failures (incl. a missing API key) surface as an in-stream `event: error` —
    EventSource can't read an HTTP error body, so streaming the message gives the client a usable
    error. The agent's single-shot fallback otherwise guarantees a terminal `final` event."""
    settings = store.load()
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise HTTPException(status_code=502, detail=f"No configuration for provider '{provider_id}'")
    try:
        provider = build_provider(settings)
        stock = gather_stock_context(ticker, period, settings, cache, provider,
                                     store=prediction_store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ctx = ToolContext(stock=stock, settings=settings, cache=cache)
    agent = ReActAgent()

    def event_stream():
        try:
            for event in agent.stream(provider, cfg.model, provider_id, ctx):
                if event.type == "final":
                    _persist_deep_final(event, stock, settings, cache, prediction_store,
                                        trace_store)
                yield _sse(event)
        except LLMError as exc:  # provider/LLM failure (e.g. missing key) -> usable in-stream error
            # TODO: a mid-run LLMError loses the partial trace (only `final` persists);
            # acceptable v1 limitation — revisit if failed deep runs need post-mortems.
            yield _sse(AgentEvent(type="error", message=str(exc)))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/traces/{ticker}", response_model=list[AgentTrace])
def get_traces(
    ticker: str,
    limit: int = 5,
    trace_store: AgentTraceStore = Depends(get_trace_store),
) -> list[AgentTrace]:
    """Most recent persisted deep-analysis traces for a ticker (newest first)."""
    results: list[AgentTrace] = []
    for j in trace_store.recent(ticker, limit):
        try:
            results.append(AgentTrace.model_validate_json(j))
        except Exception:  # noqa: BLE001 — one corrupt row must not take the endpoint down
            logger.warning("corrupt trace row for %s, skipping", ticker)
    return results


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/analyze/watchlist/stream")
def analyze_watchlist_stream(
    mode: Literal["fast", "deep"] = "fast",
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
    trace_store: AgentTraceStore = Depends(get_trace_store),
) -> StreamingResponse:
    """Run the LLM analysis for every watchlist ticker as one SSE batch (`start`, one
    `ticker` frame per state change, terminal `done`/`error`). A ticker whose
    matching-source call already exists for its latest trading day is skipped, so
    re-running resumes after a partial failure instead of re-spending tokens. Sequential
    on purpose (provider rate limits). Pre-flight failures (evaluation off, provider
    misconfigured) are a single run-level `error` event — EventSource cannot read an HTTP
    error body. A client disconnect cancels the loop at the next yield: the in-flight
    ticker still completes and records."""
    settings = store.load()
    source = SOURCE_LLM_FAST if mode == "fast" else SOURCE_LLM_DEEP

    def one_error(message: str) -> StreamingResponse:
        return StreamingResponse(
            iter([_sse(WatchlistRunEvent(type="error", message=message))]),
            media_type="text/event-stream", headers=_SSE_HEADERS)

    if not settings.evaluation.enabled:
        return one_error("Evaluation recording is disabled in Settings — enable it to use "
                         "watchlist runs.")
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        return one_error(f"No configuration for provider '{provider_id}'")
    effective = resolve_config(provider_id, cfg)
    if provider_id != "ollama" and not effective.api_key:
        return one_error(f"Missing API key for provider '{provider_id}'. Set it in Settings.")
    try:
        provider = build_provider(settings)
    except LLMError as exc:
        return one_error(str(exc))

    tickers = [t.upper().strip() for t in settings.watchlist]

    def event_stream():
        yield _sse(WatchlistRunEvent(type="start", total=len(tickers), tickers=tickers))
        analyzed = skipped = failed = 0
        for i, ticker in enumerate(tickers):
            yield _sse(WatchlistRunEvent(type="ticker", ticker=ticker, index=i,
                                         total=len(tickers), status="running"))
            try:
                stock = get_stock_data(ticker, period, settings.indicator_params, cache)
                if not stock.candles:
                    raise ValueError("no price data")
                if prediction_store.get_prediction(ticker, stock.candles[-1].time, source):
                    skipped += 1
                    yield _sse(WatchlistRunEvent(type="ticker", ticker=ticker, index=i,
                                                 total=len(tickers), status="skipped"))
                    continue
                fell_back = False
                if mode == "fast":
                    result = run_analysis(ticker, period, settings, cache, prediction_store)
                else:
                    deep_stock = gather_stock_context(ticker, period, settings, cache,
                                                      provider, store=prediction_store)
                    ctx = ToolContext(stock=deep_stock, settings=settings, cache=cache)
                    result, trace = ReActAgent().run(provider, cfg.model, provider_id, ctx)
                    if result is None:
                        raise LLMError("agent produced no result")
                    _persist_deep_final(AgentEvent(type="final", result=result, trace=trace),
                                        deep_stock, settings, cache, prediction_store,
                                        trace_store)
                    fell_back = trace.fell_back if trace else True
                analyzed += 1
                yield _sse(WatchlistRunEvent(
                    type="ticker", ticker=ticker, index=i, total=len(tickers),
                    status="done", recommendation=result.current_recommendation,
                    confidence=result.confidence, fell_back=fell_back))
            except Exception as exc:  # noqa: BLE001 — per-ticker isolation
                logger.warning("watchlist %s run failed for %s: %s", mode, ticker, exc)
                failed += 1
                yield _sse(WatchlistRunEvent(type="ticker", ticker=ticker, index=i,
                                             total=len(tickers), status="failed",
                                             error=str(exc)))
        yield _sse(WatchlistRunEvent(type="done", analyzed=analyzed, skipped=skipped,
                                     failed=failed))

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


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
    graph = effective_graph(cache, "focus")
    if sector:
        full = load_snapshot(cache, "all")
        merged = merge_sector(full, board) if full else board
        merged = apply_network(merged, graph, settings)
        save_snapshot(merged, cache)
    else:
        save_snapshot(apply_network(board, graph, settings), cache)
    return board


@router.get("/screen/sectors", response_model=list[str])
def screen_sectors() -> list[str]:
    return list_sectors()


@router.get("/graph", response_model=KnowledgeGraph)
def get_graph(scope: str = "focus", cache: Cache = Depends(get_cache)) -> KnowledgeGraph:
    if scope == "imported":
        return load_overlay(cache)
    if scope == "focus":  # overlay-merged; all other scopes return the raw snapshot
        return effective_graph(cache, "focus")
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
        save_snapshot(apply_network(board, effective_graph(cache, "focus"), settings), cache)
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


@router.post("/graph/import", response_model=ImportReport)
def import_graph(payload: dict, cache: Cache = Depends(get_cache)) -> ImportReport:
    body = payload or {}
    name = str(body.get("name", ""))
    model = body.get("payload", body)  # accept {name, payload} or a bare model
    resolver = TickerResolver(universe.load_universe())
    graph, report = normalize_import(model, resolver)
    created_at = datetime.now(timezone.utc).isoformat()
    summary = add_import_set(name, graph, cache, created_at=created_at)
    report.id = summary.id
    report.name = summary.name
    return report


@router.get("/graph/imports", response_model=list[ImportSetSummary])
def list_imports(cache: Cache = Depends(get_cache)) -> list[ImportSetSummary]:
    return list_import_sets(cache)


@router.get("/graph/imports/{set_id}", response_model=KnowledgeGraph)
def get_import_set(set_id: str, cache: Cache = Depends(get_cache)) -> KnowledgeGraph:
    """One import set's graph, for the merge-into-graph preview."""
    graph = load_import_graph(set_id, cache)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No import set '{set_id}'")
    return graph


@router.delete("/graph/imports")
def delete_import(set_id: str = Query(...), cache: Cache = Depends(get_cache)) -> dict:
    return {"deleted": delete_import_set(set_id, cache)}


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
    source: Source = "llm_fast",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    settings = store.load()
    try:
        text = explain_prediction(ticker, call_date, settings, cache, prediction_store,
                                  source=source)
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


@router.post("/evaluation/snapshot")
def snapshot_evaluation(
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> dict:
    """Snapshot the watchlist's technical/network calls as dated predictions (no body —
    the watchlist lives in settings)."""
    settings = store.load()
    if not settings.evaluation.enabled:
        return {"recorded": 0, "skipped": [], "disabled": True}
    return snapshot_watchlist(settings, cache, prediction_store)
