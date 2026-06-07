# Type-Aware Symmetric Network Influence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `competitor` / `partner` / `other` relationships influence the BUY/SELL/HOLD of *both* endpoint companies, while `supplier` / `customer` / `owner` / `subsidiary` stay one-directional.

**Architecture:** A new `NetworkConfig.symmetric_types` list (default `["competitor","partner","other"]`, empty = today's directed behavior) drives a single shared `incident_edges(ticker, edges, symmetric)` selector. `compute_network_signal` derives the neighbour as the *other* endpoint per edge and inverts the news-event sign on reverse edges (the news was judged from the source's side). All three edge-selection sites (`apply_network`, `score_one`, `analysis_service`) route through `incident_edges`. Influence is computed at read time — no new edges are materialized, no data migration.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / pytest (backend); React + Vite + TypeScript / Vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-06-07-network-symmetric-influence-design.md`

**Commands (run backend steps from `backend/`, frontend steps from `frontend/`):**
- Backend single test: `.venv/Scripts/python.exe -m pytest tests/test_x.py::test_name -v`
- Backend full suite: `.venv/Scripts/python.exe -m pytest -q`
- Frontend tests: `npx vitest run`
- Frontend type-gate + build: `npm run build` (= `tsc -b && vite build`)

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `backend/app/models/schemas.py` | `NetworkConfig` | add `symmetric_types` field |
| `backend/app/analysis/network.py` | edge selection + per-edge scoring | add `incident_edges`; reverse-aware `compute_network_signal`; `apply_network` via helper; drop unused `defaultdict` |
| `backend/app/screener/service.py` | `score_one` (Dashboard) | route edge selection through `incident_edges` |
| `backend/app/services/analysis_service.py` | LLM-analysis network context | route edge selection through `incident_edges` |
| `backend/tests/test_network.py` | unit tests | add config-default, `incident_edges`, reverse-scoring, `apply_network` both/directional/off tests |
| `backend/tests/test_score_one.py` | integration | add reverse-edge test |
| `backend/tests/test_analysis_service.py` | integration | add reverse-edge test |
| `frontend/src/types.ts` | `NetworkConfig` TS mirror | add `symmetric_types` |
| `frontend/src/hooks/useWatchlist.test.tsx`, `frontend/src/pages/Dashboard.test.tsx`, `frontend/src/pages/Settings.test.tsx` | fixtures | add `symmetric_types` to inline `network` literals |

---

## Task 1: Add `NetworkConfig.symmetric_types`

**Files:**
- Modify: `backend/app/models/schemas.py` (the `NetworkConfig` class, ~line 184)
- Test: `backend/tests/test_network.py`

`RelationType` is already defined at `schemas.py:104` (above `NetworkConfig`) and `Field` is already imported (used by `NetworkSignal`). No new imports needed.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_network.py`:

```python
def test_network_config_defaults_symmetric_types():
    # competitor/partner/other are mutual by default; supplier/customer/owner/subsidiary are not.
    assert NetworkConfig().symmetric_types == ["competitor", "partner", "other"]
    assert "supplier" not in NetworkConfig().symmetric_types
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py::test_network_config_defaults_symmetric_types -v`
Expected: FAIL with `AttributeError: 'NetworkConfig' object has no attribute 'symmetric_types'`.

- [ ] **Step 3: Add the field**

In `backend/app/models/schemas.py`, change the `NetworkConfig` class from:

```python
class NetworkConfig(BaseModel):
    enabled: bool = True
    focus_top_n: int = 30
    max_edges_per_company: int = 8
    min_confidence: float = 0.4
    weight: float = 0.5        # the tilt cap (network family weight)
    alpha_event: float = 0.6   # blend weight on the edge news-event term
    beta_state: float = 0.4    # blend weight on the neighbour-state term
```

to:

```python
class NetworkConfig(BaseModel):
    enabled: bool = True
    focus_top_n: int = 30
    max_edges_per_company: int = 8
    min_confidence: float = 0.4
    weight: float = 0.5        # the tilt cap (network family weight)
    alpha_event: float = 0.6   # blend weight on the edge news-event term
    beta_state: float = 0.4    # blend weight on the neighbour-state term
    # Relationship types scored in BOTH directions (mutual). [] reproduces the legacy
    # purely-directed behavior. Pydantic's default backfills any legacy persisted Settings.
    symmetric_types: list[RelationType] = Field(
        default_factory=lambda: ["competitor", "partner", "other"]
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py::test_network_config_defaults_symmetric_types -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_network.py
git commit -m "feat(network): add NetworkConfig.symmetric_types (mutual relationship types)"
```

---

## Task 2: Add the `incident_edges` selector

**Files:**
- Modify: `backend/app/analysis/network.py` (insert helper after `_direction_word`, ~line 31)
- Test: `backend/tests/test_network.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_network.py`:

```python
def test_incident_edges_forward_all_reverse_symmetric_only():
    from app.analysis.network import incident_edges
    edges = [
        GraphEdge(source="A", target="X", type="partner", sentiment="neutral", weight=1, confidence=1),   # reverse + mutual -> in
        GraphEdge(source="B", target="X", type="supplier", sentiment="neutral", weight=1, confidence=1),  # reverse + directional -> out
        GraphEdge(source="X", target="C", type="supplier", sentiment="neutral", weight=1, confidence=1),  # forward (any type) -> in
    ]
    got = incident_edges("X", edges, {"partner", "competitor", "other"})
    assert {(e.source, e.target) for e in got} == {("A", "X"), ("X", "C")}


def test_incident_edges_self_loop_counted_once():
    from app.analysis.network import incident_edges
    e = GraphEdge(source="X", target="X", type="partner", sentiment="neutral", weight=1, confidence=1)
    assert incident_edges("X", [e], {"partner"}) == [e]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py::test_incident_edges_forward_all_reverse_symmetric_only tests/test_network.py::test_incident_edges_self_loop_counted_once -v`
Expected: FAIL with `ImportError: cannot import name 'incident_edges'`.

- [ ] **Step 3: Add the helper**

In `backend/app/analysis/network.py`, insert this function immediately after `_direction_word` (the line `return "bullish" if signed > 0 ...`) and before `def compute_network_signal(`:

```python
def incident_edges(ticker: str, edges: list[GraphEdge], symmetric: set[str]) -> list[GraphEdge]:
    """Edges that should score ``ticker``: forward (ticker is the source, any type) plus reverse
    (ticker is the target AND the relationship is a mutual type). A self-loop is counted once."""
    out: list[GraphEdge] = []
    for e in edges:
        if e.source == ticker:
            out.append(e)
        elif e.target == ticker and e.type in symmetric:
            out.append(e)
    return out
```

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py::test_incident_edges_forward_all_reverse_symmetric_only tests/test_network.py::test_incident_edges_self_loop_counted_once -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/network.py backend/tests/test_network.py
git commit -m "feat(network): add incident_edges (forward-all + reverse-symmetric selector)"
```

---

## Task 3: Make `compute_network_signal` reverse-aware

**Files:**
- Modify: `backend/app/analysis/network.py` (`compute_network_signal`, ~lines 33-61)
- Test: `backend/tests/test_network.py`

The neighbour becomes the *other* endpoint, and on a reverse edge the news-event sign is multiplied by the type sign (competitor inverts; partner/other keep). Forward output is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_network.py`:

```python
def test_reverse_competitor_inverts_event_sign():
    # Edge C -> X (competitor); scoring X via the reverse edge. Positive news for C is bearish for X.
    edges = [GraphEdge(source="C", target="X", type="competitor", sentiment="positive", weight=1, confidence=1)]
    sig = compute_network_signal("X", edges, {}, NetworkConfig())
    assert sig.signed < 0
    assert sig.influences[0].neighbour == "C"


def test_reverse_partner_keeps_event_sign():
    edges = [GraphEdge(source="P", target="X", type="partner", sentiment="positive", weight=1, confidence=1)]
    sig = compute_network_signal("X", edges, {}, NetworkConfig())
    assert sig.signed > 0
    assert sig.influences[0].neighbour == "P"


def test_reverse_uses_source_as_neighbour_state():
    # X is the target of a partner edge from P; P's bearish technical state drags X down.
    idx = {"P": _score("P", net=-0.8, direction="sell")}
    edges = [GraphEdge(source="P", target="X", type="partner", sentiment="neutral", weight=1, confidence=1)]
    sig = compute_network_signal("X", edges, idx, NetworkConfig())
    assert sig.signed < 0
    assert sig.influences[0].neighbour == "P" and sig.influences[0].neighbour_direction == "sell"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py -k "reverse" -v`
Expected: FAIL — current code reads `base_index.get(e.target)` (so neighbour is `"X"`, not the source) and never inverts the event term, so the sign / neighbour assertions fail.

- [ ] **Step 3: Rewrite the per-edge loop**

In `backend/app/analysis/network.py`, replace the body of `compute_network_signal` from `for e in edges:` through the `influences.append(...)` block. Change:

```python
    for e in edges:
        nb = base_index.get(e.target)
        nb_net = nb.base_net if nb else 0.0   # neighbour's PRE-network vote -> one hop, no feedback
        nb_dir = nb.direction if nb else "unknown"
        state = _type_sign(e.type) * nb_net
        event = _SENTIMENT.get(e.sentiment, 0.0)
        w = e.weight * e.confidence
        e_signed = w * (cfg.alpha_event * event + cfg.beta_state * state)
        e_intensity = w * max(abs(event), abs(state))
        signed_sum += e_signed
        intensity_sum += e_intensity
        influences.append(NetworkInfluence(
            neighbour=e.target,
            name=nb.name if nb else "",
            type=e.type,
            edge_sentiment=e.sentiment,
            neighbour_direction=nb_dir,
            signed=round(e_signed, 3),
            reason=f"{e.type} {e.target} ({_direction_word(e_signed)})",
        ))
```

to:

```python
    for e in edges:
        is_reverse = e.source != ticker            # ticker is the TARGET -> neighbour is the source
        neighbour_id = e.source if is_reverse else e.target
        nb = base_index.get(neighbour_id)
        nb_net = nb.base_net if nb else 0.0   # neighbour's PRE-network vote -> one hop, no feedback
        nb_dir = nb.direction if nb else "unknown"
        tsign = _type_sign(e.type)
        state = tsign * nb_net
        event = _SENTIMENT.get(e.sentiment, 0.0)
        # The edge's news sentiment was judged from the SOURCE side; on a reverse edge it lands on
        # the neighbour with the type sign (competitor inverts; partner/other keep).
        event_term = tsign * event if is_reverse else event
        w = e.weight * e.confidence
        e_signed = w * (cfg.alpha_event * event_term + cfg.beta_state * state)
        e_intensity = w * max(abs(event_term), abs(state))
        signed_sum += e_signed
        intensity_sum += e_intensity
        influences.append(NetworkInfluence(
            neighbour=neighbour_id,
            name=nb.name if nb else "",
            type=e.type,
            edge_sentiment=e.sentiment,
            neighbour_direction=nb_dir,
            signed=round(e_signed, 3),
            reason=f"{e.type} {neighbour_id} ({_direction_word(e_signed)})",
        ))
```

- [ ] **Step 4: Run the reverse tests AND the existing forward tests to verify all pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py -v`
Expected: PASS — new reverse tests pass; existing forward tests (`test_supplier_moves_with_neighbour`, `test_competitor_flips_sign`, `test_event_term_applies_without_scored_neighbour`, `test_signed_and_intensity_are_clamped`) remain green (forward path is unchanged because `is_reverse` is `False` when `e.source == ticker`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/network.py backend/tests/test_network.py
git commit -m "feat(network): reverse-aware neighbour + event-sign in compute_network_signal"
```

---

## Task 4: Route `apply_network` through `incident_edges`

**Files:**
- Modify: `backend/app/analysis/network.py` (`apply_network`, ~lines 102-128, and the `defaultdict` import at line 9)
- Test: `backend/tests/test_network.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_network.py`:

```python
def test_apply_network_symmetric_edge_tilts_both_endpoints():
    # A partner edge AAA -> BBB scores AAA (forward) AND BBB (reverse).
    board = _board(_score("AAA", net=0.0, direction="hold"), _score("BBB", net=0.0, direction="hold"))
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAA", target="BBB", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    out = apply_network(board, graph, Settings())
    a = next(i for i in out.items if i.ticker == "AAA")
    b = next(i for i in out.items if i.ticker == "BBB")
    assert a.network is not None and b.network is not None
    assert a.components.get("network", 0) > 0 and b.components.get("network", 0) > 0


def test_apply_network_directional_edge_skips_target():
    # A supplier edge is directional: only the source (AAA) is scored, not the target (BBB).
    board = _board(_score("AAA", net=0.0, direction="hold"), _score("BBB", net=0.0, direction="hold"))
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAA", target="BBB", type="supplier", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    out = apply_network(board, graph, Settings())
    assert next(i for i in out.items if i.ticker == "BBB").network is None


def test_apply_network_empty_symmetric_types_is_directed():
    board = _board(_score("AAA", net=0.0, direction="hold"), _score("BBB", net=0.0, direction="hold"))
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAA", target="BBB", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    settings = Settings()
    settings.network.symmetric_types = []
    out = apply_network(board, graph, settings)
    assert next(i for i in out.items if i.ticker == "BBB").network is None  # directed: target unscored
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py::test_apply_network_symmetric_edge_tilts_both_endpoints -v`
Expected: FAIL — current `apply_network` buckets by `e.source` only, so `BBB` has no edges and `b.network is None`, failing the both-endpoints assertion.

- [ ] **Step 3: Rewrite `apply_network` and drop the unused import**

In `backend/app/analysis/network.py`, replace the edge-bucketing block inside `apply_network`. Change:

```python
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
```

to:

```python
    base_index = {s.ticker: s for s in board.items}
    symmetric = set(ncfg.symmetric_types)

    new_items = []
    for s in board.items:
        edges = incident_edges(s.ticker, graph.edges, symmetric)
        if not edges:
            new_items.append(s)
            continue
        sig = compute_network_signal(s.ticker, edges, base_index, ncfg)
        new_items.append(blend_network_into_score(s, sig, settings))
```

Then remove the now-unused import at the top of the file (line 9):

```python
from collections import defaultdict
```

(Delete that line entirely — `defaultdict` has no other use in the file.)

- [ ] **Step 4: Run the new tests AND existing apply_network tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network.py -v`
Expected: PASS — new tests pass; existing `test_apply_network_noop_when_no_graph`, `test_apply_network_tilts_hold_to_sell`, `test_apply_network_cap_cannot_flip_strong_buy`, `test_apply_network_is_idempotent` remain green (their edges are forward, behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/network.py backend/tests/test_network.py
git commit -m "feat(network): apply_network selects edges via incident_edges (both endpoints)"
```

---

## Task 5: Route `score_one` through `incident_edges`

**Files:**
- Modify: `backend/app/screener/service.py` (import line 11; edge selection line 74)
- Test: `backend/tests/test_score_one.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_score_one.py`:

```python
def test_score_one_blends_reverse_symmetric_edge(tmp_path, monkeypatch):
    # Edge MSFT -> AAPL (partner). Scoring AAPL must pick it up via the reverse direction.
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    save_graph(KnowledgeGraph(scope="focus", nodes=["AAPL", "MSFT"], edges=[
        GraphEdge(source="MSFT", target="AAPL", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)]), cache)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="Microsoft", price=1, change_pct=0, score=60,
                   direction="buy", net=0.5, base_score=60.0, base_net=0.5)]), cache)
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert out.network is not None and out.network.signed > 0
    assert out.network.influences[0].neighbour == "MSFT"


def test_score_one_skips_reverse_directional_edge(tmp_path, monkeypatch):
    # Edge MSFT -> AAPL (supplier) is directional: AAPL (the target) gets no signal.
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    save_graph(KnowledgeGraph(scope="focus", nodes=["AAPL", "MSFT"], edges=[
        GraphEdge(source="MSFT", target="AAPL", type="supplier", sentiment="positive",
                  weight=1.0, confidence=1.0)]), cache)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="Microsoft", price=1, change_pct=0, score=60,
                   direction="buy", net=0.5, base_score=60.0, base_net=0.5)]), cache)
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    assert out.network is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_score_one.py::test_score_one_blends_reverse_symmetric_edge -v`
Expected: FAIL — current `score_one` filters `e.source == ticker`, so a `MSFT -> AAPL` edge is skipped and `out.network is None`.

- [ ] **Step 3: Swap the edge selector**

In `backend/app/screener/service.py`, change the import on line 11 from:

```python
from app.analysis.network import blend_network_into_score, compute_network_signal
```

to:

```python
from app.analysis.network import blend_network_into_score, compute_network_signal, incident_edges
```

Then change line 74 from:

```python
            edges = [e for e in graph.edges if e.source == ticker]
```

to:

```python
            edges = incident_edges(ticker, graph.edges, set(settings.network.symmetric_types))
```

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_score_one.py -v`
Expected: PASS — new tests pass; existing `test_score_one_base`, `test_score_one_blends_network`, `test_score_one_network_failure_degrades` remain green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/service.py backend/tests/test_score_one.py
git commit -m "feat(network): score_one selects edges via incident_edges"
```

---

## Task 6: Route `analysis_service` through `incident_edges`

**Files:**
- Modify: `backend/app/services/analysis_service.py` (import line 8; edge selection line 58)
- Test: `backend/tests/test_analysis_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analysis_service.py`:

```python
def test_run_analysis_enriches_network_reverse_symmetric(tmp_path, monkeypatch):
    # Edge TSM -> AAPL (partner). Analysing AAPL must enrich its network via the reverse edge.
    import app.services.analysis_service as svc
    from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore
    from app.network.store import save_graph
    from app.screener.store import save_snapshot
    from tests.test_screener_service import _stock

    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40,
                   direction="sell", net=-0.9)]), cache)
    save_graph(KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="TSM", target="AAPL", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)]), cache)

    monkeypatch.setattr(svc, "get_stock_data", lambda *a, **k: _stock("AAPL"))
    monkeypatch.setattr(svc, "build_provider", lambda s: object())
    captured = {}

    def fake_analyze(stock, provider, model, provider_name):
        captured["network"] = stock.network
        from app.models.schemas import AnalysisResult
        return AnalysisResult(ticker="AAPL", provider=provider_name, model=model,
                              generated_at="t", overall_summary="", news_analysis="",
                              sentiment="neutral", current_recommendation="hold", confidence=0.5)

    monkeypatch.setattr(svc, "analyze", fake_analyze)
    settings = Settings(); settings.providers["anthropic"].api_key = "x"
    svc.run_analysis("AAPL", "1y", settings, cache)
    assert captured["network"] is not None
    assert captured["network"].influences[0].neighbour == "TSM"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analysis_service.py::test_run_analysis_enriches_network_reverse_symmetric -v`
Expected: FAIL — current code filters `e.source == ticker`, so the `TSM -> AAPL` edge is skipped and `stock.network` stays `None`.

- [ ] **Step 3: Swap the edge selector**

In `backend/app/services/analysis_service.py`, change the import on line 8 from:

```python
from app.analysis.network import compute_network_signal
```

to:

```python
from app.analysis.network import compute_network_signal, incident_edges
```

Then change line 58 from:

```python
            edges = [e for e in graph.edges if e.source == ticker]
```

to:

```python
            edges = incident_edges(ticker, graph.edges, set(ncfg.symmetric_types))
```

(`ncfg = settings.network` is already in scope from line 52.)

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analysis_service.py -v`
Expected: PASS — new test passes; existing `test_run_analysis_enriches_network` (a forward `AAPL -> TSM` supplier edge) and `test_run_analysis_uses_overlay_when_no_focus_snapshot` (a forward `AAPL -> TSM` partner edge) remain green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/analysis_service.py backend/tests/test_analysis_service.py
git commit -m "feat(network): analysis_service selects edges via incident_edges"
```

---

## Task 7: Mirror `symmetric_types` in the frontend type + fixtures

**Files:**
- Modify: `frontend/src/types.ts` (`NetworkConfig`, lines 50-53)
- Modify: `frontend/src/hooks/useWatchlist.test.tsx` (line 19)
- Modify: `frontend/src/pages/Dashboard.test.tsx` (line 37)
- Modify: `frontend/src/pages/Settings.test.tsx` (line 32)

`RelationType` is already defined and exported in `types.ts:22`.

- [ ] **Step 1: Add the field to the TS interface**

In `frontend/src/types.ts`, change:

```typescript
export interface NetworkConfig {
  enabled: boolean; focus_top_n: number; max_edges_per_company: number;
  min_confidence: number; weight: number; alpha_event: number; beta_state: number;
}
```

to:

```typescript
export interface NetworkConfig {
  enabled: boolean; focus_top_n: number; max_edges_per_company: number;
  min_confidence: number; weight: number; alpha_event: number; beta_state: number;
  symmetric_types: RelationType[];
}
```

- [ ] **Step 2: Run the type-gate to verify it fails**

Run (from `frontend/`): `npm run build`
Expected: FAIL — `tsc -b` reports the three fixtures' `network` objects are missing the required `symmetric_types` property.

- [ ] **Step 3: Update the three fixtures**

In each of `frontend/src/hooks/useWatchlist.test.tsx`, `frontend/src/pages/Dashboard.test.tsx`, and `frontend/src/pages/Settings.test.tsx`, change the `network` literal from:

```typescript
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4 },
```

to:

```typescript
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4, symmetric_types: ['competitor', 'partner', 'other'] },
```

- [ ] **Step 4: Run the build + tests to verify they pass**

Run (from `frontend/`): `npm run build` then `npx vitest run`
Expected: build succeeds (type-gate green); vitest all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/hooks/useWatchlist.test.tsx frontend/src/pages/Dashboard.test.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(network): mirror symmetric_types in NetworkConfig TS type + fixtures"
```

---

## Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Backend full suite**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (the prior baseline 284 + the new tests added here). No failures, no errors.

- [ ] **Step 2: Frontend tests + build**

Run (from `frontend/`): `npx vitest run` then `npm run build`
Expected: all vitest pass; build (tsc -b + vite build) succeeds.

- [ ] **Step 3: Sanity-check the off-switch end to end (optional but recommended)**

Confirm `test_apply_network_empty_symmetric_types_is_directed` (Task 4) is present and green — this is the regression guard proving `symmetric_types=[]` reproduces the legacy directed behavior.

- [ ] **Step 4: Finish the branch**

Use **superpowers:finishing-a-development-branch** to merge `feat/network-symmetric-influence` back to `master` (local ff-merge; do not push unless explicitly asked).
