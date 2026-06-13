# Portfolio Module + Discover Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fast, focused **Portfolio** module (scan/score only watchlist + active-ontology companies) that becomes the primary scoring source via base-index precedence, plus Discover quality-of-life features (exchange / S&P-membership columns, custom-company add with auto-fetch, search filter, button tooltips).

**Architecture:** One backend function `portfolio_universe(settings, cache) = watchlist ∪ active-ontology tickers` feeds a new scan scope `"portfolio"` (cached at `screen_snapshot:portfolio`), a base-index precedence helper (portfolio overlaid on the Discover `all` board), and the Evaluation runs. A new `/portfolio` page and the existing Discover page share one refactored `ScoreBoard` component. Discover stays the broad S&P explorer + custom-company search + fallback.

**Tech Stack:** Backend — FastAPI, Pydantic v2, SQLite KV cache, pytest. Frontend — React + TypeScript, TanStack Query, react-router, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-06-13-portfolio-module-and-discover-enhancements-design.md`

**Conventions (from the repo):**
- Run backend tests from `backend/` with the venv: `cd backend; .venv\Scripts\python -m pytest <path> -q`.
- Run frontend tests from `frontend/`: `npm test -- <path>` (Vitest, `run` mode is the default in CI; use `npm test -- --run <path>` to avoid watch mode).
- Dev servers run with `--reload`/HMR — edits go live immediately.
- Commit style: `feat:` / `fix:` / `refactor:` / `test:`. No Claude co-author trailer.

---

## File Structure

**Backend (modify):**
- `app/models/schemas.py` — `StockScore` +`exchange`/`in_sp500`; `UniverseEntry` +`exchange`; `StockData` +`exchange`/`sector`.
- `app/data/market.py` — `friendly_exchange(info)`; `get_stock_data`'s info source now also yields exchange/sector.
- `app/services/stock_service.py` — populate `StockData.exchange`/`sector`.
- `app/data/universe.py` — `is_sp500_member`; Phase 3 custom store (`list_custom`/`add_custom`/`delete_custom`/`resolve_custom_entry`).
- `app/screener/service.py` — `portfolio_universe`; `_resolve_entries` (scope→entries incl. `"portfolio"` and Phase-3 custom merge); scan populates exchange/in_sp500/sector; `score_one` uses `combined_base_index`.
- `app/screener/store.py` — `combined_base_index(cache)`.
- `app/analysis/network.py` — `apply_network(..., base_override=None)`.
- `app/api/routes.py` — `/screen` scope param; `_persist_rescan` portfolio branch; rescan stream scope; `GET /portfolio/tickers`; Phase 2 repoint of watchlist stream; Phase 3 custom endpoints.
- `app/evaluation/signals.py` — Phase 2: `snapshot_watchlist` iterates `portfolio_universe`.

**Frontend (create/modify):**
- `src/types.ts` — `StockScore` +`exchange`/`in_sp500`; `StockData` +`exchange`/`sector`.
- `src/api/client.ts` — `getScreen` scope; `streamRescan` scope; Phase 3 custom-universe calls.
- `src/hooks/queries.ts` — `useScreen` scope; `usePortfolioTickers`; Phase 3 custom hooks.
- `src/hooks/useRescanRun.ts` — `start` takes `scope`.
- `src/state/watchlistRunState.tsx` — `rescanAndSnapshot(scope?)` plumbing.
- `src/components/ScoreBoard.tsx` — **create** (refactor of `DiscoverBoard`): exchange/S&P columns, search filter, tooltips, optional `onRemove`.
- `src/components/DiscoverBoard.tsx` + `DiscoverBoard.test.tsx` — **delete** (replaced by `ScoreBoard`).
- `src/pages/Portfolio.tsx` — **create**.
- `src/pages/Discover.tsx` — use `ScoreBoard`; toolbar tooltips; Phase 3 add-company form.
- `src/App.tsx` — `/portfolio` route + nav.
- `src/components/EvaluationCommandBar.tsx` — Phase 2 labels + portfolio rescan.
- `src/pages/Graph.tsx` — Phase 2 board-colour precedence.
- `src/components/AddCompanyForm.tsx` — **create** (Phase 3).

---

# PHASE 1 — Portfolio module + base-index precedence

## Task 1: Schema fields for exchange / membership

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_schemas.py`:

```python
from app.models.schemas import StockData, StockScore, UniverseEntry


def test_stockscore_exchange_and_membership_default():
    s = StockScore(ticker="X", name="X", price=1.0, change_pct=0.0, score=1.0, direction="hold")
    assert s.exchange == "" and s.in_sp500 is True  # defaults keep old cached boards valid


def test_universe_entry_optional_exchange():
    assert UniverseEntry(ticker="X", name="X", sector="Tech").exchange == ""


def test_stockdata_exchange_and_sector_default():
    d = StockData(
        ticker="X", company_name="X", as_of="t",
        price={"current": 1, "change": 0, "change_pct": 0},
        candles=[], fundamentals={}, indicators={},
    )
    assert d.exchange == "" and d.sector == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_schemas.py -q`
Expected: FAIL — `StockScore` has no `exchange`/`in_sp500`, etc.

- [ ] **Step 3: Implement**

In `backend/app/models/schemas.py`, `UniverseEntry`:

```python
class UniverseEntry(BaseModel):
    ticker: str
    name: str
    sector: str
    exchange: str = ""
```

In `StockData` add two fields (after `as_of`):

```python
class StockData(BaseModel):
    ticker: str
    company_name: str
    as_of: str
    exchange: str = ""
    sector: str = ""
    price: PriceSummary
    candles: list[Candle]
    ...
```

In `StockScore` add two fields (after `sector`):

```python
class StockScore(BaseModel):
    ticker: str
    name: str
    sector: str = ""
    exchange: str = ""
    in_sp500: bool = True
    price: float
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_schemas.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_schemas.py
git commit -m "feat: add exchange/in_sp500 to StockScore, exchange/sector to StockData"
```

---

## Task 2: Friendly exchange name + StockData population

**Files:**
- Modify: `backend/app/data/market.py`, `backend/app/services/stock_service.py`
- Test: `backend/tests/test_market.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_market.py`:

```python
from app.data.market import friendly_exchange


def test_friendly_exchange_maps_known_codes():
    assert friendly_exchange({"exchange": "NMS"}) == "NASDAQ"
    assert friendly_exchange({"exchange": "NYQ"}) == "NYSE"


def test_friendly_exchange_falls_back_to_full_name_then_code():
    assert friendly_exchange({"exchange": "XYZ", "fullExchangeName": "Some Exchange"}) == "Some Exchange"
    assert friendly_exchange({"exchange": "XYZ"}) == "XYZ"
    assert friendly_exchange({}) == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_market.py -q`
Expected: FAIL — `friendly_exchange` not defined.

- [ ] **Step 3: Implement**

In `backend/app/data/market.py`, add near `company_name`:

```python
_EXCHANGE_NAMES = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NaN": "",
    "NYQ": "NYSE", "PCX": "NYSE Arca", "ASE": "NYSE American", "BTS": "BATS",
}


def friendly_exchange(info: dict) -> str:
    """Human-readable exchange from yfinance `.info` — maps the common short codes, else
    falls back to `fullExchangeName`, else the raw code, else ''."""
    code = str(info.get("exchange") or "").strip()
    if code in _EXCHANGE_NAMES:
        return _EXCHANGE_NAMES[code]
    full = str(info.get("fullExchangeName") or "").strip()
    return full or code
```

In `backend/app/services/stock_service.py`, import and populate. Change the import:

```python
from app.data.market import (
    build_candles,
    build_fundamentals,
    build_price,
    company_name,
    fetch_history,
    fetch_info,
    friendly_exchange,
)
```

and the `StockData(...)` construction (add two fields):

```python
    data = StockData(
        ticker=ticker,
        company_name=name,
        as_of=datetime.now(timezone.utc).isoformat(),
        exchange=friendly_exchange(info),
        sector=str(info.get("sector") or ""),
        price=build_price(df),
        candles=build_candles(df),
        fundamentals=build_fundamentals(info),
        indicators=compute_indicators(df, params),
        news=get_news(ticker, name, limit=10),
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_market.py tests/test_stock_service.py -q`
Expected: PASS (existing stock_service tests still pass — new fields default).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/market.py backend/app/services/stock_service.py backend/tests/test_market.py
git commit -m "feat: friendly exchange name + populate StockData exchange/sector"
```

---

## Task 3: `is_sp500_member`

**Files:**
- Modify: `backend/app/data/universe.py`
- Test: `backend/tests/test_universe.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_universe.py`:

```python
from app.data.universe import is_sp500_member


def test_is_sp500_member_checks_committed_list():
    assert is_sp500_member("AAPL") is True
    assert is_sp500_member("aapl ") is True      # normalized
    assert is_sp500_member("NOTREAL") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_universe.py::test_is_sp500_member_checks_committed_list -q`
Expected: FAIL — `is_sp500_member` not defined.

- [ ] **Step 3: Implement**

In `backend/app/data/universe.py`, add after `list_sectors`:

```python
@lru_cache
def _sp500_tickers() -> frozenset[str]:
    return frozenset(e.ticker for e in _all_entries())


def is_sp500_member(ticker: str) -> bool:
    """True iff the ticker is in the committed S&P 500 list (never includes custom companies)."""
    return ticker.upper().strip() in _sp500_tickers()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_universe.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/universe.py backend/tests/test_universe.py
git commit -m "feat: is_sp500_member committed-list membership check"
```

---

## Task 4: `portfolio_universe`

**Files:**
- Modify: `backend/app/screener/service.py`
- Test: `backend/tests/test_screener_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_screener_service.py`:

```python
from app.models.schemas import KnowledgeGraph


def test_portfolio_universe_unions_watchlist_and_ontology_tickers(monkeypatch):
    s = Settings()
    s.watchlist = ["AAPL", "msft "]
    monkeypatch.setattr(service, "active_graph", lambda cache: KnowledgeGraph(
        nodes=["MSFT", "NVDA", "ext:openai", "man:concept"]))
    out = service.portfolio_universe(s, cache=None)
    # watchlist first (deduped, upper-cased), then ontology TICKER nodes (ext:/man: skipped)
    assert out == ["AAPL", "MSFT", "NVDA"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py::test_portfolio_universe_unions_watchlist_and_ontology_tickers -q`
Expected: FAIL — `portfolio_universe` not defined.

- [ ] **Step 3: Implement**

In `backend/app/screener/service.py`, add imports and the function. The module already imports `active_graph` and `load_universe`; add `UniverseEntry` and `is_sp500_member`:

```python
from app.data.universe import is_sp500_member, load_universe
from app.models.schemas import ScreenBoard, Settings, StockScore, UniverseEntry
```

```python
def _is_ticker_node(node: str) -> bool:
    """Native ontology nodes are bare tickers; imported/manual nodes carry an `ext:`/`man:` prefix."""
    return ":" not in node


def portfolio_universe(settings: Settings, cache: Cache) -> list[str]:
    """The focused universe = watchlist ∪ active-ontology ticker nodes (order-preserving, deduped,
    upper-cased). Empty when the watchlist is empty and no ontology is active."""
    order: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        t = raw.upper().strip()
        if t and t not in seen:
            seen.add(t)
            order.append(t)

    for t in settings.watchlist:
        add(t)
    for node in active_graph(cache).nodes:
        if _is_ticker_node(node):
            add(node)
    return order
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/service.py backend/tests/test_screener_service.py
git commit -m "feat: portfolio_universe (watchlist + active-ontology tickers)"
```

---

## Task 5: Scope resolution + scan populates exchange/in_sp500/sector

**Files:**
- Modify: `backend/app/screener/service.py`
- Test: `backend/tests/test_screener_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_screener_service.py`:

```python
def test_scan_portfolio_scope_synthesizes_entries_and_tags(monkeypatch):
    s = Settings()
    s.watchlist = ["AAPL", "PRIV"]   # PRIV is NOT in sp500.json
    monkeypatch.setattr(service, "active_graph", lambda cache: KnowledgeGraph(nodes=[]))

    def fake_get(ticker, *a, **k):
        st = _stock(ticker)
        return st.model_copy(update={"exchange": "NASDAQ", "sector": "Tech"})

    monkeypatch.setattr(service, "get_stock_data", fake_get)
    board = service.run_scan("portfolio", s, Cache(str(__import__("tempfile").mkdtemp() + "/c.db")))

    assert board.scope == "portfolio"
    by = {i.ticker: i for i in board.items}
    assert by["AAPL"].in_sp500 is True and by["PRIV"].in_sp500 is False
    assert by["PRIV"].exchange == "NASDAQ"           # from fetched StockData
    assert by["PRIV"].sector == "Tech"               # synth entry had no sector -> fall back to stock
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py::test_scan_portfolio_scope_synthesizes_entries_and_tags -q`
Expected: FAIL — `"portfolio"` scope resolves via `load_universe("portfolio")` → empty; no exchange/in_sp500 tagging.

- [ ] **Step 3: Implement**

In `backend/app/screener/service.py`, add the resolver and use it + tag rows. Replace the top of `iter_scan`:

```python
def _resolve_entries(scope: str | None, settings: Settings, cache: Cache) -> list[UniverseEntry]:
    """Map a scan scope to its universe entries. `"portfolio"` synthesizes an entry per
    portfolio ticker (name/sector from the universe when known, else filled live during the
    scan); a sector name / None defers to load_universe. Custom companies are merged in by a
    later phase."""
    if scope == "portfolio":
        known = {e.ticker: e for e in load_universe()}
        return [known.get(t, UniverseEntry(ticker=t, name=t, sector=""))
                for t in portfolio_universe(settings, cache)]
    return load_universe(scope)
```

In `iter_scan`, change `entries = load_universe(scope)` to:

```python
    entries = _resolve_entries(scope, settings, cache)
```

and inside the `try` block, after `score.sector = entry.sector`, replace that line with:

```python
            score.sector = entry.sector or stock.sector
            score.exchange = stock.exchange
            score.in_sp500 = is_sp500_member(entry.ticker)
            items.append(score)
```

(The existing `items.append(score)` line is replaced by the block above.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py -q`
Expected: PASS (existing `test_run_scan_*` still pass — sector path unchanged, new fields default).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/service.py backend/tests/test_screener_service.py
git commit -m "feat: portfolio scan scope + exchange/in_sp500/sector tagging"
```

---

## Task 6: `combined_base_index`

**Files:**
- Modify: `backend/app/screener/store.py`
- Test: `backend/tests/test_screener_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_screener_service.py`:

```python
def test_combined_base_index_portfolio_overrides_all(tmp_path):
    from app.screener.store import combined_base_index
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="AAA", name="A", price=1, change_pct=0, score=10, direction="hold"),
        StockScore(ticker="BBB", name="B", price=1, change_pct=0, score=20, direction="hold"),
    ]), cache)
    save_snapshot(ScreenBoard(scope="portfolio", items=[
        StockScore(ticker="BBB", name="B", price=1, change_pct=0, score=99, direction="buy"),
    ]), cache)
    idx = combined_base_index(cache)
    assert set(idx) == {"AAA", "BBB"}
    assert idx["BBB"].score == 99   # portfolio wins on conflict
    assert idx["AAA"].score == 10   # all-only ticker retained
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py::test_combined_base_index_portfolio_overrides_all -q`
Expected: FAIL — `combined_base_index` not defined.

- [ ] **Step 3: Implement**

In `backend/app/screener/store.py`, add (update the `StockScore` import too):

```python
from app.models.schemas import ScreenBoard, StockScore
```

```python
def combined_base_index(cache: Cache) -> dict[str, StockScore]:
    """Ticker -> base StockScore, the `all` board overlaid by the `portfolio` board (portfolio
    wins). The neighbour-state source for single-ticker scoring: prefer the focused portfolio
    data, fall back to the broad Discover scan."""
    out: dict[str, StockScore] = {}
    all_board = load_snapshot(cache, "all")
    if all_board:
        out.update({s.ticker: s for s in all_board.items})
    pf = load_snapshot(cache, "portfolio")
    if pf:
        out.update({s.ticker: s for s in pf.items})
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/store.py backend/tests/test_screener_service.py
git commit -m "feat: combined_base_index (portfolio overlaid on all board)"
```

---

## Task 7: `apply_network` base override

**Files:**
- Modify: `backend/app/analysis/network.py`
- Test: `backend/tests/test_network.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_network.py`:

```python
from app.analysis.network import apply_network
from app.models.schemas import GraphEdge, KnowledgeGraph, ScreenBoard, Settings, StockScore


def _row(t, base_net=0.0, base_score=50.0):
    return StockScore(ticker=t, name=t, price=1, change_pct=0, score=base_score,
                      direction="hold", net=base_net, base_net=base_net, base_score=base_score)


def test_apply_network_uses_base_override_for_offboard_neighbour():
    # Board has only AAA; its partner ZZZ lives only in the override (the all-board fallback).
    board = ScreenBoard(scope="portfolio", items=[_row("AAA")])
    graph = KnowledgeGraph(nodes=["AAA", "ZZZ"], edges=[
        GraphEdge(source="AAA", target="ZZZ", type="partner", sentiment="positive",
                  weight=1.0, confidence=1.0)])
    override = {"ZZZ": _row("ZZZ", base_net=0.8)}
    blended = apply_network(board, graph, Settings(), base_override=override)
    aaa = blended.items[0]
    assert aaa.network is not None and aaa.network.signed > 0   # picked up ZZZ via override

    # Without the override the neighbour is unknown -> no state contribution.
    plain = apply_network(board, graph, Settings())
    assert plain.items[0].network is not None  # edge still scores the event term
    assert plain.items[0].network.signed <= aaa.network.signed
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_network.py::test_apply_network_uses_base_override_for_offboard_neighbour -q`
Expected: FAIL — `apply_network` has no `base_override` parameter.

- [ ] **Step 3: Implement**

In `backend/app/analysis/network.py`, change the `apply_network` signature and base-index build:

```python
def apply_network(board: ScreenBoard, graph: KnowledgeGraph, settings: Settings,
                  base_override: dict[str, StockScore] | None = None) -> ScreenBoard:
    """Fold a capped ``network`` family into each focus company's score/direction.

    Neighbour states come from the board's own rows; ``base_override`` supplies states for
    neighbours NOT on the board (the all-board fallback when blending the portfolio board).
    Board rows always win, preserving the one-hop / blend-from-base invariants.
    """
    ncfg = settings.network
    if not ncfg.enabled:
        return board

    base_index = dict(base_override or {})
    base_index.update({s.ticker: s for s in board.items})  # board rows win
    symmetric = set(ncfg.symmetric_types)
    ...
```

(Leave the rest of the function body unchanged.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_network.py -q`
Expected: PASS (existing `apply_network` tests still pass — `base_override` defaults to None).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/network.py backend/tests/test_network.py
git commit -m "feat: apply_network base_override for off-board neighbour states"
```

---

## Task 8: `score_one` uses `combined_base_index`

**Files:**
- Modify: `backend/app/screener/service.py`
- Test: `backend/tests/test_score_one.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_score_one.py`:

```python
def test_score_one_prefers_portfolio_neighbour_state(tmp_path, monkeypatch):
    # MSFT appears in BOTH boards with different base_net; the portfolio value must win.
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: _stock())
    save_ontology(OntologyVersion(name="t", saved_at="t",
                                  graph=KnowledgeGraph(scope="explore", nodes=["AAPL", "MSFT"], edges=[
                                      GraphEdge(source="AAPL", target="MSFT", type="partner",
                                                sentiment="neutral", weight=1.0, confidence=1.0)])),
                  cache)
    set_active_ontology("t", cache)
    save_snapshot(ScreenBoard(scope="all", items=[
        StockScore(ticker="MSFT", name="MS", price=1, change_pct=0, score=50, direction="hold",
                   net=-0.5, base_score=50, base_net=-0.5)]), cache)
    save_snapshot(ScreenBoard(scope="portfolio", items=[
        StockScore(ticker="MSFT", name="MS", price=1, change_pct=0, score=80, direction="buy",
                   net=0.7, base_score=80, base_net=0.7)]), cache)
    s = Settings()
    s.truth_signal.enabled = False
    out = score_one("AAPL", s, cache)
    # partner + positive neighbour state (portfolio base_net=+0.7) -> bullish tilt, not bearish.
    assert out.network is not None and out.network.signed > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_score_one.py::test_score_one_prefers_portfolio_neighbour_state -q`
Expected: FAIL — `score_one` still reads only the `all` snapshot (neighbour base_net = −0.5 → bearish).

- [ ] **Step 3: Implement**

In `backend/app/screener/service.py`, import `combined_base_index` and use it in `score_one`. Update the import from the store:

```python
from app.screener.store import combined_base_index, load_snapshot
```

In `score_one`, replace the network block's base-index lines:

```python
    if settings.network.enabled:
        try:
            graph = active_graph(cache)
            base_index = combined_base_index(cache)
            edges = incident_edges(ticker, graph.edges, set(settings.network.symmetric_types))
            if edges:
                sig = compute_network_signal(ticker, edges, base_index, settings.network)
                score = blend_network_into_score(score, sig, settings)
        except Exception:  # noqa: BLE001 — network is best-effort; base score on any failure
            pass
```

(Removes the old `board = load_snapshot(cache, "all")` / `base_index = {...}` lines. `load_snapshot` is still imported for other uses.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_score_one.py -q`
Expected: PASS (all existing score_one tests still pass — with only an `all` board, `combined_base_index` equals the old behaviour).

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/service.py backend/tests/test_score_one.py
git commit -m "feat: score_one neighbour states prefer portfolio board"
```

---

## Task 9: API — portfolio scope (screen, rescan stream, persist, tickers)

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_screen.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_screen.py` (self-contained — overrides `get_cache`/`get_settings_store` so it does not depend on the file's fixtures):

```python
def test_screen_portfolio_scope_reads_portfolio_snapshot(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config.cache import Cache
    from app.config.settings_store import SettingsStore
    from app.deps import get_cache, get_settings_store
    from app.models.schemas import ScreenBoard, StockScore
    from app.screener.store import save_snapshot
    cache = Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: SettingsStore(str(tmp_path / "s.db"))
    try:
        save_snapshot(ScreenBoard(scope="all", items=[
            StockScore(ticker="AAA", name="A", price=1, change_pct=0, score=10, direction="hold")]), cache)
        save_snapshot(ScreenBoard(scope="portfolio", items=[
            StockScore(ticker="BBB", name="B", price=1, change_pct=0, score=99, direction="buy")]), cache)
        r = TestClient(app).get("/api/screen?scope=portfolio")
        assert r.status_code == 200
        assert [i["ticker"] for i in r.json()["items"]] == ["BBB"]   # not the all board
    finally:
        app.dependency_overrides.clear()


def test_portfolio_tickers_endpoint(tmp_path, monkeypatch):
    import app.api.routes as routes
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config.cache import Cache
    from app.config.settings_store import SettingsStore
    from app.deps import get_cache, get_settings_store
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    app.dependency_overrides[get_settings_store] = lambda: SettingsStore(str(tmp_path / "s.db"))
    try:
        monkeypatch.setattr(routes, "portfolio_universe", lambda settings, cache: ["AAPL", "MSFT"])
        r = TestClient(app).get("/api/portfolio/tickers")
        assert r.status_code == 200 and r.json()["tickers"] == ["AAPL", "MSFT"]
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_api_screen.py -q`
Expected: FAIL — `scope` not handled; `/api/portfolio/tickers` 404.

- [ ] **Step 3: Implement**

In `backend/app/api/routes.py`:

Add `portfolio_universe` to the screener import:

```python
from app.screener.service import iter_scan, portfolio_universe, run_scan, score_one
```

Replace the `screen` endpoint signature/body to honour `scope`:

```python
@router.get("/screen", response_model=ScreenBoard)
def screen(
    scope: str | None = None,
    sector: str | None = None,
    direction: str | None = None,
    limit: int | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    snap_scope = "portfolio" if scope == "portfolio" else "all"
    board = load_snapshot(cache, snap_scope)
    if board is None:
        return ScreenBoard(scope=snap_scope)  # empty -> frontend prompts a first scan
    items = board.items
    if sector and scope != "portfolio":
        items = [i for i in items if i.sector == sector]
    if direction:
        items = [i for i in items if i.direction == direction]
    n = settings.screener.top_n if limit is None else limit
    shown = items if n <= 0 else items[:n]
    return board.model_copy(update={"items": shown})
```

Replace `_persist_rescan` to add the portfolio branch (the param is now a general `scope`):

```python
def _persist_rescan(board: ScreenBoard, scope: str | None, settings: Settings, cache: Cache) -> None:
    """Network-blend a fresh scan and save it under its scope. Portfolio scans blend against the
    all-board (base_override) so off-portfolio neighbours still contribute; sector scans merge
    into the full board; an unscoped scan replaces the full board."""
    graph = active_graph(cache)
    if scope == "portfolio":
        all_board = load_snapshot(cache, "all")
        override = {s.ticker: s for s in (all_board.items if all_board else [])}
        save_snapshot(apply_network(board, graph, settings, base_override=override), cache)
        return
    if scope:
        full = load_snapshot(cache, "all")
        merged = merge_sector(full, board) if full else board.model_copy(update={"scope": "all"})
        save_snapshot(apply_network(merged, graph, settings), cache)
    else:
        save_snapshot(apply_network(board, graph, settings), cache)
```

> `board.scope` is already `"portfolio"` (iter_scan sets `scope or "all"`), so `save_snapshot`
> keys it correctly.

Update the POST route and the stream to accept `scope`. The POST route:

```python
@router.post("/screen/rescan", response_model=ScreenBoard)
def screen_rescan(
    scope: str | None = None,
    sector: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    eff = scope or sector
    board = run_scan(eff, settings, cache)
    _persist_rescan(board, eff, settings, cache)
    return board
```

The stream route:

```python
@router.get("/screen/rescan/stream")
def screen_rescan_stream(
    scope: str | None = None,
    sector: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> StreamingResponse:
    settings = store.load()
    eff = scope or sector  # "portfolio", a sector name, or None

    def event_stream():
        try:
            for step in iter_scan(eff, settings, cache):
                if isinstance(step, ScreenBoard):
                    _persist_rescan(step, eff, settings, cache)
                    yield _sse(RescanEvent(type="done", scanned=step.scanned,
                                           skipped=step.skipped, total=step.scanned))
                else:
                    yield _sse(RescanEvent(type="tick", ticker=step.ticker, scanned=step.scanned,
                                           total=step.total, skipped=step.skipped))
        except Exception as exc:  # noqa: BLE001
            logger.warning("rescan stream failed: %s", exc)
            yield _sse(RescanEvent(type="error", message=str(exc)))

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
```

Add the tickers endpoint near the other `/screen` routes:

```python
@router.get("/portfolio/tickers")
def portfolio_tickers(
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> dict:
    """The portfolio universe = watchlist ∪ active-ontology tickers (drives the Portfolio page
    empty state and the Evaluation command bar's count)."""
    return {"tickers": portfolio_universe(store.load(), cache)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_api_screen.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_screen.py
git commit -m "feat: API portfolio scope (screen/rescan/persist) + portfolio tickers endpoint"
```

---

## Task 10: Frontend types

**Files:**
- Modify: `frontend/src/types.ts`

- [ ] **Step 1: Implement (type-only, no test)**

In `frontend/src/types.ts`, `StockScore`:

```typescript
export interface StockScore {
  ticker: string;
  name: string;
  sector: string;
  exchange: string;
  in_sp500: boolean;
  price: number;
  change_pct: number;
  score: number;
  net: number;
  direction: Recommendation;
  reasons: string[];
  components: Record<string, number>;
  as_of: string;
  network?: NetworkSignal | null;
}
```

`StockData` — add optional fields:

```typescript
export interface StockData {
  ticker: string;
  company_name: string;
  as_of: string;
  exchange?: string;
  sector?: string;
  price: PriceSummary;
  ...
}
```

- [ ] **Step 2: Verify it typechecks**

Run: `cd frontend; npx tsc --noEmit`
Expected: errors ONLY in files that build a `StockScore` literal without the new fields (the test factories — fixed in Task 12). Note them; proceed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types.ts
git commit -m "feat: StockScore exchange/in_sp500, StockData exchange/sector types"
```

---

## Task 11: Frontend API + hooks — scope plumbing

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`, `frontend/src/hooks/useRescanRun.ts`, `frontend/src/state/watchlistRunState.tsx`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/api/client.test.ts` (mirror its existing `fetch`-mock style):

```typescript
it('getScreen passes scope=portfolio', async () => {
  const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ as_of: '', scope: 'portfolio', scanned: 0, skipped: 0, items: [] }),
      { status: 200 }),
  );
  await api.getScreen(undefined, undefined, 0, 'portfolio');
  expect(spy).toHaveBeenCalledWith(expect.stringContaining('scope=portfolio'), expect.anything());
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/api/client.test.ts`
Expected: FAIL — `getScreen` takes only 3 args; no `scope` in the URL.

- [ ] **Step 3: Implement**

`frontend/src/api/client.ts` — `getScreen`:

```typescript
  getScreen: (sector?: string, direction?: string, limit?: number, scope?: string) => {
    const q = new URLSearchParams();
    if (scope) q.set('scope', scope);
    if (sector) q.set('sector', sector);
    if (direction) q.set('direction', direction);
    if (limit != null) q.set('limit', String(limit));
    const qs = q.toString();
    return http<ScreenBoard>(`/screen${qs ? `?${qs}` : ''}`);
  },
```

Add a portfolio-tickers call to the `api` object:

```typescript
  getPortfolioTickers: () => http<{ tickers: string[] }>('/portfolio/tickers'),
```

`streamRescan` — rename the first param to `scope` and send `?scope=`:

```typescript
export function streamRescan(
  scope: string | undefined,
  handlers: RescanStreamHandlers,
): () => void {
  const url = `${BASE}/screen/rescan/stream${scope ? `?scope=${encodeURIComponent(scope)}` : ''}`;
  const es = new EventSource(url);
  // ... rest unchanged
```

`frontend/src/hooks/queries.ts` — `useScreen`:

```typescript
export function useScreen(sector?: string, direction?: string, limit?: number, scope?: string) {
  return useQuery({
    queryKey: ['screen', sector ?? '', direction ?? '', limit ?? '', scope ?? ''],
    queryFn: () => api.getScreen(sector, direction, limit, scope),
  });
}

export function usePortfolioTickers() {
  return useQuery({ queryKey: ['portfolio', 'tickers'], queryFn: api.getPortfolioTickers });
}
```

`frontend/src/hooks/useRescanRun.ts` — rename `start`'s first param `sector` → `scope` (pass through to `streamRescan`):

```typescript
  const start = useCallback((scope?: string, onDone?: () => void) => {
    if (runningRef.current) return;
    runningRef.current = true;
    onDoneRef.current = onDone;
    closeRef.current?.();
    setState({ ...IDLE, phase: 'running' });
    closeRef.current = streamRescan(scope, {
      // ... body unchanged
```

`frontend/src/state/watchlistRunState.tsx` — `rescanAndSnapshot` already takes `sector?`; rename to `scope?` and pass through (it already forwards to `rescanStart(scope, …)`):

```typescript
  rescanAndSnapshot: (scope?: string) => void;
```
```typescript
  const rescanAndSnapshot = useCallback((scope?: string) => {
    runReset();
    snapshotReset();
    rescanStart(scope, () => snapshotMutate());
  }, [runReset, snapshotReset, rescanStart, snapshotMutate]);
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npm test -- --run src/api/client.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/hooks/useRescanRun.ts frontend/src/state/watchlistRunState.tsx frontend/src/api/client.test.ts
git commit -m "feat: frontend screen/rescan scope plumbing + portfolio tickers"
```

---

## Task 12: Shared `ScoreBoard` (columns + search + tooltips)

**Files:**
- Create: `frontend/src/components/ScoreBoard.tsx`, `frontend/src/components/ScoreBoard.test.tsx`
- Delete: `frontend/src/components/DiscoverBoard.tsx`, `frontend/src/components/DiscoverBoard.test.tsx`
- Modify: `frontend/src/pages/Discover.tsx` (import)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ScoreBoard.test.tsx`:

```typescript
import { expect, it } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ScoreBoard } from './ScoreBoard';
import type { StockScore } from '../types';

function row(extra: Partial<StockScore>): StockScore {
  return {
    ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
    price: 1, change_pct: 0, score: 50, direction: 'hold', net: 0,
    reasons: ['RSI 50'], components: {}, as_of: 't', ...extra,
  };
}

it('renders exchange and an S&P/Custom membership badge', () => {
  const items = [row({}), row({ ticker: 'PRIV', name: 'Private Co', in_sp500: false, exchange: 'NYSE' })];
  render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.getByText('NASDAQ')).toBeInTheDocument();
  expect(screen.getByTitle(/S&P 500 member/i)).toBeInTheDocument();
  expect(screen.getByTitle(/not in the s&p 500/i)).toBeInTheDocument();
});

it('filters rows by the search box (ticker or company name)', () => {
  const items = [row({}), row({ ticker: 'TSLA', name: 'Tesla' })];
  render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} /></MemoryRouter>);
  fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'tesla' } });
  expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
  expect(screen.getByText('TSLA')).toBeInTheDocument();
});

it('shows the network badge only when a network signal is present', () => {
  const withNet = row({ network: { ticker: 'AAPL', intensity: 0.5, signed: -0.3, influences: [], reasons: ['x'] } });
  render(<MemoryRouter><ScoreBoard items={[withNet]} onAdd={() => {}} /></MemoryRouter>);
  expect(screen.getByTitle(/company-network influence/i)).toBeInTheDocument();
});

it('renders a remove (×) button only for custom rows when onRemove is given', () => {
  const items = [row({}), row({ ticker: 'PRIV', in_sp500: false })];
  render(<MemoryRouter><ScoreBoard items={items} onAdd={() => {}} onRemove={() => {}} /></MemoryRouter>);
  expect(screen.getAllByTitle(/remove this custom company/i)).toHaveLength(1);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/components/ScoreBoard.test.tsx`
Expected: FAIL — `ScoreBoard` does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/ScoreBoard.tsx`:

```typescript
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { StockScore } from '../types';
import { ScoreBar } from './ScoreBar';

interface Props {
  items: StockScore[];
  onAdd: (t: string) => void;
  /** When given, custom rows (`in_sp500 === false`) get a × remove button. */
  onRemove?: (t: string) => void;
}

export function ScoreBoard({ items, onAdd, onRemove }: Props) {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const shown = needle
    ? items.filter((s) => s.ticker.toLowerCase().includes(needle) || s.name.toLowerCase().includes(needle))
    : items;

  return (
    <div className="board-wrap">
      <div className="board-search">
        <input
          type="search"
          placeholder="Search ticker or company…"
          title="Filter the rows below by ticker or company name"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      {shown.length === 0 ? (
        <p className="muted">No matches. Try a different search, sector, or hit Rescan.</p>
      ) : (
        <table className="board">
          <thead>
            <tr>
              <th>#</th><th>Ticker</th><th>Company</th><th>Exchange</th><th>Sector</th>
              <th>Price</th><th>S&amp;P</th><th>Score</th><th>Call</th><th>Why</th><th></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s, i) => (
              <tr key={s.ticker} className="board-row"
                  onClick={() => navigate(`/?ticker=${encodeURIComponent(s.ticker)}`)}>
                <td className="muted">{i + 1}</td>
                <td className="mono">{s.ticker}</td>
                <td>{s.name}</td>
                <td className="muted">{s.exchange || '—'}</td>
                <td className="muted">{s.sector || '—'}</td>
                <td className="mono">{s.price.toFixed(2)}</td>
                <td>
                  {s.in_sp500
                    ? <span className="badge sp" title="S&P 500 member">S&amp;P 500</span>
                    : <span className="badge custom" title="Not in the S&P 500 (custom company)">Custom</span>}
                </td>
                <td>
                  <div className="score-cell"><ScoreBar score={s.score} /><span>{s.score.toFixed(0)}</span></div>
                </td>
                <td><span className={`badge ${s.direction}`}>{s.direction.toUpperCase()}</span></td>
                <td>
                  <div className="reasons">
                    {s.network && s.network.reasons.length > 0 && (
                      <span className="reason-chip net" title="company-network influence">🔗</span>
                    )}
                    {s.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
                  </div>
                </td>
                <td>
                  <button className="secondary" title="Add this company to your watchlist"
                          onClick={(e) => { e.stopPropagation(); onAdd(s.ticker); }}>
                    + Watch
                  </button>
                  {onRemove && !s.in_sp500 && (
                    <button className="secondary" title="Remove this custom company"
                            onClick={(e) => { e.stopPropagation(); onRemove(s.ticker); }}>
                      ×
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

Delete the old component + test:

```bash
git rm frontend/src/components/DiscoverBoard.tsx frontend/src/components/DiscoverBoard.test.tsx
```

In `frontend/src/pages/Discover.tsx`, change the import and usage:

```typescript
import { ScoreBoard } from '../components/ScoreBoard';
```
```typescript
        {data && <ScoreBoard items={data.items} onAdd={watch.add} />}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npm test -- --run src/components/ScoreBoard.test.tsx; npx tsc --noEmit`
Expected: PASS; tsc clean (the old DiscoverBoard literal errors from Task 10 are gone).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ScoreBoard.tsx frontend/src/components/ScoreBoard.test.tsx frontend/src/pages/Discover.tsx
git commit -m "refactor: shared ScoreBoard (exchange/S&P columns, search, tooltips); drop DiscoverBoard"
```

---

## Task 13: Portfolio page + route + nav + Discover tooltips

**Files:**
- Create: `frontend/src/pages/Portfolio.tsx`, `frontend/src/pages/Portfolio.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/pages/Discover.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/Portfolio.test.tsx`:

```typescript
import { expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('../hooks/queries', () => ({
  useScreen: vi.fn(),
  usePortfolioTickers: vi.fn(),
  useWatchlist: () => ({ add: vi.fn(), remove: vi.fn(), list: [] }),
}));
vi.mock('../state/watchlistRunState', () => ({
  useWatchlistRunContext: () => ({
    rescan: { phase: 'idle', scanned: 0, total: 0, skipped: 0, summary: null, stopped: false, stop: vi.fn() },
    snapshot: { data: null },
    rescanAndSnapshot: vi.fn(),
  }),
}));
vi.mock('../components/MarketHint', () => ({ MarketHint: () => null }));

import { useScreen, usePortfolioTickers } from '../hooks/queries';
import Portfolio from './Portfolio';

function wrap(ui: ReactNode) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => vi.clearAllMocks());

it('prompts to build a portfolio when empty', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [], as_of: '' } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: [] } } as never);
  wrap(<Portfolio />);
  expect(screen.getByText(/add to your watchlist or activate an ontology/i)).toBeInTheDocument();
});

it('renders the board when the portfolio has scored rows', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
      price: 1, change_pct: 0, score: 80, direction: 'buy', net: 0.5, reasons: [], components: {}, as_of: 't' },
  ], as_of: '2026-06-13T00:00:00Z', scanned: 1 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['AAPL'] } } as never);
  wrap(<Portfolio />);
  expect(screen.getByText('AAPL')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/pages/Portfolio.test.tsx`
Expected: FAIL — `Portfolio` does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/pages/Portfolio.tsx`:

```typescript
import { ScoreBoard } from '../components/ScoreBoard';
import { MarketHint } from '../components/MarketHint';
import { usePortfolioTickers, useScreen, useWatchlist } from '../hooks/queries';
import { useWatchlistRunContext } from '../state/watchlistRunState';

export default function Portfolio() {
  const board = useScreen(undefined, undefined, 0, 'portfolio'); // uncapped, the focused set
  const tickers = usePortfolioTickers();
  const { rescan, snapshot, rescanAndSnapshot } = useWatchlistRunContext();
  const watch = useWatchlist();

  const data = board.data;
  const scanning = rescan.phase === 'running';
  const empty = (tickers.data?.tickers.length ?? 0) === 0;

  return (
    <>
      <div className="panel commandbar">
        <div className="board-controls">
          <span className="section-label">
            Portfolio — watchlist + active ontology
            {tickers.data ? ` (${tickers.data.tickers.length})` : ''}
          </span>
          <span className="spacer" />
          {data && (
            <span className="muted board-asof">
              {data.as_of ? `As of ${new Date(data.as_of).toLocaleString()}` : 'No scan yet'}
              {data.scanned ? ` · ${data.scanned} scanned` : ''}
            </span>
          )}
          <button
            disabled={scanning || empty}
            title="Re-score your portfolio (watchlist + active ontology) — fast, only these names — and record today's technical/network snapshot."
            onClick={() => rescanAndSnapshot('portfolio')}
          >
            {scanning
              ? rescan.total ? `Scanning… ${rescan.scanned}/${rescan.total}` : 'Scanning…'
              : 'Rescan portfolio'}
          </button>
          {scanning && <button title="Stop the scan — nothing is saved." onClick={rescan.stop}>Stop</button>}
        </div>
        <MarketHint />
      </div>

      {board.isLoading && <p className="muted">Loading portfolio…</p>}
      {scanning && (
        <p className="muted mono">
          ⏳ {rescan.scanned}/{rescan.total || '?'} scanned
          {rescan.ticker ? ` · fetching ${rescan.ticker}` : ''}
        </p>
      )}
      {snapshot.data && (
        <p className="muted">
          ✓ Recorded {snapshot.data.recorded} portfolio signal{snapshot.data.recorded === 1 ? '' : 's'} for evaluation.
        </p>
      )}
      {empty && (
        <p className="muted">
          Your portfolio is empty — add to your watchlist or activate an ontology, then hit <b>Rescan portfolio</b>.
        </p>
      )}

      <section className="panel">
        <div className="panel-head">
          <span className="section-label">Portfolio board — click a row to deep-dive</span>
        </div>
        {data && <ScoreBoard items={data.items} onAdd={watch.add} />}
      </section>
    </>
  );
}
```

In `frontend/src/App.tsx`, import + route + nav (eager, like Discover):

```typescript
import Portfolio from './pages/Portfolio';
```
```typescript
            <NavLink to="/" end className={navClass}>Dashboard</NavLink>
            <NavLink to="/portfolio" className={navClass}>Portfolio</NavLink>
            <NavLink to="/discover" className={navClass}>Discover</NavLink>
```
```typescript
            <Route path="/" element={<Dashboard />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/discover" element={<Discover />} />
```

In `frontend/src/pages/Discover.tsx`, add `title` tooltips to the toolbar buttons:

```typescript
          <button className="secondary"
                  title="Re-scrape the current S&P 500 constituents and replace the local list. Rescan afterward to rebuild the board."
                  onClick={() => refreshList.mutate()} disabled={refreshList.isPending}>
            {refreshList.isPending ? 'Updating…' : 'Update S&P 500 list'}
          </button>
          <button
            title="Re-score every company in scope (fetches fresh price data — minutes cold, fast once cached) and rebuild the board."
            onClick={() => rescanAndSnapshot(sector || undefined)} disabled={scanning}>
            {scanning
              ? rescan.total ? `Scanning… ${rescan.scanned}/${rescan.total}` : 'Scanning…'
              : sector ? `Rescan ${sector}` : 'Rescan all'}
          </button>
          {scanning && <button title="Stop the scan — nothing is saved; cached tickers make a redo fast." onClick={rescan.stop}>Stop</button>}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npm test -- --run src/pages/Portfolio.test.tsx; npx tsc --noEmit`
Expected: PASS; tsc clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Portfolio.tsx frontend/src/pages/Portfolio.test.tsx frontend/src/App.tsx frontend/src/pages/Discover.tsx
git commit -m "feat: Portfolio page + route/nav; Discover toolbar tooltips"
```

---

## Phase 1 verification

- [ ] Run full backend suite: `cd backend; .venv\Scripts\python -m pytest -q` — expect all green.
- [ ] Run full frontend suite: `cd frontend; npm test -- --run` — expect all green.
- [ ] Manual (preview): start the app, open `/portfolio`. With a watchlist set and an ontology active, click **Rescan portfolio**; confirm the board fills (Exchange + S&P columns, search filter work). Verify Discover still works and shows the new columns. Use coordinate-based `preview_click` to verify the Rescan button (per repo gotcha — `element.click()` bypasses hit-testing).

---

# PHASE 2 — Evaluation repoint + Graph colour precedence

## Task 14: `snapshot_watchlist` covers the portfolio

**Files:**
- Modify: `backend/app/evaluation/signals.py`
- Test: `backend/tests/test_evaluation_signals.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_evaluation_signals.py` (uses the file's `_stock`/`_score` helpers and the `signals` module already imported at the top):

```python
def test_snapshot_covers_portfolio_not_just_watchlist(tmp_path, monkeypatch):
    from app.evaluation.signals import snapshot_watchlist
    store = PredictionStore(str(tmp_path / "p.db"))
    cache = Cache(str(tmp_path / "c.db"))
    settings = Settings()
    settings.watchlist = ["AAPL"]
    # Ontology contributes NVDA -> the snapshot must include it, not just the watchlist.
    monkeypatch.setattr(signals, "portfolio_universe", lambda s, c: ["AAPL", "NVDA"])
    monkeypatch.setattr(signals, "get_stock_data", lambda t, p, ip, c: _stock(t))
    monkeypatch.setattr(signals, "score_one", lambda t, s, c: _score(t))
    out = snapshot_watchlist(settings, cache, store)
    assert out["recorded"] == 2
    assert store.get_prediction("NVDA", "2026-06-05", "technical") is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py::test_snapshot_covers_portfolio_not_just_watchlist -q`
Expected: FAIL — `snapshot_watchlist` iterates `settings.watchlist` (records 1) and `portfolio_universe` isn't imported.

- [ ] **Step 3: Implement**

In `backend/app/evaluation/signals.py`, import `portfolio_universe` and use it. Update the existing import:

```python
from app.screener.service import SCAN_PERIOD, portfolio_universe, score_one
```

In `snapshot_watchlist`, change the loop source and the docstring:

```python
def snapshot_watchlist(settings: Settings, cache: Cache, store: PredictionStore) -> dict:
    """Record today's technical/network calls for the whole PORTFOLIO (watchlist + active
    ontology). Per-ticker isolation: one bad ticker is skipped and reported, the rest record."""
    recorded, skipped = 0, []
    for raw in portfolio_universe(settings, cache):
        ticker = raw.upper().strip()
        ...
```

(The rest of the loop body is unchanged.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_evaluation_signals.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/signals.py backend/tests/test_evaluation_signals.py
git commit -m "feat: snapshot covers the portfolio (watchlist + ontology)"
```

---

## Task 15: Watchlist LLM stream covers the portfolio

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_watchlist_run.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_watchlist_run.py` (uses the file's `_client`, `_ready_settings`, `_stock_with_candles`, `_result`, `_events`, `FakeProvider` helpers and the imported `routes`):

```python
def test_watchlist_stream_uses_portfolio_universe(tmp_path, monkeypatch):
    client, settings_store, _, _ = _client(tmp_path)
    _ready_settings(settings_store, watchlist=["AAPL"])
    # Ontology adds NVDA -> the run set is the portfolio, not just the watchlist.
    monkeypatch.setattr(routes, "portfolio_universe", lambda settings, cache: ["AAPL", "NVDA"])
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "get_stock_data", lambda t, p, ip, c: _stock_with_candles(t))
    monkeypatch.setattr(routes, "run_analysis", lambda t, p, s, c, ps: _result(t))

    evs = _events(client.get("/api/analyze/watchlist/stream?mode=fast").text)
    assert evs[0][1]["tickers"] == ["AAPL", "NVDA"]   # the start frame lists the portfolio set
    done = [p["ticker"] for n, p in evs if n == "ticker" and p["status"] == "done"]
    assert done == ["AAPL", "NVDA"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_api_watchlist_run.py::test_watchlist_stream_uses_portfolio_universe -q`
Expected: FAIL — the stream iterates `settings.watchlist` (no NVDA).

- [ ] **Step 3: Implement**

In `backend/app/api/routes.py`, inside `analyze_watchlist_stream`, replace the tickers line:

```python
    tickers = [t.upper().strip() for t in portfolio_universe(settings, cache)]
```

(Update the route docstring's "every watchlist ticker" → "every portfolio ticker (watchlist + active ontology)".)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_api_watchlist_run.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_watchlist_run.py
git commit -m "feat: watchlist LLM stream covers the portfolio (watchlist + ontology)"
```

---

## Task 16: Evaluation command bar — portfolio labels + rescan

**Files:**
- Modify: `frontend/src/components/EvaluationCommandBar.tsx`
- Test: `frontend/src/components/EvaluationCommandBar.test.tsx`

- [ ] **Step 1: Write the failing test**

Update/add in `frontend/src/components/EvaluationCommandBar.test.tsx` (mirror its existing mock setup; add a `usePortfolioTickers` mock returning two tickers):

```typescript
it('labels the bar with the portfolio count and offers a portfolio rescan', () => {
  // ...existing mocks, plus:
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['AAPL', 'NVDA'] } } as never);
  renderBar(); // the file's render helper
  expect(screen.getByText(/portfolio \(2/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /rescan portfolio/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/components/EvaluationCommandBar.test.tsx`
Expected: FAIL — bar says "watchlist (N)" and "Full Discover rescan".

- [ ] **Step 3: Implement**

In `frontend/src/components/EvaluationCommandBar.tsx`:

Add the hook and derive the portfolio count:

```typescript
import { usePortfolioTickers, useSettings } from '../hooks/queries';
```
```typescript
  const portfolio = usePortfolioTickers();
  const count = portfolio.data?.tickers.length ?? 0;
```

Change the gate to use the portfolio count, the label, and the rescan button:

```typescript
  const disabled = busy || count === 0;
```
```typescript
        <span className="section-label">
          Run on your portfolio ({count} ticker{count === 1 ? '' : 's'}: watchlist + active ontology)
        </span>
```
```typescript
        <button
          disabled={disabled}
          title="Re-score your portfolio (watchlist + active ontology) — fast, only these names — then snapshot the technical/network calls."
          onClick={() => rescanAndSnapshot('portfolio')}
        >
          {scanning
            ? rescan.total ? `Scanning… ${rescan.scanned}/${rescan.total}` : 'Scanning…'
            : 'Rescan portfolio'}
        </button>
```

Update the empty-state hint:

```typescript
      {count === 0 && (
        <p className="muted">Your portfolio is empty — add to your watchlist (★ on the Dashboard) or activate an ontology.</p>
      )}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npm test -- --run src/components/EvaluationCommandBar.test.tsx; npx tsc --noEmit`
Expected: PASS; tsc clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EvaluationCommandBar.tsx frontend/src/components/EvaluationCommandBar.test.tsx
git commit -m "feat: Evaluation command bar runs on the portfolio (watchlist + ontology)"
```

---

## Task 17: Graph node colour precedence

**Files:**
- Modify: `frontend/src/pages/Graph.tsx`
- Test: `frontend/src/pages/Graph.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/Graph.test.tsx` a case proving a portfolio row overrides the all-board row for the same ticker (assert via whatever the page exposes — e.g. the merged items passed to `GraphCanvas`, or a colour/score the canvas mock records). Concretely, mock `useScreen` to return different data per scope:

```typescript
vi.mocked(useScreen).mockImplementation((_s, _d, _l, scope) =>
  (scope === 'portfolio'
    ? { data: { items: [{ ticker: 'AAPL', score: 90, direction: 'buy', in_sp500: true,
        name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', price: 1, change_pct: 0, net: 0.6,
        reasons: [], components: {}, as_of: 't' }] } }
    : { data: { items: [{ ticker: 'AAPL', score: 10, direction: 'sell', in_sp500: true,
        name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', price: 1, change_pct: 0, net: -0.6,
        reasons: [], components: {}, as_of: 't' }] } }) as never,
);
// Assert the GraphCanvas mock received the score-90 (portfolio) AAPL row, not score-10.
```

> Adapt the assertion to how `Graph.test.tsx` already mocks `GraphCanvas` and inspects props.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/pages/Graph.test.tsx`
Expected: FAIL — the page only reads the `all` board (score 10).

- [ ] **Step 3: Implement**

In `frontend/src/pages/Graph.tsx`, fetch both boards and merge (portfolio wins). Replace the single board line (around line 20):

```typescript
  const allBoard = useScreen(undefined, undefined, 0);
  const pfBoard = useScreen(undefined, undefined, 0, 'portfolio');
  const boardItems = useMemo(() => {
    const m = new Map((allBoard.data?.items ?? []).map((s) => [s.ticker, s]));
    for (const s of pfBoard.data?.items ?? []) m.set(s.ticker, s); // portfolio wins on conflict
    return [...m.values()];
  }, [allBoard.data, pfBoard.data]);
```

Then replace the three `board.data?.items ?? []` usages (≈ lines 197, 224, 300) with `boardItems`. Ensure `useMemo` is imported.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npm test -- --run src/pages/Graph.test.tsx; npx tsc --noEmit`
Expected: PASS; tsc clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Graph.tsx frontend/src/pages/Graph.test.tsx
git commit -m "feat: Graph node colours prefer the portfolio board, fall back to all"
```

---

## Phase 2 verification

- [ ] Backend + frontend full suites green.
- [ ] Manual: on Evaluation, the bar reads "Run on your portfolio (N: watchlist + active ontology)" and **Rescan portfolio** is fast. On Graph, a ticker that's in the portfolio takes its portfolio colour/score.

---

# PHASE 3 — Discover custom companies

## Task 18: Custom-universe store + merge into `load_universe`

**Files:**
- Modify: `backend/app/data/universe.py`
- Test: `backend/tests/test_universe.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_universe.py`:

```python
def test_custom_store_round_trip_and_merge(tmp_path, monkeypatch):
    from app.config.cache import Cache
    from app.data import universe
    from app.models.schemas import UniverseEntry
    cache = Cache(str(tmp_path / "c.db"))

    assert universe.list_custom(cache) == []
    e = UniverseEntry(ticker="PRIV", name="Private Co", sector="Tech", exchange="NYSE")
    universe.add_custom(e, cache)
    assert [c.ticker for c in universe.list_custom(cache)] == ["PRIV"]

    merged = {x.ticker for x in universe.load_universe(cache=cache)}
    assert "PRIV" in merged and "AAPL" in merged       # custom appended to committed S&P
    assert universe.is_sp500_member("PRIV") is False    # committed-only membership

    assert universe.delete_custom("PRIV", cache) is True
    assert universe.list_custom(cache) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_universe.py::test_custom_store_round_trip_and_merge -q`
Expected: FAIL — `list_custom`/`add_custom`/`delete_custom` not defined; `load_universe` takes no `cache`.

- [ ] **Step 3: Implement**

In `backend/app/data/universe.py`, add the custom store and a cache-aware `load_universe`. Add the `Cache` import and `json` is already imported:

```python
from app.config.cache import Cache

_CUSTOM_KEY = "custom_universe"
_CUSTOM_TTL_SECONDS = 3650 * 24 * 60 * 60  # ~10 years (effectively permanent), like ontologies


def list_custom(cache: Cache) -> list[UniverseEntry]:
    raw = cache.get(_CUSTOM_KEY)
    if not raw:
        return []
    try:
        return [UniverseEntry(**row) for row in json.loads(raw)]
    except Exception:  # noqa: BLE001 — corrupt entry -> none
        return []


def add_custom(entry: UniverseEntry, cache: Cache) -> UniverseEntry:
    """Persist a custom (non-S&P) company; idempotent on ticker (last write wins)."""
    rows = [c for c in list_custom(cache) if c.ticker != entry.ticker]
    rows.append(entry)
    cache.set(_CUSTOM_KEY, json.dumps([c.model_dump() for c in rows]), _CUSTOM_TTL_SECONDS)
    return entry


def delete_custom(ticker: str, cache: Cache) -> bool:
    t = ticker.upper().strip()
    rows = list_custom(cache)
    kept = [c for c in rows if c.ticker != t]
    if len(kept) == len(rows):
        return False
    cache.set(_CUSTOM_KEY, json.dumps([c.model_dump() for c in kept]), _CUSTOM_TTL_SECONDS)
    return True
```

Change `load_universe` to optionally merge custom companies (keep the default so S&P-only callers are unaffected):

```python
def load_universe(sector: str | None = None, cache: Cache | None = None) -> list[UniverseEntry]:
    entries = list(_all_entries())
    if cache is not None:
        seen = {e.ticker for e in entries}
        entries += [c for c in list_custom(cache) if c.ticker not in seen]
    if sector:
        return [e for e in entries if e.sector == sector]
    return entries
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_universe.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/universe.py backend/tests/test_universe.py
git commit -m "feat: custom-universe store + optional merge into load_universe"
```

---

## Task 19: Scan + Discover board include custom companies

**Files:**
- Modify: `backend/app/screener/service.py`
- Test: `backend/tests/test_screener_service.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_screener_service.py`:

```python
def test_scan_all_includes_custom_companies(tmp_path, monkeypatch):
    from app.data import universe
    cache = Cache(str(tmp_path / "c.db"))
    universe.add_custom(UniverseEntry(ticker="PRIV", name="Priv", sector="Tech", exchange="NYSE"), cache)

    # Tiny committed list + the custom merge, so the scan stays fast and deterministic.
    monkeypatch.setattr(
        service, "load_universe",
        lambda sector=None, cache=None: ([UniverseEntry(ticker="AAA", name="A", sector="Tech")]
                                         + (universe.list_custom(cache) if cache else [])))
    monkeypatch.setattr(service, "get_stock_data", lambda t, *a, **k: _stock(t))

    board = service.run_scan(None, Settings(), cache)
    tickers = {i.ticker for i in board.items}
    assert "PRIV" in tickers and "AAA" in tickers
    assert next(i for i in board.items if i.ticker == "PRIV").in_sp500 is False
```

(`UniverseEntry` is already imported at the top of `test_screener_service.py`.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py::test_scan_all_includes_custom_companies -q`
Expected: FAIL — `_resolve_entries` calls `load_universe(scope)` without the cache, so custom companies are not scanned.

- [ ] **Step 3: Implement**

In `backend/app/screener/service.py`, thread the cache into the non-portfolio path of `_resolve_entries`:

```python
def _resolve_entries(scope: str | None, settings: Settings, cache: Cache) -> list[UniverseEntry]:
    if scope == "portfolio":
        known = {e.ticker: e for e in load_universe(cache=cache)}
        return [known.get(t, UniverseEntry(ticker=t, name=t, sector=""))
                for t in portfolio_universe(settings, cache)]
    return load_universe(scope, cache=cache)   # merge custom companies into the broad scan
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_screener_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/screener/service.py backend/tests/test_screener_service.py
git commit -m "feat: custom companies scanned in the Discover (all) board"
```

---

## Task 20: `resolve_custom_entry` (auto-fetch)

**Files:**
- Modify: `backend/app/data/universe.py`
- Test: `backend/tests/test_universe.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_universe.py`:

```python
def test_resolve_custom_entry_autofetches(tmp_path, monkeypatch):
    from app.config.cache import Cache
    from app.data import universe
    from app.models.schemas import IndicatorParams, PriceSummary, StockData
    cache = Cache(str(tmp_path / "c.db"))

    def fake_stock(ticker, period, params, cache):
        return StockData(ticker=ticker, company_name="Private Co", as_of="t",
                         exchange="NYSE", sector="Tech",
                         price=PriceSummary(current=42.5, change=0, change_pct=0),
                         candles=[], fundamentals={}, indicators={})

    monkeypatch.setattr(universe, "get_stock_data", fake_stock)
    entry, price = universe.resolve_custom_entry("priv ", IndicatorParams(), cache)
    assert entry.ticker == "PRIV" and entry.name == "Private Co"
    assert entry.sector == "Tech" and entry.exchange == "NYSE" and price == 42.5


def test_resolve_custom_entry_rejects_unknown(tmp_path, monkeypatch):
    import pytest
    from app.config.cache import Cache
    from app.data import universe
    from app.models.schemas import IndicatorParams
    monkeypatch.setattr(universe, "get_stock_data",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("No price history")))
    with pytest.raises(ValueError):
        universe.resolve_custom_entry("NOPE", IndicatorParams(), Cache(str(tmp_path / "c.db")))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_universe.py::test_resolve_custom_entry_autofetches -q`
Expected: FAIL — `resolve_custom_entry` not defined.

- [ ] **Step 3: Implement**

In `backend/app/data/universe.py`, add (import `get_stock_data` lazily inside the function to avoid an import cycle — `stock_service` imports data modules):

```python
def resolve_custom_entry(ticker: str, params, cache: Cache) -> tuple[UniverseEntry, float]:
    """Auto-fill a custom company from market data. Raises ValueError when the ticker has no
    price history (the caller maps that to HTTP 422)."""
    from app.screener.service import SCAN_PERIOD
    from app.services.stock_service import get_stock_data
    t = ticker.upper().strip()
    stock = get_stock_data(t, SCAN_PERIOD, params, cache)  # validates; raises ValueError if unknown
    entry = UniverseEntry(ticker=t, name=stock.company_name, sector=stock.sector,
                          exchange=stock.exchange)
    return entry, stock.price.current
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_universe.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/universe.py backend/tests/test_universe.py
git commit -m "feat: resolve_custom_entry auto-fetches name/sector/exchange/price"
```

---

## Task 21: Custom-company API endpoints

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_universe.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_universe.py` (the file imports `routes` and `app`; these tests override `get_cache` and monkeypatch the resolver):

```python
def test_add_list_delete_custom_company(tmp_path, monkeypatch):
    from app.config.cache import Cache
    from app.deps import get_cache
    from app.models.schemas import UniverseEntry
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    try:
        monkeypatch.setattr(routes.universe, "resolve_custom_entry",
                            lambda ticker, params, cache: (
                                UniverseEntry(ticker="PRIV", name="Priv", sector="Tech", exchange="NYSE"), 42.5))
        client = TestClient(app)
        r = client.post("/api/universe/custom", json={"ticker": "priv"})
        assert r.status_code == 200
        assert r.json()["entry"]["ticker"] == "PRIV" and r.json()["price"] == 42.5
        assert any(e["ticker"] == "PRIV" for e in client.get("/api/universe/custom").json())
        assert client.delete("/api/universe/custom/PRIV").json()["deleted"] is True
        assert client.get("/api/universe/custom").json() == []
    finally:
        app.dependency_overrides.clear()


def test_add_custom_rejects_unknown(tmp_path, monkeypatch):
    from app.config.cache import Cache
    from app.deps import get_cache
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    try:
        monkeypatch.setattr(routes.universe, "resolve_custom_entry",
                            lambda *a, **k: (_ for _ in ()).throw(ValueError("No price history")))
        resp = TestClient(app).post("/api/universe/custom", json={"ticker": "NOPE"})
        assert resp.status_code == 422
        assert "No price history" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_api_universe.py -q`
Expected: FAIL — endpoints 404.

- [ ] **Step 3: Implement**

In `backend/app/api/routes.py`, add the routes (near `update_universe`). `universe` and `UniverseEntry` are already importable (`from app.data import universe`; add `UniverseEntry` to the schema import block):

```python
@router.get("/universe/custom", response_model=list[UniverseEntry])
def list_custom_companies(cache: Cache = Depends(get_cache)) -> list[UniverseEntry]:
    return universe.list_custom(cache)


@router.post("/universe/custom")
def add_custom_company(
    payload: dict,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> dict:
    ticker = str((payload or {}).get("ticker", "")).strip()
    if not ticker:
        raise HTTPException(status_code=422, detail="A ticker is required.")
    try:
        entry, price = universe.resolve_custom_entry(ticker, store.load().indicator_params, cache)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Could not add '{ticker}': {exc}") from exc
    universe.add_custom(entry, cache)
    return {"entry": entry.model_dump(), "price": price}


@router.delete("/universe/custom/{ticker}")
def delete_custom_company(ticker: str, cache: Cache = Depends(get_cache)) -> dict:
    return {"deleted": universe.delete_custom(ticker, cache)}
```

Add `UniverseEntry` to the `from app.models.schemas import (...)` block.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend; .venv\Scripts\python -m pytest tests/test_api_universe.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_universe.py
git commit -m "feat: custom-company CRUD endpoints (auto-fetch on add)"
```

---

## Task 22: Frontend custom-company API + hooks

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/api/client.test.ts`:

```typescript
it('addCustomCompany POSTs the ticker', async () => {
  const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ entry: { ticker: 'PRIV' }, price: 42.5 }), { status: 200 }));
  await api.addCustomCompany('PRIV');
  expect(spy).toHaveBeenCalledWith(expect.stringContaining('/universe/custom'),
    expect.objectContaining({ method: 'POST' }));
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/api/client.test.ts`
Expected: FAIL — `addCustomCompany` not defined.

- [ ] **Step 3: Implement**

In `frontend/src/api/client.ts`, add to the `api` object (and a `CustomCompany`/result type in `types.ts` or inline):

```typescript
  listCustomCompanies: () => http<import('../types').StockScore[] | { ticker: string; name: string; sector: string; exchange: string }[]>('/universe/custom'),
  addCustomCompany: (ticker: string) =>
    http<{ entry: { ticker: string; name: string; sector: string; exchange: string }; price: number }>(
      '/universe/custom', { method: 'POST', body: JSON.stringify({ ticker }) }),
  deleteCustomCompany: (ticker: string) =>
    http<{ deleted: boolean }>(`/universe/custom/${encodeURIComponent(ticker)}`, { method: 'DELETE' }),
```

> Prefer a named `CustomCompany` interface in `types.ts` (`{ ticker; name; sector; exchange }`) and
> use it here instead of the inline shape — cleaner and reused by the hooks/form.

In `frontend/src/hooks/queries.ts`:

```typescript
export function useAddCustomCompany() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.addCustomCompany(ticker),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['customCompanies'] });
      qc.invalidateQueries({ queryKey: ['sectors'] });
    },
  });
}

export function useCustomCompanies() {
  return useQuery({ queryKey: ['customCompanies'], queryFn: api.listCustomCompanies });
}

export function useDeleteCustomCompany() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.deleteCustomCompany(ticker),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['customCompanies'] }),
  });
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npm test -- --run src/api/client.test.ts; npx tsc --noEmit`
Expected: PASS; tsc clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/types.ts frontend/src/api/client.test.ts
git commit -m "feat: frontend custom-company API + hooks"
```

---

## Task 23: Add-company form on Discover + remove on custom rows

**Files:**
- Create: `frontend/src/components/AddCompanyForm.tsx`, `frontend/src/components/AddCompanyForm.test.tsx`
- Modify: `frontend/src/pages/Discover.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/AddCompanyForm.test.tsx`:

```typescript
import { expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('../api/client', () => ({ api: { addCustomCompany: vi.fn(), listCustomCompanies: vi.fn(), deleteCustomCompany: vi.fn() } }));
import { api } from '../api/client';
import { AddCompanyForm } from './AddCompanyForm';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => vi.clearAllMocks());

it('submits a ticker and shows the resolved company', async () => {
  vi.mocked(api.addCustomCompany).mockResolvedValue({
    entry: { ticker: 'PRIV', name: 'Private Co', sector: 'Tech', exchange: 'NYSE' }, price: 42.5,
  });
  wrap(<AddCompanyForm />);
  fireEvent.change(screen.getByPlaceholderText(/add a company/i), { target: { value: 'priv' } });
  fireEvent.click(screen.getByRole('button', { name: /add company/i }));
  await waitFor(() => expect(screen.getByText(/Private Co/)).toBeInTheDocument());
  expect(api.addCustomCompany).toHaveBeenCalledWith('priv');
});

it('shows the error from a rejected ticker', async () => {
  vi.mocked(api.addCustomCompany).mockRejectedValue(new Error("Could not add 'NOPE': No price history"));
  wrap(<AddCompanyForm />);
  fireEvent.change(screen.getByPlaceholderText(/add a company/i), { target: { value: 'NOPE' } });
  fireEvent.click(screen.getByRole('button', { name: /add company/i }));
  await waitFor(() => expect(screen.getByText(/No price history/)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend; npm test -- --run src/components/AddCompanyForm.test.tsx`
Expected: FAIL — `AddCompanyForm` does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/AddCompanyForm.tsx`:

```typescript
import { useState } from 'react';
import { useAddCustomCompany } from '../hooks/queries';

export function AddCompanyForm() {
  const [ticker, setTicker] = useState('');
  const add = useAddCustomCompany();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = ticker.trim();
    if (t) add.mutate(t);
  };

  return (
    <form className="add-company" onSubmit={submit}>
      <input
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="Add a company by ticker (e.g. ASML)…"
        title="Add a non-S&P 500 company — its name, exchange, sector and price are fetched automatically."
      />
      <button type="submit" disabled={add.isPending || !ticker.trim()}
              title="Fetch the company's details and add it to the Discover universe.">
        {add.isPending ? 'Adding…' : 'Add company'}
      </button>
      {add.isSuccess && (
        <span className="muted">
          ✓ Added {add.data.entry.name} ({add.data.entry.ticker}) · {add.data.entry.exchange || '—'} ·
          {' '}{add.data.entry.sector || '—'} · ${add.data.price.toFixed(2)}. Rescan to score it.
        </span>
      )}
      {add.isError && <span className="error">{(add.error as Error).message}</span>}
    </form>
  );
}
```

In `frontend/src/pages/Discover.tsx`: render `<AddCompanyForm />` in the command bar (next to the toolbar buttons), and wire `onRemove` so custom rows can be deleted:

```typescript
import { AddCompanyForm } from '../components/AddCompanyForm';
import { useDeleteCustomCompany } from '../hooks/queries';
```
```typescript
  const delCustom = useDeleteCustomCompany();
```
```typescript
          {scanning && <button title="Stop the scan — nothing is saved." onClick={rescan.stop}>Stop</button>}
          <AddCompanyForm />
```
```typescript
        {data && <ScoreBoard items={data.items} onAdd={watch.add} onRemove={(t) => delCustom.mutate(t)} />}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend; npm test -- --run src/components/AddCompanyForm.test.tsx; npx tsc --noEmit`
Expected: PASS; tsc clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AddCompanyForm.tsx frontend/src/components/AddCompanyForm.test.tsx frontend/src/pages/Discover.tsx
git commit -m "feat: Discover add-company form + remove custom rows"
```

---

## Task 24: Styles for new UI

**Files:**
- Modify: the app stylesheet (find it: `frontend/src/*.css` — likely `index.css` or `App.css`)

- [ ] **Step 1: Add styles (visual only, no unit test)**

Add minimal rules so the new elements match the existing look: `.board-search input` (full-width-ish search box), `.badge.sp` / `.badge.custom` (membership badges — reuse existing `.badge` colours; `.custom` muted/grey), `.add-company` (inline flex form). Match the existing token/colour variables used elsewhere in the file.

- [ ] **Step 2: Verify in the preview**

Run the app; confirm the Discover/Portfolio search box, S&P/Custom badges, and the Add-company form render cleanly in both light and dark. Use `preview_screenshot` to capture proof.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/<stylesheet>.css
git commit -m "style: search box, membership badges, add-company form"
```

---

## Phase 3 verification

- [ ] Backend + frontend full suites green.
- [ ] Manual: on Discover, add a real non-S&P ticker (e.g. `ASML`); confirm the inline resolved info, then **Rescan all** and confirm it appears flagged **Custom** with its exchange. Remove it via the × on its row. Confirm `is_sp500_member` keeps real S&P names flagged **S&P 500**.

---

## Final self-review checklist (run before declaring done)

- [ ] **Spec coverage:** exchange/S&P columns (Task 12); custom company auto-fetch + persist (Tasks 18–23); scan watchlist only — the portfolio scope IS watchlist+ontology, and watchlist-only falls out when no ontology is active (Tasks 4–9); scan watchlist + whole ontology (Tasks 4–9); search box (Task 12); tooltips on all buttons (Tasks 12–13, 16, 23). Base-index precedence (Tasks 6–8, 17). Evaluation repoint (Tasks 14–16).
- [ ] **No stray `screen_snapshot` scope leaks:** Discover reads `all`, Portfolio reads `portfolio`, `combined_base_index` overlays them.
- [ ] **Type consistency:** `getScreen(sector, direction, limit, scope)`, `useScreen(...)`, `streamRescan(scope, handlers)`, `rescanAndSnapshot(scope?)`, `portfolio_universe(settings, cache)`, `combined_base_index(cache)`, `apply_network(board, graph, settings, base_override=None)`, `load_universe(sector=None, cache=None)`, `resolve_custom_entry(ticker, params, cache)` are used identically everywhere.
- [ ] Run the **entire** test suite once more (backend + frontend) and confirm green before any merge.
