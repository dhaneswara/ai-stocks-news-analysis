# AI Chat Assistant (multi-turn ReAct, streaming) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/chat` page with a multi-turn, ticker-agnostic ReAct assistant that streams its reasoning steps live and answers in markdown, drawing on the app's data (prices/fundamentals/technicals, news, geopolitics, ontology graph + network signal, opportunity score, portfolio board, evaluation track record).

**Architecture:** A new `backend/app/chat/` package holds a `ChatAgent` (a sibling to the existing single-ticker `ReActAgent`) and a generalized tool registry whose tools take explicit args and resolve app data on demand. The frontend owns the conversation; each turn POSTs the full history to a stateless SSE endpoint `POST /api/chat/stream` and streams `ChatEvent`s (step/final/error). Because EventSource is GET-only, the chat transport uses `fetch` + `ReadableStream` with a small hand-rolled SSE parser. Chat is exploratory: nothing is recorded to the prediction/trace stores.

**Tech Stack:** Backend — Python 3.13, FastAPI, Pydantic, pytest (venv at `backend/.venv`). Frontend — React 18 + TypeScript + Vite, React Router v7, Vitest + Testing Library. Reuses `AgentStep`, `parse_step` regex helpers, `render_tool_catalog`, `TracePanel`, the `_sse` helper, and the design tokens.

**Spec:** [docs/superpowers/specs/2026-06-14-ai-chat-assistant-design.md](../specs/2026-06-14-ai-chat-assistant-design.md)

**Conventions reminder:** Run pytest as `.venv/Scripts/python.exe -m pytest -q` **from `backend/`**. Run frontend tests as `npx vitest run <path>` **from `frontend/`**. Conventional Commits, one per task, scope `backend`/`frontend`. **No `Co-Authored-By` trailer.** Branch `feat/ai-chat-assistant` (already created; the spec is committed there).

---

## File Structure

**Backend (new)**
- `backend/app/chat/__init__.py` — empty package marker.
- `backend/app/chat/tools.py` — `ChatContext`, `ChatTool`, the 10 tool functions, `TOOLS`/`TOOL_BY_NAME`.
- `backend/app/chat/agent.py` — `ChatMessage`, `ChatEvent`, `ParsedChatStep`, `parse_chat_step`, `build_chat_system`, `ChatAgent`.
- `backend/tests/test_chat_tools.py` — tool unit tests.
- `backend/tests/test_chat_agent.py` — parser/prompt/loop tests with a fake provider.

**Backend (modified)**
- `backend/app/api/routes.py` — add `POST /api/chat/stream`; extend the `_sse` type union with `ChatEvent`.
- `backend/tests/test_api.py` — add the chat endpoint SSE test.

**Frontend (new)**
- `frontend/src/hooks/useChat.ts` — conversation state + streaming turn manager.
- `frontend/src/state/chatState.tsx` — `ChatProvider` (above the router) + `useChatContext`.
- `frontend/src/components/Markdown.tsx` — minimal markdown renderer for answers.
- `frontend/src/pages/Chat.tsx` — the chat page.
- `frontend/src/hooks/useChat.test.tsx`, `frontend/src/components/Markdown.test.tsx`, `frontend/src/pages/Chat.test.tsx` — tests.

**Frontend (modified)**
- `frontend/src/types.ts` — add `ChatMessage`, `ChatEvent`, `ChatTurn`.
- `frontend/src/api/client.ts` — add `streamChat` + the SSE-frame parser.
- `frontend/src/App.tsx` — add the `Chat` route, nav link, and `ChatProvider` wrap.
- `frontend/src/styles.css` — chat page styles.

---

## Phase 1 — Backend tools

### Task 1: Create the `chat` package and `ChatContext`/`ChatTool`

**Files:**
- Create: `backend/app/chat/__init__.py`
- Create: `backend/app/chat/tools.py`
- Test: `backend/tests/test_chat_tools.py`

- [ ] **Step 1: Create the empty package marker**

Create `backend/app/chat/__init__.py` with no content (empty file).

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_chat_tools.py`:

```python
from app.chat.tools import TOOLS, TOOL_BY_NAME, ChatContext, ChatTool
from app.config.cache import Cache
from app.models.schemas import Settings
from tests.test_analyzer import FakeProvider


def _ctx():
    return ChatContext(settings=Settings(), cache=Cache(":memory:"),
                       provider=FakeProvider([]), prediction_store=None)


def test_chat_context_holds_dependencies():
    ctx = _ctx()
    assert ctx.settings.active_provider == "anthropic"
    assert ctx.prediction_store is None


def test_chat_tool_dataclass_fields():
    t = ChatTool("echo", "echoes", '{"q": str}', lambda args, ctx: "ok")
    assert t.name == "echo"
    assert t.run({}, None) == "ok"
```

- [ ] **Step 3: Run the test to verify it fails**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chat.tools'`.

- [ ] **Step 4: Write the minimal implementation**

Create `backend/app/chat/tools.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from app.config.cache import Cache
from app.evaluation.store import PredictionStore
from app.llm.base import LLMProvider
from app.models.schemas import Settings


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


TOOLS: list[ChatTool] = []
TOOL_BY_NAME: dict[str, ChatTool] = {}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/__init__.py backend/app/chat/tools.py backend/tests/test_chat_tools.py
git commit -m "feat(backend): scaffold chat package with ChatContext and ChatTool"
```

---

### Task 2: Stock / price / news tools

**Files:**
- Modify: `backend/app/chat/tools.py`
- Test: `backend/tests/test_chat_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat_tools.py`:

```python
import app.chat.tools as chat_tools
from app.models.schemas import (
    Candle, Fundamentals, IndicatorPoint, Indicators, NewsItem, PriceSummary, StockData,
)


def _rich_stock():
    return StockData(
        ticker="NVDA", company_name="NVIDIA Corp", as_of="2026-06-12", exchange="NASDAQ",
        sector="Technology",
        price=PriceSummary(current=120.0, change=2.0, change_pct=1.7),
        candles=[Candle(time=f"2026-05-{d:02d}", open=p, high=p, low=p, close=p, volume=1)
                 for d, p in [(1, 100.0), (4, 102.0), (5, 98.0), (6, 105.0), (7, 110.0)]],
        fundamentals=Fundamentals(market_cap=3e12, pe_ratio=45.0, eps=2.6,
                                  week52_high=140.0, week52_low=80.0),
        indicators=Indicators(rsi14=[IndicatorPoint(time="2026-05-07", value=58.3)],
                              dist_from_52wk_high_pct=-14.3),
        news=[],
    )


def test_get_stock_formats_snapshot(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_stock_data", lambda t, p, ip, c: _rich_stock())
    out = chat_tools._tool_get_stock({"ticker": "nvda"}, _ctx())
    assert "NVDA" in out and "NVIDIA Corp" in out
    assert "120.00" in out
    assert "P/E 45.0" in out
    assert "RSI14 58.3" in out


def test_get_stock_requires_ticker():
    assert chat_tools._tool_get_stock({}, _ctx()).startswith("ERROR")


def test_get_stock_missing_data_is_error(monkeypatch):
    def _boom(t, p, ip, c):
        raise ValueError("no data")
    monkeypatch.setattr(chat_tools, "get_stock_data", _boom)
    assert chat_tools._tool_get_stock({"ticker": "ZZZZ"}, _ctx()).startswith("ERROR")


def test_price_window_summarizes(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_stock_data", lambda t, p, ip, c: _rich_stock())
    out = chat_tools._tool_price_window({"ticker": "NVDA", "lookback_days": 5}, _ctx())
    assert "last 5 trading days" in out
    assert "100.00 -> 110.00" in out


def test_search_news_formats(monkeypatch):
    monkeypatch.setattr(chat_tools, "search_news", lambda q, limit=5: [
        NewsItem(title="Chip demand surges", source="Reuters", published_at="2026-06-10")])
    out = chat_tools._tool_search_news({"query": "AI chips"}, _ctx())
    assert "Chip demand surges (Reuters)" in out


def test_search_news_requires_query():
    assert chat_tools._tool_search_news({}, _ctx()).startswith("ERROR")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: FAIL with `AttributeError: module 'app.chat.tools' has no attribute 'get_stock_data'` / `_tool_get_stock`.

- [ ] **Step 3: Implement the tools**

In `backend/app/chat/tools.py`, add the imports at the top (after the existing imports):

```python
import pandas as pd

from app.analysis.indicators import rsi, sma
from app.data.news import search_news
from app.services.stock_service import get_stock_data
```

Add these helpers and tool functions (above the `TOOLS` list):

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/tools.py backend/tests/test_chat_tools.py
git commit -m "feat(backend): add chat stock/price/news tools"
```

---

### Task 3: Signal tools — opportunity_score, network_signal, geopolitics, track_record

**Files:**
- Modify: `backend/app/chat/tools.py`
- Test: `backend/tests/test_chat_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat_tools.py`:

```python
from app.models.schemas import (
    GraphEdge, KnowledgeGraph, NetworkInfluence, NetworkSignal, StockScore, TruthPost, MarketMood,
)


def test_opportunity_score_formats(monkeypatch):
    monkeypatch.setattr(chat_tools, "score_one", lambda t, s, c: StockScore(
        ticker=t, name="NVIDIA", price=120.0, change_pct=1.7, score=71.0,
        direction="buy", reasons=["RSI 40 (recovering)", "above SMA50"]))
    out = chat_tools._tool_opportunity_score({"ticker": "NVDA"}, _ctx())
    assert "71/100" in out and "buy" in out and "RSI 40 (recovering)" in out


def test_opportunity_score_requires_ticker():
    assert chat_tools._tool_opportunity_score({}, _ctx()).startswith("ERROR")


def test_network_signal_disabled():
    ctx = _ctx()
    ctx.settings.network.enabled = False
    assert "disabled" in chat_tools._tool_network_signal({"ticker": "NVDA"}, ctx)


def test_network_signal_no_edges(monkeypatch):
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: KnowledgeGraph())
    assert "no active ontology" in chat_tools._tool_network_signal({"ticker": "NVDA"}, _ctx())


def test_network_signal_lists_influences(monkeypatch):
    graph = KnowledgeGraph(nodes=["NVDA", "AMD"],
                           edges=[GraphEdge(source="NVDA", target="AMD", type="competitor")])
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: graph)
    monkeypatch.setattr(chat_tools, "combined_base_index", lambda c: {})
    monkeypatch.setattr(chat_tools, "incident_edges", lambda t, e, sym: graph.edges)
    monkeypatch.setattr(chat_tools, "compute_network_signal", lambda t, e, b, cfg: NetworkSignal(
        ticker="NVDA", signed=-0.3, intensity=0.4,
        influences=[NetworkInfluence(neighbour="AMD", name="AMD", type="competitor",
                                     neighbour_direction="buy", reason="AMD strength")]))
    out = chat_tools._tool_network_signal({"ticker": "NVDA"}, _ctx())
    assert "competitor AMD" in out and "AMD strength" in out


def test_geopolitics_disabled():
    ctx = _ctx()
    ctx.settings.truth_signal.enabled = False
    assert "disabled" in chat_tools._tool_geopolitics({}, ctx)


def test_geopolitics_summarizes(monkeypatch):
    monkeypatch.setattr(chat_tools.truth_social, "fetch_recent_posts_cached",
                        lambda lh, url, cache: [TruthPost(id="1", created_at="2026-06-12", content="Tariffs incoming on chips")])
    monkeypatch.setattr(chat_tools.political, "summarize_market_mood",
                        lambda posts, prov, model, pid, cache: MarketMood(lean="risk_off", confidence=0.6, summary="Tariff risk."))
    monkeypatch.setattr(chat_tools.political, "find_mentions", lambda posts, t, name: [])
    out = chat_tools._tool_geopolitics({"ticker": "NVDA"}, _ctx())
    assert "risk_off" in out and "Tariff risk." in out


def test_track_record_none_when_no_history(monkeypatch):
    monkeypatch.setattr(chat_tools, "build_track_record_block", lambda t, store, s: None)
    ctx = ChatContext(settings=Settings(), cache=Cache(":memory:"),
                      provider=FakeProvider([]), prediction_store=object())
    assert "no matured evaluation history" in chat_tools._tool_track_record({"ticker": "NVDA"}, ctx)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: FAIL (`_tool_opportunity_score` etc. not defined).

- [ ] **Step 3: Implement the tools**

In `backend/app/chat/tools.py`, add to the imports block:

```python
from app.analysis import political
from app.analysis.network import compute_network_signal, incident_edges
from app.data import truth_social
from app.evaluation.signals import build_track_record_block
from app.network.store import active_graph
from app.screener.service import score_one
from app.screener.store import combined_base_index
```

Add these tool functions (above the `TOOLS` list):

```python
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
    edges = incident_edges(ticker, graph.edges, set(ncfg.symmetric_types))
    if not edges:
        return f"({ticker} has no relationships in the active ontology)"
    sig = compute_network_signal(ticker, edges, combined_base_index(ctx.cache), ncfg)
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
    posts = truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, ctx.cache)
    if not posts:
        return "(no recent Truth Social posts available)"
    mood = political.summarize_market_mood(
        posts, ctx.provider, _model(ctx), ctx.settings.active_provider, ctx.cache)
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/tools.py backend/tests/test_chat_tools.py
git commit -m "feat(backend): add chat signal tools (score, network, geopolitics, track record)"
```

---

### Task 4: Context tools — portfolio_board, ontology_overview, watchlist; register `TOOLS`

**Files:**
- Modify: `backend/app/chat/tools.py`
- Test: `backend/tests/test_chat_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat_tools.py`:

```python
from app.models.schemas import ScreenBoard


def test_portfolio_board_no_snapshot(monkeypatch):
    monkeypatch.setattr(chat_tools, "load_snapshot", lambda c, scope: None)
    assert "no scan results yet" in chat_tools._tool_portfolio_board({}, _ctx())


def test_portfolio_board_ranks_and_filters(monkeypatch):
    board = ScreenBoard(scope="portfolio", items=[
        StockScore(ticker="NVDA", name="NVIDIA", price=120.0, change_pct=1.0, score=80.0,
                   direction="buy", sector="Technology"),
        StockScore(ticker="KO", name="Coca-Cola", price=60.0, change_pct=0.1, score=40.0,
                   direction="hold", sector="Consumer"),
    ])
    monkeypatch.setattr(chat_tools, "load_snapshot", lambda c, scope: board)
    out = chat_tools._tool_portfolio_board({"direction": "buy"}, _ctx())
    assert "NVDA 80/100 buy" in out
    assert "KO" not in out  # filtered out by direction


def test_ontology_overview_empty(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_active_ontology", lambda c: None)
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: KnowledgeGraph())
    assert "no active ontology" in chat_tools._tool_ontology_overview({}, _ctx())


def test_ontology_overview_lists_companies(monkeypatch):
    graph = KnowledgeGraph(nodes=["NVDA", "AMD", "ext:TSMC"],
                           edges=[GraphEdge(source="NVDA", target="AMD", type="competitor")])
    monkeypatch.setattr(chat_tools, "get_active_ontology", lambda c: "Semis")
    monkeypatch.setattr(chat_tools, "active_graph", lambda c: graph)
    out = chat_tools._tool_ontology_overview({}, _ctx())
    assert "Semis" in out and "NVDA" in out and "competitor" in out


def test_watchlist_lists_tickers():
    ctx = _ctx()
    ctx.settings.watchlist = ["AAPL", "msft"]
    assert "AAPL, MSFT" in chat_tools._tool_watchlist({}, ctx)


def test_registry_has_ten_tools():
    assert {t.name for t in TOOLS} == {
        "get_stock", "price_window", "search_news", "geopolitics", "opportunity_score",
        "network_signal", "portfolio_board", "track_record", "ontology_overview", "watchlist",
    }
    assert TOOL_BY_NAME["get_stock"].run is chat_tools._tool_get_stock
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: FAIL (`_tool_portfolio_board` etc. not defined; registry empty).

- [ ] **Step 3: Implement the tools and the registry**

In `backend/app/chat/tools.py`, add to the imports block:

```python
from app.network.store import get_active_ontology
from app.screener.store import load_snapshot
```

(Note: `active_graph` is already imported from Task 3; `get_active_ontology` and `load_snapshot` are new.)

Add these tool functions (above the `TOOLS` list):

```python
def _tool_portfolio_board(args: dict, ctx: ChatContext) -> str:
    scope = str(args.get("scope") or "portfolio").strip().lower()
    snap_scope = "portfolio" if scope == "portfolio" else "all"
    board = load_snapshot(ctx.cache, snap_scope)
    if board is None or not board.items:
        return ("(no scan results yet — ask the user to run a scan on the Portfolio "
                "or Discover page first)")
    items = board.items
    sector = str(args.get("sector") or "").strip()
    if sector and snap_scope == "all":
        items = [i for i in items if i.sector.lower() == sector.lower()]
    direction = str(args.get("direction") or "").strip().lower()
    if direction in ("buy", "sell", "hold"):
        items = [i for i in items if i.direction == direction]
    limit = max(1, min(25, _int_arg(args, "limit", 10)))
    items = items[:limit]
    if not items:
        return "(no matching companies on the board)"
    return "\n".join(f"- {i.ticker} {i.score:.0f}/100 {i.direction} ({i.sector or '?'})"
                     for i in items)


def _tool_ontology_overview(args: dict, ctx: ChatContext) -> str:
    name = get_active_ontology(ctx.cache)
    graph = active_graph(ctx.cache)
    if not name or not graph.nodes:
        return "(no active ontology — the knowledge graph is empty)"
    tickers = [n for n in graph.nodes if ":" not in n]
    types = sorted({e.type for e in graph.edges})
    return (f"Active ontology '{name}': {len(graph.nodes)} nodes ({len(tickers)} companies), "
            f"{len(graph.edges)} relationships.\n"
            f"Companies: {', '.join(tickers[:40]) or '(none)'}\n"
            f"Relationship types: {', '.join(types) or '(none)'}")


def _tool_watchlist(args: dict, ctx: ChatContext) -> str:
    wl = [t.upper().strip() for t in ctx.settings.watchlist if t.strip()]
    return "Watchlist: " + (", ".join(wl) if wl else "(empty)")
```

Now replace the empty `TOOLS`/`TOOL_BY_NAME` at the bottom of the file with the full registry (the `description` strings are the LLM-facing routing text from the spec):

```python
TOOLS: list[ChatTool] = [
    ChatTool(
        "get_stock", '{"ticker": str, "period": str (optional)}',
        "Snapshot of one company: latest price & change, fundamentals (market cap, P/E, EPS, "
        "dividend, 52-week high/low), and current technicals (RSI, SMA50/200, distance from "
        "52-week high). Use first whenever the user asks about a specific ticker's current "
        "state, valuation, or technicals.",
        _tool_get_stock),
    ChatTool(
        "price_window", '{"ticker": str, "lookback_days": int=21, "indicator": "rsi|sma" (optional), "period": int (optional)}',
        "Summarize a stock's recent price action over the last N trading days, with optional RSI "
        "or SMA on that window. Use for trend/momentum, a pullback or rally, or a specific "
        "indicator over a timeframe — not the full snapshot (use get_stock for that).",
        _tool_price_window),
    ChatTool(
        "search_news", '{"query": str, "limit": int=5}',
        "Search recent news headlines for a company, sector, or free-text topic (e.g. "
        "'semiconductor export controls'). Use when the user asks what's happening, why a stock "
        "moved, or about an event or theme. Returns headlines with dates and sources.",
        _tool_search_news),
    ChatTool(
        "geopolitics", '{"ticker": str (optional)}',
        "Current political/geopolitical market mood derived from Trump's Truth Social posts, plus "
        "any posts mentioning a given company. Use for questions about political risk, "
        "tariffs/policy, Trump, or how geopolitics affects a stock.",
        _tool_geopolitics),
    ChatTool(
        "opportunity_score", '{"ticker": str}',
        "The app's deterministic (non-LLM) opportunity score for one ticker: 0-100 score, a "
        "buy/sell/hold call, and the reasons (technical + network blend). Use for a quick 'is "
        "this a buy/sell?' verdict on a single named stock.",
        _tool_opportunity_score),
    ChatTool(
        "network_signal", '{"ticker": str}',
        "A company's relationships from the active ontology graph (competitors, suppliers, "
        "customers, partners...) and the network signal its neighbours contribute. Use for "
        "questions about connections, supply chain, rivals, or how related companies' news "
        "affects it.",
        _tool_network_signal),
    ChatTool(
        "portfolio_board", '{"scope": "portfolio|all" (optional), "sector": str (optional), "direction": "buy|sell|hold" (optional), "limit": int=10}',
        "Scan and rank many companies by opportunity score, returning the top buy or sell "
        "candidates. Use when the user wants the best opportunities or a ranked list across "
        "their watchlist/portfolio or a sector — rather than one named ticker.",
        _tool_portfolio_board),
    ChatTool(
        "track_record", '{"ticker": str}',
        "The LLM's own past recommendation accuracy for a ticker (hit rate / grade across "
        "matured 1/5/20-day horizons, overconfidence flag). Use when the user asks how reliable "
        "past calls were or whether to trust the model on this stock.",
        _tool_track_record),
    ChatTool(
        "ontology_overview", "{}",
        "List the active ontology: its name and the companies and relationship types it "
        "contains. Use when the user asks what the knowledge graph knows, or to ground a network "
        "question before drilling into one ticker.",
        _tool_ontology_overview),
    ChatTool(
        "watchlist", "{}",
        "Return the user's current watchlist tickers. Use when the user says 'my watchlist', "
        "'my stocks', or 'my portfolio' without naming tickers, so you know which companies they "
        "mean.",
        _tool_watchlist),
]
TOOL_BY_NAME: dict[str, ChatTool] = {t.name: t for t in TOOLS}
```

- [ ] **Step 4: Run the whole tools file to verify**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_tools.py`
Expected: PASS (all tool tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/tools.py backend/tests/test_chat_tools.py
git commit -m "feat(backend): add chat portfolio/ontology/watchlist tools and register the 10-tool catalog"
```

---

## Phase 2 — Backend `ChatAgent`

### Task 5: Parser, system prompt, and the event/message models

**Files:**
- Create: `backend/app/chat/agent.py`
- Test: `backend/tests/test_chat_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chat_agent.py`:

```python
from app.chat.agent import (
    ChatEvent, ChatMessage, build_chat_system, parse_chat_step,
)
from app.chat.tools import TOOLS


def test_parse_action_with_json_args():
    p = parse_chat_step('Thought: look it up\nAction: get_stock({"ticker": "NVDA"})')
    assert p.thought == "look it up"
    assert p.action == "get_stock"
    assert p.action_args == {"ticker": "NVDA"}
    assert p.final_text is None


def test_parse_final_answer_is_markdown_text():
    p = parse_chat_step("Thought: done\nFinal Answer: ## NVDA\n\n**Buy** — strong trend.")
    assert p.action is None
    assert p.final_text.startswith("## NVDA")
    assert "**Buy**" in p.final_text


def test_parse_garbage_yields_no_action_no_final():
    p = parse_chat_step("I am not following the format.")
    assert p.action is None
    assert p.final_text is None


def test_parse_empty_final_is_not_final():
    p = parse_chat_step("Thought: x\nFinal Answer:   ")
    assert p.final_text is None


def test_build_chat_system_includes_protocol_and_catalog():
    sysprompt = build_chat_system(TOOLS)
    assert "Action:" in sysprompt
    assert "Final Answer:" in sysprompt
    assert "get_stock" in sysprompt        # the catalog
    assert "Markdown" in sysprompt         # final-answer format instruction


def test_chat_event_serializes():
    ev = ChatEvent(type="final", answer="hi")
    assert ev.model_dump()["type"] == "final"
    assert ev.model_dump()["answer"] == "hi"


def test_chat_message_roles():
    m = ChatMessage(role="user", content="hello")
    assert m.role == "user"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_agent.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chat.agent'`.

- [ ] **Step 3: Implement the parser, prompt, and models**

Create `backend/app/chat/agent.py`:

```python
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterator, Literal, Optional

from pydantic import BaseModel

from app.analysis.agent import (
    AgentStep, _ACTION_RE, _FINAL_RE, _THOUGHT_RE, _extract_args, render_tool_catalog,
)
from app.chat.tools import TOOLS, ChatContext, ChatTool
from app.llm.base import LLMProvider

DEFAULT_MAX_STEPS = 10
MAX_TOOL_CALLS = 12
_MAX_OBS_CHARS = 1500
_REACT_STOP = ["\nObservation:"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatEvent(BaseModel):
    type: Literal["step", "final", "error"]
    step: Optional[AgentStep] = None
    answer: str = ""       # markdown, on `final`
    message: str = ""      # on `error`


_CHAT_SYSTEM = (
    "You are MarketCortex's stock-analysis assistant. You help the user analyze stocks using the "
    "app's own data — prices, fundamentals, technicals, news, the geopolitics (Truth-Social) "
    "signal, the company ontology graph and network signal, the deterministic opportunity score, "
    "the portfolio board, and the model's own evaluation track record. Be concrete and cite the "
    "evidence you gathered. A question may span multiple companies. You are not a financial "
    "adviser; add a one-line caveat when you give a buy/sell view."
)


def build_chat_system(tools: list[ChatTool]) -> str:
    return (
        _CHAT_SYSTEM
        + "\n\nYou work step by step using TOOLS to gather evidence. On each turn reply with "
        "EXACTLY one of:\n"
        "  Thought: <your reasoning>\n  Action: <tool_name>({<json args>})\n"
        "OR, once you have enough evidence:\n"
        "  Thought: <final reasoning>\n  Final Answer: <your answer to the user, in Markdown>\n\n"
        "Rules: at most one Action per turn; after each Action you receive an Observation; never "
        "invent Observations; only call a tool if it could change your answer; answer as soon as "
        "you have enough.\n\n"
        "TOOLS:\n" + render_tool_catalog(tools)
    )


@dataclass
class ParsedChatStep:
    thought: str
    action: Optional[str]
    action_args: dict
    final_text: Optional[str]   # the markdown Final Answer, or None


def parse_chat_step(text: str) -> ParsedChatStep:
    """Tolerant ReAct parser whose Final Answer is free markdown text (not JSON). Reuses the
    single-ticker agent's Thought/Action regexes and JSON-arg extractor for consistency."""
    thought_m = _THOUGHT_RE.search(text)
    thought = thought_m.group(1).strip() if thought_m else ""

    final_m = _FINAL_RE.search(text)
    if final_m and final_m.group(1).strip():
        return ParsedChatStep(thought, None, {}, final_m.group(1).strip())

    action_m = _ACTION_RE.search(text)
    if action_m:
        if not thought:
            thought = text[: action_m.start()].strip()[:600]
        return ParsedChatStep(thought, action_m.group(1),
                              _extract_args(text[action_m.end():]), None)

    return ParsedChatStep(thought, None, {}, None)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_agent.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/agent.py backend/tests/test_chat_agent.py
git commit -m "feat(backend): add chat ReAct parser, system prompt, and event models"
```

---

### Task 6: The `ChatAgent` loop

**Files:**
- Modify: `backend/app/chat/agent.py`
- Test: `backend/tests/test_chat_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat_agent.py`:

```python
import json

from app.chat.agent import ChatAgent
from app.chat.tools import ChatContext
from app.config.cache import Cache
from app.models.schemas import Settings


class _CapturingProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []
        self.json_modes = []
        self.stops = []

    def complete(self, system, user, json_mode=True, stop=None):
        self.prompts.append(user)
        self.json_modes.append(json_mode)
        self.stops.append(stop)
        return self.outputs.pop(0)

    def list_models(self):
        return []


_ECHO = ChatTool("echo", "echo a value", '{"q": str}',
                 lambda args, ctx: f"observed:{args.get('q', '')}")


def _ctx(provider):
    return ChatContext(settings=Settings(), cache=Cache(":memory:"), provider=provider)


def _msgs(text="What about NVDA?"):
    return [ChatMessage(role="user", content=text)]


def test_agent_answers_in_one_turn():
    provider = _CapturingProvider(["Thought: easy\nFinal Answer: **NVDA** looks strong."])
    events = list(ChatAgent(tools=[_ECHO]).stream(provider, "m", "fake", _msgs(), _ctx(provider)))
    assert [e.type for e in events] == ["step", "final"]
    assert events[-1].answer == "**NVDA** looks strong."
    assert provider.json_modes == [False]      # free-text ReAct turn
    assert provider.stops == [["\nObservation:"]]


def test_agent_runs_a_tool_then_answers():
    provider = _CapturingProvider([
        'Thought: check echo\nAction: echo({"q": "hi"})',
        "Thought: done\nFinal Answer: Result was hi.",
    ])
    events = list(ChatAgent(tools=[_ECHO]).stream(provider, "m", "fake", _msgs(), _ctx(provider)))
    assert [e.type for e in events] == ["step", "step", "final"]
    assert events[0].step.action == "echo"
    assert events[0].step.observation == "observed:hi"
    assert events[-1].answer == "Result was hi."


def test_agent_seeds_conversation_history_into_the_prompt():
    provider = _CapturingProvider(["Thought: ok\nFinal Answer: yes"])
    messages = [
        ChatMessage(role="user", content="Tell me about NVDA"),
        ChatMessage(role="assistant", content="NVDA is a chipmaker."),
        ChatMessage(role="user", content="Is it a buy?"),
    ]
    list(ChatAgent(tools=[_ECHO]).stream(provider, "m", "fake", messages, _ctx(provider)))
    seed = provider.prompts[0]
    assert "Tell me about NVDA" in seed
    assert "NVDA is a chipmaker." in seed
    assert "Is it a buy?" in seed


def test_agent_tool_error_becomes_observation():
    boom = ChatTool("boom", "raises", "{}",
                    lambda args, ctx: (_ for _ in ()).throw(RuntimeError("nope")))
    provider = _CapturingProvider([
        "Thought: try\nAction: boom({})",
        "Thought: recover\nFinal Answer: handled it.",
    ])
    events = list(ChatAgent(tools=[boom]).stream(provider, "m", "fake", _msgs(), _ctx(provider)))
    assert "ERROR: boom failed: nope" in events[0].step.observation
    assert events[-1].answer == "handled it."


def test_agent_nudges_once_then_gives_graceful_final():
    provider = _CapturingProvider(["garbage one", "garbage two"])
    events = list(ChatAgent(tools=[_ECHO], max_steps=5).stream(
        provider, "m", "fake", _msgs(), _ctx(provider)))
    assert events[-1].type == "final"
    assert "couldn't complete" in events[-1].answer.lower()


def test_agent_hits_max_steps_with_graceful_final():
    actions = ['Thought: loop\nAction: echo({"q": "x"})'] * 3
    provider = _CapturingProvider(actions)
    events = list(ChatAgent(tools=[_ECHO], max_steps=3).stream(
        provider, "m", "fake", _msgs(), _ctx(provider)))
    assert events[-1].type == "final"
    assert "step limit" in events[-1].answer.lower()


def test_run_drains_to_the_answer():
    provider = _CapturingProvider(["Thought: ok\nFinal Answer: the answer"])
    answer = ChatAgent(tools=[_ECHO]).run(provider, "m", "fake", _msgs(), _ctx(provider))
    assert answer == "the answer"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_agent.py`
Expected: FAIL (`ChatAgent` not defined).

- [ ] **Step 3: Implement the loop**

Append to `backend/app/chat/agent.py`:

```python
def _render_history(messages: list[ChatMessage]) -> str:
    return "\n".join(
        f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in messages)


def _initial_transcript(messages: list[ChatMessage]) -> str:
    return (
        "Conversation so far (the last User message is the question to answer now):\n"
        f"{_render_history(messages)}\n\n"
        "Work step by step. Begin with your first Thought."
    )


class ChatAgent:
    def __init__(self, tools: Optional[list[ChatTool]] = None,
                 max_steps: int = DEFAULT_MAX_STEPS) -> None:
        self.tools = tools if tools is not None else TOOLS
        self.tool_by_name = {t.name: t for t in self.tools}
        self.max_steps = max_steps

    def stream(self, provider: LLMProvider, model: str, provider_name: str,
               messages: list[ChatMessage], ctx: ChatContext) -> Iterator[ChatEvent]:
        """Yields a `step` ChatEvent per completed step, then a terminal `final` carrying the
        markdown answer. An LLMError from the provider propagates to the caller (the endpoint
        turns it into an `error` event) — chat has no structured single-shot fallback."""
        system = build_chat_system(self.tools)
        transcript = _initial_transcript(messages)
        tool_calls = 0
        nudged = False
        for i in range(self.max_steps):
            t0 = time.monotonic()
            raw = provider.complete(system, transcript, json_mode=False, stop=_REACT_STOP)
            parsed = parse_chat_step(raw)
            step = AgentStep(index=i, thought=parsed.thought, raw=raw,
                             elapsed_ms=int((time.monotonic() - t0) * 1000))
            if parsed.final_text is not None:
                step.is_final = True
                yield ChatEvent(type="step", step=step)
                yield ChatEvent(type="final", answer=parsed.final_text)
                return
            if parsed.action in self.tool_by_name and tool_calls < MAX_TOOL_CALLS:
                tool_calls += 1
                obs = self._run_tool(parsed.action, parsed.action_args, ctx)
                step.action = parsed.action
                step.action_args = parsed.action_args
                step.observation = obs
                yield ChatEvent(type="step", step=step)
                transcript += (
                    f"\n\nThought: {parsed.thought}\nAction: {parsed.action}"
                    f"({json.dumps(parsed.action_args)})\nObservation: {obs}\n"
                )
                continue
            yield ChatEvent(type="step", step=step)
            if not nudged:
                nudged = True
                transcript += (
                    "\n\nYour reply had no valid Action or Final Answer. Reply with exactly one "
                    "'Action: <tool>({json})' or 'Final Answer: <markdown>'."
                )
                continue
            yield ChatEvent(type="final",
                            answer="I couldn't complete that — try narrowing the question or "
                                   "asking about a specific ticker.")
            return
        yield ChatEvent(type="final",
                        answer="I reached my step limit before finishing. Try a more specific "
                               "question (e.g. about one ticker or one factor).")

    def run(self, provider: LLMProvider, model: str, provider_name: str,
            messages: list[ChatMessage], ctx: ChatContext) -> str:
        """Drain stream() to the final answer (CLI / non-streaming / tests)."""
        answer = ""
        for ev in self.stream(provider, model, provider_name, messages, ctx):
            if ev.type in ("final", "error"):
                answer = ev.answer or ev.message
        return answer

    def _run_tool(self, name: str, args: dict, ctx: ChatContext) -> str:
        try:
            obs = self.tool_by_name[name].run(args, ctx)
        except Exception as exc:  # noqa: BLE001 — tool errors must never break the loop
            return f"ERROR: {name} failed: {exc}"
        return obs if len(obs) <= _MAX_OBS_CHARS else obs[:_MAX_OBS_CHARS] + " …(truncated)"
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_chat_agent.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/agent.py backend/tests/test_chat_agent.py
git commit -m "feat(backend): add multi-turn ChatAgent ReAct loop"
```

---

## Phase 3 — Backend endpoint

### Task 7: `POST /api/chat/stream`

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:

```python
from app.api import routes as api_routes
from app.chat import agent as chat_agent


def test_chat_stream_emits_steps_then_final(tmp_path, monkeypatch):
    # Fake provider: one tool call (watchlist), then a markdown final answer.
    outputs = ['Thought: check\nAction: watchlist({})', "Thought: done\nFinal Answer: **Done.**"]

    class _FakeProvider:
        name = "fake"

        def complete(self, system, user, json_mode=True, stop=None):
            return outputs.pop(0)

        def list_models(self):
            return []

    monkeypatch.setattr(api_routes, "build_provider", lambda settings: _FakeProvider())
    client, _ = _client(tmp_path)

    resp = client.post("/api/chat/stream",
                       json={"messages": [{"role": "user", "content": "What's in my watchlist?"}]})
    assert resp.status_code == 200
    body = resp.text
    assert "event: step" in body
    assert "event: final" in body
    assert "Done." in body


def test_chat_stream_rejects_empty_messages(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/api/chat/stream", json={"messages": []})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_api.py::test_chat_stream_emits_steps_then_final tests/test_api.py::test_chat_stream_rejects_empty_messages`
Expected: FAIL with 404 (route not registered).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routes.py`, add to the imports (near the other `app.chat`-adjacent imports, after the `app.analysis.agent` import on line 66):

```python
from app.chat.agent import ChatAgent, ChatEvent, ChatMessage
from app.chat.tools import ChatContext
```

Update the `_sse` type union (line 167) to include `ChatEvent`:

```python
def _sse(event: AgentEvent | WatchlistRunEvent | RescanEvent | ChatEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
```

Add the request model and route. Place it immediately after the `get_traces` route (after line 276), so it sits with the other streaming endpoints:

```python
class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


@router.post("/chat/stream")
def chat_stream(
    body: ChatRequest,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
    prediction_store: PredictionStore = Depends(get_prediction_store),
) -> StreamingResponse:
    """Multi-turn ReAct chat assistant, streamed step-by-step as Server-Sent Events over POST
    (the conversation history travels in the body, so this is POST + fetch-stream, not
    EventSource). The frontend owns the conversation; the server is stateless and records
    nothing. Provider/LLM failures surface as an in-stream `event: error`."""
    settings = store.load()
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise HTTPException(status_code=502, detail=f"No configuration for provider '{provider_id}'")
    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="The last message must be from the user.")
    try:
        provider = build_provider(settings)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ctx = ChatContext(settings=settings, cache=cache, provider=provider,
                      prediction_store=prediction_store)
    agent = ChatAgent()

    def event_stream():
        try:
            for event in agent.stream(provider, cfg.model, provider_id, body.messages, ctx):
                yield _sse(event)
        except LLMError as exc:  # provider/LLM failure -> usable in-stream error
            yield _sse(ChatEvent(type="error", message=str(exc)))

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
```

Add `BaseModel` and `Field` to the imports if not present. Check the top of `routes.py`: it imports from `fastapi` and `app.models.schemas` but not pydantic directly. Add this import near the top (after the `fastapi` imports on line 9):

```python
from pydantic import BaseModel, Field
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q tests/test_api.py::test_chat_stream_emits_steps_then_final tests/test_api.py::test_chat_stream_rejects_empty_messages`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all existing + new backend tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(backend): add POST /api/chat/stream SSE endpoint"
```

---

## Phase 4 — Frontend transport, hook, state

### Task 8: Types + `streamChat` transport

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add the chat types**

Append to `frontend/src/types.ts` (after the `AgentEvent` interface, around line 329):

```typescript
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatEvent {
  type: 'step' | 'final' | 'error';
  step?: AgentStep | null;
  answer?: string;
  message?: string;
}

/** A rendered conversation turn. For an assistant turn, `content` is the final markdown
 *  answer, `steps` is the live ReAct trace, and `error` is a per-turn transport/LLM error. */
export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
  steps?: AgentStep[];
  error?: string;
}
```

- [ ] **Step 2: Add `streamChat` and the SSE-frame parser to the client**

In `frontend/src/api/client.ts`, add `ChatEvent` and `ChatMessage` to the type import block at the top (lines 1–26): insert `ChatEvent,` and `ChatMessage,` in alphabetical position.

Append to the end of `frontend/src/api/client.ts`:

```typescript
export interface ChatStreamHandlers {
  onEvent: (event: ChatEvent) => void;
  onError: (message: string) => void;
}

/** Parse one SSE frame ("event: <type>\ndata: <json>"). The JSON payload already carries the
 *  `type`, so we trust it and ignore the redundant event-name line. */
function parseChatFrame(frame: string): ChatEvent | null {
  const data = frame
    .split('\n')
    .filter((l) => l.startsWith('data:'))
    .map((l) => l.slice(5).trim())
    .join('\n');
  if (!data) return null;
  try {
    return JSON.parse(data) as ChatEvent;
  } catch {
    return null;
  }
}

/** Stream a chat turn. EventSource is GET-only, but the conversation history must travel in a
 *  POST body, so this uses fetch + a ReadableStream SSE parser. Returns a closer the caller MUST
 *  keep and invoke on unmount/stop — it aborts the in-flight request. */
export function streamChat(messages: ChatMessage[], handlers: ChatStreamHandlers): () => void {
  const controller = new AbortController();
  (async () => {
    let resp: Response;
    try {
      resp = await fetch(`${BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages }),
        signal: controller.signal,
      });
    } catch {
      if (!controller.signal.aborted) handlers.onError('Connection error');
      return;
    }
    if (!resp.ok || !resp.body) {
      handlers.onError(`Server error (${resp.status})`);
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const event = parseChatFrame(frame);
          if (event) handlers.onEvent(event);
        }
      }
    } catch {
      if (!controller.signal.aborted) handlers.onError('Connection error');
    }
  })();
  return () => controller.abort();
}
```

- [ ] **Step 3: Type-check (no test yet — this is plumbing exercised by Task 9's tests)**

Run (from `frontend/`): `npx tsc -b`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/client.ts
git commit -m "feat(frontend): add chat types and streamChat fetch-stream transport"
```

---

### Task 9: `useChat` hook

**Files:**
- Create: `frontend/src/hooks/useChat.ts`
- Test: `frontend/src/hooks/useChat.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useChat.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import * as client from '../api/client';
import { useChat } from './useChat';

it('appends a user turn and fills the assistant turn from the stream', () => {
  let handlers: client.ChatStreamHandlers | undefined;
  vi.spyOn(client, 'streamChat').mockImplementation((_m, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useChat());

  act(() => result.current.send('What about NVDA?'));
  // user turn + empty assistant turn
  expect(result.current.turns).toHaveLength(2);
  expect(result.current.turns[0]).toMatchObject({ role: 'user', content: 'What about NVDA?' });
  expect(result.current.running).toBe(true);

  act(() => handlers!.onEvent({ type: 'step', step: { index: 0, thought: 't' } } as never));
  expect(result.current.turns[1].steps).toHaveLength(1);

  act(() => handlers!.onEvent({ type: 'final', answer: '**Buy**' } as never));
  expect(result.current.running).toBe(false);
  expect(result.current.turns[1].content).toBe('**Buy**');
});

it('sends prior turns as history on a follow-up', () => {
  const calls: client.ChatStreamHandlers[] = [];
  const sent: unknown[][] = [];
  vi.spyOn(client, 'streamChat').mockImplementation((m, h) => { sent.push(m); calls.push(h); return () => {}; });
  const { result } = renderHook(() => useChat());

  act(() => result.current.send('first'));
  act(() => calls[0].onEvent({ type: 'final', answer: 'a1' } as never));
  act(() => result.current.send('second'));

  // The second call's history includes the first Q + answer + the new question.
  expect(sent[1]).toEqual([
    { role: 'user', content: 'first' },
    { role: 'assistant', content: 'a1' },
    { role: 'user', content: 'second' },
  ]);
});

it('records a per-turn error', () => {
  let handlers: client.ChatStreamHandlers | undefined;
  vi.spyOn(client, 'streamChat').mockImplementation((_m, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useChat());
  act(() => result.current.send('x'));
  act(() => handlers!.onError('Connection error'));
  expect(result.current.running).toBe(false);
  expect(result.current.turns[1].error).toBe('Connection error');
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/hooks/useChat.test.tsx`
Expected: FAIL (`useChat` module not found).

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useChat.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react';
import { streamChat } from '../api/client';
import type { AgentStep, ChatEvent, ChatMessage, ChatTurn } from '../types';

/** Conversation state + per-turn streaming. History lives here (frontend-owned, ephemeral):
 *  each send POSTs the prior turns + the new question and fills the assistant turn as events
 *  arrive. A turnsRef mirrors state so building history and updating the in-flight turn never
 *  rely on a stale closure. */
export function useChat() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [running, setRunning] = useState(false);
  const turnsRef = useRef<ChatTurn[]>([]);
  const closeRef = useRef<(() => void) | null>(null);

  const commit = useCallback((next: ChatTurn[]) => {
    turnsRef.current = next;
    setTurns(next);
  }, []);

  const patchAssistant = useCallback((fn: (a: ChatTurn) => ChatTurn) => {
    const cur = turnsRef.current;
    const i = cur.length - 1;
    if (i < 0 || cur[i].role !== 'assistant') return;
    const copy = cur.slice();
    copy[i] = fn(copy[i]);
    commit(copy);
  }, [commit]);

  const send = useCallback((text: string) => {
    const q = text.trim();
    if (!q || running) return;
    closeRef.current?.();

    const history: ChatMessage[] = turnsRef.current.map((t) => ({ role: t.role, content: t.content }));
    const messages: ChatMessage[] = [...history, { role: 'user', content: q }];
    commit([
      ...turnsRef.current,
      { role: 'user', content: q },
      { role: 'assistant', content: '', steps: [] },
    ]);
    setRunning(true);

    let steps: AgentStep[] = [];
    closeRef.current = streamChat(messages, {
      onEvent: (e: ChatEvent) => {
        if (e.type === 'step' && e.step) {
          steps = [...steps, e.step];
          patchAssistant((a) => ({ ...a, steps }));
        } else if (e.type === 'final') {
          setRunning(false);
          patchAssistant((a) => ({ ...a, content: e.answer ?? '', steps }));
        } else if (e.type === 'error') {
          setRunning(false);
          patchAssistant((a) => ({ ...a, error: e.message || 'Error' }));
        }
      },
      onError: (message) => {
        setRunning(false);
        patchAssistant((a) => ({ ...a, error: message }));
      },
    });
  }, [running, commit, patchAssistant]);

  const stop = useCallback(() => {
    closeRef.current?.();
    setRunning(false);
  }, []);

  useEffect(() => () => closeRef.current?.(), []);

  return { turns, running, send, stop };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/hooks/useChat.test.tsx`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useChat.ts frontend/src/hooks/useChat.test.tsx
git commit -m "feat(frontend): add useChat conversation hook"
```

---

### Task 10: `ChatProvider` state

**Files:**
- Create: `frontend/src/state/chatState.tsx`

- [ ] **Step 1: Implement the provider**

Create `frontend/src/state/chatState.tsx`:

```tsx
import { createContext, useContext, type ReactNode } from 'react';
import { useChat } from '../hooks/useChat';

const ChatContext = createContext<ReturnType<typeof useChat> | null>(null);

// Holds the chat conversation ABOVE the router so it survives navigating between pages
// (React Router unmounts the Chat route otherwise). Ephemeral by design: a full page
// reload clears it.
export function ChatProvider({ children }: { children: ReactNode }) {
  const chat = useChat();
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChatContext must be used within a ChatProvider');
  return ctx;
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc -b`
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/state/chatState.tsx
git commit -m "feat(frontend): add ChatProvider for ephemeral conversation state"
```

---

## Phase 5 — Frontend page, markdown, routing, styles

### Task 11: Minimal markdown renderer

**Files:**
- Create: `frontend/src/components/Markdown.tsx`
- Test: `frontend/src/components/Markdown.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Markdown.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { Markdown } from './Markdown';

it('renders bold, code, headings, lists, and links', () => {
  const { container } = render(
    <Markdown text={'## NVDA\n\nA **strong** buy with `RSI` rising.\n\n- one\n- two\n\nSee [docs](https://x.io).'} />,
  );
  expect(container.querySelector('h4')?.textContent).toBe('NVDA');
  expect(container.querySelector('strong')?.textContent).toBe('strong');
  expect(container.querySelector('code')?.textContent).toBe('RSI');
  expect(container.querySelectorAll('li')).toHaveLength(2);
  const link = screen.getByRole('link', { name: 'docs' });
  expect(link).toHaveAttribute('href', 'https://x.io');
});

it('renders plain paragraphs', () => {
  const { container } = render(<Markdown text={'just text'} />);
  expect(container.querySelector('p')?.textContent).toBe('just text');
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/components/Markdown.test.tsx`
Expected: FAIL (`Markdown` module not found).

- [ ] **Step 3: Implement the renderer**

Create `frontend/src/components/Markdown.tsx`:

```tsx
import { type ReactNode } from 'react';

// A deliberately small Markdown renderer for the assistant's chat answers — ATX headings,
// unordered lists, paragraphs, and inline **bold**, `code`, and [links](url). Not a full
// CommonMark parser; kept minimal to avoid a heavy dependency.
const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith('**')) {
      out.push(<strong key={key++}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith('`')) {
      out.push(<code key={key++}>{tok.slice(1, -1)}</code>);
    } else {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
      out.push(
        <a key={key++} href={mm[2]} target="_blank" rel="noreferrer">{mm[1]}</a>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let para: string[] = [];
  let key = 0;

  const flushPara = () => {
    if (para.length) {
      blocks.push(<p key={key++}>{renderInline(para.join(' '))}</p>);
      para = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      blocks.push(
        <ul key={key++}>{list.map((li, i) => <li key={i}>{renderInline(li)}</li>)}</ul>,
      );
      list = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    const li = /^[-*]\s+(.*)$/.exec(line);
    if (h) {
      flushPara();
      flushList();
      const level = h[1].length;
      if (level === 1) blocks.push(<h3 key={key++}>{renderInline(h[2])}</h3>);
      else if (level === 2) blocks.push(<h4 key={key++}>{renderInline(h[2])}</h4>);
      else blocks.push(<h5 key={key++}>{renderInline(h[2])}</h5>);
    } else if (li) {
      flushPara();
      list.push(li[1]);
    } else if (line.trim() === '') {
      flushPara();
      flushList();
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara();
  flushList();
  return <div className="md">{blocks}</div>;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/components/Markdown.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Markdown.tsx frontend/src/components/Markdown.test.tsx
git commit -m "feat(frontend): add minimal Markdown renderer for chat answers"
```

---

### Task 12: The `Chat` page

**Files:**
- Create: `frontend/src/pages/Chat.tsx`
- Test: `frontend/src/pages/Chat.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/Chat.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import Chat from './Chat';
import { ChatProvider } from '../state/chatState';
import * as client from '../api/client';

function renderChat() {
  return render(<ChatProvider><Chat /></ChatProvider>);
}

it('shows suggestions and sends a question', () => {
  const send = vi.spyOn(client, 'streamChat').mockImplementation(() => () => {});
  renderChat();
  // suggestion chips visible in the empty state
  expect(screen.getByText(/strongest opportunity/i)).toBeInTheDocument();

  const box = screen.getByPlaceholderText(/Ask about a stock/i);
  fireEvent.change(box, { target: { value: 'Is NVDA a buy?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  expect(send).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Is NVDA a buy?')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/pages/Chat.test.tsx`
Expected: FAIL (`Chat` module not found).

- [ ] **Step 3: Implement the page**

Create `frontend/src/pages/Chat.tsx`:

```tsx
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useChatContext } from '../state/chatState';
import { TracePanel } from '../components/TracePanel';
import { Markdown } from '../components/Markdown';

const SUGGESTIONS = [
  'How does geopolitics affect NVDA right now?',
  'Compare AMD vs NVDA using the ontology graph.',
  "What's the strongest opportunity in my watchlist?",
];

export default function Chat() {
  const { turns, running, send, stop } = useChatContext();
  const [input, setInput] = useState('');
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, running]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = input.trim();
    if (!q || running) return;
    send(q);
    setInput('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <section className="panel chat">
      <div className="chat-log">
        {turns.length === 0 && (
          <div className="chat-empty">
            <p className="muted">
              Ask about any stock — prices, news, geopolitics, the ontology graph, or your
              portfolio. The assistant reasons step by step using the app's own data.
            </p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="chip" disabled={running}
                        onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t, i) => (
          <div key={i} className={`chat-turn ${t.role}`}>
            {t.role === 'user' ? (
              <div className="chat-bubble user">{t.content}</div>
            ) : (
              <div className="chat-bubble assistant">
                {t.steps && t.steps.length > 0 && (
                  <TracePanel steps={t.steps} running={running && i === turns.length - 1}
                              maxSteps={10} />
                )}
                {t.content && <Markdown text={t.content} />}
                {!t.content && !t.error && running && i === turns.length - 1 && (
                  <p className="muted">…thinking</p>
                )}
                {t.error && <p className="error">{t.error}</p>}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form className="chat-composer" onSubmit={submit}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about a stock, a sector, geopolitics, the ontology…"
          rows={2}
          disabled={running}
        />
        {running ? (
          <button type="button" className="btn" onClick={stop}>Stop</button>
        ) : (
          <button type="submit" className="btn gold" disabled={!input.trim()}>Send</button>
        )}
      </form>
    </section>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/pages/Chat.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Chat.tsx frontend/src/pages/Chat.test.tsx
git commit -m "feat(frontend): add Chat page with live trace and markdown answers"
```

---

### Task 13: Routing, nav, and the `ChatProvider` wrap

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Wire the page into the app**

Edit `frontend/src/App.tsx`:

1. Add the page import (after the `Evaluation` import, line 7):
```tsx
import Chat from './pages/Chat';
```
2. Add the provider import (after the `WatchlistRunProvider` import, line 10):
```tsx
import { ChatProvider } from './state/chatState';
```
3. Wrap the app with `ChatProvider` — change the opening providers (lines 19–20) to:
```tsx
    <DashboardStateProvider>
    <WatchlistRunProvider>
    <ChatProvider>
```
and the closing providers (lines 51–52) to:
```tsx
    </ChatProvider>
    </WatchlistRunProvider>
    </DashboardStateProvider>
```
4. Add the nav link (after the Evaluation `NavLink`, line 35):
```tsx
            <NavLink to="/chat" className={navClass}>Chat</NavLink>
```
5. Add the route (after the Evaluation `Route`, line 46):
```tsx
            <Route path="/chat" element={<Chat />} />
```

- [ ] **Step 2: Type-check and run the full frontend suite**

Run (from `frontend/`): `npx tsc -b && npm test`
Expected: no type errors; all tests pass (existing + new).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): add Chat route, nav link, and ChatProvider"
```

---

### Task 14: Chat page styles

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Append the chat styles**

Append to `frontend/src/styles.css` (uses the existing tokens; mirrors the `.panel`/trace look):

```css
/* ============================================================================
   Chat assistant
   ========================================================================== */
.chat {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 180px);
  min-height: 420px;
  padding: 0;
  overflow: hidden;
}
.chat-log {
  flex: 1;
  overflow-y: auto;
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.chat-empty { margin: auto; max-width: 560px; text-align: center; }
.chat-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
  margin-top: 16px;
}
.chat-suggestions .chip {
  background: var(--panel-2);
  border: 1px solid var(--panel-brd);
  color: var(--ink-soft);
  border-radius: 999px;
  padding: 8px 14px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.chat-suggestions .chip:hover:not(:disabled) { border-color: var(--gold-line); color: var(--ink); }
.chat-suggestions .chip:disabled { opacity: 0.5; cursor: default; }

.chat-turn { display: flex; }
.chat-turn.user { justify-content: flex-end; }
.chat-turn.assistant { justify-content: flex-start; }
.chat-bubble { max-width: 80%; border-radius: var(--radius); padding: 12px 16px; line-height: 1.5; }
.chat-bubble.user {
  background: var(--gold-tint);
  border: 1px solid var(--gold-line);
  color: var(--ink);
  white-space: pre-wrap;
}
.chat-bubble.assistant {
  background: var(--panel-2);
  border: 1px solid var(--panel-brd);
  max-width: 88%;
}
.chat-bubble .md > :first-child { margin-top: 0; }
.chat-bubble .md > :last-child { margin-bottom: 0; }
.chat-bubble .md h3, .chat-bubble .md h4, .chat-bubble .md h5 {
  font-family: var(--serif);
  margin: 12px 0 6px;
}
.chat-bubble .md code {
  font-family: var(--mono);
  font-size: 0.9em;
  background: var(--panel);
  padding: 1px 5px;
  border-radius: 5px;
}
.chat-bubble .md a { color: var(--gold); }

.chat-composer {
  display: flex;
  gap: 10px;
  padding: 14px 18px;
  border-top: 1px solid var(--hairline);
  align-items: flex-end;
}
.chat-composer textarea {
  flex: 1;
  resize: none;
  background: var(--panel);
  border: 1px solid var(--panel-brd);
  border-radius: 12px;
  color: var(--ink);
  font: inherit;
  padding: 10px 12px;
  line-height: 1.4;
}
.chat-composer textarea:focus { outline: none; border-color: var(--gold-line); }
.chat-composer .btn { white-space: nowrap; }
```

> Note: `.btn`, `.btn.gold`, `.muted`, `.error`, and the `.trace*` classes already exist in `styles.css`. If `.btn` does not exist (verify with a quick search), reuse whatever the existing command-bar buttons use (e.g. the class on the Dashboard "Analyze with LLM" button) instead of `.btn`, and update `Chat.tsx` accordingly.

- [ ] **Step 2: Verify the page in the browser**

Start the dev servers if not running, then verify visually (see the spec's verification workflow). The dev server runs with HMR, so the new CSS applies immediately. Confirm: the nav shows **Chat**; the empty state shows suggestion chips; sending a question shows a user bubble, a live trace, then a markdown answer; **Stop** halts a run.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles.css
git commit -m "style(frontend): add chat page styles"
```

---

## Final verification

- [ ] **Backend:** from `backend/`, run `.venv/Scripts/python.exe -m pytest -q` → all pass.
- [ ] **Frontend:** from `frontend/`, run `npx tsc -b && npm test` → no type errors, all pass.
- [ ] **Manual smoke (real provider):** with an API key configured in Settings, open `/chat` and ask "How does geopolitics affect NVDA?" and a follow-up ("is it a buy?") — confirm steps stream live, the follow-up uses prior context, and Stop works.
- [ ] **Finish the branch:** use superpowers:finishing-a-development-branch to merge `feat/ai-chat-assistant` to `master` (ff-merge per repo convention).

---

## Spec-coverage self-review

- **Multi-turn memory (D1):** Task 6 seeds full history into the transcript; Task 9 sends prior turns; test `test_agent_seeds_conversation_history_into_the_prompt` + `sends prior turns as history`. ✓
- **Stream steps + markdown final (D2):** Tasks 6/9/11/12 — `step` events → `TracePanel`, `final` → `Markdown`. No provider changes. ✓
- **All four tool groups (D3):** Tasks 2–4 implement the 10 tools; `test_registry_has_ten_tools`. ✓
- **Ephemeral session (D4):** Task 10 `ChatProvider` above the router; no SQLite, no persistence (Task 7 endpoint records nothing). ✓
- **Sibling agent (D5):** new `app/chat/` package; `ReActAgent` untouched. ✓
- **POST + fetch-stream transport (D6):** Task 7 endpoint + Task 8 `streamChat`. ✓
- **Tool descriptions verbatim (spec §7):** Task 4 registry strings match the spec catalog. ✓
- **Error handling (spec §13):** tool errors → observation (`test_agent_tool_error_becomes_observation`); nudge + graceful finals (max-steps / no-action tests); LLMError → `error` event (endpoint try/except); transport error → per-turn error (`records a per-turn error`); Stop aborts (`stop()` + AbortController). ✓
- **Testing (spec §14):** backend tool/loop/parser/endpoint tests; frontend hook/markdown/page tests. ✓

No gaps found. No placeholders. Type names consistent across tasks (`ChatTool`, `ChatContext`, `ChatMessage`, `ChatEvent`, `ChatTurn`, `parse_chat_step`, `build_chat_system`, `streamChat`, `useChat`, `ChatProvider`, `Markdown`).
