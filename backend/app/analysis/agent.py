from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field

from app.analysis.analyzer import _JSON_SCHEMA_HINT, _SYSTEM_PROMPT, extract_json
from app.analysis.indicators import rsi, sma
from app.analysis.network import compute_network_signal, incident_edges
from app.config.cache import Cache
from app.data.market import fetch_info
from app.data.news import search_news
from app.models.schemas import AnalysisResult, NetworkSignal, Settings, StockData
from app.network.store import effective_graph
from app.screener.service import score_one
from app.screener.store import load_snapshot


@dataclass
class ToolContext:
    """Everything the tools need, gathered once before the loop starts."""
    stock: StockData
    settings: Settings
    cache: Cache


@dataclass
class Tool:
    name: str
    description: str
    args_spec: str  # short JSON-ish description of args, shown in the prompt catalog
    run: Callable[[dict, "ToolContext"], str]


class AgentStep(BaseModel):
    index: int
    thought: str = ""
    action: Optional[str] = None          # tool name, or None for a final/empty step
    action_args: dict = Field(default_factory=dict)
    observation: Optional[str] = None
    is_final: bool = False
    elapsed_ms: int = 0


class AgentTrace(BaseModel):
    ticker: str
    provider: str
    model: str
    started_at: str
    elapsed_ms: int = 0
    stopped_reason: Literal["final", "max_steps", "parse_error", "no_action"] = "final"
    fell_back: bool = False                # True when the single-shot fallback produced `final`
    steps: list[AgentStep] = Field(default_factory=list)
    final: Optional[AnalysisResult] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_THOUGHT_RE = re.compile(r"Thought:\s*(.*?)(?=\n(?:Action:|Final Answer:)|\Z)", re.S)
_ACTION_RE = re.compile(r"Action:\s*([A-Za-z_]\w*)\s*\((.*)\)\s*\Z", re.S)
_FINAL_RE = re.compile(r"Final Answer:\s*(.*)\Z", re.S)


@dataclass
class ParsedStep:
    thought: str
    action: Optional[str]          # tool name, or None
    action_args: dict
    final_json: Optional[dict]     # parsed Final Answer JSON, or None


def parse_step(text: str) -> ParsedStep:
    thought_m = _THOUGHT_RE.search(text)
    thought = thought_m.group(1).strip() if thought_m else ""

    final_m = _FINAL_RE.search(text)
    if final_m:
        try:
            return ParsedStep(thought, None, {}, extract_json(final_m.group(1)))
        except (json.JSONDecodeError, ValueError):
            return ParsedStep(thought, None, {}, None)

    action_m = _ACTION_RE.search(text)
    if action_m:
        raw_args = action_m.group(2).strip()
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return ParsedStep(thought, action_m.group(1), args, None)

    return ParsedStep(thought, None, {}, None)


def render_tool_catalog(tools: list[Tool]) -> str:
    return "\n".join(f"- {t.name}({t.args_spec}): {t.description}" for t in tools)


def build_react_system(tools: list[Tool]) -> str:
    return (
        _SYSTEM_PROMPT
        + "\n\nYou work step by step using TOOLS to gather evidence. On each turn reply with "
        "EXACTLY one of:\n"
        "  Thought: <your reasoning>\n  Action: <tool_name>({<json args>})\n"
        "OR, once you have enough evidence:\n"
        "  Thought: <final reasoning>\n  Final Answer: <one JSON object for the schema below>\n\n"
        "Rules: at most one Action per turn; after each Action you receive an Observation; never "
        "invent Observations; only call a tool if it could change your recommendation.\n\n"
        "TOOLS:\n" + render_tool_catalog(tools) + "\n\n"
        "Your Final Answer MUST be a single JSON object (no prose, no code fences) with these "
        "fields:\n" + _JSON_SCHEMA_HINT
    )


def _int_arg(args: dict, key: str, default: int) -> int:
    """Parse an int tool-arg defensively — the LLM may emit a string or a non-number."""
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError):
        return default


_FUND_FIELDS: dict[str, list[str]] = {
    "earnings": ["trailingEps", "forwardEps", "earningsGrowth", "earningsQuarterlyGrowth"],
    "revenue": ["totalRevenue", "revenueGrowth", "revenuePerShare"],
    "margins": ["grossMargins", "operatingMargins", "profitMargins", "ebitdaMargins"],
    "valuation": ["trailingPE", "forwardPE", "priceToBook", "pegRatio"],
    "growth": ["earningsGrowth", "revenueGrowth"],
}


def _tool_get_fundamentals(args: dict, ctx: ToolContext) -> str:
    detail = str(args.get("detail") or "valuation").strip().lower()
    fields = _FUND_FIELDS.get(detail)
    if fields is None:
        return f"ERROR: unknown detail '{detail}'. Options: {', '.join(_FUND_FIELDS)}"
    info = fetch_info(ctx.stock.ticker)
    lines = [f"- {f}: {info.get(f)}" for f in fields if info.get(f) is not None]
    return "\n".join(lines) if lines else f"({detail} data not available)"


def _tool_fetch_news(args: dict, ctx: ToolContext) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "ERROR: 'query' is required"
    limit = max(1, min(10, _int_arg(args, "limit", 5)))
    items = search_news(f"{query} stock", limit)
    if not items:
        return "(no headlines found)"
    return "\n".join(f"- [{n.published_at}] {n.title} ({n.source})" for n in items)


def _tool_price_window(args: dict, ctx: ToolContext) -> str:
    candles = ctx.stock.candles
    if not candles:
        return "(no price history)"
    lookback = max(2, min(len(candles), _int_arg(args, "lookback_days", 21)))
    window = candles[-lookback:]
    closes = [c.close for c in window]
    start, end, lo, hi = closes[0], closes[-1], min(closes), max(closes)
    move = (end / start - 1.0) * 100 if start else 0.0
    out = [
        f"Window: last {lookback} trading days ({window[0].time} to {window[-1].time})",
        f"Close start -> end: {start:.2f} -> {end:.2f} ({move:+.1f}%)",
        f"Window low / high: {lo:.2f} / {hi:.2f}",
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


def _network_signal_for(ticker: str, ctx: ToolContext) -> Optional[NetworkSignal]:
    ncfg = ctx.settings.network
    if not ncfg.enabled:
        return None
    try:
        graph = effective_graph(ctx.cache, "focus")
        board = load_snapshot(ctx.cache, "all")
        base_index = {s.ticker: s for s in (board.items if board else [])}
        edges = incident_edges(ticker, graph.edges, set(ncfg.symmetric_types))
        if not edges:
            return None
        return compute_network_signal(ticker, edges, base_index, ncfg)
    except Exception:  # noqa: BLE001 — network is best-effort
        return None


def _tool_app_signals(args: dict, ctx: ToolContext) -> str:
    kind = str(args.get("kind") or "score").strip().lower()
    ticker = str(args.get("ticker") or ctx.stock.ticker).strip().upper()
    if kind == "score":
        try:
            s = score_one(ticker, ctx.settings, ctx.cache)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: score unavailable for {ticker}: {exc}"
        reasons = "; ".join(s.reasons[:5]) or "(none)"
        return f"{ticker} opportunity score {s.score:.0f}/100, lean {s.direction}. Drivers: {reasons}"
    if kind == "network":
        sig = _network_signal_for(ticker, ctx)
        if sig is None or not sig.influences:
            return f"({ticker}: no company-network signal)"
        return "\n".join(f"- {i.type} {i.neighbour} ({i.name}): {i.reason}" for i in sig.influences[:6])
    return "ERROR: 'kind' must be 'score' or 'network'"
