# Agentic "Deep Analysis" (prompted ReAct) — Design Spec

- **Date:** 2026-06-08
- **Status:** Proposed (awaiting review)
- **Author:** giri + Claude
- **Area:** `backend/app/analysis`, `backend/app/llm`, `backend/app/api`, `backend/app/evaluation`, `frontend/src`

## 1. Summary

Add an **opt-in, agentic "Deep Analysis"** path to the dashboard that runs the LLM as a
bounded **ReAct loop** (Reason → Act → Observe) with tools to pull data on demand, instead of
the current single-shot call. The agent's reasoning **trace** is streamed live to the UI
(step-level, via SSE) so the user can see what the LLM is doing and that progress is happening,
and is persisted for later review. The existing fast single-shot path is unchanged and remains
the default.

The trace doubles as the observability the user originally asked for ("track what the LLM is
doing"): per-run transparency, a browsable history, and a developer debugging view all come
from the one `AgentTrace` object.

## 2. Background — how Analyze-with-LLM works today

The current flow (`POST /analyze/{ticker}` → [`run_analysis`](../../../backend/app/services/analysis_service.py) →
[`analyze`](../../../backend/app/analysis/analyzer.py)) is a **single-shot, structured-output call**, not an agent:

1. Python gathers a **fixed** bundle of data first: price candles, RSI/SMA50/SMA200,
   fundamentals, ~10 news headlines, Trump/Truth-Social mood + mentions, and the
   company-network signal.
2. It builds one system + one user prompt (`build_user_prompt`) and makes **one** call:
   `provider.complete(system, user) -> str` (for Anthropic, a single `messages.create()` with
   **no `tools`** parameter).
3. It extracts JSON; on failure it makes **one** repair call. That single retry is the only loop.
4. **Python**, not the LLM, post-processes: `_snap_signals` and `_filter_incoherent_signals`.

**It is not ReAct.** The model never decides to fetch more data, never calls a tool, never
iterates. Today's accuracy levers are rich pre-computed context, a strict prompt, the JSON
repair, and deterministic guardrails.

**What's tracked today:** only the *outcome* (the evaluation feature records
ticker/provider/model/recommendation/confidence/entry-price to SQLite and scores it vs. real
price at 1/5/20 days). The **prompt, raw response, token usage, latency, and retries are not
captured anywhere**, and there is no tracing tooling.

## 3. Goals / Non-goals

**Goals**
- An opt-in agentic analysis that can fetch targeted evidence on demand, aiming to improve
  recommendation accuracy over the single-shot path.
- A live, step-level streamed reasoning trace in the dashboard ("what the LLM is doing" +
  visible progress).
- Persist traces for later inspection (history / audit).
- Make "is it actually more accurate?" measurable via the existing evaluation harness.
- Zero changes to the existing fast path's behavior or contract.

**Non-goals (v1)**
- Native provider function-calling (we use prompted ReAct; see Decision D5).
- Token-level "typing" streaming (step-level only; see Decision D6).
- Adaptive escalation between fast and deep (deep is an explicit opt-in; see Decision D4).
- New external data sources — every tool wraps code we already have.

## 4. Decision log (from brainstorming)

| ID | Decision | Choice |
|----|----------|--------|
| D1 | Primary intent | Improve accuracy via an agentic/ReAct approach; observability comes along for free as the trace. |
| D2 | Agent tools | All four: targeted news, deeper fundamentals, price-history/event-study, and the app's own signals (network + Discover score). |
| D3 | Posture | **Opt-in "Deep Analysis" button**; fast single-shot stays the default. |
| D4 | Adaptive escalation | Deferred (explicit opt-in only). |
| D5 | Loop architecture | **A · Prompted ReAct** (text Thought/Action/Observation loop over the existing `complete()`), provider-agnostic. Not native function-calling. |
| D6 | Streaming | **Step-level SSE** in v1 (each step as it completes + progress indicator). Token-level deferred. |

## 5. Architecture & flow

A new opt-in path running parallel to the untouched single-shot. The agent loop is implemented
as a **generator** so that the same code serves both streaming (yield each event) and
non-streaming (drain to the final result) callers — there is **no parallel code path**.

```
GET /analyze/{ticker}/deep/stream?period=2y          (SSE, text/event-stream)
  → gather_stock_context(ticker, period, settings, cache)   # extracted from run_analysis
  → for event in ReActAgent.stream(stock, provider, tools, max_steps=6):
        yield SSE(event)                                     # step_started/thought/action/observation/final/error
        loop body:
          text = provider.complete(react_system, transcript)
          step = parse(text)            # Thought + (Action(tool,args) | Final Answer(json))
          if Action:  obs = tools[name].run(args); transcript += "\nObservation: " + obs
          if Final:   result = finalize(json); stop
  → finalize(): same AnalysisResult as today → _snap_signals → _filter_incoherent_signals
  → on `final`: persist AgentTrace; record_prediction(mode='deep')
  → on any failure: fall back to single-shot analyze(); emit that as the `final` event
```

**Crux of the reuse:** the agent's Final Answer uses the **exact same `AnalysisResult`
schema** as today (reusing `_JSON_SCHEMA_HINT`), so signal-snapping, incoherent-signal
filtering, the evaluation recorder, and the existing dashboard rendering all work unchanged.
The agent only changes *how* the JSON is produced.

**Shared data-gathering refactor:** extract the data-gathering portion of `run_analysis`
(stock data + network signal + truth-social mood) into a `gather_stock_context(...)` helper so
both the fast and deep paths use one implementation. The fast `run_analysis` keeps its current
behavior by calling the helper, then `analyze()`.

## 6. New module: `backend/app/analysis/agent.py`

- **`Tool`** (dataclass): `name`, `description`, `args_spec` (short text describing args), and
  `run(args: dict, ctx: ToolContext) -> str`. `ctx` carries the already-gathered `stock`,
  `settings`, and `cache` so tools reuse existing fetchers and the cache.
- **`TOOL_REGISTRY`**: the four tools (Section 7).
- **`AgentEvent`** (pydantic): one of `step_started`, `thought`, `action`, `observation`,
  `final`, `error` (see Section 9 for fields).
- **`ReActAgent.stream(stock, provider, model, provider_name, *, max_steps=6) -> Iterator[AgentEvent]`**:
  - Builds the **ReAct system prompt**: the tool catalog (names + descriptions + arg specs),
    the strict response protocol (Section 8), and the final-answer schema (`_JSON_SCHEMA_HINT`).
  - Seeds the transcript with the **same context block** `build_user_prompt` produces today, so
    the agent starts from everything the single-shot already knows and *augments* via tools.
  - Drives the loop, yielding an event per phase; enforces `max_steps`, a per-tool-call cap, and
    a wall-clock timeout.
  - On a format violation: emit one corrective nudge ("you broke the format, reply with exactly
    one Thought and one Action or Final Answer"); if it still fails, treat the text as the final
    answer (graceful degradation) or fall back to single-shot.
- **`ReActAgent.run(...) -> tuple[AnalysisResult, AgentTrace]`**: a thin wrapper that drains
  `stream()` and returns the final result + accumulated trace (for the CLI / non-streaming
  callers and tests).

## 7. The four tools (each wraps existing code — no new data sources)

| Tool | Signature (args) | Wraps | Observation (truncated string) |
|------|------------------|-------|--------------------------------|
| `fetch_news` | `query: str, limit: int=5` | `app/data/news.py` | `[date] title (source)` lines beyond the seed headlines |
| `get_fundamentals` | `detail: str` (e.g. `earnings`,`revenue`,`margins`,`growth`) | `app/data/market.py` / yfinance | key figures not in the seed snapshot |
| `price_window` | `around: str` (e.g. `last_earnings`) **or** `lookback_days: int`; optional `indicator`,`period` | `market.py` candles + `app/analysis/indicators.py` | OHLC summary + % move + requested indicator values |
| `app_signals` | `kind: 'network' \| 'score'`, optional `ticker` | `network.py` (`compute_network_signal`,`incident_edges`,`effective_graph`,`load_snapshot`) + `scoring.py` (`score_one`) | neighbours' recent leans / the deterministic Discover score + reasons |

Tool contract: validate args; return a **string observation** truncated to a token budget
(~400 tokens); **never raise into the loop** — errors become `Observation: ERROR: <msg>` so the
agent can adapt. Tool outputs may be cached via the existing `Cache`.

## 8. ReAct response protocol

The model is instructed to reply with exactly one of these per turn:

```
Thought: <reasoning about what to check next>
Action: <tool_name>(<json args>)
```
or, when it has enough evidence:
```
Thought: <final reasoning>
Final Answer: <single JSON object matching the AnalysisResult schema>
```

Python parses the last `Action:` or `Final Answer:`. The `Action:` arg payload is JSON for
robust parsing. Parsing is defensive (tolerates code fences, extra prose) and has the one-shot
corrective nudge described above.

## 9. Trace & persistence (the observability)

**`AgentTrace`** (pydantic, returned + persisted):
`ticker`, `provider`, `model`, `started_at`, `elapsed_ms`, `stopped_reason`
(`final` | `max_steps` | `error` | `fallback`), `token_usage` (when the provider exposes it),
`steps: list[Step]`, `final: AnalysisResult`.
**`Step`**: `index`, `thought`, `action: {tool, args} | None`, `final: bool`,
`observation: str | None`, `elapsed_ms`.

**Persistence:** a new SQLite table `agent_traces(ticker, call_date, provider, model, trace_json,
created_at, PRIMARY KEY(ticker, call_date))`, in a new `AgentTraceStore` (mirroring the
`PredictionStore` pattern). Written when the `final` event fires. This delivers the
"running history / audit log" for free.

## 10. Streaming (SSE)

- **Transport:** Server-Sent Events over a **GET** endpoint (inputs are only ticker + period, so
  `EventSource` works; settings are read server-side). Implemented with FastAPI
  `StreamingResponse` emitting `text/event-stream` (dep-free; `sse-starlette` optional if we want
  heartbeats/retry helpers).
- **Events:** each `AgentEvent` is serialized as one SSE message (`event:` = type,
  `data:` = JSON). Terminal events are `final` (carries `{result, trace}`) and `error`.
- **Recording on completion:** trace persistence + `record_prediction` happen when the generator
  yields `final`, server-side, so they occur even if the loop ends via fallback. (Open item:
  client-disconnect mid-stream — v1 records on `final` within the streaming generator; running
  fully detached is a possible later hardening.)

## 11. API changes

- **New:** `GET /analyze/{ticker}/deep/stream?period=2y` → SSE stream of agent events; the
  `final` event carries `{ result: AnalysisResult, trace: AgentTrace }`.
- **New:** `GET /traces/{ticker}` → most recent stored `AgentTrace`(s) for history.
- **Unchanged:** `POST /analyze/{ticker}` (fast single-shot) keeps its exact contract.

## 12. Frontend changes

- A **Deep Analysis** button beside *Analyze with LLM* on `pages/Dashboard.tsx`.
- A new client helper in `api/client.ts` + a hook (custom `EventSource` hook, not React Query,
  since this is a stream) that accumulates events into trace state.
- A collapsible **"Agent trace — what the LLM did"** panel (alongside/extending
  `components/ReasoningPanel.tsx`) that appends each Thought → Action(args) → Observation as it
  arrives, with a live `step 3/6 · fetching news…` indicator and a spinner on the in-flight step.
- On `final`, the normal analysis output (signals, key factors, network influence, etc.) renders
  exactly as today from the shared `AnalysisResult`.

## 13. Safety / limits / fallback

- Hard caps: `max_steps=6`, per-tool-call cap, wall-clock timeout.
- Tool errors are fed back as `Observation: ERROR: …`, never raised.
- On **any** agent failure (format unrecoverable, timeout, exception), **fall back to the
  existing single-shot** `analyze()` and emit it as the `final` event — Deep Analysis never
  hard-fails.
- Token/step budget guards to bound cost.

## 14. Measurement (prove it's worth it)

- Add a `mode TEXT DEFAULT 'fast'` column to the evaluation `predictions` table (safe additive
  SQLite migration) and thread `mode` through `record_prediction`.
- The evaluation page/CLI gains a **fast vs. deep** comparison on the same 1/5/20-day hit/score,
  turning "is ReAct more accurate?" into a tracked number.

## 15. Testing

- **Tools:** unit tests against fixture data (deterministic), including the error→observation path.
- **Loop:** tests with a **mock provider** that emits scripted Thought/Action/Final-Answer turns;
  assert tool dispatch, observation threading, `max_steps` enforcement, the format-repair nudge,
  and graceful fallback. The generator design makes this a clean event-sequence assertion.
- **Parser:** malformed / fenced / extra-prose model outputs.
- **Streaming:** endpoint emits the expected event sequence and a schema-valid `final`.
- **Smoke:** a `deep` analysis yields a schema-valid `AnalysisResult` and a persisted trace.

## 16. Suggested build order (each independently shippable)

1. **Core loop + tools + non-streaming `run()`** (generator, 4 tools, fallback, tests).
2. **SSE streaming endpoint + frontend Deep Analysis button + live trace panel.**
3. **Trace persistence + `GET /traces/{ticker}` history.**
4. **Eval-harness `mode` tagging + fast-vs-deep comparison.**

## 17. Open questions / risks

- **Format-following reliability** across providers (esp. Ollama/local models). Mitigated by the
  corrective nudge + fallback; the eval harness will surface it. Upgrade path is native
  function-calling (Decision D5, deferred).
- **Cost/latency** per deep run (~5–8 calls, ~10–20s). Bounded by caps; opt-in keeps it off the
  default path.
- **Client disconnect** mid-stream (Section 10 open item).
- **yfinance fundamentals depth** — `get_fundamentals` is limited to fields yfinance exposes;
  some `detail` values may return "not available".
