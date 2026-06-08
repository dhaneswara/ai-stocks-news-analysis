# Agentic Deep Analysis — Phase 1 (Core ReAct Agent + Tools) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bounded, prompted-ReAct agent that produces the existing `AnalysisResult` by reasoning over tools, callable via `ReActAgent.run()`, with an always-on fallback to the current single-shot analysis.

**Architecture:** A new `backend/app/analysis/agent.py` implements a text-protocol ReAct loop on top of the existing `LLMProvider.complete(system, user) -> str` (no provider changes). Each turn the model emits `Thought` + (`Action: tool({json})` | `Final Answer: {json}`); Python parses it, runs the tool, appends an `Observation`, and re-calls until a final answer. Four tools wrap existing data/analysis code. The loop accumulates an `AgentTrace`. On any failure it falls back to the existing `analyze()`. Final-answer JSON reuses the exact `AnalysisResult` schema, so `_snap_signals`/`_filter_incoherent_signals` and all downstream code are reused unchanged.

**Tech Stack:** Python 3.11, Pydantic v2, pytest. Reuses `app/analysis/analyzer.py`, `app/analysis/indicators.py`, `app/analysis/network.py`, `app/data/market.py`, `app/data/news.py`, `app/screener/service.py`.

**Scope:** This plan is **Phase 1 of 4** from the design spec
([2026-06-08-agentic-deep-analysis-design.md](../specs/2026-06-08-agentic-deep-analysis-design.md) §16). It delivers a fully tested backend agent with no HTTP/UI surface. Deferred to their own plans: **Phase 2** (SSE streaming endpoint + Deep Analysis button + live trace panel), **Phase 3** (trace persistence + `GET /traces/{ticker}`), **Phase 4** (evaluation `mode` tagging + fast-vs-deep comparison).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/app/analysis/agent.py` (create) | The whole agent: data types (`ToolContext`, `Tool`, `AgentStep`, `AgentTrace`), the `parse_step` parser, the ReAct prompt builder, the four tools, the `TOOLS` registry, and the `ReActAgent` loop. |
| `backend/app/data/news.py` (modify) | Add `search_news(query, limit)` — a targeted feed search for the `fetch_news` tool. |
| `backend/tests/test_agent.py` (create) | All Phase 1 tests. |

All names introduced (so later tasks stay consistent): `ToolContext`, `Tool`, `ParsedStep`, `parse_step`, `AgentStep`, `AgentTrace`, `render_tool_catalog`, `build_react_system`, `_tool_fetch_news`, `_tool_get_fundamentals`, `_tool_price_window`, `_tool_app_signals`, `_network_signal_for`, `TOOLS`, `TOOL_BY_NAME`, `_finalize`, `_now_iso`, `_AgentFailure`, `ReActAgent`. Constants: `DEFAULT_MAX_STEPS = 6`, `MAX_TOOL_CALLS = 8`, `_MAX_OBS_CHARS = 1500`.

> All test commands run from the `backend/` directory with the project venv active (`backend/.venv`). pytest config lives in `backend/pyproject.toml` (`pythonpath = ["."]`, `testpaths = ["tests"]`).

---

### Task 1: Agent data types

**Files:**
- Create: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_agent.py
from app.analysis.agent import AgentStep, AgentTrace, Tool, ToolContext
from app.config.cache import Cache
from app.models.schemas import Settings
from tests.test_analyzer import _stock  # reuse the existing minimal StockData factory


def test_tool_context_holds_dependencies():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    assert ctx.stock.ticker == "AAPL"
    assert ctx.settings.active_provider == "anthropic"


def test_tool_dataclass_fields():
    t = Tool("echo", "echoes", '{"q": str}', lambda args, ctx: "ok")
    assert t.name == "echo"
    assert t.run({}, None) == "ok"


def test_agent_trace_serializes_with_steps():
    trace = AgentTrace(ticker="AAPL", provider="fake", model="m", started_at="2026-06-08T00:00:00Z")
    trace.steps.append(AgentStep(index=0, thought="hi", action="echo", action_args={"q": "x"},
                                 observation="ok"))
    dumped = trace.model_dump()
    assert dumped["ticker"] == "AAPL"
    assert dumped["stopped_reason"] == "final"
    assert dumped["fell_back"] is False
    assert dumped["steps"][0]["action"] == "echo"
    assert dumped["steps"][0]["is_final"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.agent'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/analysis/agent.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from pydantic import BaseModel, Field

from app.config.cache import Cache
from app.models.schemas import AnalysisResult, Settings, StockData


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
    stopped_reason: str = "final"          # final | max_steps | parse_error | no_action
    fell_back: bool = False                # True when the single-shot fallback produced `final`
    steps: list[AgentStep] = Field(default_factory=list)
    final: Optional[AnalysisResult] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): add ReAct agent data types"
```

---

### Task 2: ReAct response parser

**Files:**
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
from app.analysis.agent import parse_step


def test_parse_action_with_json_args():
    p = parse_step('Thought: check the news\nAction: fetch_news({"query": "NVDA earnings", "limit": 3})')
    assert p.thought == "check the news"
    assert p.action == "fetch_news"
    assert p.action_args == {"query": "NVDA earnings", "limit": 3}
    assert p.final_json is None


def test_parse_final_answer_json():
    p = parse_step('Thought: done\nFinal Answer: {"current_recommendation": "buy"}')
    assert p.action is None
    assert p.final_json == {"current_recommendation": "buy"}


def test_parse_final_answer_in_code_fence():
    p = parse_step('Thought: x\nFinal Answer:\n```json\n{"a": 1}\n```')
    assert p.final_json == {"a": 1}


def test_parse_garbage_yields_no_action_no_final():
    p = parse_step("I am not following the format at all.")
    assert p.action is None
    assert p.final_json is None


def test_parse_action_with_malformed_args_defaults_to_empty():
    p = parse_step("Thought: t\nAction: price_window(not json)")
    assert p.action == "price_window"
    assert p.action_args == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k parse -v`
Expected: FAIL with `ImportError: cannot import name 'parse_step'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/analysis/agent.py
import json
import re

from app.analysis.analyzer import extract_json

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -k parse -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): parse ReAct Thought/Action/Final-Answer turns"
```

---

### Task 3: Tool catalog + ReAct system prompt

**Files:**
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
from app.analysis.agent import build_react_system, render_tool_catalog

_DUMMY_TOOLS = [Tool("fetch_news", "Search recent headlines.", '{"query": str}', lambda a, c: "")]


def test_render_tool_catalog_lists_name_args_and_description():
    cat = render_tool_catalog(_DUMMY_TOOLS)
    assert "fetch_news" in cat
    assert '{"query": str}' in cat
    assert "Search recent headlines." in cat


def test_build_react_system_includes_protocol_catalog_and_schema():
    sysprompt = build_react_system(_DUMMY_TOOLS)
    assert "Action:" in sysprompt
    assert "Final Answer:" in sysprompt
    assert "fetch_news" in sysprompt          # the catalog
    assert "current_recommendation" in sysprompt  # the AnalysisResult schema hint
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k catalog -v`
Expected: FAIL with `ImportError: cannot import name 'render_tool_catalog'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/analysis/agent.py
from app.analysis.analyzer import _JSON_SCHEMA_HINT, _SYSTEM_PROMPT


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -k catalog -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): build ReAct system prompt with tool catalog"
```

---

### Task 4: `search_news` helper + `fetch_news` tool

**Files:**
- Modify: `backend/app/data/news.py`
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
from app.analysis import agent as agent_mod
from app.models.schemas import NewsItem


def test_fetch_news_tool_formats_headlines(monkeypatch):
    monkeypatch.setattr(agent_mod, "search_news", lambda q, limit=5: [
        NewsItem(title="NVDA beats", source="Reuters", published_at="2026-06-01"),
        NewsItem(title="Guidance raised", source="CNBC", published_at="2026-06-02"),
    ])
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_fetch_news({"query": "NVDA earnings", "limit": 2}, ctx)
    assert "NVDA beats (Reuters)" in out
    assert "Guidance raised (CNBC)" in out


def test_fetch_news_tool_requires_query():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_fetch_news({}, ctx)
    assert out.startswith("ERROR")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k fetch_news -v`
Expected: FAIL with `AttributeError: module 'app.analysis.agent' has no attribute 'search_news'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/data/news.py (after parse_feed)
def search_news(query: str, limit: int = 5) -> list[NewsItem]:
    """Targeted feed search for an arbitrary query (used by the deep-analysis agent)."""
    try:
        return parse_feed(_fetch_feed(query), limit)
    except Exception:
        return []
```

```python
# add to backend/app/analysis/agent.py
from app.data.news import search_news


def _tool_fetch_news(args: dict, ctx: ToolContext) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "ERROR: 'query' is required"
    limit = max(1, min(10, int(args.get("limit", 5) or 5)))
    items = search_news(f"{query} stock", limit)
    if not items:
        return "(no headlines found)"
    return "\n".join(f"- [{n.published_at}] {n.title} ({n.source})" for n in items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -k fetch_news -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/news.py backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): fetch_news tool + search_news helper"
```

---

### Task 5: `get_fundamentals` tool

**Files:**
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
def test_get_fundamentals_tool_returns_requested_fields(monkeypatch):
    monkeypatch.setattr(agent_mod, "fetch_info", lambda ticker: {
        "trailingEps": 5.2, "forwardEps": 6.1, "earningsGrowth": 0.18, "marketCap": 1e12})
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_get_fundamentals({"detail": "earnings"}, ctx)
    assert "trailingEps: 5.2" in out
    assert "forwardEps: 6.1" in out
    assert "marketCap" not in out  # not part of the 'earnings' field set


def test_get_fundamentals_tool_unknown_detail():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_get_fundamentals({"detail": "nonsense"}, ctx)
    assert out.startswith("ERROR")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k get_fundamentals -v`
Expected: FAIL with `AttributeError: module 'app.analysis.agent' has no attribute '_tool_get_fundamentals'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/analysis/agent.py
from app.data.market import fetch_info

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -k get_fundamentals -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): get_fundamentals tool"
```

---

### Task 6: `price_window` tool

**Files:**
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

> Note: v1 supports `lookback_days` over the already-gathered candles plus an optional `indicator` (`rsi`/`sma`). The spec's `around="last_earnings"` event-study mode is **deferred** — it needs an earnings-calendar fetch not currently in the data layer. The agent never sees `around`, so it cannot call it.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
from app.models.schemas import Candle


def _stock_with_prices():
    s = _stock()
    s.candles = [Candle(time=f"2026-05-{d:02d}", open=p, high=p, low=p, close=p, volume=1)
                 for d, p in [(1, 100.0), (4, 102.0), (5, 98.0), (6, 105.0), (7, 110.0)]]
    return s


def test_price_window_tool_summarizes_window():
    ctx = ToolContext(stock=_stock_with_prices(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_price_window({"lookback_days": 5}, ctx)
    assert "last 5 trading days" in out
    assert "100.00 -> 110.00" in out        # start -> end
    assert "98.00 / 110.00" in out          # low / high


def test_price_window_tool_no_candles():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))  # _stock() has []
    out = agent_mod._tool_price_window({"lookback_days": 5}, ctx)
    assert out == "(no price history)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k price_window -v`
Expected: FAIL with `AttributeError: module 'app.analysis.agent' has no attribute '_tool_price_window'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/analysis/agent.py
import pandas as pd

from app.analysis.indicators import rsi, sma


def _tool_price_window(args: dict, ctx: ToolContext) -> str:
    candles = ctx.stock.candles
    if not candles:
        return "(no price history)"
    lookback = max(2, min(len(candles), int(args.get("lookback_days", 21) or 21)))
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
        period = int(args.get("period", 14 if indicator == "rsi" else 50) or 14)
        series = pd.Series([c.close for c in candles], dtype="float64")
        computed = rsi(series, period) if indicator == "rsi" else sma(series, period)
        val = computed.iloc[-1]
        if pd.notna(val):
            out.append(f"{indicator.upper()}({period}) latest: {float(val):.2f}")
    return "\n".join(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -k price_window -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): price_window tool"
```

---

### Task 7: `app_signals` tool

**Files:**
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
from app.models.schemas import StockScore


def test_app_signals_score(monkeypatch):
    monkeypatch.setattr(agent_mod, "score_one", lambda t, s, c: StockScore(
        ticker=t, name="Apple Inc.", price=150.0, change_pct=0.7, score=63.0,
        direction="buy", reasons=["RSI 33 (oversold)", "above SMA50"]))
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_app_signals({"kind": "score"}, ctx)
    assert "63/100" in out
    assert "lean buy" in out
    assert "RSI 33 (oversold)" in out


def test_app_signals_invalid_kind():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_app_signals({"kind": "bogus"}, ctx)
    assert out.startswith("ERROR")


def test_app_signals_network_none_when_no_edges(monkeypatch):
    monkeypatch.setattr(agent_mod, "_network_signal_for", lambda ticker, ctx: None)
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_app_signals({"kind": "network"}, ctx)
    assert "no company-network signal" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k app_signals -v`
Expected: FAIL with `AttributeError: module 'app.analysis.agent' has no attribute '_tool_app_signals'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/analysis/agent.py
from app.analysis.network import compute_network_signal, incident_edges
from app.models.schemas import NetworkSignal
from app.network.store import effective_graph
from app.screener.service import score_one
from app.screener.store import load_snapshot


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -k app_signals -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): app_signals tool (score + network)"
```

---

### Task 8: `TOOLS` registry

**Files:**
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
from app.analysis.agent import TOOL_BY_NAME, TOOLS


def test_registry_has_the_four_tools():
    assert {t.name for t in TOOLS} == {"fetch_news", "get_fundamentals", "price_window", "app_signals"}
    assert TOOL_BY_NAME["fetch_news"].run is agent_mod._tool_fetch_news
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k registry -v`
Expected: FAIL with `ImportError: cannot import name 'TOOLS'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/analysis/agent.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent.py -k registry -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): register the four agent tools"
```

---

### Task 9: The `ReActAgent` loop + fallback

**Files:**
- Modify: `backend/app/analysis/agent.py`
- Test: `backend/tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_agent.py
import json

from app.analysis.agent import ReActAgent
from tests.test_analyzer import VALID_PAYLOAD, FakeProvider, _stock

_ECHO = Tool("echo", "echo a value", '{"q": str}', lambda args, ctx: f"observed:{args.get('q', '')}")


def _ctx(stock=None):
    return ToolContext(stock=stock or _stock(), settings=Settings(), cache=Cache(":memory:"))


def test_agent_returns_final_answer_in_one_turn():
    provider = FakeProvider([f'Thought: enough info\nFinal Answer: {json.dumps(VALID_PAYLOAD)}'])
    agent = ReActAgent(tools=[_ECHO])
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.current_recommendation == "buy"
    assert trace.stopped_reason == "final"
    assert trace.fell_back is False
    assert trace.steps[-1].is_final is True
    assert provider.calls == 1


def test_agent_runs_a_tool_then_finalizes():
    provider = FakeProvider([
        'Thought: check echo\nAction: echo({"q": "hi"})',
        f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}',
    ])
    agent = ReActAgent(tools=[_ECHO])
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.sentiment == "bullish"
    assert trace.steps[0].action == "echo"
    assert trace.steps[0].observation == "observed:hi"
    assert provider.calls == 2


def test_agent_falls_back_to_single_shot_on_max_steps():
    # Always emits a tool action, never a final answer -> hits max_steps -> single-shot fallback.
    # The fallback analyze() consumes one more provider output (valid JSON).
    actions = ['Thought: loop\nAction: echo({"q": "x"})'] * 3
    provider = FakeProvider([*actions, json.dumps(VALID_PAYLOAD)])
    agent = ReActAgent(tools=[_ECHO], max_steps=3)
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.current_recommendation == "buy"   # came from the fallback
    assert trace.stopped_reason == "max_steps"
    assert trace.fell_back is True


def test_agent_nudges_once_then_falls_back_on_garbage():
    # Two garbage turns (one nudge, then still garbage) -> fallback consumes the final valid JSON.
    provider = FakeProvider(["garbage one", "garbage two", json.dumps(VALID_PAYLOAD)])
    agent = ReActAgent(tools=[_ECHO], max_steps=5)
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.current_recommendation == "buy"
    assert trace.stopped_reason == "no_action"
    assert trace.fell_back is True


def test_agent_tool_error_becomes_observation_not_crash():
    boom = Tool("boom", "always raises", "{}", lambda args, ctx: (_ for _ in ()).throw(RuntimeError("nope")))
    provider = FakeProvider([
        'Thought: try boom\nAction: boom({})',
        f'Thought: recover\nFinal Answer: {json.dumps(VALID_PAYLOAD)}',
    ])
    agent = ReActAgent(tools=[boom])
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert "ERROR: boom failed: nope" in trace.steps[0].observation
    assert result.current_recommendation == "buy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k agent_ -v`
Expected: FAIL with `ImportError: cannot import name 'ReActAgent'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/analysis/agent.py
import time

from pydantic import ValidationError

from app.analysis.analyzer import (
    _filter_incoherent_signals,
    _snap_signals,
    _to_result,
    analyze,
    build_user_prompt,
)
from app.llm.base import LLMProvider

DEFAULT_MAX_STEPS = 6
MAX_TOOL_CALLS = 8
_MAX_OBS_CHARS = 1500


class _AgentFailure(Exception):
    """Internal: the agent could not produce a valid final answer; triggers single-shot fallback."""


def _finalize(payload: dict, stock: StockData, provider_name: str, model: str) -> AnalysisResult:
    result = _to_result(payload, stock.ticker, provider_name, model)
    result.market_mood = stock.market_mood
    result.network = stock.network
    return _filter_incoherent_signals(_snap_signals(result, stock), stock)


class ReActAgent:
    def __init__(self, tools: Optional[list[Tool]] = None, max_steps: int = DEFAULT_MAX_STEPS) -> None:
        self.tools = tools if tools is not None else TOOLS
        self.tool_by_name = {t.name: t for t in self.tools}
        self.max_steps = max_steps

    def run(self, provider: LLMProvider, model: str, provider_name: str,
            ctx: ToolContext) -> tuple[AnalysisResult, AgentTrace]:
        stock = ctx.stock
        trace = AgentTrace(ticker=stock.ticker, provider=provider_name, model=model,
                           started_at=_now_iso())
        t0 = time.monotonic()
        try:
            result = self._drive(provider, model, provider_name, ctx, trace)
        except _AgentFailure:
            trace.fell_back = True
            result = analyze(stock, provider, model=model, provider_name=provider_name)
        trace.final = result
        trace.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result, trace

    def _drive(self, provider: LLMProvider, model: str, provider_name: str,
               ctx: ToolContext, trace: AgentTrace) -> AnalysisResult:
        stock = ctx.stock
        system = build_react_system(self.tools)
        transcript = build_user_prompt(stock)
        tool_calls = 0
        nudged = False
        for i in range(self.max_steps):
            raw = provider.complete(system, transcript)
            parsed = parse_step(raw)
            step = AgentStep(index=i, thought=parsed.thought)
            if parsed.final_json is not None:
                step.is_final = True
                trace.steps.append(step)
                try:
                    return _finalize(parsed.final_json, stock, provider_name, model)
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
                transcript += (
                    f"\n\nThought: {parsed.thought}\nAction: {parsed.action}"
                    f"({json.dumps(parsed.action_args)})\nObservation: {obs}\n"
                )
                continue
            trace.steps.append(step)
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
```

- [ ] **Step 4: Run the full agent test file to verify everything passes**

Run: `python -m pytest tests/test_agent.py -v`
Expected: PASS (all tests across Tasks 1–9)

- [ ] **Step 5: Run the whole backend suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: PASS (existing suite unaffected; new `test_agent.py` green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): ReAct loop with tool dispatch and single-shot fallback"
```

---

## Self-Review

**Spec coverage (against the design spec):**
- §5/§6 ReAct loop, seeded transcript, finalize reuse — Task 9 (`_drive`, `_finalize`). ✓
- §6 generator-source-of-truth — Phase 1 ships `run()` (drains the loop); the streaming generator is Phase 2 (noted in scope). ✓ (intentional phasing)
- §7 four tools wrapping existing code — Tasks 4–7. ✓ (`around="last_earnings"` explicitly deferred in Task 6 note)
- §8 ReAct protocol — Task 3. ✓
- §9 `AgentTrace`/`AgentStep` — Task 1 (persistence to SQLite is Phase 3, per scope). ✓
- §13 step cap, per-tool cap, tool-errors-as-observations, single-shot fallback — Task 9. ✓
- §10/§11/§12 SSE + endpoints + frontend — **Phase 2/3**, not this plan. ✓ (declared in Scope)
- §14 eval `mode` tagging — **Phase 4**. ✓
- §15 testing: per-tool, mock-provider loop, parser, fallback — Tasks 2,4–7,9. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete and runnable. The Task 6 note is a scoped deferral (the agent never sees the deferred arg), not a placeholder.

**Type consistency:** `ParsedStep(thought, action, action_args, final_json)` produced by `parse_step` and consumed in `_drive` ✓. `AgentStep` fields (`action`, `action_args`, `observation`, `is_final`) set in `_drive` match Task 1 ✓. `AgentTrace.stopped_reason`/`fell_back` set in `run`/`_drive` match Task 1 ✓. `ToolContext(stock, settings, cache)` used consistently in all tool tests ✓. `ReActAgent.run(provider, model, provider_name, ctx)` arg order matches all Task 9 tests ✓. Tools reuse verified signatures: `search_news(query, limit)`, `fetch_info(ticker)`, `rsi/sma(series, n)`, `score_one(ticker, settings, cache)`, `incident_edges/compute_network_signal/effective_graph/load_snapshot` ✓.

## Notes for the implementer
- `_stock()`, `VALID_PAYLOAD`, and `FakeProvider` are imported from the existing `tests/test_analyzer.py` — do not redefine them.
- The autouse `conftest.py` fixture stubs Truth Social, so the fallback `analyze()` path stays hermetic (no live HTTP) in `test_agent_*` tests.
- Keep all four `import` blocks at the top of `agent.py` when done (tasks add them incrementally for readability; a final tidy-up into one import block is fine and won't change behavior).
