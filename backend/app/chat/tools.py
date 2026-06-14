from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from app.analysis import political
from app.analysis.indicators import rsi, sma
from app.analysis.network import compute_network_signal, incident_edges
from app.config.cache import Cache
from app.data import truth_social
from app.data.news import search_news
from app.evaluation.signals import build_track_record_block
from app.evaluation.store import PredictionStore
from app.llm.base import LLMProvider
from app.models.schemas import Settings
from app.network.store import active_graph
from app.screener.service import score_one
from app.screener.store import combined_base_index
from app.services.stock_service import get_stock_data


@dataclass
class ChatContext:
    """Dependencies the chat tools resolve data through, built once before the loop."""
    settings: Settings
    cache: Cache
    provider: LLMProvider
    prediction_store: Optional[PredictionStore] = None


@dataclass
class ChatTool:
    name: str
    description: str          # LLM-facing routing text, rendered into the system prompt
    args_spec: str            # short JSON-ish arg description for the catalog
    run: Callable[[dict, "ChatContext"], str]


def _int_arg(args: dict, key: str, default: int) -> int:
    """Parse an int tool-arg defensively — the LLM may emit a string or a non-number."""
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError):
        return default


def _model(ctx: ChatContext) -> str:
    return ctx.settings.providers[ctx.settings.active_provider].model


def _fmt(v: object) -> str:
    return "n/a" if v is None else f"{v}"


def _fmt_cap(v: Optional[float]) -> str:
    """Human-readable market cap (e.g. 3.00T / 45.20B / 980.00M) — the raw float repr
    (3000000000000.0) is noise in an LLM observation."""
    if v is None:
        return "n/a"
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= scale:
            return f"{v / scale:.2f}{suffix}"
    return f"{v:.0f}"


def _last(points: list) -> Optional[float]:
    return points[-1].value if points else None


def _tool_get_stock(args: dict, ctx: ChatContext) -> str:
    ticker = str(args.get("ticker") or "").strip().upper()
    if not ticker:
        return "ERROR: 'ticker' is required"
    period = str(args.get("period") or "1y").strip()
    try:
        stock = get_stock_data(ticker, period, ctx.settings.indicator_params, ctx.cache)
    except ValueError as exc:
        return f"ERROR: no data for {ticker}: {exc}"
    p, f, ind = stock.price, stock.fundamentals, stock.indicators
    rsi_v, sma50_v, sma200_v = _last(ind.rsi14), _last(ind.sma50), _last(ind.sma200)
    return "\n".join([
        f"{ticker} — {stock.company_name} ({stock.exchange or '?'}, {stock.sector or '?'})",
        f"Price {p.current:.2f} {p.currency} ({p.change_pct:+.2f}% today)",
        f"Market cap {_fmt_cap(f.market_cap)}, P/E {_fmt(f.pe_ratio)}, EPS {_fmt(f.eps)}, "
        f"div yield {_fmt(f.dividend_yield)}",
        f"52wk high/low {_fmt(f.week52_high)}/{_fmt(f.week52_low)}, "
        f"dist from 52wk high {_fmt(ind.dist_from_52wk_high_pct)}%",
        f"RSI14 {_fmt(round(rsi_v, 1) if rsi_v is not None else None)}, "
        f"SMA50 {_fmt(round(sma50_v, 2) if sma50_v is not None else None)}, "
        f"SMA200 {_fmt(round(sma200_v, 2) if sma200_v is not None else None)}",
    ])


def _tool_price_window(args: dict, ctx: ChatContext) -> str:
    ticker = str(args.get("ticker") or "").strip().upper()
    if not ticker:
        return "ERROR: 'ticker' is required"
    try:
        stock = get_stock_data(ticker, "1y", ctx.settings.indicator_params, ctx.cache)
    except ValueError as exc:
        return f"ERROR: no data for {ticker}: {exc}"
    candles = stock.candles
    if not candles:
        return f"(no price history for {ticker})"
    lookback = max(2, min(len(candles), _int_arg(args, "lookback_days", 21)))
    window = candles[-lookback:]
    closes = [c.close for c in window]
    start, end, lo, hi = closes[0], closes[-1], min(closes), max(closes)
    move = (end / start - 1.0) * 100 if start else 0.0
    out = [
        f"{ticker} window: last {lookback} trading days ({window[0].time} to {window[-1].time})",
        f"Close {start:.2f} -> {end:.2f} ({move:+.1f}%); low/high {lo:.2f}/{hi:.2f}",
    ]
    indicator = str(args.get("indicator") or "").strip().lower()
    if indicator in ("rsi", "sma"):
        period = _int_arg(args, "period", 14 if indicator == "rsi" else 50)
        series = pd.Series([c.close for c in candles], dtype="float64")
        computed = rsi(series, period) if indicator == "rsi" else sma(series, period)
        val = computed.iloc[-1]
        if pd.notna(val):
            out.append(f"{indicator.upper()}({period}) latest: {float(val):.2f}")
    return "\n".join(out)


def _tool_search_news(args: dict, ctx: ChatContext) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "ERROR: 'query' is required"
    limit = max(1, min(10, _int_arg(args, "limit", 5)))
    # No " stock" suffix (unlike the single-ticker agent's fetch_news): chat queries can be
    # about any topic, sector, or event, not just equities.
    items = search_news(query, limit)
    if not items:
        return "(no headlines found)"
    return "\n".join(f"- [{n.published_at}] {n.title} ({n.source})" for n in items)


def _tool_opportunity_score(args: dict, ctx: ChatContext) -> str:
    ticker = str(args.get("ticker") or "").strip().upper()
    if not ticker:
        return "ERROR: 'ticker' is required"
    try:
        s = score_one(ticker, ctx.settings, ctx.cache)
    except ValueError as exc:
        return f"ERROR: no data for {ticker}: {exc}"
    reasons = "; ".join(s.reasons[:6]) or "(none)"
    return f"{ticker} opportunity score {s.score:.0f}/100 — call {s.direction}. Drivers: {reasons}"


def _tool_network_signal(args: dict, ctx: ChatContext) -> str:
    ticker = str(args.get("ticker") or "").strip().upper()
    if not ticker:
        return "ERROR: 'ticker' is required"
    ncfg = ctx.settings.network
    if not ncfg.enabled:
        return "(network signal is disabled in Settings)"
    graph = active_graph(ctx.cache)
    if not graph.edges:
        return "(no active ontology — no network relationships)"
    try:
        edges = incident_edges(ticker, graph.edges, set(ncfg.symmetric_types))
        if not edges:
            return f"({ticker} has no relationships in the active ontology)"
        sig = compute_network_signal(ticker, edges, combined_base_index(ctx.cache), ncfg)
    except Exception as exc:  # noqa: BLE001 — network is best-effort; never break the loop
        return f"(network signal unavailable for {ticker}: {exc})"
    if not sig.influences:
        return f"({ticker}: no scored network influences)"
    lines = [f"{ticker} network signal (signed {sig.signed:+.2f}, intensity {sig.intensity:.2f}):"]
    for i in sig.influences[:8]:
        lines.append(f"- {i.type} {i.neighbour} ({i.name or i.neighbour}) [{i.edge_sentiment}], "
                     f"neighbour lean {i.neighbour_direction}: {i.reason}")
    return "\n".join(lines)


def _tool_geopolitics(args: dict, ctx: ChatContext) -> str:
    ts = ctx.settings.truth_signal
    if not ts.enabled:
        return "(geopolitics / Truth-Social signal is disabled in Settings)"
    try:
        posts = truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, ctx.cache)
        if not posts:
            return "(no recent Truth Social posts available)"
        mood = political.summarize_market_mood(
            posts, ctx.provider, _model(ctx), ctx.settings.active_provider, ctx.cache)
    except Exception as exc:  # noqa: BLE001 — best-effort; never break the loop
        return f"(geopolitics signal unavailable: {exc})"
    lines = [f"Market mood: {mood.lean} (confidence {mood.confidence:.0%}). {mood.summary}".strip()]
    for t in mood.themes[:4]:
        lines.append(f"- {t.label} [{t.lean}]: {t.quote}")
    ticker = str(args.get("ticker") or "").strip().upper()
    if ticker:
        mentions = political.find_mentions(posts, ticker, "")
        lines.append(f"{ticker} mentioned in {len(mentions)} post(s): {mentions[0].excerpt}"
                     if mentions else f"No direct {ticker} mentions in recent posts.")
    return "\n".join(lines)


def _tool_track_record(args: dict, ctx: ChatContext) -> str:
    ticker = str(args.get("ticker") or "").strip().upper()
    if not ticker:
        return "ERROR: 'ticker' is required"
    if ctx.prediction_store is None:
        return "(evaluation store unavailable)"
    block = build_track_record_block(ticker, ctx.prediction_store, ctx.settings)
    return block or f"(no matured evaluation history for {ticker} yet)"


TOOLS: list[ChatTool] = []
TOOL_BY_NAME: dict[str, ChatTool] = {}
