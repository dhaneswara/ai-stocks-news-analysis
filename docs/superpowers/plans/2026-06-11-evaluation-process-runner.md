# Evaluation Process Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command bar on the Evaluation page with four watchlist-wide process buttons — snapshot technical/network calls, batch fast LLM analysis, batch deep LLM analysis (with Stop), and a full Discover rescan — so feeding the scoreboard no longer requires visiting other pages company-by-company.

**Architecture:** One new SSE endpoint `GET /api/analyze/watchlist/stream?mode=fast|deep` loops the watchlist sequentially server-side, skipping tickers whose matching-source call already exists for their latest trading day, and emits per-ticker progress events. The frontend mirrors the existing `streamDeepAnalysis` EventSource pattern (client fn → hook → component). Snapshot and rescan buttons reuse existing endpoints/hooks unchanged.

**Tech Stack:** FastAPI + sse via `StreamingResponse` (backend), React + TanStack Query + EventSource (frontend), pytest / vitest + testing-library.

**Spec:** `docs/superpowers/specs/2026-06-11-evaluation-process-runner-design.md`

---

## File map

| File | Change |
|---|---|
| `backend/app/models/schemas.py` | Add `WatchlistRunEvent` (Task 1) |
| `backend/app/api/routes.py` | Add `GET /analyze/watchlist/stream` fast mode (Task 1), deep mode (Task 2) |
| `backend/tests/test_api_watchlist_run.py` | New — all endpoint tests (Tasks 1–2) |
| `frontend/src/types.ts` | Add `TickerRunStatus`, `WatchlistRunEvent` (Task 3) |
| `frontend/src/api/client.ts` | Add `streamWatchlistRun` + handler type (Task 3) |
| `frontend/src/api/client.test.ts` | Tests for `streamWatchlistRun` (Task 3) |
| `frontend/src/hooks/useWatchlistRun.ts` | New hook (Task 4) |
| `frontend/src/hooks/useWatchlistRun.test.tsx` | New hook tests (Task 4) |
| `frontend/src/components/EvaluationCommandBar.tsx` | New component (Task 5) |
| `frontend/src/components/EvaluationCommandBar.test.tsx` | New component tests (Task 5) |
| `frontend/src/styles.css` | `.run-strip` / `.run-chip` styles (Task 5) |
| `frontend/src/pages/Evaluation.tsx` | Render the command bar (Task 6) |
| `frontend/src/pages/Evaluation.test.tsx` | Extend api mock + bar-presence test (Task 6) |
| `README.md`, `backend/README.md`, `frontend/README.md` | Docs (Task 7) |

Commands below assume the repo root `C:\workspace\ai-stocks-news-analysis`. Backend tests: `cd backend; .venv\Scripts\python.exe -m pytest ...`. Frontend: `cd frontend; npx vitest run ...`.

---

### Task 1: Backend — `WatchlistRunEvent` + fast-mode batch endpoint

**Files:**
- Modify: `backend/app/models/schemas.py` (add model after `AnalysisResult` / next to `Source`, ~line 248)
- Modify: `backend/app/api/routes.py` (imports + new endpoint after `analyze_deep_stream`, ~line 211)
- Create: `backend/tests/test_api_watchlist_run.py`

Background you need:
- Predictions are keyed by the **last candle's** `time` (a trading day), not the calendar day. The skip check is `prediction_store.get_prediction(ticker, last_candle_date, source)` → row or `None`.
- `run_analysis(ticker, period, settings, cache, prediction_store)` does its own provider checks, 24h-caches, and records `llm_fast` + the technical/network pair on the fresh path.
- `_sse(event)` in `routes.py` serializes any pydantic model with a `.type` field into an SSE frame; `routes.py` already imports `get_stock_data`, `run_analysis`, `build_provider`, `SOURCE_LLM_FAST`, `SOURCE_LLM_DEEP`.
- Tests override deps exactly like `backend/tests/test_api_deep_stream.py` does and reuse `FakeProvider`/`_stock` from `backend/tests/test_analyzer.py`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_watchlist_run.py`:

```python
import json

from fastapi.testclient import TestClient

from app.analysis.trace_store import AgentTraceStore
from app.api import routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_prediction_store, get_settings_store, get_trace_store
from app.evaluation.store import PredictionStore
from app.llm.base import LLMError
from app.main import app
from app.models.schemas import AnalysisResult, Candle
from tests.test_analyzer import FakeProvider, _stock


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    settings_store = SettingsStore(str(tmp_path / "settings.db"))
    pred_store = PredictionStore(str(tmp_path / "pred.db"))
    trace_store = AgentTraceStore(str(tmp_path / "trace.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: settings_store
    app.dependency_overrides[get_prediction_store] = lambda: pred_store
    app.dependency_overrides[get_trace_store] = lambda: trace_store
    return TestClient(app), settings_store, pred_store, trace_store


def teardown_function():
    app.dependency_overrides.clear()


def _ready_settings(settings_store, *, watchlist=None, enabled=True):
    """Default settings pass the endpoint pre-flight: evaluation on + an API key set
    (so the env never leaks into the key check)."""
    s = settings_store.load()
    s.evaluation.enabled = enabled
    s.providers[s.active_provider].api_key = "k"
    if watchlist is not None:
        s.watchlist = watchlist
    settings_store.save(s)
    return s


def _stock_with_candles(ticker="AAPL"):
    s = _stock()
    s.ticker = ticker
    s.candles = [
        Candle(time="2026-06-04", open=1, high=1, low=1, close=200.0, volume=1),
        Candle(time="2026-06-05", open=1, high=1, low=1, close=204.0, volume=1),
    ]
    return s


def _result(ticker="AAPL"):
    return AnalysisResult(
        ticker=ticker, provider="fake", model="m", generated_at="t",
        overall_summary="s", news_analysis="n", sentiment="bullish",
        current_recommendation="buy", confidence=0.7,
    )


def _events(text):
    """Parse an SSE body into [(event_name, payload_dict), ...]."""
    out = []
    for frame in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _seed_prediction(pred_store, ticker, call_date, source):
    pred_store.upsert_prediction(
        ticker=ticker, call_date=call_date, provider="x", model="m",
        recommendation="buy", confidence=0.5, sentiment="bullish",
        entry_price=204.0, source=source,
    )


# ---------------- pre-flight ----------------

def test_watchlist_stream_rejects_unknown_mode(tmp_path):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store)
    resp = client.get("/api/analyze/watchlist/stream?mode=weird")
    assert resp.status_code == 422


def test_watchlist_stream_errors_when_evaluation_disabled(tmp_path):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, enabled=False)
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    assert resp.status_code == 200
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["error"]
    assert "disabled" in evs[0][1]["message"]


def test_watchlist_stream_errors_when_key_missing(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    s = settings_store.load()
    s.evaluation.enabled = True          # key left empty on purpose
    settings_store.save(s)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["error"]
    assert "API key" in evs[0][1]["message"]


def test_watchlist_stream_errors_when_provider_build_fails(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store)

    def boom(settings):
        raise LLMError("provider down")
    monkeypatch.setattr(routes, "build_provider", boom)
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["error"]
    assert "provider down" in evs[0][1]["message"]


def test_watchlist_stream_empty_watchlist_is_a_noop_run(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=[])
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert [n for n, _ in evs] == ["start", "done"]
    assert evs[0][1]["total"] == 0
    summary = evs[1][1]
    assert (summary["analyzed"], summary["skipped"], summary["failed"]) == (0, 0, 0)


# ---------------- fast mode ----------------

def test_fast_run_analyzes_every_ticker(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL", "MSFT"])
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    calls = []

    def fake_run(t, p, s, c, ps):
        calls.append(t)
        return _result(t)
    monkeypatch.setattr(routes, "run_analysis", fake_run)

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert calls == ["AAPL", "MSFT"]
    names = [n for n, _ in evs]
    assert names == ["start", "ticker", "ticker", "ticker", "ticker", "done"]
    assert evs[0][1]["tickers"] == ["AAPL", "MSFT"]
    done_events = [p for n, p in evs if n == "ticker" and p["status"] == "done"]
    assert [d["ticker"] for d in done_events] == ["AAPL", "MSFT"]
    assert done_events[0]["recommendation"] == "buy"
    summary = evs[-1][1]
    assert (summary["analyzed"], summary["skipped"], summary["failed"]) == (2, 0, 0)


def test_fast_run_skips_ticker_already_recorded_for_last_trading_day(tmp_path, monkeypatch):
    client, settings_store, pred_store, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    _seed_prediction(pred_store, "AAPL", "2026-06-05", "llm_fast")  # = last candle date
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    calls = []
    monkeypatch.setattr(routes, "run_analysis",
                        lambda t, p, s, c, ps: calls.append(t) or _result(t))

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    assert calls == []                                   # analyzer never invoked
    statuses = [p["status"] for n, p in evs if n == "ticker"]
    assert statuses == ["running", "skipped"]
    assert evs[-1][1]["skipped"] == 1


def test_fast_run_is_not_skipped_by_a_deep_call(tmp_path, monkeypatch):
    """Cross-source independence: an llm_deep row must not suppress the fast run."""
    client, settings_store, pred_store, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    _seed_prediction(pred_store, "AAPL", "2026-06-05", "llm_deep")
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    monkeypatch.setattr(routes, "run_analysis", lambda t, p, s, c, ps: _result(t))

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    assert _events(resp.text)[-1][1]["analyzed"] == 1


def test_fast_run_isolates_a_failing_ticker(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL", "MSFT"])
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))

    def fake_stock(t, p, ip, c):
        if t == "AAPL":
            raise ValueError("boom")
        return _stock_with_candles(t)
    monkeypatch.setattr(routes, "get_stock_data", fake_stock)
    monkeypatch.setattr(routes, "run_analysis", lambda t, p, s, c, ps: _result(t))

    resp = client.get("/api/analyze/watchlist/stream?mode=fast")
    evs = _events(resp.text)
    by_status = {p["ticker"]: p["status"] for n, p in evs
                 if n == "ticker" and p["status"] != "running"}
    assert by_status == {"AAPL": "failed", "MSFT": "done"}
    failed = [p for n, p in evs if n == "ticker" and p["status"] == "failed"][0]
    assert "boom" in failed["error"]
    summary = evs[-1][1]
    assert (summary["analyzed"], summary["skipped"], summary["failed"]) == (1, 0, 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_watchlist_run.py -q
```

Expected: all tests FAIL — the 422 test gets 404 (route missing) and the rest error similarly. If you see import errors for `WatchlistRunEvent`, that's also an expected failure at this point only if you imported it; this test file deliberately does not import it.

- [ ] **Step 3: Add the `WatchlistRunEvent` model**

In `backend/app/models/schemas.py`, directly under the `Source = Literal[...]` line (~line 248):

```python
class WatchlistRunEvent(BaseModel):
    """One SSE frame of a watchlist-wide LLM batch run.

    `start` carries total/tickers; `ticker` carries per-ticker progress; `done` carries the
    summary counts; `error` is a run-level failure (pre-flight) with `message`."""
    type: Literal["start", "ticker", "done", "error"]
    ticker: str = ""
    index: int = 0
    total: int = 0
    status: Optional[Literal["running", "done", "skipped", "failed"]] = None
    recommendation: str = ""
    confidence: float = 0.0
    fell_back: bool = False
    error: str = ""
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    message: str = ""
    tickers: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add the endpoint (fast mode only)**

In `backend/app/api/routes.py`:

4a. Imports — add `Literal` (new line after `from datetime import ...`), extend the factory and schemas imports:

```python
from typing import Literal
```

Change `from app.llm.factory import build_provider` to:

```python
from app.llm.factory import build_provider, resolve_config
```

Add `WatchlistRunEvent,` to the `from app.models.schemas import (...)` block (alphabetical — after `StockScore,`).

4b. Widen the `_sse` annotation (line ~131) so both event models fit:

```python
def _sse(event: AgentEvent | WatchlistRunEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
```

4c. Add the endpoint right after the `get_traces` route (~line 227). `mode` is
`Literal["fast"]` for now — Task 2 widens it to `"deep"`; FastAPI turns the Literal into
422 for anything else, which is exactly the contract the 422 test pins:

```python
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/analyze/watchlist/stream")
def analyze_watchlist_stream(
    mode: Literal["fast"] = "fast",
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
    source = SOURCE_LLM_FAST

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
        build_provider(settings)  # pre-flight only here; Task 2's deep branch keeps the instance
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
                result = run_analysis(ticker, period, settings, cache, prediction_store)
                analyzed += 1
                yield _sse(WatchlistRunEvent(
                    type="ticker", ticker=ticker, index=i, total=len(tickers),
                    status="done", recommendation=result.current_recommendation,
                    confidence=result.confidence))
            except Exception as exc:  # noqa: BLE001 — per-ticker isolation
                logger.warning("watchlist %s run failed for %s", mode, ticker)
                failed += 1
                yield _sse(WatchlistRunEvent(type="ticker", ticker=ticker, index=i,
                                             total=len(tickers), status="failed",
                                             error=str(exc)))
        yield _sse(WatchlistRunEvent(type="done", analyzed=analyzed, skipped=skipped,
                                     failed=failed))

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers=_SSE_HEADERS)
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_watchlist_run.py -q
```

Expected: all PASS. Then the full suite to catch regressions:

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q
```

Expected: PASS (no existing test touches the new route).

- [ ] **Step 6: Commit**

```powershell
cd C:\workspace\ai-stocks-news-analysis
git add backend/app/models/schemas.py backend/app/api/routes.py backend/tests/test_api_watchlist_run.py
git commit -m "feat(backend): watchlist fast-LLM batch SSE endpoint with skip-already-done"
```

---

### Task 2: Backend — deep mode for the batch endpoint

**Files:**
- Modify: `backend/app/api/routes.py` (widen `mode`, add the deep branch)
- Modify: `backend/tests/test_api_watchlist_run.py` (append deep tests)

Background you need:
- `ReActAgent().run(provider, cfg.model, provider_id, ctx)` drains the agent stream and returns `(result, trace)` — `result` is `Optional[AnalysisResult]`, `trace.fell_back` is `True` when the single-shot fallback produced the answer. An `LLMError` from the fallback propagates (nothing left to fall back to).
- `_persist_deep_final(event, stock, settings, cache, prediction_store, trace_store)` (already in `routes.py`) persists the trace and records the prediction as `llm_deep` — or honestly as `llm_fast` when `trace.fell_back` — plus the technical/network pair. It needs an `AgentEvent`.
- `gather_stock_context(ticker, period, settings, cache, provider, store=...)` builds the full `StockData` the agent needs (network signal, mood, track record). The cheap `get_stock_data` skip-check happens first so skipped tickers never touch LLM-adjacent work.
- `record_deterministic_pair` inside `_persist_deep_final` calls `score_one`, which the tests fake via `signals.score_one` exactly like `test_api_deep_stream.py` does.

- [ ] **Step 1: Append the failing deep tests**

Append to `backend/tests/test_api_watchlist_run.py`:

```python
# ---------------- deep mode ----------------

from app.evaluation import signals
from app.models.schemas import StockScore
from tests.test_analyzer import VALID_PAYLOAD


def _fake_score():
    return StockScore(ticker="AAPL", name="Apple", sector="", price=204.0, change_pct=0.5,
                      score=70.0, direction="buy", net=0.3, base_net=0.3, base_score=70.0,
                      as_of="t")


def _deep_ready(monkeypatch, outputs):
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    monkeypatch.setattr(routes, "gather_stock_context",
                        lambda t, p, s, c, prov, store=None: _stock_with_candles(t))
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider(outputs))
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _fake_score())


def test_deep_run_records_llm_deep_and_trace(tmp_path, monkeypatch):
    client, settings_store, pred_store, trace_store = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    _deep_ready(monkeypatch,
                [f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}'])

    resp = client.get("/api/analyze/watchlist/stream?mode=deep")
    evs = _events(resp.text)
    done = [p for n, p in evs if n == "ticker" and p["status"] == "done"][0]
    assert done["fell_back"] is False
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_deep") is not None
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_fast") is None
    assert len(trace_store.recent("AAPL")) == 1
    assert evs[-1][1]["analyzed"] == 1


def test_deep_run_skips_on_existing_llm_deep_only(tmp_path, monkeypatch):
    """An llm_fast row does not suppress a deep run; an llm_deep row does."""
    client, settings_store, pred_store, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    _seed_prediction(pred_store, "AAPL", "2026-06-05", "llm_fast")
    _deep_ready(monkeypatch,
                [f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}'])
    resp = client.get("/api/analyze/watchlist/stream?mode=deep")
    assert _events(resp.text)[-1][1]["analyzed"] == 1   # fast row ignored

    _seed_prediction(pred_store, "AAPL", "2026-06-05", "llm_deep")
    resp = client.get("/api/analyze/watchlist/stream?mode=deep")
    assert _events(resp.text)[-1][1]["skipped"] == 1    # deep row skips


def test_deep_fallback_is_done_with_fell_back_flag_and_records_fast(tmp_path, monkeypatch):
    client, settings_store, pred_store, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    # Two protocol-breaking turns exhaust the agent -> single-shot fallback eats the third.
    _deep_ready(monkeypatch, ["nonsense", "still nonsense", json.dumps(VALID_PAYLOAD)])

    resp = client.get("/api/analyze/watchlist/stream?mode=deep")
    evs = _events(resp.text)
    done = [p for n, p in evs if n == "ticker" and p["status"] == "done"][0]
    assert done["fell_back"] is True
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_fast") is not None
    assert pred_store.get_prediction("AAPL", "2026-06-05", "llm_deep") is None


def test_deep_llm_error_marks_ticker_failed_and_run_completes(tmp_path, monkeypatch):
    class _Raising:
        name = "raise"

        def complete(self, system, user, json_mode=True, stop=None):
            raise LLMError("provider down")

    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL", "MSFT"])
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    monkeypatch.setattr(routes, "gather_stock_context",
                        lambda t, p, s, c, prov, store=None: _stock_with_candles(t))
    monkeypatch.setattr(routes, "build_provider", lambda settings: _Raising())
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _fake_score())

    resp = client.get("/api/analyze/watchlist/stream?mode=deep")
    evs = _events(resp.text)
    statuses = [p["status"] for n, p in evs if n == "ticker" and p["status"] != "running"]
    assert statuses == ["failed", "failed"]
    summary = evs[-1][1]
    assert (summary["analyzed"], summary["skipped"], summary["failed"]) == (0, 0, 2)
```

- [ ] **Step 2: Run to verify the new tests fail**

```powershell
cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_watchlist_run.py -q
```

Expected: the four new deep tests FAIL with 422 (`mode=deep` not yet allowed); Task 1 tests still PASS.

- [ ] **Step 3: Widen the mode and add the deep branch**

In `backend/app/api/routes.py`, inside `analyze_watchlist_stream`:

3a. Change the signature line:

```python
    mode: Literal["fast", "deep"] = "fast",
```

3b. Change the source line to be mode-aware:

```python
    source = SOURCE_LLM_FAST if mode == "fast" else SOURCE_LLM_DEEP
```

3c. Keep the provider instance from the pre-flight — change:

```python
        build_provider(settings)  # pre-flight only here; Task 2's deep branch keeps the instance
```

to:

```python
        provider = build_provider(settings)
```

3d. Replace the fast-only analyze block — these lines:

```python
                result = run_analysis(ticker, period, settings, cache, prediction_store)
                analyzed += 1
                yield _sse(WatchlistRunEvent(
                    type="ticker", ticker=ticker, index=i, total=len(tickers),
                    status="done", recommendation=result.current_recommendation,
                    confidence=result.confidence))
```

with:

```python
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
```

(`gather_stock_context`, `ToolContext`, `ReActAgent`, `AgentEvent`, `_persist_deep_final`
are already imported/defined in `routes.py` — no import changes.)

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_watchlist_run.py -q
```

Expected: all PASS. Then full backend suite:

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
cd C:\workspace\ai-stocks-news-analysis
git add backend/app/api/routes.py backend/tests/test_api_watchlist_run.py
git commit -m "feat(backend): deep mode for the watchlist batch stream"
```

---

### Task 3: Frontend — types + `streamWatchlistRun` client

**Files:**
- Modify: `frontend/src/types.ts` (after `SnapshotResult`, ~line 152)
- Modify: `frontend/src/api/client.ts` (import + new function after `streamDeepAnalysis`)
- Modify: `frontend/src/api/client.test.ts` (append tests; `FakeEventSource` already exists there)

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/api/client.test.ts` (after the existing `streamDeepAnalysis` tests; reuses the file's `FakeEventSource` class):

```typescript
describe('streamWatchlistRun', () => {
  it('targets the batch endpoint with the mode and forwards start/ticker/done', () => {
    (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
    const events: { type: string }[] = [];
    streamWatchlistRun('fast', { onEvent: (e) => events.push(e), onError: vi.fn() });
    const es = FakeEventSource.last!;
    expect(es.url).toContain('/analyze/watchlist/stream?mode=fast');
    es.emit('start', JSON.stringify({ total: 2, tickers: ['AAPL', 'MSFT'] }));
    es.emit('ticker', JSON.stringify({ ticker: 'AAPL', status: 'running' }));
    es.emit('done', JSON.stringify({ analyzed: 1, skipped: 1, failed: 0 }));
    expect(events.map((e) => e.type)).toEqual(['start', 'ticker', 'done']);
    expect(es.closed).toBe(true); // closed after the terminal done
  });

  it('forwards a server-sent error event with data and closes', () => {
    (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
    const events: { type: string; message?: string }[] = [];
    streamWatchlistRun('deep', { onEvent: (e) => events.push(e), onError: vi.fn() });
    FakeEventSource.last!.emit('error', JSON.stringify({ message: 'disabled' }));
    expect(events).toEqual([{ type: 'error', message: 'disabled' }]);
    expect(FakeEventSource.last!.closed).toBe(true);
  });

  it('reports a connection error when the native error event has no data', () => {
    (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
    const onError = vi.fn();
    streamWatchlistRun('fast', { onEvent: vi.fn(), onError });
    FakeEventSource.last!.emit('error');
    expect(onError).toHaveBeenCalledWith('Connection error');
    expect(FakeEventSource.last!.closed).toBe(true);
  });
});
```

Also extend the import at the top of the file:

```typescript
import { api, streamDeepAnalysis, streamWatchlistRun } from './client';
```

- [ ] **Step 2: Run to verify failure**

```powershell
cd frontend; npx vitest run src/api/client.test.ts
```

Expected: FAIL — `streamWatchlistRun` is not exported.

- [ ] **Step 3: Add the types**

In `frontend/src/types.ts`, after the `SnapshotResult` interface (~line 152):

```typescript
export type TickerRunStatus = 'running' | 'done' | 'skipped' | 'failed';

/** One SSE frame of a watchlist-wide LLM batch run (mode=fast|deep). */
export interface WatchlistRunEvent {
  type: 'start' | 'ticker' | 'done' | 'error';
  ticker?: string;
  index?: number;
  total?: number;
  status?: TickerRunStatus;
  recommendation?: Recommendation | '';
  confidence?: number;
  fell_back?: boolean;
  error?: string;
  analyzed?: number;
  skipped?: number;
  failed?: number;
  message?: string;
  tickers?: string[];
}
```

(`Recommendation` is declared above in the same file — no import needed.)

- [ ] **Step 4: Add the client function**

In `frontend/src/api/client.ts`:

4a. Add `WatchlistRunEvent,` to the `import type { ... } from '../types'` block (alphabetical — after `TestResult,`).

4b. Append after `streamDeepAnalysis`:

```typescript
export interface WatchlistStreamHandlers {
  onEvent: (event: WatchlistRunEvent) => void;
  onError: (message: string) => void;
}

/** Open the SSE stream for a watchlist-wide LLM batch run. Returns a closer the caller
 *  MUST keep and invoke on unmount/stop — EventSource auto-reconnects otherwise, which
 *  would restart the batch from the top. */
export function streamWatchlistRun(
  mode: 'fast' | 'deep',
  handlers: WatchlistStreamHandlers,
): () => void {
  const es = new EventSource(`${BASE}/analyze/watchlist/stream?mode=${mode}`);
  const forward = (type: WatchlistRunEvent['type']) => (e: MessageEvent) => {
    try {
      handlers.onEvent({ ...(JSON.parse(e.data) as WatchlistRunEvent), type });
    } catch {
      handlers.onError('Malformed event from server');
    }
  };
  es.addEventListener('start', forward('start') as EventListener);
  es.addEventListener('ticker', forward('ticker') as EventListener);
  es.addEventListener('done', ((e: MessageEvent) => {
    forward('done')(e);
    es.close(); // terminal — close before EventSource auto-reconnects
  }) as EventListener);
  es.addEventListener('error', ((e: MessageEvent) => {
    if (e.data) forward('error')(e);          // server-sent run-level error (has data)
    else handlers.onError('Connection error'); // native connection failure (no data)
    es.close();
  }) as EventListener);
  return () => es.close();
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
cd frontend; npx vitest run src/api/client.test.ts
```

Expected: PASS (all, including the pre-existing tests).

- [ ] **Step 6: Commit**

```powershell
cd C:\workspace\ai-stocks-news-analysis
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(frontend): watchlist batch-run SSE client and event types"
```

---

### Task 4: Frontend — `useWatchlistRun` hook

**Files:**
- Create: `frontend/src/hooks/useWatchlistRun.ts`
- Create: `frontend/src/hooks/useWatchlistRun.test.tsx`

The hook needs a `QueryClientProvider` in tests because it invalidates `['evaluation']` on every terminal transition (done / run-level error / transport error / stop).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/hooks/useWatchlistRun.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import * as client from '../api/client';
import { useWatchlistRun } from './useWatchlistRun';

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, 'invalidateQueries');
  const closer = vi.fn();
  const handlers: { current?: client.WatchlistStreamHandlers } = {};
  vi.spyOn(client, 'streamWatchlistRun').mockImplementation((_m, h) => {
    handlers.current = h;
    return closer;
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useWatchlistRun(), { wrapper });
  return { hook, handlers, closer, invalidate };
}

it('tracks ticker statuses through a full run and invalidates on done', () => {
  const { hook, handlers, invalidate } = setup();
  act(() => hook.result.current.start('fast'));
  expect(hook.result.current.phase).toBe('running');
  expect(hook.result.current.mode).toBe('fast');

  act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
  expect(hook.result.current.tickers).toEqual(['AAPL', 'MSFT']);

  act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'AAPL', status: 'running' }));
  act(() => handlers.current!.onEvent({
    type: 'ticker', ticker: 'AAPL', status: 'done', recommendation: 'buy',
  }));
  act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'MSFT', status: 'skipped' }));
  expect(hook.result.current.statuses['AAPL']).toMatchObject({ status: 'done', recommendation: 'buy' });
  expect(hook.result.current.statuses['MSFT'].status).toBe('skipped');

  act(() => handlers.current!.onEvent({ type: 'done', analyzed: 1, skipped: 1, failed: 0 }));
  expect(hook.result.current.phase).toBe('done');
  expect(hook.result.current.summary).toEqual({ analyzed: 1, skipped: 1, failed: 0 });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['evaluation'] });
});

it('ignores start() while already running', () => {
  const { hook } = setup();
  act(() => hook.result.current.start('fast'));
  act(() => hook.result.current.start('deep'));
  expect(client.streamWatchlistRun).toHaveBeenCalledTimes(1);
  expect(hook.result.current.mode).toBe('fast');
});

it('surfaces a run-level error event', () => {
  const { hook, handlers } = setup();
  act(() => hook.result.current.start('deep'));
  act(() => handlers.current!.onEvent({ type: 'error', message: 'disabled' }));
  expect(hook.result.current.phase).toBe('error');
  expect(hook.result.current.message).toBe('disabled');
});

it('surfaces a transport error', () => {
  const { hook, handlers } = setup();
  act(() => hook.result.current.start('fast'));
  act(() => handlers.current!.onError('Connection error'));
  expect(hook.result.current.phase).toBe('error');
  expect(hook.result.current.message).toBe('Connection error');
});

it('stop() closes the stream, marks the run stopped and invalidates', () => {
  const { hook, closer, invalidate } = setup();
  act(() => hook.result.current.start('fast'));
  act(() => hook.result.current.stop());
  expect(closer).toHaveBeenCalled();
  expect(hook.result.current.phase).toBe('done');
  expect(hook.result.current.stopped).toBe(true);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['evaluation'] });
});

it('closes the stream on unmount', () => {
  const { hook, closer } = setup();
  act(() => hook.result.current.start('fast'));
  hook.unmount();
  expect(closer).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run to verify failure**

```powershell
cd frontend; npx vitest run src/hooks/useWatchlistRun.test.tsx
```

Expected: FAIL — module `./useWatchlistRun` not found.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useWatchlistRun.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { streamWatchlistRun } from '../api/client';
import type { Recommendation, TickerRunStatus } from '../types';

export type RunMode = 'fast' | 'deep';
export type RunPhase = 'idle' | 'running' | 'done' | 'error';

export interface TickerRunState {
  status: TickerRunStatus;
  recommendation?: Recommendation | '';
  fellBack?: boolean;
  error?: string;
}

export interface WatchlistRunState {
  phase: RunPhase;
  mode: RunMode | null;
  total: number;
  tickers: string[];
  statuses: Record<string, TickerRunState>;
  summary: { analyzed: number; skipped: number; failed: number } | null;
  stopped: boolean;
  message: string | null;
}

const IDLE: WatchlistRunState = {
  phase: 'idle', mode: null, total: 0, tickers: [], statuses: {}, summary: null,
  stopped: false, message: null,
};

/** Drive a watchlist-wide LLM batch run (mode=fast|deep) over SSE. One run at a time;
 *  every terminal transition (done / error / stop) refreshes the evaluation board. */
export function useWatchlistRun() {
  const qc = useQueryClient();
  const [state, setState] = useState<WatchlistRunState>(IDLE);
  const closeRef = useRef<(() => void) | null>(null);
  const runningRef = useRef(false);

  const finish = useCallback(
    () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
    [qc],
  );

  const start = useCallback((mode: RunMode) => {
    if (runningRef.current) return;
    runningRef.current = true;
    setState({ ...IDLE, phase: 'running', mode });
    closeRef.current = streamWatchlistRun(mode, {
      onEvent: (e) => {
        if (e.type === 'start') {
          setState((s) => ({ ...s, total: e.total ?? 0, tickers: e.tickers ?? [] }));
        } else if (e.type === 'ticker' && e.ticker) {
          setState((s) => ({
            ...s,
            statuses: {
              ...s.statuses,
              [e.ticker as string]: {
                status: e.status ?? 'running',
                recommendation: e.recommendation,
                fellBack: e.fell_back,
                error: e.error,
              },
            },
          }));
        } else if (e.type === 'done') {
          runningRef.current = false;
          setState((s) => ({
            ...s,
            phase: 'done',
            summary: {
              analyzed: e.analyzed ?? 0, skipped: e.skipped ?? 0, failed: e.failed ?? 0,
            },
          }));
          finish();
        } else if (e.type === 'error') {
          runningRef.current = false;
          setState((s) => ({ ...s, phase: 'error', message: e.message || 'Run error' }));
          finish();
        }
      },
      onError: (message) => {
        runningRef.current = false;
        setState((s) => ({ ...s, phase: 'error', message }));
        finish();
      },
    });
  }, [finish]);

  const stop = useCallback(() => {
    if (!runningRef.current) return;
    runningRef.current = false;
    closeRef.current?.();
    setState((s) => ({ ...s, phase: 'done', stopped: true }));
    finish();
  }, [finish]);

  useEffect(() => () => closeRef.current?.(), []); // close the stream on unmount

  return { ...state, start, stop };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
cd frontend; npx vitest run src/hooks/useWatchlistRun.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
cd C:\workspace\ai-stocks-news-analysis
git add frontend/src/hooks/useWatchlistRun.ts frontend/src/hooks/useWatchlistRun.test.tsx
git commit -m "feat(frontend): useWatchlistRun hook for batch-run progress"
```

---

### Task 5: Frontend — `EvaluationCommandBar` component + styles

**Files:**
- Create: `frontend/src/components/EvaluationCommandBar.tsx`
- Create: `frontend/src/components/EvaluationCommandBar.test.tsx`
- Modify: `frontend/src/styles.css` (append chip styles)

Existing hooks used: `useWatchlist` (settings-backed list), `useSnapshotEvaluation`
(POST `/evaluation/snapshot`, invalidates `['evaluation']`), `useRescan` (POST
`/screen/rescan`, no sector → full board) — all in `frontend/src/hooks/queries.ts`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/EvaluationCommandBar.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EvaluationCommandBar } from './EvaluationCommandBar';
import type { WatchlistStreamHandlers } from '../api/client';

const handlers: { current?: WatchlistStreamHandlers } = {};
const closer = vi.fn();

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
    snapshotEvaluation: vi.fn(),
    rescan: vi.fn(),
  },
  streamWatchlistRun: vi.fn((_mode: string, h: WatchlistStreamHandlers) => {
    handlers.current = h;
    return closer;
  }),
}));

import { api, streamWatchlistRun } from '../api/client';

function renderBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EvaluationCommandBar />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  handlers.current = undefined;
  vi.mocked(api.getSettings).mockResolvedValue({ watchlist: ['AAPL', 'MSFT'] } as never);
  vi.mocked(api.snapshotEvaluation).mockResolvedValue({ recorded: 2, skipped: [] });
  vi.mocked(api.rescan).mockResolvedValue({ items: [] } as never);
});

describe('EvaluationCommandBar', () => {
  it('renders the four process buttons once the watchlist loads', async () => {
    renderBar();
    expect(await screen.findByText(/run on your watchlist \(2 tickers\)/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /fast llm analysis/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /deep llm analysis/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /full discover rescan/i })).toBeEnabled();
  });

  it('disables everything and hints when the watchlist is empty', async () => {
    vi.mocked(api.getSettings).mockResolvedValue({ watchlist: [] } as never);
    renderBar();
    expect(await screen.findByText(/add tickers to your watchlist first/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /fast llm analysis/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeDisabled();
  });

  it('snapshot button records and reports', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /snapshot technical\/network/i }));
    expect(await screen.findByText(/recorded 2 watchlist signals/i)).toBeInTheDocument();
    expect(api.snapshotEvaluation).toHaveBeenCalledTimes(1);
  });

  it('rescan chains a snapshot on success', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /full discover rescan/i }));
    await waitFor(() => expect(api.rescan).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.snapshotEvaluation).toHaveBeenCalledTimes(1));
  });

  it('runs a fast batch with live chips, disabling the other buttons', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /fast llm analysis/i }));
    expect(vi.mocked(streamWatchlistRun)).toHaveBeenCalledWith('fast', expect.anything());

    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
    act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'AAPL', status: 'running' }));
    expect(screen.getByText(/⏳ AAPL/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument();

    act(() => handlers.current!.onEvent({
      type: 'ticker', ticker: 'AAPL', status: 'done', recommendation: 'buy',
    }));
    act(() => handlers.current!.onEvent({ type: 'ticker', ticker: 'MSFT', status: 'skipped' }));
    expect(screen.getByText(/✓ AAPL BUY/)).toBeInTheDocument();
    expect(screen.getByText(/− MSFT/)).toBeInTheDocument();

    act(() => handlers.current!.onEvent({ type: 'done', analyzed: 1, skipped: 1, failed: 0 }));
    expect(screen.getByText(/analyzed 1 · skipped 1 · failed 0/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeEnabled();
  });

  it('stop closes the stream and notes the run was stopped', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /deep llm analysis/i }));
    act(() => handlers.current!.onEvent({ type: 'start', total: 2, tickers: ['AAPL', 'MSFT'] }));
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(closer).toHaveBeenCalled();
    expect(screen.getByText(/stopped — run again to resume/i)).toBeInTheDocument();
  });

  it('shows a run-level error line', async () => {
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /fast llm analysis/i }));
    act(() => handlers.current!.onEvent({ type: 'error', message: 'Evaluation recording is disabled' }));
    expect(screen.getByText(/run failed: evaluation recording is disabled/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```powershell
cd frontend; npx vitest run src/components/EvaluationCommandBar.test.tsx
```

Expected: FAIL — module `./EvaluationCommandBar` not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/EvaluationCommandBar.tsx`:

```tsx
import { useRescan, useSnapshotEvaluation, useWatchlist } from '../hooks/queries';
import { useWatchlistRun } from '../hooks/useWatchlistRun';
import type { TickerRunStatus } from '../types';

const CHIP_ICON: Record<TickerRunStatus, string> = {
  running: '⏳', done: '✓', skipped: '−', failed: '✗',
};

/** One button per watchlist-wide process: snapshot technical/network calls, fast/deep LLM
 *  batches (live per-ticker progress + Stop), and a full Discover rescan. One process at
 *  a time. */
export function EvaluationCommandBar() {
  const watch = useWatchlist();
  const snapshot = useSnapshotEvaluation();
  const rescan = useRescan();
  const run = useWatchlistRun();

  const running = run.phase === 'running';
  const busy = snapshot.isPending || rescan.isPending || running;
  const disabled = busy || watch.list.length === 0;
  const progressed = Object.values(run.statuses).filter((t) => t.status !== 'running').length;

  return (
    <div className="panel commandbar">
      <div className="board-controls">
        <span className="section-label">Run on your watchlist ({watch.list.length} tickers)</span>
        <span className="spacer" />
        <button className="secondary" disabled={disabled} onClick={() => snapshot.mutate()}>
          {snapshot.isPending ? 'Snapshotting…' : 'Snapshot technical/network'}
        </button>
        <button className="secondary" disabled={disabled} onClick={() => run.start('fast')}>
          {running && run.mode === 'fast' ? 'Analyzing…' : 'Fast LLM analysis'}
        </button>
        <button className="secondary" disabled={disabled} onClick={() => run.start('deep')}>
          {running && run.mode === 'deep' ? 'Deep analyzing…' : 'Deep LLM analysis (slow)'}
        </button>
        <button
          className="secondary" disabled={disabled}
          onClick={() => rescan.mutate(undefined, { onSuccess: () => snapshot.mutate() })}
        >
          {rescan.isPending ? 'Scanning…' : 'Full Discover rescan'}
        </button>
        {running && <button onClick={run.stop}>Stop</button>}
      </div>

      {watch.list.length === 0 && (
        <p className="muted">Add tickers to your watchlist first (★ on the Dashboard).</p>
      )}

      {run.tickers.length > 0 && (running || run.summary || run.stopped) && (
        <div className="run-strip">
          {running && <span className="muted mono">{progressed}/{run.total}</span>}
          {run.tickers.map((t) => {
            const st = run.statuses[t];
            return (
              <span key={t} className={`run-chip ${st?.status ?? 'pending'}`} title={st?.error ?? ''}>
                {st ? CHIP_ICON[st.status] : '·'} {t}
                {st?.status === 'done' && st.recommendation
                  ? ` ${st.recommendation.toUpperCase()}` : ''}
              </span>
            );
          })}
        </div>
      )}

      {run.summary && (
        <p className="muted">
          Analyzed {run.summary.analyzed} · skipped {run.summary.skipped} · failed {run.summary.failed}.
        </p>
      )}
      {run.stopped && <p className="muted">Stopped — run again to resume the rest.</p>}
      {run.phase === 'error' && run.message && <p className="error">Run failed: {run.message}</p>}
      {snapshot.data && (
        <p className="muted">
          ✓ Recorded {snapshot.data.recorded} watchlist signal{snapshot.data.recorded === 1 ? '' : 's'} for
          evaluation{snapshot.data.skipped.length ? ` (${snapshot.data.skipped.length} skipped)` : ''}.
        </p>
      )}
      {snapshot.isError && <p className="error">Snapshot failed: {(snapshot.error as Error).message}</p>}
      {rescan.isError && <p className="error">Rescan failed: {(rescan.error as Error).message}</p>}
    </div>
  );
}
```

- [ ] **Step 4: Add the chip styles**

Append to `frontend/src/styles.css` (end of file):

```css
/* ----- Evaluation command bar: watchlist run progress ---------------------- */
.run-strip { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
.run-chip {
  font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.02em;
  color: var(--ink-soft); background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--panel-brd); border-radius: 999px;
  padding: 2px 9px; white-space: nowrap;
}
.run-chip.running { border-color: var(--gold-line); background: var(--gold-tint); color: var(--gold-bright); }
.run-chip.done { border-color: rgba(95, 211, 155, 0.35); color: var(--buy); }
.run-chip.skipped { opacity: 0.55; }
.run-chip.failed { border-color: rgba(240, 129, 124, 0.4); color: var(--sell); }
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
cd frontend; npx vitest run src/components/EvaluationCommandBar.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
cd C:\workspace\ai-stocks-news-analysis
git add frontend/src/components/EvaluationCommandBar.tsx frontend/src/components/EvaluationCommandBar.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): evaluation command bar with watchlist process buttons"
```

---

### Task 6: Frontend — wire the bar into the Evaluation page

**Files:**
- Modify: `frontend/src/pages/Evaluation.tsx` (import + render)
- Modify: `frontend/src/pages/Evaluation.test.tsx` (extend the api mock; add a presence test)

- [ ] **Step 1: Extend the page test (failing first)**

In `frontend/src/pages/Evaluation.test.tsx`:

1a. Replace the existing `vi.mock('../api/client', ...)` block with one that also covers the command-bar hooks (the page now mounts them):

```tsx
vi.mock('../api/client', () => ({
  api: {
    getEvaluation: vi.fn(),
    explainPrediction: vi.fn(),
    deleteTracked: vi.fn(),
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
    snapshotEvaluation: vi.fn(),
    rescan: vi.fn(),
  },
  streamWatchlistRun: vi.fn(() => () => {}),
}));
```

1b. In `beforeEach`, add:

```tsx
  vi.mocked(api.getSettings).mockResolvedValue({ watchlist: ['AAPL'] } as never);
```

1c. Append a new test inside the `describe('Evaluation page', ...)` block:

```tsx
  it('renders the watchlist command bar above the board', async () => {
    renderPage();
    expect(await screen.findByRole('button', { name: /fast llm analysis/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /deep llm analysis/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /snapshot technical\/network/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /full discover rescan/i })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run to verify the new test fails**

```powershell
cd frontend; npx vitest run src/pages/Evaluation.test.tsx
```

Expected: the new test FAILS (no command bar yet); the pre-existing tests must still PASS.

- [ ] **Step 3: Render the bar on the page**

In `frontend/src/pages/Evaluation.tsx`:

3a. Add the import (with the other component imports at the top):

```tsx
import { EvaluationCommandBar } from '../components/EvaluationCommandBar';
```

3b. In the `Evaluation` component's return, add the bar as the first child of the fragment:

```tsx
  return (
    <>
      <EvaluationCommandBar />
      <section className="panel">
```

(The rest of the page is unchanged.)

- [ ] **Step 4: Run the page tests to verify they pass**

```powershell
cd frontend; npx vitest run src/pages/Evaluation.test.tsx
```

Expected: PASS (all).

- [ ] **Step 5: Full frontend gates**

```powershell
cd frontend; npx vitest run
cd frontend; npm run build
```

Expected: all tests PASS; build (type-check + bundle) succeeds.

- [ ] **Step 6: Commit**

```powershell
cd C:\workspace\ai-stocks-news-analysis
git add frontend/src/pages/Evaluation.tsx frontend/src/pages/Evaluation.test.tsx
git commit -m "feat(frontend): run watchlist processes from the Evaluation page"
```

---

### Task 7: Docs + final gates

**Files:**
- Modify: `README.md` (evaluation feature bullet + "Configure & use" step 6)
- Modify: `backend/README.md` (endpoint list + signal-source table)
- Modify: `frontend/README.md` (Evaluation page bullet)

- [ ] **Step 1: README.md**

1a. In the **Signal-source scoreboard (evaluation)** bullet (~line 89), after the sentence ending "…snapshotted automatically every time you **Rescan** Discover;" insert:

```markdown
an **action bar on the Evaluation page** can also run every process watchlist-wide on
  demand — snapshot the technical/network calls, batch the **fast** or **deep** LLM
  analysis across the whole watchlist (live per-ticker progress, a Stop button, and
  already-recorded tickers skipped so reruns only fill gaps), or trigger a full Discover
  rescan;
```

(Keep the existing "a deep run that silently fell back…" sentence after it.)

1b. In **Configure & use** step 6 (~line 189), after "— and click **Explain miss** on a bad one." add:

```markdown
The action bar at the top runs any process for the whole watchlist — snapshot
   technical/network calls, fast/deep LLM batches, or a full Discover rescan — without
   visiting the other pages.
```

- [ ] **Step 2: backend/README.md**

2a. In the endpoint list, after the `GET /api/analyze/{ticker}/deep/stream` line (~line 35), add:

```markdown
- `GET  /api/analyze/watchlist/stream?mode=fast|deep&period=2y` — run the fast/deep analysis for **every watchlist ticker** as one SSE batch (per-ticker progress events; a ticker whose matching-source call already exists for its latest trading day is skipped)
```

2b. In the signal-source table (~line 214), extend the `llm_fast` and `llm_deep` rows' trigger column with ", and watchlist-wide via `GET /api/analyze/watchlist/stream`" (keep each row on one line).

- [ ] **Step 3: frontend/README.md**

In the **Evaluation** bullet (~line 26), append before the final period:

```markdown
, plus an **action bar** that runs any process watchlist-wide — snapshot technical/network calls, batch fast/deep LLM analyses (live per-ticker chips + Stop; already-recorded tickers are skipped), or a full Discover rescan
```

- [ ] **Step 4: Final full gates**

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q
cd frontend; npx vitest run
cd frontend; npm run build
```

Expected: everything green.

- [ ] **Step 5: Commit**

```powershell
cd C:\workspace\ai-stocks-news-analysis
git add README.md backend/README.md frontend/README.md
git commit -m "docs: document the evaluation process-runner action bar"
```
