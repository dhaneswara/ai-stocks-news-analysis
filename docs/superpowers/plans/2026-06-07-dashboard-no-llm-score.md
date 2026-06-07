# Dashboard no-LLM opportunity score — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the Discover board's no-LLM opportunity score (0–100 + buy/sell/hold + reasons + 🔗 network) for the currently-loaded ticker, automatically, in the Dashboard summary header.

**Architecture:** A new `GET /api/score/{ticker}` runs the existing pure `score_stock` on freshly-loaded data and blends the company-network signal exactly as the board does — so the number matches Discover. The per-row network blend is extracted from `apply_network` into a shared helper (DRY). The frontend auto-loads it via a `useScore` hook and renders a compact `ScoreChip` in the summary; the LLM *Analyze* path is untouched.

**Tech Stack:** Backend — Python 3.13, FastAPI, Pydantic v2, pytest. Frontend — React + TS, TanStack Query, Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-06-07-dashboard-no-llm-score-design.md`

**Conventions:** backend tests from `backend/`: `.venv/Scripts/python.exe -m pytest -q`. Frontend from `frontend/`: `npx vitest run` and `npm run build` (the build gate is `tsc -b`; `tsc --noEmit` is a no-op here). Conventional Commits, one per task, **NO `Co-Authored-By: Claude` trailer**. Branch `feat/dashboard-no-llm-score` (already created; the spec commit lives there).

---

## File structure
- Modify `backend/app/analysis/network.py` — extract `blend_network_into_score`; `apply_network` calls it (Task 1).
- Modify `backend/app/screener/service.py` — add `score_one` (Task 2).
- Modify `backend/app/api/routes.py` — add `GET /score/{ticker}` (Task 3).
- Modify `frontend/src/api/client.ts` + `frontend/src/hooks/queries.ts` (Task 4).
- Create `frontend/src/components/ScoreBar.tsx`; modify `frontend/src/components/DiscoverBoard.tsx` (Task 5).
- Create `frontend/src/components/ScoreChip.tsx` (Task 6).
- Modify `frontend/src/pages/Dashboard.tsx` + `frontend/src/styles.css` + `frontend/src/pages/Dashboard.test.tsx` (Task 7).
- Tests: extend `backend/tests/test_network.py` (Task 1); create `backend/tests/test_score_one.py` (Task 2), `backend/tests/test_api_score.py` (Task 3); extend `frontend/src/api/client.test.ts` (Task 4); create `frontend/src/components/ScoreChip.test.tsx` (Task 6).

---

## Task 1: Extract `blend_network_into_score` (DRY)

**Files:**
- Modify: `backend/app/analysis/network.py`
- Test: `backend/tests/test_network.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_network.py`:

```python
def test_blend_network_into_score():
    from app.analysis.network import blend_network_into_score
    from app.models.schemas import NetworkSignal, Settings, StockScore
    s = StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold",
                   net=0.0, base_score=50.0, base_net=0.0)
    sig = NetworkSignal(ticker="AAPL", intensity=1.0, signed=1.0, influences=[],
                        reasons=["partner X (bullish)"])
    out = blend_network_into_score(s, sig, Settings())
    assert out.network is sig
    assert out.score > 50.0                 # positive intensity raised the score
    assert out.net > 0.0 and out.direction == "buy"
    assert out.components["network"] == 1.0
    assert out.reasons[0] == "partner X (bullish)"   # network reasons first
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest tests/test_network.py::test_blend_network_into_score -q`
Expected: FAIL — `ImportError: cannot import name 'blend_network_into_score'`.

- [ ] **Step 3: Edit `network.py`**

Add the helper (it imports nothing new — `_clamp`, `_DIRECTION_THRESHOLD`, `_DIRECTIONAL`, `NetworkSignal`, `StockScore`, `Settings` are already in the module):

```python
def blend_network_into_score(s: StockScore, sig: NetworkSignal, settings: Settings) -> StockScore:
    """Fold a computed network signal into ONE row's score/direction. Closed-form re-blend from
    base_score/base_net (never the already-blended score/net) so it stays idempotent. Shared by
    apply_network (per row) and the single-ticker score path."""
    weights = settings.screener.weights
    w_base = sum(weights.values()) or 1.0
    w_dir = sum(weights.get(f, 0.0) for f in _DIRECTIONAL) or 1.0
    w_net = settings.network.weight
    final_score = (s.base_score * w_base + 100.0 * sig.intensity * w_net) / (w_base + w_net)
    final_net = _clamp((s.base_net * w_dir + sig.signed * w_net) / (w_dir + w_net), -1.0, 1.0)
    direction = (
        "buy" if final_net > _DIRECTION_THRESHOLD
        else "sell" if final_net < -_DIRECTION_THRESHOLD
        else "hold"
    )
    components = dict(s.components)
    components["network"] = round(sig.intensity, 2)
    return s.model_copy(update={
        "score": round(_clamp(final_score, 0.0, 100.0), 1),
        "net": round(final_net, 3),
        "direction": direction,
        "components": components,
        "reasons": sig.reasons + s.reasons,   # network reasons first
        "network": sig,
    })
```

Then replace the body of `apply_network` so it uses the helper (remove the now-duplicated `w_base`/`w_dir`/`w_net` setup and the inline blend):

```python
def apply_network(board: ScreenBoard, graph: KnowledgeGraph, settings: Settings) -> ScreenBoard:
    """Fold a capped `network` family into each focus company's score/direction.

    Pure: reads neighbours' BASE scores (one hop, no feedback) and returns a new board. Blends from
    each row's ``base_score``/``base_net`` (never the already-blended values) via
    ``blend_network_into_score``, so applying it twice is idempotent and never double-counts.
    """
    ncfg = settings.network
    if not ncfg.enabled or not graph.edges:
        return board

    base_index = {s.ticker: s for s in board.items}
    edges_by_source: dict[str, list[GraphEdge]] = defaultdict(list)
    for e in graph.edges:
        edges_by_source[e.source].append(e)

    new_items = []
    for s in board.items:
        edges = edges_by_source.get(s.ticker)
        if not edges:
            new_items.append(s)
            continue
        sig = compute_network_signal(s.ticker, edges, base_index, ncfg)
        new_items.append(blend_network_into_score(s, sig, settings))

    new_items.sort(key=lambda x: x.score, reverse=True)
    return board.model_copy(update={"items": new_items})
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest tests/test_network.py -q`
Expected: PASS (the new test AND all existing `apply_network` tests — proving the extraction is behavior-preserving).

- [ ] **Step 5: Run the full backend suite** (network is consumed in several routes)

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/network.py backend/tests/test_network.py
git commit -m "refactor(network): extract blend_network_into_score (reused by single-ticker score)"
```

---

## Task 2: `score_one` single-ticker scorer

**Files:**
- Modify: `backend/app/screener/service.py`
- Test: `backend/tests/test_score_one.py` (new)

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_score_one.py`:

```python
import app.screener.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Candle, Fundamentals, GraphEdge, Indicators, KnowledgeGraph, PriceSummary,
    ScreenBoard, Settings, StockData, StockScore,
)
from app.network.store import save_graph
from app.screener.service import score_one
from app.screener.store import save_snapshot


def _stock(ticker="AAPL"):
    return StockData(
        ticker=ticker, company_name="Apple", as_of="2026-06-06",
        price=PriceSummary(current=100, change=1, change_pct=1.0),
        candles=[Candle(time="2026-06-05", open=1, high=1, low=1, close=1, volume=1)],
        fundamentals=Fundamentals(), indicators=Indicators(), news=[],
    )


def test_score_one_base(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    s = Settings()
    s.network.enabled = False
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert isinstance(out, StockScore) and out.ticker == "AAPL"
    assert out.network is None          # no blend when network disabled


def test_score_one_blends_network(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    save_graph(KnowledgeGraph(scope="focus", nodes=["AAPL", "MSFT"], edges=[
        GraphEdge(source="AAPL", target="MSFT", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)]), cache)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="Microsoft", price=1, change_pct=0, score=60,
                   direction="buy", net=0.5, base_score=60.0, base_net=0.5)]), cache)
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert out.network is not None and out.network.signed > 0
    assert out.components.get("network") is not None


def test_score_one_network_failure_degrades(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    # effective_graph raising must NOT break scoring — base score still returned.
    monkeypatch.setattr(service, "effective_graph", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert isinstance(out, StockScore) and out.network is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_score_one.py -q`
Expected: FAIL — `ImportError: cannot import name 'score_one'`.

- [ ] **Step 3: Edit `screener/service.py`**

Add imports near the top (the file already imports `political`, `score_stock`, `load_universe`, `get_stock_data`, `truth_social`). Add `StockScore` to the existing `from app.models.schemas import ScreenBoard, Settings` line (→ `ScreenBoard, Settings, StockScore`), and add:

```python
from app.analysis.network import blend_network_into_score, compute_network_signal
from app.network.store import effective_graph
from app.screener.store import load_snapshot
```

Add the function (below `run_scan`):

```python
def score_one(ticker: str, settings: Settings, cache: Cache) -> StockScore:
    """Score a single ticker on-demand (no LLM), network-blended to match the Discover board.

    Raises ValueError (via get_stock_data) when the ticker has no data — the route maps that to 404.
    The network block is best-effort: any failure degrades to the base technical score.
    """
    stock = get_stock_data(ticker, SCAN_PERIOD, settings.indicator_params, cache)
    ts = settings.truth_signal
    posts = (
        truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
        if ts.enabled else []
    )
    mentions = political.find_mentions(posts, ticker, stock.company_name)
    score = score_stock(stock, mentions, settings.screener)
    score.sector = next((e.sector for e in load_universe() if e.ticker == ticker), "")

    if settings.network.enabled:
        try:
            graph = effective_graph(cache, "focus")
            board = load_snapshot(cache, "all")
            base_index = {s.ticker: s for s in (board.items if board else [])}
            edges = [e for e in graph.edges if e.source == ticker]
            if edges:
                sig = compute_network_signal(ticker, edges, base_index, settings.network)
                score = blend_network_into_score(score, sig, settings)
        except Exception:  # noqa: BLE001 — network is best-effort; base score on any failure
            pass
    return score
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_score_one.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/service.py backend/tests/test_score_one.py
git commit -m "feat(score): add score_one single-ticker scorer (network-blended, best-effort)"
```

---

## Task 3: `GET /api/score/{ticker}` route

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_score.py` (new)

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_api_score.py`:

```python
import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.config.cache import Cache
from app.deps import get_cache
from app.main import app
from app.models.schemas import StockScore


@pytest.fixture
def client(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    try:
        yield TestClient(app), cache
    finally:
        app.dependency_overrides.pop(get_cache, None)


def test_get_score_ok(client, monkeypatch):
    tc, _ = client
    monkeypatch.setattr(routes, "score_one", lambda ticker, settings, cache: StockScore(
        ticker=ticker, name="Apple", price=1, change_pct=0, score=72.0, direction="buy", net=0.3))
    r = tc.get("/api/score/aapl")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL" and body["score"] == 72.0 and body["direction"] == "buy"


def test_get_score_404_on_bad_ticker(client, monkeypatch):
    tc, _ = client

    def boom(ticker, settings, cache):
        raise ValueError("No price history for ZZZZ")

    monkeypatch.setattr(routes, "score_one", boom)
    r = tc.get("/api/score/ZZZZ")
    assert r.status_code == 404 and "No price history" in r.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_score.py -q`
Expected: FAIL — 404 with FastAPI's default "Not Found" (route undefined) for the OK test.

- [ ] **Step 3: Edit `routes.py`**

Add `score_one` to the existing `from app.screener.service import run_scan` import (it currently imports `run_scan`):

```python
from app.screener.service import run_scan, score_one
```

Add the route (place it right after the `GET /stock/{ticker}` route, near the top of the stock/score section). `StockScore` and `HTTPException` are already imported:

```python
@router.get("/score/{ticker}", response_model=StockScore)
def get_score(
    ticker: str,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> StockScore:
    """No-LLM opportunity score for a single ticker (Discover parity, network-blended)."""
    try:
        return score_one(ticker.upper().strip(), store.load(), cache)
    except ValueError as exc:   # no data for ticker -> 404, same convention as GET /stock/{ticker}
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_score.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_score.py
git commit -m "feat(score): add GET /api/score/{ticker} route"
```

---

## Task 4: Client method + hook

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test** — append inside the `describe('api client', …)` block in `frontend/src/api/client.test.ts`:

```typescript
  it('getScore GETs /score/{ticker}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticker: 'AAPL', score: 72 }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getScore('AAPL');
    expect(fetchMock.mock.calls[0][0] as string).toContain('/score/AAPL');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/api/client.test.ts`
Expected: FAIL — `api.getScore is not a function`.

- [ ] **Step 3: Edit `client.ts`**

Add `StockScore` to the existing type import block from `../types`. Then add the method to the `api` object (e.g. after `getSectors`):

```typescript
  getScore: (ticker: string) => http<StockScore>(`/score/${encodeURIComponent(ticker)}`),
```

- [ ] **Step 4: Edit `queries.ts`**

Add (place after the existing `useScreen` hook):

```typescript
export function useScore(ticker: string) {
  return useQuery({
    queryKey: ['score', ticker],
    queryFn: () => api.getScore(ticker),
    enabled: ticker.length > 0,
    retry: false,
  });
}
```

- [ ] **Step 5: Run test + type-check**

Run (from `frontend/`): `npx vitest run src/api/client.test.ts` → PASS. Then `npx tsc -b` → clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/api/client.test.ts
git commit -m "feat(score): add getScore client + useScore hook"
```

---

## Task 5: Extract shared `ScoreBar`

**Files:**
- Create: `frontend/src/components/ScoreBar.tsx`
- Modify: `frontend/src/components/DiscoverBoard.tsx`

- [ ] **Step 1: Create `frontend/src/components/ScoreBar.tsx`**

```tsx
export function ScoreBar({ score }: { score: number }) {
  return (
    <div className="score-bar" title={`${score.toFixed(0)} / 100`}>
      <span style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
    </div>
  );
}
```

- [ ] **Step 2: Edit `DiscoverBoard.tsx`** — remove the local `ScoreBar` function and import the shared one. Change the top of the file from:

```tsx
import { useNavigate } from 'react-router-dom';
import type { StockScore } from '../types';

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="score-bar" title={`${score.toFixed(0)} / 100`}>
      <span style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
    </div>
  );
}
```

to:

```tsx
import { useNavigate } from 'react-router-dom';
import type { StockScore } from '../types';
import { ScoreBar } from './ScoreBar';
```

(The rest of `DiscoverBoard.tsx` — which already uses `<ScoreBar score={s.score} />` — is unchanged.)

- [ ] **Step 3: Run the board test + type-check**

Run (from `frontend/`): `npx vitest run src/components/DiscoverBoard.test.tsx` → PASS (board still renders). Then `npx tsc -b` → clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ScoreBar.tsx frontend/src/components/DiscoverBoard.tsx
git commit -m "refactor(ui): extract shared ScoreBar component"
```

---

## Task 6: `ScoreChip` component

**Files:**
- Create: `frontend/src/components/ScoreChip.tsx`
- Test: `frontend/src/components/ScoreChip.test.tsx` (new)

- [ ] **Step 1: Write the failing tests** — create `frontend/src/components/ScoreChip.test.tsx`:

```tsx
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ScoreChip } from './ScoreChip';
import type { StockScore } from '../types';

function s(extra: Partial<StockScore> = {}): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0,
    score: 72, direction: 'buy', net: 0.3, reasons: ['RSI 28 (oversold)'], components: {}, as_of: 't',
    ...extra,
  };
}

it('renders score, call, and reasons', () => {
  render(<ScoreChip score={s()} />);
  expect(screen.getByText('72')).toBeInTheDocument();
  expect(screen.getByText('BUY')).toBeInTheDocument();
  expect(screen.getByText(/RSI 28/)).toBeInTheDocument();
});

it('shows the 🔗 network badge only when a network signal is present', () => {
  const { rerender } = render(<ScoreChip score={s()} />);
  expect(screen.queryByText('🔗')).not.toBeInTheDocument();
  rerender(<ScoreChip score={s({
    network: { ticker: 'AAPL', intensity: 0.5, signed: 0.3, influences: [], reasons: ['partner MSFT (bullish)'] },
  })} />);
  expect(screen.getByText('🔗')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/components/ScoreChip.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `frontend/src/components/ScoreChip.tsx`**

```tsx
import type { StockScore } from '../types';
import { ScoreBar } from './ScoreBar';

/** Compact no-LLM opportunity score for the Dashboard summary — mirrors a Discover row's cells. */
export function ScoreChip({ score }: { score: StockScore }) {
  const net = score.network;
  return (
    <div className="score-chip">
      <span className="section-label">Signal</span>
      <div className="score-cell"><ScoreBar score={score.score} /><span>{score.score.toFixed(0)}</span></div>
      <span className={`badge ${score.direction}`}>{score.direction.toUpperCase()}</span>
      <div className="reasons">
        {net && net.reasons.length > 0 && (
          <span className="reason-chip net" title={net.reasons.join(' · ')}>🔗</span>
        )}
        {score.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/components/ScoreChip.test.tsx` → PASS. Then `npx tsc -b` → clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ScoreChip.tsx frontend/src/components/ScoreChip.test.tsx
git commit -m "feat(score): add ScoreChip summary component"
```

---

## Task 7: Wire the Dashboard + styles

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`, `frontend/src/styles.css`, `frontend/src/pages/Dashboard.test.tsx`

- [ ] **Step 1: Update the Dashboard test** — `frontend/src/pages/Dashboard.test.tsx`.

(a) Add `getScore: vi.fn()` to the `vi.mock('../api/client', …)` `api` object (the page now calls `useScore` on every render, so the mock must expose it):

```typescript
vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    getStock: vi.fn(),
    analyze: vi.fn(),
    getSectors: vi.fn(),
    getScreen: vi.fn(),
    saveSettings: vi.fn(),
    listProviders: vi.fn(),
    getMood: vi.fn(),
    rescan: vi.fn(),
    refreshUniverse: vi.fn(),
    getScore: vi.fn(),
  },
}));
```

(b) Add `StockScore` to the `../types` import and a `SCORE` fixture near the other fixtures:

```typescript
const SCORE: StockScore = {
  ticker: 'AAPL', name: 'Apple Inc.', sector: 'Tech', price: 200, change_pct: 0.5,
  score: 72, direction: 'buy', net: 0.3, reasons: ['RSI 28 (oversold)'], components: {}, as_of: '2026-06-06',
};
```

(c) Add a default mock in `beforeEach`:

```typescript
  vi.mocked(api.getScore).mockResolvedValue(SCORE);
```

(d) Append a test:

```typescript
describe('Dashboard no-LLM score', () => {
  it('shows the opportunity score chip on ticker load', async () => {
    renderApp();
    expect(await screen.findByText('72')).toBeInTheDocument();
    expect(screen.getByText(/RSI 28 \(oversold\)/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npx vitest run src/pages/Dashboard.test.tsx`
Expected: the new test FAILS (no chip rendered); the existing tests still pass (they don't depend on the chip, and `getScore` is now mocked).

- [ ] **Step 3: Edit `Dashboard.tsx`**

Add imports:

```typescript
import { ScoreChip } from '../components/ScoreChip';
```
and add `useScore` to the existing `../hooks/queries` import (which already imports `useAnalyze, useStock, useWatchlist`):

```typescript
import { useAnalyze, useScore, useStock, useWatchlist } from '../hooks/queries';
```

Add the hook call near the other hooks (after `const stock = useStock(ticker);`):

```typescript
  const score = useScore(ticker);
```

Render the chip in the summary, directly under the `.hero-quote` div, still inside `.summary-id`. Change:

```tsx
              <div className="hero-quote">
                <span className="hero-price">
                  <span className="cur">{d.price.currency === 'USD' ? '$' : ''}</span>
                  {d.price.current.toFixed(2)}
                </span>
                <span className={`hero-change ${up ? 'up' : 'down'}`}>
                  <span className="arrow">{up ? '▲' : '▼'}</span>
                  {sign}{d.price.change.toFixed(2)} ({sign}{d.price.change_pct.toFixed(2)}%)
                </span>
              </div>
            </div>
```

to (add the `{score.data && …}` line before the closing `</div>` of `.summary-id`):

```tsx
              <div className="hero-quote">
                <span className="hero-price">
                  <span className="cur">{d.price.currency === 'USD' ? '$' : ''}</span>
                  {d.price.current.toFixed(2)}
                </span>
                <span className={`hero-change ${up ? 'up' : 'down'}`}>
                  <span className="arrow">{up ? '▲' : '▼'}</span>
                  {sign}{d.price.change.toFixed(2)} ({sign}{d.price.change_pct.toFixed(2)}%)
                </span>
              </div>
              {score.data && <ScoreChip score={score.data} />}
            </div>
```

- [ ] **Step 4: Edit `styles.css`** — append near the other `.score-*` / `.summary` rules:

```css
.score-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  flex-wrap: wrap;
}
```

- [ ] **Step 5: Run tests + type-check**

Run (from `frontend/`): `npx vitest run src/pages/Dashboard.test.tsx` → all PASS. Then `npx tsc -b` → clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/styles.css frontend/src/pages/Dashboard.test.tsx
git commit -m "feat(score): show no-LLM ScoreChip in the Dashboard summary"
```

---

## Task 8: Full verification

**Files:** none.

- [ ] **Step 1: Backend suite** — from `backend/`: `.venv/Scripts/python.exe -m pytest -q` → ALL PASS.
- [ ] **Step 2: Frontend suite + build** — from `frontend/`: `npx vitest run` and `npm run build` → ALL PASS, build clean.
- [ ] **Step 3 (optional): live browser smoke** — start backend (isolated temp `DATA_DIR`, back up + restore the real cache) + `npm run dev`; load a ticker on the Dashboard and confirm the Signal chip shows a score/call/reasons matching the Discover row, and that it updates when switching tickers. (Skip if relying on automated coverage; report honestly which was done.)

---

## Self-review notes for the implementer
- **Idempotency invariant preserved:** `blend_network_into_score` blends from `base_score`/`base_net`, never the already-blended values — Task 1's behavior-preserving refactor keeps `apply_network` idempotent (existing tests prove it).
- **Numbers match Discover** because `score_one` uses the same `SCAN_PERIOD = "1y"`, the same `score_stock`, and the same blend; the network neighbours come from the same `"all"` snapshot.
- **Non-critical UI:** `useScore` has `retry: false`; on error `score.data` is undefined and the chip simply doesn't render — never blocks the Dashboard.
- **No new persistence / no LLM** on this path (cheap; reuses `get_stock_data`'s cache).
