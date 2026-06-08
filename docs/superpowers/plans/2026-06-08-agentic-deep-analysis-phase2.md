# Agentic Deep Analysis — Phase 2 (SSE Streaming + Deep Analysis UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Phase 1 ReAct engine into the dashboard: a **Deep Analysis** button that streams the agent's reasoning steps live (step-level SSE) into a trace panel, then renders the final analysis exactly like the fast path.

**Architecture:** The `ReActAgent` loop becomes a **generator** (`stream()` yields `AgentEvent`s — one `step` per completed step, then a terminal `final` carrying the `AnalysisResult` + `AgentTrace`); the existing `run()` just drains it (no parallel code path). A new **GET SSE endpoint** `/analyze/{ticker}/deep/stream` serves those events as `text/event-stream`, reusing a new `gather_stock_context` helper extracted from `run_analysis`. The frontend opens an `EventSource`, accumulates steps in a `useDeepAnalyze` hook, shows them in a `TracePanel`, and on `final` reuses the existing `setAnalysis` path so the chart markers + `ReasoningPanel` render unchanged.

**Tech Stack:** Python 3.11, FastAPI `StreamingResponse`, Pydantic v2, pytest + `TestClient`. Frontend: React + TS, native `EventSource`, vitest + @testing-library/react.

**Scope:** Phase 2 of 4 (spec [design](../specs/2026-06-08-agentic-deep-analysis-design.md) §5/§10/§11/§12; Phase 1 is merged). **Deferred:** trace persistence + `GET /traces` (Phase 3); evaluation `mode` tagging + fast-vs-deep comparison (Phase 4); token-level streaming. The deep path does **not** record predictions in Phase 2 (that's Phase 4's mode-tagged recording).

**Branch:** create `feat/agentic-deep-analysis-phase2` off `master` before Task 1.

---

## File Structure

| File | Change |
|------|--------|
| `backend/app/analysis/agent.py` | Add `AgentEvent`; refactor `ReActAgent` loop into `stream()` (generator) + `_run_loop`; `run()` drains `stream()`. |
| `backend/app/services/analysis_service.py` | Extract `gather_stock_context(ticker, period, settings, cache, provider)` from `run_analysis`. |
| `backend/app/api/routes.py` | Add `GET /analyze/{ticker}/deep/stream` (SSE) + `_sse` formatter. |
| `backend/tests/test_agent.py` | `stream()` event-sequence tests. |
| `backend/tests/test_analysis_service.py` | `gather_stock_context` test. |
| `backend/tests/test_api_deep_stream.py` (create) | SSE endpoint test via `TestClient`. |
| `frontend/src/types.ts` | `AgentStep`, `AgentTrace`, `AgentEvent`. |
| `frontend/src/api/client.ts` | `streamDeepAnalysis(ticker, period, handlers) => closeFn`. |
| `frontend/src/api/client.test.ts` | EventSource-mock test for `streamDeepAnalysis`. |
| `frontend/src/hooks/useDeepAnalyze.ts` (create) + `.test.tsx` | streaming hook (state machine over the client). |
| `frontend/src/components/TracePanel.tsx` (create) + `.test.tsx` | live step list + progress. |
| `frontend/src/components/TickerBar.tsx` + `.test.tsx` | **Deep Analysis** button. |
| `frontend/src/pages/Dashboard.tsx` | wire the hook + button + trace panel. |

> Backend tests: `cd D:/workspace/ai-stocks-news-analysis/backend && .venv/Scripts/python.exe -m pytest <args>`.
> Frontend tests/build: `cd D:/workspace/ai-stocks-news-analysis/frontend && npm test -- <args>` and `npm run build`.

---

### Task 1: Agent `stream()` generator + `AgentEvent`

**Files:** Modify `backend/app/analysis/agent.py`; Test `backend/tests/test_agent.py`

- [ ] **Step 1: Write failing tests** — append to `backend/tests/test_agent.py`:

```python
from app.analysis.agent import AgentEvent  # add to the existing agent imports at the top


def test_stream_yields_steps_then_final():
    provider = FakeProvider([
        'Thought: check\nAction: echo({"q": "hi"})',
        f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}',
    ])
    events = list(ReActAgent(tools=[_ECHO]).stream(provider, "m", "fake", _ctx()))
    assert [e.type for e in events] == ["step", "step", "final"]
    assert events[0].step.action == "echo"
    assert events[-1].result.current_recommendation == "buy"
    assert events[-1].trace.stopped_reason == "final"
    assert events[-1].trace.fell_back is False


def test_stream_emits_final_on_fallback():
    provider = FakeProvider(["garbage", "garbage", json.dumps(VALID_PAYLOAD)])
    events = list(ReActAgent(tools=[_ECHO], max_steps=5).stream(provider, "m", "fake", _ctx()))
    assert events[-1].type == "final"
    assert events[-1].trace.fell_back is True
    assert events[-1].result.current_recommendation == "buy"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_agent.py -k stream -v`
Expected: FAIL with `ImportError: cannot import name 'AgentEvent'`

- [ ] **Step 3: Implement** — in `backend/app/analysis/agent.py`, add `AgentEvent` just before `class ReActAgent` and REPLACE the existing `run` + `_drive` methods with `stream` + `run` + `_run_loop` (keep `_run_tool` unchanged):

```python
class AgentEvent(BaseModel):
    type: Literal["step", "final", "error"]
    step: Optional[AgentStep] = None
    result: Optional[AnalysisResult] = None
    trace: Optional[AgentTrace] = None
    message: str = ""
```

```python
    def stream(self, provider: LLMProvider, model: str, provider_name: str,
               ctx: ToolContext) -> "Iterator[AgentEvent]":
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
                  ctx: ToolContext, trace: AgentTrace) -> "Iterator[AgentStep]":
        """Yields each AgentStep as it completes; sets trace.final and returns on a valid final
        answer; raises _AgentFailure on parse_error / no_action / max_steps."""
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
```

Also add `Iterator` to the `typing` import at the top: `from typing import Callable, Iterator, Literal, Optional`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_agent.py -v`
Expected: PASS — the 2 new `stream` tests AND all pre-existing agent tests (the Phase-1 `run()` tests still pass because `run()` now drains `stream()`). 31 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/agent.py backend/tests/test_agent.py
git commit -m "feat(deep-analysis): expose the ReAct loop as a streaming generator"
```

---

### Task 2: Extract `gather_stock_context`

**Files:** Modify `backend/app/services/analysis_service.py`; Test `backend/tests/test_analysis_service.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_analysis_service.py`:

```python
def test_gather_stock_context_returns_get_stock_data_result(monkeypatch):
    from app.config.cache import Cache
    from app.models.schemas import Settings
    from app.services import analysis_service
    from tests.test_analyzer import _stock

    sentinel = _stock()
    monkeypatch.setattr(analysis_service, "get_stock_data", lambda t, p, ip, c: sentinel)
    settings = Settings()
    settings.network.enabled = False
    settings.truth_signal.enabled = False  # both off -> gather returns the stock unmodified
    out = analysis_service.gather_stock_context("aapl", "1y", settings, Cache(":memory:"), provider=None)
    assert out is sentinel
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_analysis_service.py -k gather -v`
Expected: FAIL with `AttributeError: module 'app.services.analysis_service' has no attribute 'gather_stock_context'`

- [ ] **Step 3: Implement** — in `backend/app/services/analysis_service.py`, add `gather_stock_context` and call it from `run_analysis`. Add this function (above `run_analysis`):

```python
def gather_stock_context(ticker, period, settings, cache, provider) -> StockData:
    """Build the StockData the analyzers consume: price/indicators/news + the company-network
    signal + the truth-social mood. Shared by the fast (run_analysis) and deep (agent) paths."""
    ticker = ticker.upper().strip()
    stock = get_stock_data(ticker, period, settings.indicator_params, cache)

    ncfg = settings.network
    if ncfg.enabled:
        graph = effective_graph(cache, "focus")
        if graph.edges:
            board = load_snapshot(cache, "all")
            base_index = {s.ticker: s for s in (board.items if board else [])}
            edges = incident_edges(ticker, graph.edges, set(ncfg.symmetric_types))
            if edges:
                stock.network = compute_network_signal(ticker, edges, base_index, ncfg)

    ts = settings.truth_signal
    if ts.enabled:
        posts = truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
        stock.trump_mentions = political.find_mentions(posts, ticker, stock.company_name)
        cfg = settings.providers[settings.active_provider]
        stock.market_mood = political.summarize_market_mood(
            posts, provider, cfg.model, settings.active_provider, cache
        )
    return stock
```

Then REPLACE the data-gathering block inside `run_analysis` (everything from `stock = get_stock_data(...)` down to just before `result = analyze(...)`) with:

```python
    provider = build_provider(settings)
    stock = gather_stock_context(ticker, period, settings, cache, provider)
```

(So `run_analysis` keeps building `provider`, then delegates gathering to the helper, then calls `analyze(stock, provider, model=cfg.model, provider_name=provider_id)` exactly as before.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_analysis_service.py -v`
Expected: PASS — the new gather test AND all pre-existing `run_analysis` tests (behavior-preserving refactor).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/analysis_service.py backend/tests/test_analysis_service.py
git commit -m "refactor(deep-analysis): extract gather_stock_context from run_analysis"
```

---

### Task 3: SSE endpoint

**Files:** Modify `backend/app/api/routes.py`; Test `backend/tests/test_api_deep_stream.py` (create)

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_api_deep_stream.py`:

```python
import json

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from tests.test_analyzer import VALID_PAYLOAD, FakeProvider, _stock

client = TestClient(app)


def test_deep_stream_emits_steps_and_final(monkeypatch):
    monkeypatch.setattr(routes, "gather_stock_context", lambda t, p, s, c, prov: _stock())
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider([f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}']),
    )
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: final" in resp.text
    assert '"current_recommendation":"buy"' in resp.text


def test_deep_stream_404_when_no_price_data(monkeypatch):
    def boom(*a, **k):
        raise ValueError("No price history for ticker 'ZZZZ'")
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "gather_stock_context", boom)
    resp = client.get("/api/analyze/ZZZZ/deep/stream")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_api_deep_stream.py -v`
Expected: FAIL (404 from the unknown route, or AttributeError) — the endpoint doesn't exist yet.

- [ ] **Step 3: Implement** — in `backend/app/api/routes.py`:
  1. Add imports near the top: `from fastapi.responses import StreamingResponse` and `from app.analysis.agent import AgentEvent, ReActAgent, ToolContext`.
  2. Extend the analysis-service import: `from app.services.analysis_service import gather_stock_context, run_analysis`.
  3. Add the formatter + endpoint (place after `analyze_ticker`):

```python
def _sse(event: AgentEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


@router.get("/analyze/{ticker}/deep/stream")
def analyze_deep_stream(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> StreamingResponse:
    """Agentic (ReAct) deep analysis, streamed step-by-step as Server-Sent Events. Pre-stream
    failures (no data / missing key) return a normal 404/502; once streaming, the agent's
    single-shot fallback guarantees a terminal `final` (or an `error`) event."""
    settings = store.load()
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise HTTPException(status_code=502, detail=f"No configuration for provider '{provider_id}'")
    try:
        provider = build_provider(settings)
        stock = gather_stock_context(ticker, period, settings, cache, provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ctx = ToolContext(stock=stock, settings=settings, cache=cache)
    agent = ReActAgent()

    def event_stream():
        try:
            for event in agent.stream(provider, cfg.model, provider_id, ctx):
                yield _sse(event)
        except LLMError as exc:  # fallback analyze() also failed — surface as a clean SSE error
            yield _sse(AgentEvent(type="error", message=str(exc)))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_api_deep_stream.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the whole backend suite (no regressions)**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_deep_stream.py
git commit -m "feat(deep-analysis): SSE endpoint GET /analyze/{ticker}/deep/stream"
```

---

### Task 4: Frontend types + `streamDeepAnalysis` SSE client

**Files:** Modify `frontend/src/types.ts`, `frontend/src/api/client.ts`; Test `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test** — append to `frontend/src/api/client.test.ts`:

```typescript
import { streamDeepAnalysis } from './client';

class FakeEventSource {
  static last: FakeEventSource | null = null;
  url: string;
  listeners: Record<string, (e: { data?: string }) => void> = {};
  closed = false;
  constructor(url: string) { this.url = url; FakeEventSource.last = this; }
  addEventListener(type: string, cb: (e: { data?: string }) => void) { this.listeners[type] = cb; }
  close() { this.closed = true; }
  emit(type: string, data?: string) { this.listeners[type]?.({ data }); }
}

it('forwards step then final events and closes after final', () => {
  (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
  const events: { type: string }[] = [];
  streamDeepAnalysis('AAPL', '1y', { onEvent: (e) => events.push(e), onError: vi.fn() });
  const es = FakeEventSource.last!;
  expect(es.url).toContain('/analyze/AAPL/deep/stream?period=1y');
  es.emit('step', JSON.stringify({ step: { index: 0, thought: 'hi', action: 'fetch_news' } }));
  es.emit('final', JSON.stringify({ result: { current_recommendation: 'buy' }, trace: { steps: [] } }));
  expect(events.map((e) => e.type)).toEqual(['step', 'final']);
  expect(es.closed).toBe(true);
});

it('reports a connection error when the native error event has no data', () => {
  (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
  const onError = vi.fn();
  streamDeepAnalysis('ZZZZ', '1y', { onEvent: vi.fn(), onError });
  FakeEventSource.last!.emit('error');
  expect(onError).toHaveBeenCalled();
  expect(FakeEventSource.last!.closed).toBe(true);
});
```

Ensure the file's top imports include `vi` (e.g. `import { expect, it, vi } from 'vitest';` — match the existing import line in this test file, adding `vi` if absent).

- [ ] **Step 2: Run to verify it fails**

Run: `cd D:/workspace/ai-stocks-news-analysis/frontend && npm test -- src/api/client.test.ts`
Expected: FAIL — `streamDeepAnalysis` is not exported.

- [ ] **Step 3: Implement**

In `frontend/src/types.ts`, append:

```typescript
export interface AgentStep {
  index: number;
  thought: string;
  action: string | null;
  action_args: Record<string, unknown>;
  observation: string | null;
  is_final: boolean;
  elapsed_ms: number;
}
export interface AgentTrace {
  ticker: string;
  provider: string;
  model: string;
  started_at: string;
  elapsed_ms: number;
  stopped_reason: 'final' | 'max_steps' | 'parse_error' | 'no_action';
  fell_back: boolean;
  steps: AgentStep[];
  final: AnalysisResult | null;
}
export interface AgentEvent {
  type: 'step' | 'final' | 'error';
  step?: AgentStep | null;
  result?: AnalysisResult | null;
  trace?: AgentTrace | null;
  message?: string;
}
```

In `frontend/src/api/client.ts`, add the `AgentEvent` type import and the function (after the `api` object is fine):

```typescript
import type { /* …existing… */ AgentEvent } from '../types';

export interface DeepStreamHandlers {
  onEvent: (event: AgentEvent) => void;
  onError: (message: string) => void;
}

/** Open an SSE stream for an agentic deep analysis. Returns a closer the caller MUST keep and
 *  invoke on unmount — EventSource auto-reconnects otherwise, which would restart the analysis. */
export function streamDeepAnalysis(
  ticker: string,
  period: string,
  handlers: DeepStreamHandlers,
): () => void {
  const url =
    `${BASE}/analyze/${encodeURIComponent(ticker)}/deep/stream?period=${encodeURIComponent(period)}`;
  const es = new EventSource(url);
  const forward = (type: AgentEvent['type']) => (e: MessageEvent) => {
    try {
      handlers.onEvent({ ...(JSON.parse(e.data) as AgentEvent), type });
    } catch {
      handlers.onError('Malformed event from server');
    }
  };
  es.addEventListener('step', forward('step') as EventListener);
  es.addEventListener('final', ((e: MessageEvent) => {
    forward('final')(e);
    es.close(); // terminal — close before EventSource auto-reconnects
  }) as EventListener);
  es.addEventListener('error', ((e: MessageEvent) => {
    if (e.data) forward('error')(e);          // server-sent `event: error` (has data)
    else handlers.onError('Connection error'); // native connection failure (no data)
    es.close();
  }) as EventListener);
  return () => es.close();
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm test -- src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(deep-analysis): SSE client streamDeepAnalysis + agent types"
```

---

### Task 5: `useDeepAnalyze` hook

**Files:** Create `frontend/src/hooks/useDeepAnalyze.ts`, `frontend/src/hooks/useDeepAnalyze.test.tsx`

- [ ] **Step 1: Write the failing test** — create `frontend/src/hooks/useDeepAnalyze.test.tsx`:

```typescript
import { act, renderHook } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import * as client from '../api/client';
import { useDeepAnalyze } from './useDeepAnalyze';

it('accumulates steps and captures the final result', () => {
  let handlers: client.DeepStreamHandlers | undefined;
  vi.spyOn(client, 'streamDeepAnalysis').mockImplementation((_t, _p, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useDeepAnalyze('AAPL', '1y'));

  act(() => result.current.start());
  expect(result.current.running).toBe(true);

  act(() => handlers!.onEvent({ type: 'step', step: { index: 0, thought: 't' } } as never));
  expect(result.current.steps).toHaveLength(1);

  act(() => handlers!.onEvent({ type: 'final', result: { current_recommendation: 'buy' }, trace: { fell_back: false } } as never));
  expect(result.current.running).toBe(false);
  expect(result.current.result?.current_recommendation).toBe('buy');
});

it('surfaces a transport error', () => {
  let handlers: client.DeepStreamHandlers | undefined;
  vi.spyOn(client, 'streamDeepAnalysis').mockImplementation((_t, _p, h) => { handlers = h; return () => {}; });
  const { result } = renderHook(() => useDeepAnalyze('AAPL', '1y'));
  act(() => result.current.start());
  act(() => handlers!.onError('Connection error'));
  expect(result.current.running).toBe(false);
  expect(result.current.error).toBe('Connection error');
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- src/hooks/useDeepAnalyze.test.tsx`
Expected: FAIL — module/hook doesn't exist.

- [ ] **Step 3: Implement** — create `frontend/src/hooks/useDeepAnalyze.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react';
import { streamDeepAnalysis } from '../api/client';
import type { AgentStep, AnalysisResult } from '../types';

export interface DeepAnalyzeState {
  steps: AgentStep[];
  result: AnalysisResult | null;
  running: boolean;
  error: string | null;
  fellBack: boolean;
}

const IDLE: DeepAnalyzeState = { steps: [], result: null, running: false, error: null, fellBack: false };

export function useDeepAnalyze(ticker: string, period: string) {
  const [state, setState] = useState<DeepAnalyzeState>(IDLE);
  const closeRef = useRef<(() => void) | null>(null);

  const start = useCallback(() => {
    closeRef.current?.();
    setState({ ...IDLE, running: true });
    closeRef.current = streamDeepAnalysis(ticker, period, {
      onEvent: (e) => {
        if (e.type === 'step' && e.step) {
          setState((s) => ({ ...s, steps: [...s.steps, e.step as AgentStep] }));
        } else if (e.type === 'final') {
          setState((s) => ({
            ...s, running: false, result: e.result ?? null, fellBack: e.trace?.fell_back ?? false,
          }));
        } else if (e.type === 'error') {
          setState((s) => ({ ...s, running: false, error: e.message || 'Analysis error' }));
        }
      },
      onError: (message) => setState((s) => ({ ...s, running: false, error: message })),
    });
  }, [ticker, period]);

  useEffect(() => () => closeRef.current?.(), []); // close the stream on unmount

  return { ...state, start };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm test -- src/hooks/useDeepAnalyze.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useDeepAnalyze.ts frontend/src/hooks/useDeepAnalyze.test.tsx
git commit -m "feat(deep-analysis): useDeepAnalyze streaming hook"
```

---

### Task 6: `TracePanel` component

**Files:** Create `frontend/src/components/TracePanel.tsx`, `frontend/src/components/TracePanel.test.tsx`

- [ ] **Step 1: Write the failing test** — create `frontend/src/components/TracePanel.test.tsx`:

```typescript
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TracePanel } from './TracePanel';
import type { AgentStep } from '../types';

const step: AgentStep = {
  index: 0, thought: 'check the news', action: 'fetch_news',
  action_args: { query: 'x' }, observation: 'NVDA beats', is_final: false, elapsed_ms: 0,
};

it('renders each step with its thought, action and observation', () => {
  render(<TracePanel running={false} steps={[step]} />);
  expect(screen.getByText('check the news')).toBeInTheDocument();
  expect(screen.getByText('fetch_news')).toBeInTheDocument();
  expect(screen.getByText('NVDA beats')).toBeInTheDocument();
});

it('shows live progress while running', () => {
  render(<TracePanel running steps={[]} />);
  expect(screen.getByText(/step 0\s*\/\s*6/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- src/components/TracePanel.test.tsx`
Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement** — create `frontend/src/components/TracePanel.tsx`:

```typescript
import type { AgentStep } from '../types';

export function TracePanel({
  steps, running, fellBack = false, maxSteps = 6,
}: { steps: AgentStep[]; running: boolean; fellBack?: boolean; maxSteps?: number }) {
  return (
    <div className="trace">
      <div className="trace-head">
        <span className="section-label">Agent trace — what the LLM is doing</span>
        {running && <span className="trace-progress">step {steps.length} / {maxSteps}…</span>}
        {fellBack && <span className="badge bearish">fell back to single-shot</span>}
      </div>
      <ol className="trace-steps">
        {steps.map((s, i) => (
          <li key={i} className={`trace-step${s.is_final ? ' final' : ''}`}>
            {s.thought && <p className="trace-thought">{s.thought}</p>}
            {s.action && (
              <p className="trace-action">
                <b>{s.action}</b>(<code>{JSON.stringify(s.action_args)}</code>)
              </p>
            )}
            {s.observation && <pre className="trace-obs">{s.observation}</pre>}
            {s.is_final && <p className="trace-final-label">→ final answer</p>}
          </li>
        ))}
        {running && <li className="trace-step pending muted">…thinking</li>}
      </ol>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm test -- src/components/TracePanel.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/TracePanel.tsx frontend/src/components/TracePanel.test.tsx
git commit -m "feat(deep-analysis): TracePanel live agent-trace component"
```

---

### Task 7: Deep Analysis button (TickerBar) + Dashboard wiring

**Files:** Modify `frontend/src/components/TickerBar.tsx`, `frontend/src/components/TickerBar.test.tsx`, `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Write the failing test** — in `frontend/src/components/TickerBar.test.tsx`, (a) add `onDeepAnalyze`/`deepAnalyzing` to the `setup()` render props, and (b) append a test:

In `setup()`, change the rendered element to also pass:
```tsx
      onDeepAnalyze={vi.fn()}
      deepAnalyzing={false}
```
And return `onDeepAnalyze` so tests can assert on it — update `setup` to create `const onDeepAnalyze = vi.fn();`, pass it, and include it in the returned object.

Append:
```typescript
it('fires onDeepAnalyze when the Deep Analysis button is clicked', () => {
  const onDeepAnalyze = vi.fn();
  render(
    <TickerBar
      watchlist={['AAPL']} current="AAPL"
      onSelect={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()}
      onAnalyze={vi.fn()} analyzing={false} canAnalyze
      onDeepAnalyze={onDeepAnalyze} deepAnalyzing={false}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: /deep analysis/i }));
  expect(onDeepAnalyze).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- src/components/TickerBar.test.tsx`
Expected: FAIL — `onDeepAnalyze` not a prop / no Deep Analysis button.

- [ ] **Step 3: Implement**

In `frontend/src/components/TickerBar.tsx`, add `onDeepAnalyze: () => void;` and `deepAnalyzing: boolean;` to the props type and destructuring, and add the button right after the existing Analyze button:

```tsx
      <button type="button" onClick={onAnalyze} disabled={!canAnalyze || analyzing}>
        {analyzing ? 'Analyzing…' : 'Analyze with LLM'}
      </button>
      <button
        type="button"
        className="secondary"
        onClick={onDeepAnalyze}
        disabled={!canAnalyze || deepAnalyzing}
        title="Agentic analysis — the LLM pulls data step-by-step; slower, streamed live"
      >
        {deepAnalyzing ? 'Deep analyzing…' : 'Deep Analysis'}
      </button>
```

In `frontend/src/pages/Dashboard.tsx`:
1. Import: `import { TracePanel } from '../components/TracePanel';` and `import { useDeepAnalyze } from '../hooks/useDeepAnalyze';`.
2. After `const analyze = useAnalyze(...)`, add: `const deep = useDeepAnalyze(ticker, RANGE_TO_PERIOD[range]);`.
3. Add a handler and an effect that promotes the deep result into the shared analysis state:
```tsx
  const runDeepAnalyze = () => { setSelected(null); deep.start(); };
  useEffect(() => { if (deep.result) setAnalysis(deep.result); }, [deep.result, setAnalysis]);
```
4. Pass the new props to `<TickerBar … onDeepAnalyze={runDeepAnalyze} deepAnalyzing={deep.running} />`.
5. Surface a deep error near the other error lines:
```tsx
      {deep.error && <p className="error">Deep analysis failed: {deep.error}</p>}
```
6. In the Analysis `<section className="panel analysis">`, render the trace above the reasoning. Replace the panel body with:
```tsx
              {(deep.running || deep.steps.length > 0) && (
                <TracePanel steps={deep.steps} running={deep.running} fellBack={deep.fellBack} />
              )}
              {analysis ? (
                <div className="analysis-scroll"><ReasoningPanel result={analysis} /></div>
              ) : !deep.running && deep.steps.length === 0 ? (
                <p className="muted">Click “Analyze with LLM” for a fast call, or “Deep Analysis” to watch the agent pull data step-by-step.</p>
              ) : null}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm test -- src/components/TickerBar.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the whole frontend suite + typecheck + build**

Run: `npm test` then `npm run build`
Expected: all tests pass; `tsc -b` + build clean. (If `pages/Dashboard.test.tsx` constructs `TickerBar` indirectly, confirm it still renders — the Dashboard supplies the new props itself, so no test change is needed there; fix any fallout if it appears.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/TickerBar.tsx frontend/src/components/TickerBar.test.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(deep-analysis): Deep Analysis button + live trace panel on the dashboard"
```

---

## Self-Review

**Spec coverage (design spec §5/§10/§11/§12):**
- §5 generator is the single source of truth, `run()` drains it — Task 1. ✓
- §5 `gather_stock_context` extracted so the endpoint can build `ToolContext` — Task 2. ✓
- §10 step-level SSE transport (GET, `text/event-stream`, `Cache-Control: no-cache`) — Task 3. ✓
- §10/§12 EventSource client closing on terminal events (no auto-reconnect restart) — Task 4. ✓
- §11 `GET /analyze/{ticker}/deep/stream`; fast `POST /analyze` untouched — Task 3. ✓
- §12 Deep Analysis button; live "step N/6" trace panel; final renders via the shared `AnalysisResult`/`ReasoningPanel` — Tasks 6–7. ✓
- Deferred (NOT this plan): trace persistence + `GET /traces` (Phase 3); eval `mode` tagging (Phase 4); token-level streaming. ✓ Declared in Scope.

**Placeholder scan:** none — every step has complete code/commands.

**Type/name consistency:** `AgentEvent{type,step,result,trace,message}` identical in backend (Task 1) and frontend (Task 4). `stream(provider, model, provider_name, ctx)` signature matches the endpoint call (Task 3) and `run()`'s drain (Task 1). `streamDeepAnalysis(ticker, period, {onEvent,onError}) => closeFn` matches the hook (Task 5) and its test (Task 4). `TracePanel{steps,running,fellBack,maxSteps}` matches Dashboard usage (Task 7). `gather_stock_context(ticker, period, settings, cache, provider)` matches the endpoint (Task 3) and run_analysis (Task 2).

**Risk note:** the one cross-cutting refactor is Task 1 (the loop → generator); it's guarded by the **entire Phase-1 `run()` test suite staying green** (run() now drains stream()). Task 2 is likewise guarded by the existing `run_analysis` tests.

## Notes for the implementer
- `_stock`, `VALID_PAYLOAD`, `FakeProvider` come from `backend/tests/test_analyzer.py` — import, don't redefine.
- Frontend tests run in jsdom, which has **no** `EventSource` — the client test installs a fake global; the hook test mocks `streamDeepAnalysis` so it never touches `EventSource`. Existing Dashboard/other tests never call `start()`, so they never open a real stream.
- CSS for `.trace*` classes is optional polish (Phase 2 ships the live behavior; styling can follow). Don't block on it.
