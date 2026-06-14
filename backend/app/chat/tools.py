from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from app.analysis.indicators import rsi, sma
from app.config.cache import Cache
from app.data.news import search_news
from app.evaluation.store import PredictionStore
from app.llm.base import LLMProvider
from app.models.schemas import Settings
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
        f"Market cap {_fmt(f.market_cap)}, P/E {_fmt(f.pe_ratio)}, EPS {_fmt(f.eps)}, "
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
    items = search_news(query, limit)
    if not items:
        return "(no headlines found)"
    return "\n".join(f"- [{n.published_at}] {n.title} ({n.source})" for n in items)


TOOLS: list[ChatTool] = []
TOOL_BY_NAME: dict[str, ChatTool] = {}
