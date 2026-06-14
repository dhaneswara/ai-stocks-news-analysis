# AI Chat Assistant (multi-turn ReAct, streaming) — Design Spec

- **Date:** 2026-06-14
- **Status:** Proposed (awaiting review)
- **Author:** giri + Claude
- **Area:** `backend/app/chat` (new), `backend/app/api`, `frontend/src`

## 1. Summary

Add a new **`/chat` page**: a conversational AI assistant that helps the user analyze stocks
through whatever data the app already holds — price/fundamentals/technicals, news, the
geopolitics (Trump / Truth-Social) signal, the ontology graph + network signal, the
deterministic opportunity score, the portfolio board, and the LLM's own evaluation track record.

The assistant is a **multi-turn, ticker-agnostic ReAct agent** (Reason → Act → Observe) that
**streams its reasoning steps live** to a per-message trace panel, then renders a free-form
markdown answer. It is a **sibling** to the existing single-ticker `ReActAgent` (deep analysis),
not a modification of it.

## 2. Background — what exists today

- The app has a working prompted-ReAct engine, [`ReActAgent`](../../../backend/app/analysis/agent.py),
  but it is **bound to a single ticker** (`StockData`), answers **one** analysis question, emits
  a structured `AnalysisResult` JSON final answer, and **records a prediction + trace** for the
  evaluation harness. It is the wrong shape for free-form, multi-turn, cross-ticker chat.
- Streaming today uses **native `EventSource` (GET)**: `useDeepAnalyze` → `streamDeepAnalysis`
  → `GET /analyze/{ticker}/deep/stream`, with `TracePanel` rendering `AgentStep`s as they arrive.
- LLM providers expose only **whole-message completion** (`provider.complete(...) -> str`); there
  is no token-level streaming.
- Every data source the chat needs already exists as a callable (see §6); no new external data.

## 3. Goals / Non-goals

**Goals**
- A conversational assistant that can pull from all of the app's data via tools and reason
  across **any** ticker / topic, not a fixed pre-bound context.
- **Multi-turn**: the agent remembers prior turns in the session and supports follow-ups.
- **Live streamed reasoning**: each ReAct step (Thought / Action / Observation) appears as it
  happens, per assistant message; the final answer renders as markdown.
- Reuse existing patterns and components (`AgentStep`, `TracePanel`, `_sse()`, pure-CSS tokens).
- Zero changes to the existing fast/deep analysis paths or the evaluation store.

**Non-goals (v1)**
- Token-level "typing" streaming of the final answer (step-level only; see Decision D2).
- Persisting conversations to disk (ephemeral session; see Decision D4).
- Recording chat answers as tracked predictions — chat is exploratory (see §5, §9).
- Native provider function-calling (prompted ReAct, like the existing agent).
- New external data sources — every tool wraps code we already have.

## 4. Decision log (from brainstorming)

| ID | Decision | Choice |
|----|----------|--------|
| D1 | Conversation model | **Multi-turn with memory** — history replayed to the model each turn. |
| D2 | Streaming granularity | **Stream ReAct steps + a final markdown answer.** No token streaming → no provider changes. |
| D3 | Data scope (tools) | **All four groups**: stock/fundamentals/technicals; news; geopolitics; ontology+score+portfolio+evaluation. (Full catalog in §7.) |
| D4 | Persistence | **Ephemeral session** — history lives in frontend state, survives navigation, clears on reload. Server is stateless. |
| D5 | Agent placement | **New `ChatAgent` sibling**, not an extension of `ReActAgent` (keeps deep-analysis focused & un-regressed). |
| D6 | Transport | **`POST /api/chat/stream` + `fetch`/`ReadableStream` SSE** (EventSource is GET-only; multi-turn history is too large/fragile for a query param). |

## 5. Architecture & flow

The frontend owns the conversation. Each user turn POSTs the **full message history** to a
stateless streaming endpoint, which runs the agent and streams events back:

```
POST /api/chat/stream            body: { messages: [{role, content}, ...] }   (SSE, text/event-stream)
  → build provider from settings (active_provider)
  → ctx = ChatContext(settings, cache, stores)         # tools resolve app data on demand
  → for event in ChatAgent.stream(provider, model, provider_id, messages, ctx, max_steps=10):
        yield _sse(event)                               # step | final | error
        loop body:
          text = provider.complete(react_system, transcript, json_mode=False, stop=["\nObservation:"])
          step = parse_step(text)                       # Thought + (Action(tool,args) | Final Answer(text))
          if Action:        obs = run_tool(name, args, ctx); transcript += "\nObservation: " + obs
          if Final Answer:  answer = text; stop
  → final event carries { answer: markdown string }
  → no prediction/trace persistence (chat is exploratory)
```

The loop is a **generator** (like `ReActAgent`) so the same code can stream events or be drained
to a final answer in tests. The conversation history is rendered into the ReAct transcript so the
agent has prior context; the **current** user message is the active task.

**Why stateless:** the "ephemeral session" choice maps exactly onto "frontend owns history,
server keeps nothing." No session table, no TTLs, no cleanup.

## 6. Existing functions the tools wrap (no new data sources)

| Capability | Function (file) |
|---|---|
| Stock snapshot (price/fundamentals/indicators/news/network/mood) | `gather_stock_context` (`app/services/analysis_service.py`) |
| Raw fundamentals | `fetch_info` (`app/data/market.py`) |
| Candles + indicators | `fetch_history` (`app/data/market.py`), `rsi`/`sma` (`app/analysis/indicators.py`) |
| News search | `search_news` / `get_news` (`app/data/news.py`) |
| Geopolitics mood + mentions | `fetch_recent_posts_cached` + `summarize_market_mood` + `find_mentions` (`app/data/truth_social.py`, `app/analysis/political.py`) |
| Opportunity score (single) | `score_one` (`app/screener/service.py`) |
| Network signal | `active_graph` (`app/network/store.py`) + `incident_edges`/`compute_network_signal` (`app/analysis/network.py`) |
| Ranked board | `run_scan` (`app/screener/service.py`) |
| Evaluation track record | `build_track_record_block` (`app/evaluation/signals.py`) |
| Active ontology overview | `active_graph` (`app/network/store.py`) |
| Watchlist / portfolio universe | `settings.watchlist` / `portfolio_universe` (`app/screener/service.py`) |

## 7. New module: `backend/app/chat/`

- **`app/chat/tools.py`**
  - **`ChatContext`** (dataclass): `settings`, `cache`, and the stores tools need
    (`prediction_store` for `track_record`). Tools resolve data lazily per call.
  - **`Tool`** (dataclass): `name`, `description` (the LLM-facing routing text below),
    `args_spec` (short arg hint), `run(args: dict, ctx: ChatContext) -> str`.
  - **`TOOLS` / `TOOL_BY_NAME`**: the catalog below. Tool contract: validate args; return a
    **string observation** truncated to a token budget; **never raise into the loop** — errors
    become `Observation: ERROR: <msg>` so the agent can adapt. Outputs may use the existing `Cache`.

  **Tool catalog (descriptions are the routing logic and ship verbatim in the system prompt):**

  | Tool | Args | LLM-facing description |
  |---|---|---|
  | `get_stock` | `{ticker, period?}` | Snapshot of one company: latest price & change, fundamentals (market cap, P/E, EPS, dividend, 52-week high/low), and current technicals (RSI, SMA50/200, distance from 52-week high). Use first whenever the user asks about a specific ticker's current state, valuation, or technicals. |
  | `price_window` | `{ticker, lookback_days, indicator?}` | Summarize a stock's recent price action over the last N trading days, with optional RSI or SMA on that window. Use for trend/momentum, a pullback or rally, or a specific indicator over a timeframe — not the full snapshot (use `get_stock`). |
  | `search_news` | `{query, limit?}` | Search recent news headlines for a company, sector, or free-text topic (e.g. "semiconductor export controls"). Use when the user asks what's happening, why a stock moved, or about an event or theme. Returns headlines with dates and sources. |
  | `geopolitics` | `{ticker?}` | Current political/geopolitical market mood derived from Trump's Truth Social posts, plus any posts mentioning a given company. Use for questions about political risk, tariffs/policy, Trump, or how geopolitics affects a stock. |
  | `opportunity_score` | `{ticker}` | The app's deterministic (non-LLM) opportunity score for one ticker: 0–100 score, a buy/sell/hold call, and the reasons (technical + network blend). Use for a quick "is this a buy/sell?" verdict on a single named stock. |
  | `network_signal` | `{ticker}` | A company's relationships from the active ontology graph (competitors, suppliers, customers, partners…) and the network signal its neighbours contribute. Use for questions about connections, supply chain, rivals, or how related companies' news affects it. |
  | `portfolio_board` | `{scope?, direction?, limit?}` | Scan and rank many companies by opportunity score, returning the top buy or sell candidates. Use when the user wants the best opportunities or a ranked list across their watchlist/portfolio or a sector — rather than one named ticker. |
  | `track_record` | `{ticker}` | The LLM's own past recommendation accuracy for a ticker (hit rate / grade across matured 1/5/20-day horizons, overconfidence flag). Use when the user asks how reliable past calls were or whether to trust the model on this stock. |
  | `ontology_overview` | `{}` | List the active ontology: its name and the companies and relationship types it contains. Use when the user asks what the knowledge graph knows, or to ground a network question before drilling into one ticker. |
  | `watchlist` | `{}` | Return the user's current watchlist tickers. Use when the user says "my watchlist", "my stocks", or "my portfolio" without naming tickers, so you know which companies they mean. |

- **`app/chat/agent.py`**
  - **`ChatMessage`** (pydantic): `role: 'user' | 'assistant'`, `content: str`.
  - **`ChatEvent`** (pydantic): `type: 'step' | 'final' | 'error'`; `step: AgentStep | None`
    (reuse the existing `AgentStep` so `TracePanel` works unchanged); `answer: str = ''`
    (markdown, on `final`); `message: str = ''` (on `error`).
  - **`build_chat_system(tools)`**: a chat-oriented system prompt — assistant role, the ReAct
    protocol (§8), the tool catalog (rendered from descriptions + arg specs), and the instruction
    to end with a markdown `Final Answer:`. (No `AnalysisResult` JSON schema.)
  - **`ChatAgent.stream(provider, model, provider_id, messages, ctx, *, max_steps=10) -> Iterator[ChatEvent]`**:
    seeds the transcript from `messages` (history + current question), drives the loop, yields a
    `step` per tool call (or malformed step), and a terminal `final` (markdown answer) or `error`.
    One corrective nudge on format violation (reuse the tolerant `parse_step` approach); on an
    unrecoverable failure, emit an `error` event (no AnalysisResult fallback — chat has no
    structured contract to fall back to).
  - **`ChatAgent.run(...) -> str`**: drains `stream()` to the final answer (tests / non-streaming).

## 8. ReAct response protocol

Per turn the model replies with exactly one of:

```
Thought: <what to check next>
Action: <tool_name>(<json args>)
```
or, when it has enough evidence:
```
Thought: <final reasoning>
Final Answer: <markdown answer to the user>
```

Parsing reuses the existing tolerant approach (regex for `Thought:`/`Action:`, `raw_decode` for
the JSON args, tolerant of code fences / trailing prose). `stop=["\nObservation:"]` prevents the
model from hallucinating tool output. The **only** difference from `ReActAgent` is the final
answer is **free markdown**, not JSON.

## 9. Persistence & recording

**None.** The server is stateless for chat; the conversation lives in frontend state. Chat
answers are **not** written to the prediction/evaluation store or the trace store — chat is
exploratory, mirroring the app's "manual/merged graph edits are exploration-only, don't feed
scores" philosophy. This keeps the source scoreboard clean and avoids polluting accuracy metrics.

## 10. API changes

- **New:** `POST /api/chat/stream` — body `{ messages: [{role, content}, ...] }`, returns an SSE
  stream (`StreamingResponse`, `media_type="text/event-stream"`, reusing `_SSE_HEADERS` and
  `_sse()`). Events: `step` (carries `AgentStep`), `final` (carries `{answer}`), `error`.
- **Unchanged:** all existing endpoints.

## 11. Frontend changes

- **`api/client.ts`** — `streamChat(messages, handlers)`:
  - `fetch(`${BASE}/chat/stream`, { method:'POST', body: JSON, signal })` then read
    `response.body.getReader()`; a small (~30-line) SSE parser splits on `\n\n` and dispatches
    `event:`/`data:` to `handlers.onEvent` / `handlers.onError`.
  - Returns a closer that calls `controller.abort()` (same closer contract as the EventSource fns).
  - This is the one deliberate divergence from the EventSource pattern (Decision D6), required for
    a POST body.
- **`hooks/useChat.ts`** — manages the in-flight assistant turn: accumulates live `steps`, sets
  the final answer, exposes `send(text)` / `stop()` / `running` / `error`. Closes the stream on
  unmount and on a new send.
- **`state/chatState.tsx`** — `ChatProvider` mounted above the router (like `DashboardStateProvider`),
  holding the `messages` list so the conversation survives navigation but clears on reload.
- **`pages/Chat.tsx`** — a scrolling message list:
  - User messages as bubbles; assistant messages rendered as **markdown**.
  - Each assistant turn shows a collapsible **`TracePanel`** (reused as-is) of its ReAct steps,
    with the live `step n/max` indicator while running.
  - A composer (textarea + **Send**, **Stop** while running) and a few **suggestion chips**
    (e.g. "How does geopolitics affect NVDA?", "Compare AMD vs NVDA using the ontology",
    "What's the strongest opportunity in my watchlist?").
- **Routing/nav** — register `<Route path="/chat">` and a `Chat` `NavLink` in `App.tsx`; wrap the
  app with `ChatProvider`.
- **Markdown** — check for an existing renderer; if none, add a minimal safe markdown renderer
  (headings/bold/lists/code/links) rather than a heavy dependency. Confirm during implementation.
- **Styling** — pure CSS in `styles.css` using existing tokens (`--panel`, `--gold`, `--buy`,
  `--sell`, serif/sans/mono), matching the Dashboard/Evaluation look.

## 12. SSE event shapes

```
event: step
data: {"type":"step","step":{ "index":0,"thought":"…","action":"get_stock",
        "action_args":{"ticker":"NVDA"},"observation":"…","is_final":false,"elapsed_ms":420 }}

event: final
data: {"type":"final","answer":"## NVDA\n\nGeopolitically, …"}

event: error
data: {"type":"error","message":"LLM provider error: …"}
```

## 13. Safety / limits / errors

- Hard caps: `max_steps=10`, observation truncation (reuse the existing char cap), one format-repair
  nudge.
- Tool errors → `Observation: ERROR: …`, never raised. Missing prerequisites (no active ontology,
  no API key, no Truth-Social data) → a clear "not available" observation the agent can reason about.
- Step cap reached without a final answer → a graceful assistant message ("I couldn't finish that
  — try narrowing the question").
- LLM/provider failure → `error` event; the composer re-enables and shows the message inline.
- **Stop** aborts the in-flight fetch and discards the partial turn.

## 14. Testing

- **Backend**
  - Tools: each tool's happy path against fixture data + the error→observation path + arg validation.
  - Loop: a **mock provider** emitting scripted Thought/Action/Final-Answer turns — assert tool
    dispatch, observation threading, multi-turn history seeding, `max_steps` enforcement, the
    format-repair nudge, and the markdown final answer.
  - Parser: malformed / fenced / extra-prose outputs (reuse/extend existing parser tests).
  - Endpoint: `POST /api/chat/stream` emits a well-formed `step…final` SSE sequence (sandboxed via
    the existing `conftest.py` temp `DATA_DIR`).
- **Frontend**
  - `useChat` against a mocked streaming `fetch` (step → final → done); assert `stop()` aborts.
  - `Chat` page renders user/assistant turns + the trace; suggestion chip seeds the composer.

## 15. Suggested build order (each independently shippable)

1. **Tools + `ChatContext`** (`app/chat/tools.py`) with unit tests.
2. **`ChatAgent` loop + `build_chat_system` + events** (`app/chat/agent.py`), non-streaming `run()`
   + loop tests with a mock provider.
3. **`POST /api/chat/stream` endpoint** + SSE test.
4. **Frontend transport + hook + state** (`streamChat`, `useChat`, `ChatProvider`) with tests.
5. **`Chat.tsx` page + routing/nav + styles + markdown rendering.**

## 16. Open questions / risks

- **Format-following reliability** across providers (esp. local/Ollama). Mitigated by the
  corrective nudge; on failure we surface an `error` (no structured fallback exists for chat).
- **Latency/cost** per multi-step turn (more tool calls than deep analysis since chat is open-ended).
  Bounded by `max_steps=10`; the user controls scope by how they phrase questions.
- **Prompt size** as the conversation grows — history is replayed each turn. v1 sends full history;
  a later turn-window/summarization cap can be added if needed.
- **Markdown renderer** choice (existing vs. minimal new) — to confirm in implementation.
- **Provider whole-message latency** means the final answer appears all at once after the last
  step; acceptable given D2 (steps provide the live "something is happening" feedback).
