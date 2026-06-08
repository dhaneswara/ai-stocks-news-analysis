from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator, Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from app.analysis.analyzer import (
    _JSON_SCHEMA_HINT, _SYSTEM_PROMPT, _filter_incoherent_signals,
    _snap_signals, _to_result, analyze, build_user_prompt, extract_json,
)
from app.llm.base import LLMProvider
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
    raw: str = ""                         # the model's raw output for this turn (trace/debug visibility)


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


_THOUGHT_RE = re.compile(r"Thought:\s*(.*?)(?=\n\s*(?:Action:|Final Answer:)|\Z)", re.S)
_ACTION_RE = re.compile(r"Action:\s*([A-Za-z_]\w*)", re.S)  # tool NAME only; args parsed separately
_FINAL_RE = re.compile(r"Final Answer:\s*(.*)\Z", re.S)


@dataclass
class ParsedStep:
    thought: str
    action: Optional[str]          # tool name, or None
    action_args: dict
    final_json: Optional[dict]     # parsed Final Answer JSON, or None


def _extract_args(after_name: str) -> dict:
    """Pull the first JSON object after an action name, tolerating a leading `(`, code fences,
    and any trailing prose. `json.JSONDecoder().raw_decode` reads exactly one value and ignores
    the rest, so nested braces AND a hallucinated `Observation:` after the call are both fine."""
    start = after_name.find("{")
    if start == -1:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(after_name[start:])
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def parse_step(text: str) -> ParsedStep:
    """Tolerant ReAct parser. Real models add trailing text, code fences, and skip the literal
    'Thought:' label — the action is matched by NAME (not anchored to end-of-string) and its
    args are JSON-decoded out of the surrounding noise, so a turn is no longer dropped wholesale."""
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
        if not thought:  # no 'Thought:' label — use any reasoning written before the Action line
            thought = text[: action_m.start()].strip()[:600]
        return ParsedStep(thought, action_m.group(1), _extract_args(text[action_m.end():]), None)

    # Last resort: some models skip the protocol and emit the answer JSON directly, with no
    # 'Final Answer:' label (a model deciding the seeded context is enough is a valid outcome).
    # Accept it as the final answer iff it carries the schema signature — a tool-result-shaped
    # blob without 'current_recommendation' stays a non-final step.
    try:
        obj = extract_json(text)
        if isinstance(obj, dict) and "current_recommendation" in obj:
            return ParsedStep(thought, None, {}, obj)
    except (json.JSONDecodeError, ValueError):
        pass

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


TOOLS: list[Tool] = [
    Tool("fetch_news", "Search recent news headlines for a topic worth investigating.",
         '{"query": str, "limit": int=5}', _tool_fetch_news),
    Tool("get_fundamentals", "Pull deeper financials beyond the snapshot.",
         '{"detail": "earnings|revenue|margins|valuation|growth"}', _tool_get_fundamentals),
    Tool("price_window", "Summarize a recent price window; optional indicator (rsi/sma).",
         '{"lookback_days": int=21, "indicator": "rsi|sma" (optional), "period": int (optional)}',
         _tool_price_window),
    Tool("app_signals", "Get the app's deterministic opportunity score or company-network signal.",
         '{"kind": "score|network", "ticker": str (optional)}', _tool_app_signals),
]
TOOL_BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}

# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------

DEFAULT_MAX_STEPS = 6
MAX_TOOL_CALLS = 8        # secondary guard; under the default max_steps the step cap binds first
_MAX_OBS_CHARS = 1500


class _AgentFailure(Exception):
    """Internal: the agent could not produce a valid final answer; triggers single-shot fallback."""


def _finalize(payload: dict, stock: StockData, provider_name: str, model: str) -> AnalysisResult:
    result = _to_result(payload, stock.ticker, provider_name, model)
    result.market_mood = stock.market_mood
    result.network = stock.network
    return _filter_incoherent_signals(_snap_signals(result, stock), stock)


class AgentEvent(BaseModel):
    type: Literal["step", "final", "error"]
    step: Optional[AgentStep] = None
    result: Optional[AnalysisResult] = None
    trace: Optional[AgentTrace] = None
    message: str = ""


class ReActAgent:
    def __init__(self, tools: Optional[list[Tool]] = None, max_steps: int = DEFAULT_MAX_STEPS) -> None:
        self.tools = tools if tools is not None else TOOLS
        self.tool_by_name = {t.name: t for t in self.tools}
        self.max_steps = max_steps

    def stream(self, provider: LLMProvider, model: str, provider_name: str,
               ctx: ToolContext) -> Iterator[AgentEvent]:
        """Single source of truth: yields one 'step' AgentEvent per completed step, then a
        terminal 'final' carrying the AnalysisResult + AgentTrace. Never raises — any agent
        failure falls back to the single-shot analyze()."""
        stock = ctx.stock
        trace = AgentTrace(ticker=stock.ticker, provider=provider_name, model=model,
                           started_at=_now_iso())
        t0 = time.monotonic()
        try:
            for step in self._run_loop(provider, model, provider_name, ctx, trace):
                yield AgentEvent(type="step", step=step)
            result = trace.final  # set by _run_loop on a valid final answer
        except _AgentFailure:
            # Agent couldn't produce a valid final answer — fall back to the single-shot path.
            # An LLMError from here propagates by design: nothing is left to fall back to.
            trace.fell_back = True
            result = analyze(stock, provider, model=model, provider_name=provider_name)
            trace.final = result
        trace.elapsed_ms = int((time.monotonic() - t0) * 1000)
        yield AgentEvent(type="final", result=result, trace=trace)

    def run(self, provider: LLMProvider, model: str, provider_name: str,
            ctx: ToolContext) -> tuple[AnalysisResult, AgentTrace]:
        """Drain stream() to its terminal event; return (result, trace). For CLI / non-streaming."""
        result: Optional[AnalysisResult] = None
        trace: Optional[AgentTrace] = None
        for ev in self.stream(provider, model, provider_name, ctx):
            if ev.type == "final":
                result, trace = ev.result, ev.trace
        return result, trace

    def _run_loop(self, provider: LLMProvider, model: str, provider_name: str,
                  ctx: ToolContext, trace: AgentTrace) -> Iterator[AgentStep]:
        """Yields each AgentStep as it completes; sets trace.final and returns on a valid final
        answer; raises _AgentFailure on parse_error / no_action / max_steps."""
        stock = ctx.stock
        system = build_react_system(self.tools)
        transcript = build_user_prompt(stock)
        tool_calls = 0
        nudged = False
        for i in range(self.max_steps):
            raw = provider.complete(system, transcript, json_mode=False)  # ReAct needs free text
            parsed = parse_step(raw)
            step = AgentStep(index=i, thought=parsed.thought, raw=raw)
            if parsed.final_json is not None:
                step.is_final = True
                trace.steps.append(step)
                yield step
                try:
                    trace.final = _finalize(parsed.final_json, stock, provider_name, model)
                    return
                except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                    trace.stopped_reason = "parse_error"
                    raise _AgentFailure("invalid final answer") from exc
            if parsed.action in self.tool_by_name and tool_calls < MAX_TOOL_CALLS:
                tool_calls += 1
                obs = self._run_tool(parsed.action, parsed.action_args, ctx)
                step.action = parsed.action
                step.action_args = parsed.action_args
                step.observation = obs
                trace.steps.append(step)
                yield step
                transcript += (
                    f"\n\nThought: {parsed.thought}\nAction: {parsed.action}"
                    f"({json.dumps(parsed.action_args)})\nObservation: {obs}\n"
                )
                continue
            trace.steps.append(step)
            yield step
            if not nudged:
                nudged = True
                transcript += (
                    "\n\nYour reply had no valid Action or Final Answer. Reply with exactly one "
                    "'Action: <tool>({json})' or 'Final Answer: {json}'."
                )
                continue
            trace.stopped_reason = "no_action"
            raise _AgentFailure("no valid action or final answer")
        trace.stopped_reason = "max_steps"
        raise _AgentFailure("reached max steps")

    def _run_tool(self, name: str, args: dict, ctx: ToolContext) -> str:
        try:
            obs = self.tool_by_name[name].run(args, ctx)
        except Exception as exc:  # noqa: BLE001 — tool errors must never break the loop
            return f"ERROR: {name} failed: {exc}"
        return obs if len(obs) <= _MAX_OBS_CHARS else obs[:_MAX_OBS_CHARS] + " …(truncated)"
