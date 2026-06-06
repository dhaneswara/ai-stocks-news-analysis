# Company Knowledge Graph — Phase A (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AI-driven company knowledge graph and fold a capped, explainable "network" signal into the existing buy/sell/hold scorer — delivering the actual decision impact (no visual page yet; that is Phase B).

**Architecture:** An LLM extracts typed, directional, cited relationship *edges* from each focus company's news (one cached call/company/day, mirroring `political.py`). A **pure** propagation pass blends each edge's news sentiment with the neighbour's current technical condition and re-blends the result into the scorer via a closed form. The graph is cached like `screen_snapshot`; propagation re-runs freely (no LLM), so Rescan stays fast.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic / pytest (backend); React 18 + TS / Vite 5 / vitest + @testing-library (frontend). LLM via the existing `complete(system,user)->str` provider protocol + `extract_json`.

**Spec:** `docs/superpowers/specs/2026-06-06-company-knowledge-graph-design.md`

**Conventions (from repo memory):** venv interpreter is `backend/.venv/Scripts/python.exe`; run tests from `backend/` as `.venv/Scripts/python.exe -m pytest -q`. Commits use Conventional Commits and **must NOT** include a `Co-Authored-By: Claude` trailer. Work happens on branch `feat/company-knowledge-graph` (already created).

---

## File structure

**Backend — create:**
- `backend/app/analysis/network.py` — pure propagation: sign rules, `compute_network_signal`, `apply_network`.
- `backend/app/analysis/relationships.py` — AI extraction: `TickerResolver`, `extract_relationships`.
- `backend/app/network/__init__.py`, `backend/app/network/service.py` (`build_graph`), `backend/app/network/store.py` (`save_graph`/`load_graph`), `backend/app/network/runner.py` (`run`), `backend/app/network/__main__.py` (CLI).
- Tests: `test_network_schema.py`, `test_network.py`, `test_relationships.py`, `test_network_store.py`, `test_network_service.py`, `test_network_runner.py`, `test_api_graph.py`.

**Backend — modify:**
- `backend/app/models/schemas.py` — new models + field additions.
- `backend/app/analysis/scoring.py` — populate `StockScore.net`.
- `backend/app/analysis/analyzer.py` — `_format_network` prompt section + copy `network` onto the result.
- `backend/app/services/analysis_service.py` — enrich `StockData.network` from the cached graph.
- `backend/app/api/routes.py` — `GET /api/graph`, `POST /api/graph/rebuild`, network in `screen/rescan`.

**Frontend — modify/create:**
- `frontend/src/types.ts` — new types + field additions.
- `frontend/src/components/DiscoverBoard.tsx` — 🔗 network badge.
- `frontend/src/components/NetworkPanel.tsx` (create) + `frontend/src/components/ReasoningPanel.tsx` (wire in).
- Tests: `frontend/src/components/NetworkPanel.test.tsx`; update `frontend/src/pages/Dashboard.test.tsx` fixture.

---

## Task 1: Schemas — graph, network, config & field additions

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_network_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_network_schema.py
from app.models.schemas import (
    GraphEdge, KnowledgeGraph, NetworkConfig, NetworkInfluence, NetworkSignal,
    Settings, StockScore,
)


def test_graph_edge_defaults():
    e = GraphEdge(source="AAPL", target="GOOGL", type="partner")
    assert e.sentiment == "neutral" and e.weight == 0.5 and e.confidence == 0.5


def test_knowledge_graph_round_trip():
    g = KnowledgeGraph(scope="focus", nodes=["AAPL"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative")
    ], built=1, skipped=0)
    again = KnowledgeGraph.model_validate_json(g.model_dump_json())
    assert again.edges[0].target == "TSM" and again.built == 1


def test_network_signal_and_influence():
    sig = NetworkSignal(ticker="AAPL", intensity=0.5, signed=-0.3, influences=[
        NetworkInfluence(neighbour="TSM", type="supplier", edge_sentiment="negative",
                         neighbour_direction="sell", signed=-0.3, reason="supplier TSM (bearish)")
    ], reasons=["supplier TSM (bearish)"])
    assert sig.influences[0].neighbour == "TSM"


def test_stock_score_gains_net_and_network():
    s = StockScore(ticker="AAPL", name="Apple", price=1.0, change_pct=0.0,
                   score=10.0, direction="hold")
    assert s.net == 0.0 and s.network is None


def test_settings_has_network_defaults():
    n = Settings().network
    assert n.enabled and n.focus_top_n == 30 and n.weight == 0.5
    assert n.alpha_event == 0.6 and n.beta_state == 0.4
```

- [ ] **Step 2: Run it — expect failure** — `.venv/Scripts/python.exe -m pytest tests/test_network_schema.py -q` → ImportError (`GraphEdge` undefined).

- [ ] **Step 3: Implement — add to `backend/app/models/schemas.py`**

Add the new types (place after `Mention`):

```python
RelationType = Literal["supplier", "customer", "partner", "competitor", "owner", "subsidiary"]


class GraphEdge(BaseModel):
    source: str
    target: str
    type: RelationType
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"  # effect ON THE SOURCE
    weight: float = 0.5        # 0..1 materiality
    confidence: float = 0.5    # 0..1 extraction confidence
    evidence: str = ""
    url: str = ""
    as_of: str = ""


class KnowledgeGraph(BaseModel):
    as_of: str = ""
    scope: str = "focus"
    nodes: list[str] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    built: int = 0
    skipped: int = 0


class NetworkInfluence(BaseModel):
    neighbour: str
    name: str = ""
    type: RelationType
    edge_sentiment: str = "neutral"
    neighbour_direction: str = "unknown"
    signed: float = 0.0
    reason: str = ""


class NetworkSignal(BaseModel):
    ticker: str
    intensity: float = 0.0
    signed: float = 0.0
    influences: list[NetworkInfluence] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class NetworkConfig(BaseModel):
    enabled: bool = True
    focus_top_n: int = 30
    max_edges_per_company: int = 8
    min_confidence: float = 0.4
    weight: float = 0.5        # the tilt cap (network family weight)
    alpha_event: float = 0.6   # blend weight on the edge news-event term
    beta_state: float = 0.4    # blend weight on the neighbour-state term
```

Then extend existing models:

```python
# in StockScore — add these two fields:
    net: float = 0.0                                  # -1..1 directional vote (for re-blend)
    network: Optional["NetworkSignal"] = None         # set after propagation

# in StockData — add:
    network: Optional["NetworkSignal"] = None

# in AnalysisResult — add:
    network: Optional["NetworkSignal"] = None

# in Settings — add:
    network: NetworkConfig = Field(default_factory=NetworkConfig)
```

(`NetworkSignal` is defined above `StockScore`/`StockData`/`AnalysisResult` in the file, so the annotations resolve without quotes; the quoted form above is safe regardless.)

- [ ] **Step 4: Run it — expect pass** — `.venv/Scripts/python.exe -m pytest tests/test_network_schema.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_network_schema.py
git commit -m "feat(backend): add knowledge-graph and network-signal schemas"
```

---

## Task 2: `score_stock` populates `StockScore.net`

**Files:**
- Modify: `backend/app/analysis/scoring.py:148-177` (the `score_stock` return)
- Test: `backend/tests/test_scoring.py` (append)

- [ ] **Step 1: Write the failing test** (append to `test_scoring.py`)

```python
def test_score_stock_populates_net_sign_matches_direction():
    from app.analysis.scoring import score_stock
    from app.models.schemas import ScreenerConfig
    from tests.test_screener_service import _stock  # reuse the shared fixture builder

    bull = score_stock(_stock("AAA", rsi_last=20.0, week52_low=99.0), [], ScreenerConfig())
    assert bull.direction == "buy" and bull.net > 0
    bear = score_stock(_stock("BBB", rsi_last=85.0), [], ScreenerConfig())
    assert bear.net < 0
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_scoring.py::test_score_stock_populates_net_sign_matches_direction -q` → AttributeError/AssertionError (`net` is 0.0).

- [ ] **Step 3: Implement** — in `score_stock`, the `net` is already computed; add it to the returned `StockScore`:

```python
    return StockScore(
        ticker=stock.ticker,
        name=stock.company_name,
        price=stock.price.current,
        change_pct=stock.price.change_pct,
        score=round(_clamp(score, 0.0, 100.0), 1),
        direction=direction,
        net=round(_clamp(net, -1.0, 1.0), 3),     # <-- add this line
        reasons=reasons,
        components={f: round(sig.intensity, 2) for f, sig in families.items()},
        as_of=stock.as_of,
    )
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_scoring.py -q` → PASS (all scoring tests still green).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/scoring.py backend/tests/test_scoring.py
git commit -m "feat(backend): expose directional net on StockScore for re-blend"
```

---

## Task 3: Propagation — sign rules & `compute_network_signal`

**Files:**
- Create: `backend/app/analysis/network.py`
- Test: `backend/tests/test_network.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_network.py
from app.analysis.network import compute_network_signal
from app.models.schemas import GraphEdge, NetworkConfig, StockScore


def _score(ticker, net, direction="hold"):
    return StockScore(ticker=ticker, name=ticker, price=1.0, change_pct=0.0,
                      score=10.0, direction=direction, net=net)


def _edge(target, type, sentiment="neutral", weight=1.0, confidence=1.0):
    return GraphEdge(source="X", target=target, type=type, sentiment=sentiment,
                     weight=weight, confidence=confidence)


def test_supplier_moves_with_neighbour():
    idx = {"S": _score("S", net=-0.8, direction="sell")}
    sig = compute_network_signal("X", [_edge("S", "supplier")], idx, NetworkConfig())
    assert sig.signed < 0  # bearish supplier drags X down


def test_competitor_flips_sign():
    idx = {"C": _score("C", net=0.8, direction="buy")}
    sig = compute_network_signal("X", [_edge("C", "competitor")], idx, NetworkConfig())
    assert sig.signed < 0  # a strong competitor is bearish for X


def test_event_term_applies_without_scored_neighbour():
    sig = compute_network_signal("X", [_edge("Z", "partner", sentiment="positive")], {}, NetworkConfig())
    assert sig.signed > 0 and sig.influences[0].neighbour_direction == "unknown"


def test_signed_and_intensity_are_clamped():
    idx = {f"N{i}": _score(f"N{i}", net=-1.0, direction="sell") for i in range(5)}
    edges = [_edge(f"N{i}", "supplier", sentiment="negative") for i in range(5)]
    sig = compute_network_signal("X", edges, idx, NetworkConfig())
    assert -1.0 <= sig.signed <= 0.0 and 0.0 <= sig.intensity <= 1.0
    assert sig.signed == -1.0  # five strong-bearish edges clamp the floor
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_network.py -q` → ImportError.

- [ ] **Step 3: Implement `backend/app/analysis/network.py`**

```python
"""Pure, deterministic propagation of relationship signal across the knowledge graph.

No LLM, no I/O. `compute_network_signal` blends each edge's news-event sentiment (judged for
the SOURCE company) with the neighbour's current technical condition; `apply_network` (next
task) folds the result into the board via a closed-form re-blend.
"""
from __future__ import annotations

from app.models.schemas import GraphEdge, NetworkConfig, NetworkInfluence, NetworkSignal, StockScore

_SENTIMENT = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _type_sign(rel_type: str) -> float:
    """Competitor is the only relationship where you move AGAINST the neighbour."""
    return -1.0 if rel_type == "competitor" else 1.0


def _direction_word(signed: float) -> str:
    return "bullish" if signed > 0 else "bearish" if signed < 0 else "neutral"


def compute_network_signal(
    ticker: str,
    edges: list[GraphEdge],
    base_index: dict[str, StockScore],
    cfg: NetworkConfig,
) -> NetworkSignal:
    influences: list[NetworkInfluence] = []
    signed_sum = 0.0
    intensity_sum = 0.0
    for e in edges:
        nb = base_index.get(e.target)
        nb_net = nb.net if nb else 0.0
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
    influences.sort(key=lambda i: abs(i.signed), reverse=True)
    return NetworkSignal(
        ticker=ticker,
        intensity=round(_clamp(intensity_sum, 0.0, 1.0), 3),
        signed=round(_clamp(signed_sum, -1.0, 1.0), 3),
        influences=influences,
        reasons=[i.reason for i in influences[:3]],
    )
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_network.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/network.py backend/tests/test_network.py
git commit -m "feat(backend): pure network-signal propagation with sign rules"
```

---

## Task 4: Propagation — `apply_network` re-blend into the board

**Files:**
- Modify: `backend/app/analysis/network.py`
- Test: `backend/tests/test_network.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
from app.analysis.network import apply_network
from app.models.schemas import KnowledgeGraph, ScreenBoard, Settings


def _board(*scores):
    return ScreenBoard(as_of="t", scope="all", scanned=len(scores), items=list(scores))


def test_apply_network_noop_when_no_graph():
    board = _board(_score("AAPL", net=0.0))
    out = apply_network(board, KnowledgeGraph(), Settings())
    assert out.items[0].network is None and out.items[0].direction == "hold"


def test_apply_network_tilts_hold_to_sell():
    # AAPL is a borderline HOLD; a strongly bearish supplier should tilt it to SELL.
    board = _board(
        _score("AAPL", net=0.0, direction="hold"),
        _score("TSM", net=-0.9, direction="sell"),
    )
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    out = apply_network(board, graph, Settings())
    aapl = next(i for i in out.items if i.ticker == "AAPL")
    assert aapl.direction == "sell" and aapl.network is not None
    assert aapl.network.reasons and aapl.components.get("network", 0) > 0


def test_apply_network_cap_cannot_flip_strong_buy():
    # A strong technical BUY must survive one bearish network edge (tilt, not override).
    board = _board(
        _score("NVDA", net=0.9, direction="buy"),
        _score("INTC", net=0.8, direction="buy"),
    )
    graph = KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="NVDA", target="INTC", type="competitor", sentiment="negative",
                  weight=1.0, confidence=1.0)
    ])
    out = apply_network(board, graph, Settings())
    nvda = next(i for i in out.items if i.ticker == "NVDA")
    assert nvda.direction == "buy"  # capped weight tilts but does not flip
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_network.py -q` → ImportError (`apply_network`).

- [ ] **Step 3: Implement — append to `backend/app/analysis/network.py`**

```python
from collections import defaultdict

from app.analysis.scoring import _DIRECTION_THRESHOLD
from app.models.schemas import KnowledgeGraph, ScreenBoard, Settings

_DIRECTIONAL = ("extremes", "trend", "momentum")


def apply_network(board: ScreenBoard, graph: KnowledgeGraph, settings: Settings) -> ScreenBoard:
    """Fold a capped `network` family into each focus company's score/direction.

    Pure: reads neighbours' BASE scores (one hop, no feedback) and returns a new board.
    Re-blend is the closed form of adding one weighted family to `score_stock`'s own formula,
    so it needs only the stored `score` and `net` plus the configured weights.
    """
    ncfg = settings.network
    if not ncfg.enabled or not graph.edges:
        return board

    weights = settings.screener.weights
    w_base = sum(weights.values()) or 1.0
    w_dir = sum(weights.get(f, 0.0) for f in _DIRECTIONAL) or 1.0
    w_net = ncfg.weight

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
        final_score = (s.score * w_base + 100.0 * sig.intensity * w_net) / (w_base + w_net)
        final_net = _clamp((s.net * w_dir + sig.signed * w_net) / (w_dir + w_net), -1.0, 1.0)
        direction = (
            "buy" if final_net > _DIRECTION_THRESHOLD
            else "sell" if final_net < -_DIRECTION_THRESHOLD
            else "hold"
        )
        components = dict(s.components)
        components["network"] = round(sig.intensity, 2)
        new_items.append(s.model_copy(update={
            "score": round(_clamp(final_score, 0.0, 100.0), 1),
            "net": round(final_net, 3),
            "direction": direction,
            "components": components,
            "reasons": sig.reasons + s.reasons,   # network reasons first
            "network": sig,
        }))

    new_items.sort(key=lambda x: x.score, reverse=True)
    return board.model_copy(update={"items": new_items})
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_network.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/network.py backend/tests/test_network.py
git commit -m "feat(backend): re-blend network family into the opportunity board"
```

---

## Task 5: Extraction — `TickerResolver` (closed-vocab grounding)

**Files:**
- Create: `backend/app/analysis/relationships.py`
- Test: `backend/tests/test_relationships.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_relationships.py
from app.analysis.relationships import TickerResolver
from app.models.schemas import UniverseEntry

UNIVERSE = [
    UniverseEntry(ticker="AAPL", name="Apple Inc.", sector="Information Technology"),
    UniverseEntry(ticker="GOOGL", name="Alphabet Inc.", sector="Communication Services"),
    UniverseEntry(ticker="TSM", name="Taiwan Semiconductor Manufacturing", sector="Information Technology"),
]


def test_resolve_by_exact_ticker():
    r = TickerResolver(UNIVERSE)
    assert r.resolve("whatever", "aapl") == "AAPL"


def test_resolve_by_normalized_name():
    r = TickerResolver(UNIVERSE)
    assert r.resolve("Apple", None) == "AAPL"           # suffix-stripped match
    assert r.resolve("Alphabet Inc.", None) == "GOOGL"


def test_resolve_drops_unknown():
    r = TickerResolver(UNIVERSE)
    assert r.resolve("Some Private Startup", "PRIV") is None
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_relationships.py -q` → ImportError.

- [ ] **Step 3: Implement `backend/app/analysis/relationships.py`** (resolver portion)

```python
"""AI extraction of inter-company relationship edges from a company's news headlines.

Mirrors `political.py`: one cached LLM call per company per day, parse with `extract_json`,
degrade silently to an empty edge list on any failure. `TickerResolver` grounds every edge
target in the universe (closed vocabulary) so the model cannot invent nodes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import get_args

from app.analysis.analyzer import extract_json
from app.config.cache import Cache
from app.llm.base import LLMProvider
from app.models.schemas import GraphEdge, NetworkConfig, NewsItem, RelationType, UniverseEntry

_RELATION_TYPES = set(get_args(RelationType))
_SUFFIX_RE = re.compile(
    r"\b(inc|corp|corporation|co|ltd|plc|company|companies|holdings|group|the|class [abc])\b\.?",
    re.I,
)


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", _SUFFIX_RE.sub("", (name or "").lower())).strip()


class TickerResolver:
    """Resolve an LLM-named company to a canonical universe ticker, else None."""

    def __init__(self, entries: list[UniverseEntry]) -> None:
        self._by_ticker = {e.ticker.upper(): e.ticker for e in entries}
        self._by_name = {_normalize(e.name): e.ticker for e in entries}

    def resolve(self, name: str, ticker_hint: str | None) -> str | None:
        if ticker_hint and ticker_hint.upper() in self._by_ticker:
            return self._by_ticker[ticker_hint.upper()]
        norm = _normalize(name)
        return self._by_name.get(norm) if norm else None
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_relationships.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/relationships.py backend/tests/test_relationships.py
git commit -m "feat(backend): TickerResolver to ground graph nodes in the universe"
```

---

## Task 6: Extraction — `extract_relationships` (LLM + cache + degrade)

**Files:**
- Modify: `backend/app/analysis/relationships.py`
- Test: `backend/tests/test_relationships.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
import json as _json
from app.analysis.relationships import extract_relationships
from app.config.cache import Cache
from app.models.schemas import NewsItem, NetworkConfig, StockData, PriceSummary, Fundamentals, Indicators


class FakeProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def _stock_with_news(*titles):
    return StockData(
        ticker="AAPL", company_name="Apple Inc.", as_of="t",
        price=PriceSummary(current=1, change=0, change_pct=0),
        candles=[], fundamentals=Fundamentals(), indicators=Indicators(),
        news=[NewsItem(title=t, url=f"https://n/{i}") for i, t in enumerate(titles)],
    )


EDGES_JSON = _json.dumps({"edges": [
    {"target_name": "Taiwan Semiconductor", "target_ticker": "TSM", "type": "supplier",
     "sentiment": "negative", "weight": 0.8, "confidence": 0.9, "evidence": "TSMC warns on supply"},
    {"target_name": "Unknown Private Co", "target_ticker": "PRIV", "type": "partner",
     "sentiment": "positive", "weight": 0.5, "confidence": 0.9, "evidence": "x"},
    {"target_name": "Alphabet", "target_ticker": "GOOGL", "type": "partner",
     "sentiment": "positive", "weight": 0.5, "confidence": 0.1, "evidence": "low conf"},
]})


def test_extract_parses_filters_and_grounds(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    edges = extract_relationships(
        _stock_with_news("TSMC warns on supply"), RESOLVER, FakeProvider([EDGES_JSON]),
        "m", "fake", cache, NetworkConfig())
    targets = {e.target for e in edges}
    assert targets == {"TSM"}             # PRIV dropped (unresolved), GOOGL dropped (low conf)
    assert edges[0].source == "AAPL" and edges[0].type == "supplier"


def test_extract_is_cached_per_day(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    p = FakeProvider([EDGES_JSON])  # only one output
    a = extract_relationships(_stock_with_news("x"), RESOLVER, p, "m", "fake", cache, NetworkConfig())
    b = extract_relationships(_stock_with_news("x"), RESOLVER, p, "m", "fake", cache, NetworkConfig())
    assert p.calls == 1 and len(a) == len(b)


def test_extract_degrades_to_empty_on_bad_json(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    edges = extract_relationships(_stock_with_news("x"), RESOLVER, FakeProvider(["not json"]),
                                  "m", "fake", cache, NetworkConfig())
    assert edges == []
```

Add at the top of the file (after `UNIVERSE`): `RESOLVER = TickerResolver(UNIVERSE + [UniverseEntry(ticker="TSM", name="Taiwan Semiconductor Manufacturing", sector="Information Technology")])` — but `TSM` is already in `UNIVERSE`, so simply: `RESOLVER = TickerResolver(UNIVERSE)`.

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_relationships.py -q` → ImportError (`extract_relationships`).

- [ ] **Step 3: Implement — append to `backend/app/analysis/relationships.py`**

```python
_REL_TTL_SECONDS = 24 * 60 * 60

_SYSTEM = (
    "You extract business relationships between public companies from news headlines about ONE "
    "company (the SOURCE). For each relationship, classify its type and judge the news event's "
    "likely effect ON THE SOURCE company. Respond with ONLY a single JSON object, no prose, no "
    "code fences."
)


def _schema_hint(ticker: str) -> str:
    return f"""Return JSON with exactly this shape:
{{"edges":[{{"target_name": string, "target_ticker": string|null, "type": string,
            "sentiment": "positive"|"negative"|"neutral", "weight": number 0..1,
            "confidence": number 0..1, "evidence": string}}]}}
- "type" = the TARGET's role relative to {ticker}: supplier|customer|partner|competitor|owner|subsidiary.
- "sentiment" = the event's likely effect on {ticker} (positive = good for {ticker}).
- Include only relationships actually supported by the headlines; "evidence" = a short quote.
- Return an empty list if none."""


def build_extract_prompt(stock) -> tuple[str, str]:
    headlines = "\n".join(
        f"- [{n.published_at}] {n.title} ({n.source})" for n in stock.news[:10]
    ) or "- (none)"
    user = f"{stock.company_name} ({stock.ticker}). Recent headlines:\n{headlines}\n\n{_schema_hint(stock.ticker)}"
    return _SYSTEM, user


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _citation_url(evidence: str, news: list[NewsItem]) -> str:
    ev = (evidence or "").lower()
    for n in news:
        title = (n.title or "").lower()
        if title and any(len(w) > 4 and w in ev for w in title.split()):
            return n.url
    return ""


def extract_relationships(
    stock,
    resolver: TickerResolver,
    provider: LLMProvider,
    model: str,
    provider_name: str,
    cache: Cache,
    cfg: NetworkConfig,
    *,
    now: datetime | None = None,
) -> list[GraphEdge]:
    now = now or datetime.now(timezone.utc)
    if not stock.news:
        return []

    key = f"relationships:{provider_name}:{model}:{stock.ticker}:{now.date().isoformat()}"
    cached = cache.get(key)
    if cached is not None:
        try:
            return [GraphEdge(**e) for e in json.loads(cached)]
        except Exception:
            pass  # corrupt entry -> recompute

    system, user = build_extract_prompt(stock)
    edges: list[GraphEdge] = []
    try:
        payload = extract_json(provider.complete(system, user))
        raw = payload.get("edges", []) if isinstance(payload, dict) else []
        for item in raw:
            if not isinstance(item, dict):
                continue
            target = resolver.resolve(item.get("target_name", ""), item.get("target_ticker"))
            if not target or target == stock.ticker:
                continue
            rel_type = item.get("type")
            if rel_type not in _RELATION_TYPES:
                continue
            try:
                conf = float(item.get("confidence", 0.0))
                weight = float(item.get("weight", 0.5))
            except (TypeError, ValueError):
                continue
            if conf < cfg.min_confidence:
                continue
            sentiment = item.get("sentiment", "neutral")
            if sentiment not in ("positive", "negative", "neutral"):
                sentiment = "neutral"
            evidence = str(item.get("evidence", ""))[:200]
            edges.append(GraphEdge(
                source=stock.ticker, target=target, type=rel_type, sentiment=sentiment,
                weight=_clamp01(weight), confidence=_clamp01(conf), evidence=evidence,
                url=_citation_url(evidence, stock.news), as_of=now.isoformat(),
            ))
    except Exception:
        return []  # degrade silently

    edges.sort(key=lambda e: e.weight * e.confidence, reverse=True)
    edges = edges[: cfg.max_edges_per_company]
    cache.set(key, json.dumps([e.model_dump() for e in edges]), _REL_TTL_SECONDS)
    return edges
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_relationships.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/relationships.py backend/tests/test_relationships.py
git commit -m "feat(backend): AI extraction of relationship edges from news"
```

---

## Task 7: Graph snapshot store

**Files:**
- Create: `backend/app/network/__init__.py` (empty), `backend/app/network/store.py`
- Test: `backend/tests/test_network_store.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_network_store.py
from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph
from app.network.store import load_graph, save_graph


def test_graph_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    g = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier")], built=1)
    save_graph(g, cache)
    loaded = load_graph(cache, "focus")
    assert loaded is not None and loaded.edges[0].target == "TSM"
    assert load_graph(cache, "other") is None
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_network_store.py -q` → ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/network/__init__.py
```
```python
# backend/app/network/store.py
"""Persist the latest knowledge graph in the existing Cache (SQLite KV), keyed
`graph_snapshot:<scope>` with a long TTL — mirrors `screener/store.py`."""
from __future__ import annotations

from app.config.cache import Cache
from app.models.schemas import KnowledgeGraph

_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _key(scope: str) -> str:
    return f"graph_snapshot:{scope}"


def save_graph(graph: KnowledgeGraph, cache: Cache) -> None:
    cache.set(_key(graph.scope), graph.model_dump_json(), _SNAPSHOT_TTL_SECONDS)


def load_graph(cache: Cache, scope: str = "focus") -> KnowledgeGraph | None:
    raw = cache.get(_key(scope))
    return KnowledgeGraph.model_validate_json(raw) if raw is not None else None
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_network_store.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/__init__.py backend/app/network/store.py backend/tests/test_network_store.py
git commit -m "feat(backend): persist knowledge-graph snapshot in cache"
```

---

## Task 8: `build_graph` over the focus set

**Files:**
- Create: `backend/app/network/service.py`
- Test: `backend/tests/test_network_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_network_service.py
import app.network.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Fundamentals, GraphEdge, Indicators, PriceSummary, ScreenBoard, Settings,
    StockData, StockScore, UniverseEntry,
)


def _stock(ticker):
    return StockData(ticker=ticker, company_name=f"{ticker} Inc.", as_of="t",
                     price=PriceSummary(current=1, change=0, change_pct=0),
                     candles=[], fundamentals=Fundamentals(), indicators=Indicators())


def _wire(monkeypatch, edges_for):
    monkeypatch.setattr(service, "build_provider", lambda s: object())
    monkeypatch.setattr(service, "load_universe", lambda: [
        UniverseEntry(ticker="AAPL", name="Apple", sector="Tech"),
        UniverseEntry(ticker="TSM", name="Taiwan Semi", sector="Tech")])
    monkeypatch.setattr(service, "get_stock_data", lambda t, *a, **k: _stock(t))
    monkeypatch.setattr(service, "extract_relationships",
                        lambda stock, *a, **k: edges_for.get(stock.ticker, []))


def test_focus_is_watchlist_plus_top_n(tmp_path, monkeypatch):
    edges = {"AAPL": [GraphEdge(source="AAPL", target="TSM", type="supplier")]}
    _wire(monkeypatch, edges)
    board = ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="MS", price=1, change_pct=0, score=90, direction="buy")])
    monkeypatch.setattr(service, "load_snapshot", lambda cache, scope="all": board)
    settings = Settings(); settings.watchlist = ["AAPL"]; settings.network.focus_top_n = 5
    g = service.build_graph(None, settings, Cache(str(tmp_path / "c.db")))
    assert set(g.nodes) >= {"AAPL", "TSM"} and g.built == 2  # AAPL (watchlist) + MSFT (top-n)
    assert any(e.target == "TSM" for e in g.edges)


def test_skips_failures(tmp_path, monkeypatch):
    _wire(monkeypatch, {})
    monkeypatch.setattr(service, "load_snapshot", lambda cache, scope="all": None)

    def boom(t, *a, **k):
        if t == "TSM":
            raise ValueError("no data")
        return _stock(t)

    monkeypatch.setattr(service, "get_stock_data", boom)
    settings = Settings(); settings.watchlist = ["AAPL", "TSM"]
    g = service.build_graph(None, settings, Cache(str(tmp_path / "c.db")))
    assert g.built == 1 and g.skipped == 1


def test_disabled_returns_empty(tmp_path, monkeypatch):
    _wire(monkeypatch, {})
    monkeypatch.setattr(service, "load_snapshot", lambda cache, scope="all": None)
    settings = Settings(); settings.network.enabled = False
    g = service.build_graph(None, settings, Cache(str(tmp_path / "c.db")))
    assert g.edges == [] and g.built == 0
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_network_service.py -q` → ImportError.

- [ ] **Step 3: Implement `backend/app/network/service.py`**

```python
"""Build the knowledge graph over the focus set (watchlist ∪ top board names).

Mirrors `screener/service.run_scan`: per-company try/except so one bad name never aborts the
build; reuses cached `get_stock_data` (news included). Only edge extraction costs an LLM call.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.relationships import TickerResolver, extract_relationships
from app.config.cache import Cache
from app.data.universe import load_universe
from app.llm.base import LLMError
from app.llm.factory import build_provider
from app.models.schemas import KnowledgeGraph, Settings
from app.screener.store import load_snapshot
from app.services.stock_service import get_stock_data

NETWORK_PERIOD = "1y"


def _focus_set(settings: Settings, cache: Cache) -> list[str]:
    board = load_snapshot(cache, "all")
    top = [i.ticker for i in board.items[: settings.network.focus_top_n]] if board else []
    seen: set[str] = set()
    focus: list[str] = []
    for t in list(settings.watchlist) + top:
        tu = (t or "").upper().strip()
        if tu and tu not in seen:
            seen.add(tu)
            focus.append(tu)
    return focus


def build_graph(scope: str | None, settings: Settings, cache: Cache, *, now: datetime | None = None) -> KnowledgeGraph:
    now = now or datetime.now(timezone.utc)
    out_scope = scope or "focus"
    ncfg = settings.network
    if not ncfg.enabled:
        return KnowledgeGraph(as_of=now.isoformat(), scope=out_scope)

    try:
        provider = build_provider(settings)
    except LLMError:
        return KnowledgeGraph(as_of=now.isoformat(), scope=out_scope)  # no usable provider -> empty
    provider_id = settings.active_provider
    model = settings.providers[provider_id].model
    resolver = TickerResolver(load_universe())

    edges = []
    nodes: set[str] = set()
    built = skipped = 0
    for ticker in _focus_set(settings, cache):
        try:
            stock = get_stock_data(ticker, NETWORK_PERIOD, settings.indicator_params, cache)
            es = extract_relationships(stock, resolver, provider, model, provider_id, cache, ncfg, now=now)
            edges.extend(es)
            nodes.add(ticker)
            for e in es:
                nodes.add(e.target)
            built += 1
        except Exception:  # noqa: BLE001 — one bad name must not abort the build
            skipped += 1
            continue

    return KnowledgeGraph(
        as_of=now.isoformat(), scope=out_scope, nodes=sorted(nodes),
        edges=edges, built=built, skipped=skipped,
    )
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_network_service.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/service.py backend/tests/test_network_service.py
git commit -m "feat(backend): build knowledge graph over the focus set"
```

---

## Task 9: Daily runner + CLI

**Files:**
- Create: `backend/app/network/runner.py`, `backend/app/network/__main__.py`
- Test: `backend/tests/test_network_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_network_runner.py
import app.network.runner as runner
from app.config.cache import Cache
from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore
from app.network.store import load_graph
from app.screener.store import load_snapshot, save_snapshot


def test_run_builds_saves_and_bakes_into_board(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold", net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40, direction="sell", net=-0.9),
    ]), cache)
    graph = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)], built=1)
    monkeypatch.setattr(runner, "build_graph", lambda scope, settings, cache: graph)

    result = runner.run(Settings(), cache)
    assert result["enabled"] and result["built"] == 1
    assert load_graph(cache, "focus") is not None
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None  # influence baked into the stored board


def test_run_disabled_is_noop(tmp_path):
    settings = Settings(); settings.network.enabled = False
    assert runner.run(settings, Cache(str(tmp_path / "c.db")))["enabled"] is False
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_network_runner.py -q` → ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/network/runner.py
from __future__ import annotations

import logging

from app.analysis.network import apply_network
from app.config.cache import Cache
from app.models.schemas import Settings
from app.network.service import build_graph
from app.network.store import save_graph
from app.screener.store import load_snapshot, save_snapshot

logger = logging.getLogger("network")


def run(settings: Settings, cache: Cache, scope: str | None = None) -> dict:
    if not settings.network.enabled:
        logger.info("Network signal disabled; nothing to do.")
        return {"enabled": False, "built": 0}
    graph = build_graph(scope, settings, cache)
    save_graph(graph, cache)
    board = load_snapshot(cache, "all")
    if board is not None:
        save_snapshot(apply_network(board, graph, settings), cache)  # bake influence in
    logger.info("Graph built: built=%d skipped=%d edges=%d", graph.built, graph.skipped, len(graph.edges))
    return {"enabled": True, "built": graph.built, "skipped": graph.skipped, "edges": len(graph.edges)}
```

```python
# backend/app/network/__main__.py
from __future__ import annotations

import argparse
import logging
import os
import sys

from app.deps import DATA_DIR, get_cache, get_settings_store
from app.network.runner import run
from app.network.service import build_graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.network",
        description="Build the company knowledge graph and bake its signal into the board.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build and log, but do not save.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)
    settings = get_settings_store().load()
    cache = get_cache()
    log = logging.getLogger("network")
    if args.dry_run:
        g = build_graph(None, settings, cache)
        log.info("Dry run: built=%d skipped=%d edges=%d", g.built, g.skipped, len(g.edges))
        return 0
    log.info("Done: %s", run(settings, cache))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_network_runner.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/runner.py backend/app/network/__main__.py backend/tests/test_network_runner.py
git commit -m "feat(backend): daily network runner and CLI"
```

---

## Task 10: API — `GET /api/graph` & `POST /api/graph/rebuild`

**Files:**
- Modify: `backend/app/api/routes.py` (imports near line 13-27; add routes after the `screen` routes, ~line 179)
- Test: `backend/tests/test_api_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_graph.py
import app.api.routes as routes
from fastapi.testclient import TestClient
from app.deps import get_cache
from app.main import app
from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore
from app.network.store import load_graph
from app.screener.store import load_snapshot, save_snapshot

client = TestClient(app)


def test_get_graph_empty_when_none():
    get_cache().set("graph_snapshot:focus", "", 1)  # ensure miss path is exercised
    r = client.get("/api/graph?scope=does-not-exist")
    assert r.status_code == 200 and r.json()["edges"] == []


def test_rebuild_builds_and_bakes(monkeypatch):
    cache = get_cache()
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold", net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40, direction="sell", net=-0.9),
    ]), cache)
    graph = KnowledgeGraph(scope="focus", nodes=["AAPL", "TSM"], edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)], built=1)
    monkeypatch.setattr(routes, "build_graph", lambda scope, settings, cache: graph)

    r = client.post("/api/graph/rebuild")
    assert r.status_code == 200 and r.json()["built"] == 1
    assert load_graph(cache, "focus") is not None
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_api_graph.py -q` → 404 / ImportError.

- [ ] **Step 3: Implement** — add imports to `routes.py`:

```python
from app.analysis.network import apply_network
from app.models.schemas import KnowledgeGraph
from app.network.service import build_graph
from app.network.store import load_graph, save_graph
```

Add routes (after `screen_sectors`, before `test_alert`):

```python
@router.get("/graph", response_model=KnowledgeGraph)
def get_graph(scope: str = "focus", cache: Cache = Depends(get_cache)) -> KnowledgeGraph:
    graph = load_graph(cache, scope)
    return graph if graph is not None else KnowledgeGraph(scope=scope)


@router.post("/graph/rebuild", response_model=KnowledgeGraph)
def rebuild_graph(
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> KnowledgeGraph:
    settings = store.load()
    graph = build_graph(None, settings, cache)
    save_graph(graph, cache)
    board = load_snapshot(cache, "all")
    if board is not None:
        save_snapshot(apply_network(board, graph, settings), cache)
    return graph
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_api_graph.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_graph.py
git commit -m "feat(backend): graph read + rebuild API endpoints"
```

---

## Task 11: Network influence in `screen/rescan`

**Files:**
- Modify: `backend/app/api/routes.py:160-174` (the `screen_rescan` handler)
- Test: `backend/tests/test_api_graph.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_rescan_applies_cached_graph(monkeypatch):
    cache = get_cache()
    # A cached graph exists; a fresh base scan should come back network-adjusted.
    from app.network.store import save_graph
    save_graph(KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
                  weight=1.0, confidence=1.0)]), cache)
    fresh = ScreenBoard(scope="all", items=[
        StockScore(ticker="AAPL", name="Apple", price=1, change_pct=0, score=50, direction="hold", net=0.0),
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40, direction="sell", net=-0.9),
    ])
    monkeypatch.setattr(routes, "run_scan", lambda scope, settings, cache: fresh)

    r = client.post("/api/screen/rescan")
    assert r.status_code == 200
    aapl = next(i for i in load_snapshot(cache, "all").items if i.ticker == "AAPL")
    assert aapl.network is not None  # propagation applied on rescan, no LLM
```

- [ ] **Step 2: Run it — expect failure** — `... -m pytest tests/test_api_graph.py::test_rescan_applies_cached_graph -q` → AssertionError (`network is None`).

- [ ] **Step 3: Implement** — replace the body of `screen_rescan`:

```python
@router.post("/screen/rescan", response_model=ScreenBoard)
def screen_rescan(
    sector: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    board = run_scan(sector, settings, cache)
    graph = load_graph(cache, "focus")
    if sector:
        full = load_snapshot(cache, "all")
        merged = merge_sector(full, board) if full else board
        if graph is not None:
            merged = apply_network(merged, graph, settings)
        save_snapshot(merged, cache)
    else:
        to_save = apply_network(board, graph, settings) if graph is not None else board
        save_snapshot(to_save, cache)
    return board
```

- [ ] **Step 4: Run it — expect pass** — `... -m pytest tests/test_api_graph.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_graph.py
git commit -m "feat(backend): apply cached network signal on rescan"
```

---

## Task 12: Deep-dive integration (analysis_service + analyzer)

**Files:**
- Modify: `backend/app/services/analysis_service.py` (after `get_stock_data`, ~line 35)
- Modify: `backend/app/analysis/analyzer.py` (add `_format_network`, prompt section, copy onto result)
- Test: `backend/tests/test_analyzer.py` (append) and `backend/tests/test_analysis_service.py` (append)

- [ ] **Step 1: Write the failing tests**

In `test_analyzer.py` (append):

```python
def test_format_network_and_result_carries_it():
    from app.analysis.analyzer import _format_network, build_user_prompt
    from app.models.schemas import NetworkInfluence, NetworkSignal
    from tests.test_screener_service import _stock

    stock = _stock("AAPL")
    stock.network = NetworkSignal(ticker="AAPL", intensity=0.5, signed=-0.4, influences=[
        NetworkInfluence(neighbour="TSM", name="Taiwan Semi", type="supplier",
                         edge_sentiment="negative", neighbour_direction="sell",
                         signed=-0.4, reason="supplier TSM (bearish)")], reasons=["supplier TSM (bearish)"])
    assert "TSM" in _format_network(stock.network)
    assert "NETWORK" in build_user_prompt(stock).upper()
```

In `test_analysis_service.py` (append) — verify enrichment from a cached graph (mirror the file's existing stub style; reference `as svc`):

```python
def test_run_analysis_enriches_network(tmp_path, monkeypatch):
    import app.services.analysis_service as svc
    from app.config.cache import Cache
    from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore
    from app.network.store import save_graph
    from app.screener.store import save_snapshot
    from tests.test_screener_service import _stock

    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="TSM", name="Taiwan Semi", price=1, change_pct=0, score=40,
                   direction="sell", net=-0.9)]), cache)
    save_graph(KnowledgeGraph(scope="focus", edges=[
        GraphEdge(source="AAPL", target="TSM", type="supplier", sentiment="negative",
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
    assert captured["network"] is not None and captured["network"].influences[0].neighbour == "TSM"
```

- [ ] **Step 2: Run them — expect failure** — `... -m pytest tests/test_analyzer.py tests/test_analysis_service.py -q` → ImportError/AssertionError.

- [ ] **Step 3a: Implement analyzer changes** (`backend/app/analysis/analyzer.py`)

Add import: `from app.models.schemas import ... NetworkSignal` (extend the existing import line). Add the formatter:

```python
def _format_network(net: "NetworkSignal | None") -> str:
    if net is None or not net.influences:
        return "- (no company-network signal)"
    lines = []
    for i in net.influences[:6]:
        lean = "bullish" if i.signed > 0 else "bearish" if i.signed < 0 else "neutral"
        lines.append(
            f"- {i.type} {i.neighbour} ({i.name}): neighbour is {i.neighbour_direction}, "
            f"news {i.edge_sentiment} -> {lean} for {net.ticker}"
        )
    return "\n".join(lines)
```

In `build_user_prompt`, add a section after the TRUMP MENTIONS block (before `{_JSON_SCHEMA_HINT}`):

```python
COMPANY NETWORK (relationships inferred from news; one hop):
{_format_network(stock.network)}

Weigh COMPANY NETWORK as a stock-specific factor like news, but treat it as noisy and
low-certainty: it must not override strong technical or fundamental evidence, and you must NOT
create dated buy/sell signals from it (it informs the current recommendation only).
```

In `analyze`'s `_finalize`, copy it onto the result (next to `result.market_mood = stock.market_mood`):

```python
        result.market_mood = stock.market_mood
        result.network = stock.network
```

- [ ] **Step 3b: Implement analysis_service enrichment** (`backend/app/services/analysis_service.py`)

Add imports:

```python
from app.analysis.network import compute_network_signal
from app.network.store import load_graph
from app.screener.store import load_snapshot
```

After `stock = get_stock_data(...)` and `provider = build_provider(settings)`, before the `ts = settings.truth_signal` block, insert:

```python
    ncfg = settings.network
    if ncfg.enabled:
        graph = load_graph(cache, "focus")
        if graph is not None and graph.edges:
            board = load_snapshot(cache, "all")
            base_index = {s.ticker: s for s in (board.items if board else [])}
            edges = [e for e in graph.edges if e.source == ticker]
            if edges:
                stock.network = compute_network_signal(ticker, edges, base_index, ncfg)
```

- [ ] **Step 4: Run them — expect pass** — `... -m pytest tests/test_analyzer.py tests/test_analysis_service.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/analyzer.py backend/app/services/analysis_service.py backend/tests/test_analyzer.py backend/tests/test_analysis_service.py
git commit -m "feat(backend): surface network influence in the deep-dive analysis"
```

---

## Task 13: Frontend types

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/pages/Dashboard.test.tsx` (add `network` to the `SETTINGS` fixture)

- [ ] **Step 1: Add types to `frontend/src/types.ts`**

```ts
export type RelationType = 'supplier' | 'customer' | 'partner' | 'competitor' | 'owner' | 'subsidiary';
export type EdgeSentiment = 'positive' | 'negative' | 'neutral';
export interface NetworkInfluence {
  neighbour: string;
  name: string;
  type: RelationType;
  edge_sentiment: EdgeSentiment;
  neighbour_direction: string;
  signed: number;
  reason: string;
}
export interface NetworkSignal {
  ticker: string;
  intensity: number;
  signed: number;
  influences: NetworkInfluence[];
  reasons: string[];
}
export interface GraphEdge {
  source: string; target: string; type: RelationType; sentiment: EdgeSentiment;
  weight: number; confidence: number; evidence: string; url: string; as_of: string;
}
export interface KnowledgeGraph {
  as_of: string; scope: string; nodes: string[]; edges: GraphEdge[]; built: number; skipped: number;
}
export interface NetworkConfig {
  enabled: boolean; focus_top_n: number; max_edges_per_company: number;
  min_confidence: number; weight: number; alpha_event: number; beta_state: number;
}
```

- [ ] **Step 2: Extend existing interfaces** — add to `StockScore`: `net: number;` and `network?: NetworkSignal | null;`. Add to `StockData`: `network?: NetworkSignal | null;`. Add to `AnalysisResult`: `network?: NetworkSignal | null;`. Add to `Settings`: `network: NetworkConfig;`.

- [ ] **Step 3: Fix the test fixture** — in `Dashboard.test.tsx`, add to the `SETTINGS` object:

```ts
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4 },
```

- [ ] **Step 4: Typecheck/build** — Run (from `frontend/`): `npm run build` → Expected: succeeds (no TS errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/pages/Dashboard.test.tsx
git commit -m "feat(frontend): types for knowledge graph and network signal"
```

---

## Task 14: Frontend — board 🔗 network badge

**Files:**
- Modify: `frontend/src/components/DiscoverBoard.tsx`
- Test: `frontend/src/components/DiscoverBoard.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/DiscoverBoard.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DiscoverBoard } from './DiscoverBoard';
import type { StockScore } from '../types';

function row(extra: Partial<StockScore>): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0,
    score: 50, direction: 'hold', net: 0, reasons: ['RSI 50'], components: {}, as_of: 't',
    ...extra,
  };
}

it('shows a network badge only when a network signal is present', () => {
  const withNet = row({
    network: { ticker: 'AAPL', intensity: 0.5, signed: -0.3,
      influences: [], reasons: ['supplier TSM (bearish)'] },
  });
  render(<MemoryRouter><DiscoverBoard items={[withNet]} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.getByTitle(/company-network influence/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run it — expect failure** — Run (from `frontend/`): `npx vitest run src/components/DiscoverBoard.test.tsx` → FAIL (no badge).

- [ ] **Step 3: Implement** — in `DiscoverBoard.tsx`, change the "Why" cell to render the badge when `s.network` is present:

```tsx
              <td>
                <div className="reasons">
                  {s.network && s.network.reasons.length > 0 && (
                    <span className="reason-chip net" title="company-network influence">🔗</span>
                  )}
                  {s.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
                </div>
              </td>
```

- [ ] **Step 4: Run it — expect pass** — `npx vitest run src/components/DiscoverBoard.test.tsx` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DiscoverBoard.tsx frontend/src/components/DiscoverBoard.test.tsx
git commit -m "feat(frontend): network badge on the Discover board"
```

---

## Task 15: Frontend — deep-dive Network influence panel

**Files:**
- Create: `frontend/src/components/NetworkPanel.tsx`
- Modify: `frontend/src/components/ReasoningPanel.tsx`
- Test: `frontend/src/components/NetworkPanel.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/NetworkPanel.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NetworkPanel } from './NetworkPanel';
import type { NetworkSignal } from '../types';

const NET: NetworkSignal = {
  ticker: 'AAPL', intensity: 0.5, signed: -0.4,
  influences: [{ neighbour: 'TSM', name: 'Taiwan Semi', type: 'supplier',
    edge_sentiment: 'negative', neighbour_direction: 'sell', signed: -0.4, reason: 'supplier TSM (bearish)' }],
  reasons: ['supplier TSM (bearish)'],
};

it('renders nothing without a signal', () => {
  const { container } = render(<NetworkPanel network={null} />);
  expect(container).toBeEmptyDOMElement();
});

it('lists neighbour influences', () => {
  render(<NetworkPanel network={NET} />);
  expect(screen.getByText(/Network influence/i)).toBeInTheDocument();
  expect(screen.getByText(/TSM/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run it — expect failure** — `npx vitest run src/components/NetworkPanel.test.tsx` → FAIL (module missing).

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/NetworkPanel.tsx
import type { NetworkSignal } from '../types';

export function NetworkPanel({ network }: { network?: NetworkSignal | null }) {
  if (!network || network.influences.length === 0) return null;
  return (
    <>
      <h4>Network influence 🔗</h4>
      <ul className="factor-list">
        {network.influences.map((inf, i) => {
          const lean = inf.signed > 0 ? 'bullish' : inf.signed < 0 ? 'bearish' : 'neutral';
          return (
            <li key={i}>
              <b>{inf.type} {inf.neighbour}</b>{inf.name ? ` (${inf.name})` : ''} — neighbour {inf.neighbour_direction},
              {' '}news {inf.edge_sentiment} → <span className={`badge ${lean === 'bullish' ? 'buy' : lean === 'bearish' ? 'sell' : 'hold'}`}>{lean}</span>
            </li>
          );
        })}
      </ul>
    </>
  );
}
```

Wire into `ReasoningPanel.tsx`: add `import { NetworkPanel } from './NetworkPanel';` and render after the market-mood note:

```tsx
      {result.market_mood && result.market_mood.post_count > 0 && (
        /* ...existing mood note... */
      )}

      <NetworkPanel network={result.network} />
```

- [ ] **Step 4: Run it — expect pass** — `npx vitest run src/components/NetworkPanel.test.tsx` → PASS.

- [ ] **Step 5: Full suites green** — Backend: from `backend/`, `.venv/Scripts/python.exe -m pytest -q` (expect all green). Frontend: from `frontend/`, `npm run build` then `npx vitest run` (expect all green).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/NetworkPanel.tsx frontend/src/components/NetworkPanel.test.tsx frontend/src/components/ReasoningPanel.tsx
git commit -m "feat(frontend): network influence panel in the deep-dive"
```

---

## Self-review notes (author check against the spec)

- **Spec coverage:** schemas (T1) · `StockScore.net` (T2) · sign rules + hybrid blend (T3) · re-blend/cap/no-feedback (T4) · `TickerResolver` closed vocab (T5) · extraction + cache + degrade + min_conf + max_edges (T6) · graph store (T7) · `build_graph` focus set (T8) · runner + CLI + bake-in (T9) · `GET`/`POST /api/graph` (T10) · rescan applies network (T11) · deep-dive enrichment + analyzer section + `AnalysisResult.network` (T12) · FE types (T13) · board badge (T14) · deep-dive panel (T15). **Phase B (visual graph page) is intentionally not here.**
- **Type consistency:** `compute_network_signal(ticker, edges, base_index, cfg)` and `apply_network(board, graph, settings)` are called with these exact signatures in T9/T11/T12 and the routes. `load_graph(cache, scope)` / `save_graph(graph, cache)` consistent across T7–T12. `extract_relationships(stock, resolver, provider, model, provider_name, cache, cfg, *, now)` consistent T6/T8.
- **Deferred to Phase B:** graph page, nav, rebuild button UI, `api.getGraph`/`rebuildGraph` client methods, edge-type/sector filters, `react-force-graph-2d` dependency.
- **Config UI:** `NetworkConfig` ships with defaults and is editable via `PUT /api/settings`; a dedicated Settings → Network form is optional and not required for Phase A (consistent with how `ScreenerConfig` shipped without a tuning UI).

## Scheduling note (ops)

Schedule `python -m app.network` to run **after** `python -m app.screener` (post-close) so it bakes onto the fresh base board. The interactive Rescan re-applies network from the cached graph, so only the cron ordering needs care. Document this alongside the existing screener schedule entry.
