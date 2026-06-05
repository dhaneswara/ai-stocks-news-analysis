# Discover — Opportunity Board — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Screen the whole S&P 500 with a cheap, no-LLM scoring engine and present an auto-ranked "opportunity board" (0–100 score + buy/sell/hold + plain reasons), so you stop clicking stock-by-stock; clicking a row reuses the existing per-ticker LLM deep-dive.

**Architecture:** A pure scorer (`analysis/scoring.py`) turns a `StockData` + Trump mentions into a `StockScore`. A scan service (`screener/service.py`) runs it over a static universe (`data/sp500.json`) and stores a ranked snapshot in the existing `Cache` (`screener/store.py`). A scheduled runner (`python -m app.screener`, mirroring `app.alerts`) refreshes the snapshot daily; three API routes read/rescan/list-sectors. A new **Discover** page renders the board, filters by sector/direction, and deep-links into the existing Dashboard.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pytest (backend); React + TS + Vite + vitest, @tanstack/react-query, react-router-dom v7 (frontend). SQLite `Cache` for the snapshot.

---

**Spec:** [docs/superpowers/specs/2026-06-05-discover-opportunity-board-design.md](../specs/2026-06-05-discover-opportunity-board-design.md)

**Conventions (apply to every task):**
- Run backend tests from `backend/` with the venv interpreter: `.venv/Scripts/python.exe -m pytest -q`.
- Run a single test: `.venv/Scripts/python.exe -m pytest tests/test_x.py::test_name -v`.
- Commits use Conventional Commits and **end with** the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Frontend: from `frontend/`, `npm run test` (vitest) and `npm run build` (tsc + vite).
- A backend autouse fixture in `tests/conftest.py` stubs the Truth Social fetch to return no posts, so scans are hermetic by default (catalyst signal contributes 0 unless a test passes mentions explicitly).

---

## File structure

**Backend (create):**
- `backend/app/data/sp500.json` — static S&P 500 constituents (`ticker`, `name`, `sector`).
- `backend/app/data/universe.py` — load + sector-filter + list sectors (no I/O beyond the file).
- `backend/app/analysis/scoring.py` — pure signal helpers + `score_stock` (no LLM).
- `backend/app/screener/__init__.py`, `service.py`, `store.py`, `runner.py`, `__main__.py`.
- `backend/tests/test_universe.py`, `test_screener_schema.py`, `test_scoring.py`,
  `test_screener_service.py`, `test_screener_runner.py`, `test_api_screen.py`.

**Backend (modify):**
- `backend/app/models/schemas.py` — `UniverseEntry`, `StockScore`, `ScreenBoard`, `ScreenerConfig`; `Settings.screener`.
- `backend/app/api/routes.py` — `GET /api/screen`, `POST /api/screen/rescan`, `GET /api/screen/sectors`.

**Frontend (modify):**
- `frontend/src/types.ts` — `StockScore`, `ScreenBoard`.
- `frontend/src/api/client.ts` (+ `client.test.ts`) — `getScreen`, `rescan`, `getSectors`.
- `frontend/src/hooks/queries.ts` — `useScreen`, `useRescan`, `useSectors`.
- `frontend/src/App.tsx` — Discover route + nav link.
- `frontend/src/pages/Dashboard.tsx` — preselect ticker from a `?ticker=` query param.
- `frontend/src/styles.css` — board styles.

**Frontend (create):**
- `frontend/src/pages/Discover.tsx`, `frontend/src/components/DiscoverBoard.tsx`.

---

## Task 1: Universe data file + loader

**Files:**
- Create: `backend/app/data/sp500.json`, `backend/app/data/universe.py`
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_universe.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_universe.py`:

```python
from app.data.universe import list_sectors, load_universe
from app.models.schemas import UniverseEntry


def test_load_universe_returns_entries():
    u = load_universe()
    assert len(u) >= 20
    assert all(isinstance(e, UniverseEntry) for e in u)
    aapl = next(e for e in u if e.ticker == "AAPL")
    assert aapl.sector == "Information Technology"


def test_load_universe_filters_by_sector():
    energy = load_universe("Energy")
    assert energy and all(e.sector == "Energy" for e in energy)


def test_list_sectors_distinct_sorted():
    sectors = list_sectors()
    assert sectors == sorted(set(sectors))
    assert "Information Technology" in sectors
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_universe.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.universe'`.

- [ ] **Step 3: Add the `UniverseEntry` schema**

In `backend/app/models/schemas.py`, add **after** `class NewsItem` (around line 61):

```python
class UniverseEntry(BaseModel):
    ticker: str
    name: str
    sector: str
```

- [ ] **Step 4: Create the data file**

Create `backend/app/data/sp500.json` (a curated **starter** set across all 11 GICS sectors — the
loader is size-agnostic, so expanding to the full ~500 later is a data-only change requiring no
code change; see the docstring in Step 5):

```json
[
  { "ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology" },
  { "ticker": "MSFT", "name": "Microsoft Corp.", "sector": "Information Technology" },
  { "ticker": "NVDA", "name": "NVIDIA Corp.", "sector": "Information Technology" },
  { "ticker": "AVGO", "name": "Broadcom Inc.", "sector": "Information Technology" },
  { "ticker": "GOOGL", "name": "Alphabet Inc.", "sector": "Communication Services" },
  { "ticker": "META", "name": "Meta Platforms Inc.", "sector": "Communication Services" },
  { "ticker": "NFLX", "name": "Netflix Inc.", "sector": "Communication Services" },
  { "ticker": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary" },
  { "ticker": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary" },
  { "ticker": "HD", "name": "Home Depot Inc.", "sector": "Consumer Discretionary" },
  { "ticker": "PG", "name": "Procter & Gamble Co.", "sector": "Consumer Staples" },
  { "ticker": "KO", "name": "Coca-Cola Co.", "sector": "Consumer Staples" },
  { "ticker": "COST", "name": "Costco Wholesale Corp.", "sector": "Consumer Staples" },
  { "ticker": "JPM", "name": "JPMorgan Chase & Co.", "sector": "Financials" },
  { "ticker": "BAC", "name": "Bank of America Corp.", "sector": "Financials" },
  { "ticker": "V", "name": "Visa Inc.", "sector": "Financials" },
  { "ticker": "UNH", "name": "UnitedHealth Group Inc.", "sector": "Health Care" },
  { "ticker": "JNJ", "name": "Johnson & Johnson", "sector": "Health Care" },
  { "ticker": "LLY", "name": "Eli Lilly and Co.", "sector": "Health Care" },
  { "ticker": "CAT", "name": "Caterpillar Inc.", "sector": "Industrials" },
  { "ticker": "BA", "name": "Boeing Co.", "sector": "Industrials" },
  { "ticker": "HON", "name": "Honeywell International Inc.", "sector": "Industrials" },
  { "ticker": "XOM", "name": "Exxon Mobil Corp.", "sector": "Energy" },
  { "ticker": "CVX", "name": "Chevron Corp.", "sector": "Energy" },
  { "ticker": "NEE", "name": "NextEra Energy Inc.", "sector": "Utilities" },
  { "ticker": "DUK", "name": "Duke Energy Corp.", "sector": "Utilities" },
  { "ticker": "AMT", "name": "American Tower Corp.", "sector": "Real Estate" },
  { "ticker": "PLD", "name": "Prologis Inc.", "sector": "Real Estate" },
  { "ticker": "LIN", "name": "Linde plc", "sector": "Materials" },
  { "ticker": "SHW", "name": "Sherwin-Williams Co.", "sector": "Materials" }
]
```

- [ ] **Step 5: Implement the loader**

Create `backend/app/data/universe.py`:

```python
"""Static S&P 500 universe for the Discover screen.

`sp500.json` is a committed snapshot (ticker / name / GICS sector). It deliberately avoids any
network scrape on the request path. The list drifts (adds/drops) — refresh it manually (e.g.
quarterly) by replacing the file with a fresh constituent dump; no code change is needed. The
starter file ships a representative subset across all 11 sectors; appending the remaining names
only grows the data file.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models.schemas import UniverseEntry

_DATA_FILE = Path(__file__).with_name("sp500.json")


@lru_cache
def _all_entries() -> tuple[UniverseEntry, ...]:
    raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return tuple(UniverseEntry(**row) for row in raw)


def load_universe(sector: str | None = None) -> list[UniverseEntry]:
    entries = _all_entries()
    if sector:
        return [e for e in entries if e.sector == sector]
    return list(entries)


def list_sectors() -> list[str]:
    return sorted({e.sector for e in _all_entries()})
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_universe.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/data/sp500.json backend/app/data/universe.py backend/app/models/schemas.py backend/tests/test_universe.py
git commit   # feat(backend): add S&P 500 universe data file + loader
```

---

## Task 2: Screener schemas

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_screener_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_screener_schema.py`:

```python
from app.models.schemas import ScreenBoard, ScreenerConfig, Settings, StockScore


def test_screener_config_defaults():
    cfg = ScreenerConfig()
    assert cfg.enabled is True
    assert cfg.top_n == 25
    assert cfg.rsi_low == 30.0 and cfg.rsi_high == 70.0
    assert set(cfg.weights) == {"extremes", "trend", "momentum", "volume", "catalyst"}
    assert cfg.weights["extremes"] == 1.0


def test_settings_includes_screener():
    assert Settings().screener.top_n == 25


def test_stockscore_minimal_defaults():
    s = StockScore(ticker="AAPL", name="Apple Inc.", price=200.0, change_pct=1.0,
                   score=70.0, direction="buy")
    assert s.sector == "" and s.reasons == [] and s.components == {} and s.as_of == ""


def test_screenboard_defaults():
    b = ScreenBoard()
    assert b.items == [] and b.scope == "all" and b.scanned == 0 and b.as_of == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_screener_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'StockScore'`.

- [ ] **Step 3: Add the models**

In `backend/app/models/schemas.py`, add **after** `class RuleHit` (near the end, before `_default_providers`):

```python
class StockScore(BaseModel):
    ticker: str
    name: str
    sector: str = ""
    price: float
    change_pct: float
    score: float                       # 0–100 opportunity
    direction: Literal["buy", "sell", "hold"]
    reasons: list[str] = Field(default_factory=list)
    components: dict[str, float] = Field(default_factory=dict)
    as_of: str = ""


class ScreenBoard(BaseModel):
    as_of: str = ""
    scope: str = "all"
    scanned: int = 0
    skipped: int = 0
    items: list[StockScore] = Field(default_factory=list)


def _default_screener_weights() -> dict[str, float]:
    return {"extremes": 1.0, "trend": 1.0, "momentum": 0.8, "volume": 0.4, "catalyst": 0.5}


class ScreenerConfig(BaseModel):
    enabled: bool = True
    top_n: int = 25
    default_sector: Optional[str] = None
    rsi_low: float = 30.0
    rsi_high: float = 70.0
    weights: dict[str, float] = Field(default_factory=_default_screener_weights)
```

- [ ] **Step 4: Extend `Settings`**

Add one field to `class Settings` (after `truth_signal`):

```python
    screener: ScreenerConfig = Field(default_factory=ScreenerConfig)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_screener_schema.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all existing tests still pass (`screener` defaults keep `Settings` backward-compatible;
`merge_settings` carries it through via `deepcopy` — no masking needed, no secrets).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_screener_schema.py
git commit   # feat(backend): add screener schemas (StockScore, ScreenBoard, ScreenerConfig)
```

---

## Task 3: Scoring engine — signal helpers (pure)

**Files:**
- Create: `backend/app/analysis/scoring.py`
- Test: `backend/tests/test_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scoring.py`:

```python
from app.analysis.scoring import (
    _breakout_signal,
    _catalyst_signal,
    _cross_signal,
    _low_proximity_signal,
    _momentum_signal,
    _rsi_signal,
    _trend_signal,
    _volume_signal,
)
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    Mention,
    PriceSummary,
    ScreenerConfig,
    StockData,
)

CFG = ScreenerConfig()


def _pts(values):
    return [IndicatorPoint(time=f"d{i}", value=float(v)) for i, v in enumerate(values)]


def _candles(closes, vols=None):
    vols = vols or [1_000_000.0] * len(closes)
    return [
        Candle(time=f"d{i}", open=c, high=c, low=c, close=c, volume=float(v))
        for i, (c, v) in enumerate(zip(closes, vols))
    ]


def _stock(*, rsi_series=(50.0, 50.0), sma50_series=(100.0, 100.0), sma200_series=(100.0, 100.0),
           price=100.0, change_pct=0.0, week52_low=50.0, week52_high=150.0, dist_high=-10.0,
           closes=None, vols=None, ticker="AAPL", company="Apple Inc."):
    closes = closes if closes is not None else [100.0] * 30
    return StockData(
        ticker=ticker, company_name=company, as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=price, change=0.0, change_pct=change_pct, currency="USD"),
        candles=_candles(closes, vols),
        fundamentals=Fundamentals(week52_low=week52_low, week52_high=week52_high),
        indicators=Indicators(sma50=_pts(sma50_series), sma200=_pts(sma200_series),
                              rsi14=_pts(rsi_series), dist_from_52wk_high_pct=dist_high),
    )


def test_rsi_oversold_is_bullish():
    sig = _rsi_signal(_stock(rsi_series=(40, 25)), CFG)
    assert sig.signed > 0 and sig.intensity > 0 and "oversold" in sig.reason


def test_rsi_overbought_is_bearish():
    sig = _rsi_signal(_stock(rsi_series=(60, 80)), CFG)
    assert sig.signed < 0 and "overbought" in sig.reason


def test_rsi_neutral_is_silent():
    assert _rsi_signal(_stock(rsi_series=(50, 55)), CFG).intensity == 0


def test_low_proximity_near_low_is_bullish():
    sig = _low_proximity_signal(_stock(price=52, week52_low=50))
    assert sig.signed > 0 and "52-wk low" in sig.reason


def test_low_proximity_far_is_silent():
    assert _low_proximity_signal(_stock(price=100, week52_low=50)).intensity == 0


def test_golden_cross_is_bullish():
    sig = _cross_signal(_stock(sma50_series=(99, 101), sma200_series=(100, 100)), CFG)
    assert sig.signed == 1.0 and "golden" in sig.reason


def test_death_cross_is_bearish():
    sig = _cross_signal(_stock(sma50_series=(101, 99), sma200_series=(100, 100)), CFG)
    assert sig.signed == -1.0 and "death" in sig.reason


def test_trend_uptrend_and_downtrend():
    up = _trend_signal(_stock(price=120, sma50_series=(110, 110), sma200_series=(100, 100)))
    down = _trend_signal(_stock(price=80, sma50_series=(90, 90), sma200_series=(100, 100)))
    assert up.signed > 0 and down.signed < 0


def test_momentum_positive_and_insufficient():
    pos = _momentum_signal(_stock(closes=[100.0] * 29 + [115.0]))
    assert pos.signed > 0 and "1mo" in pos.reason
    assert _momentum_signal(_stock(closes=[100.0] * 10)).intensity == 0


def test_breakout_near_high_only():
    assert _breakout_signal(_stock(dist_high=-1.0)).signed > 0
    assert _breakout_signal(_stock(dist_high=-20.0)).intensity == 0


def test_volume_surge_has_no_direction():
    vols = [1_000_000.0] * 29 + [3_000_000.0]
    sig = _volume_signal(_stock(closes=[100.0] * 30, vols=vols))
    assert sig.intensity > 0 and sig.signed == 0 and "avg" in sig.reason
    assert _volume_signal(_stock(closes=[100.0] * 30)).intensity == 0


def test_catalyst_boosts_without_direction():
    m = [Mention(post_id="1", created_at="t", matched="$AAPL", excerpt="x", url="")]
    sig = _catalyst_signal(m)
    assert sig.intensity > 0 and sig.signed == 0
    assert _catalyst_signal([]).intensity == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.scoring'`.

- [ ] **Step 3: Implement the signal helpers**

Create `backend/app/analysis/scoring.py`:

```python
"""Pure, deterministic opportunity scoring — no LLM, no I/O.

Each helper turns a `StockData` (plus Trump mentions) into a `_Sig`:
- intensity (0..1): how strongly the signal is firing → drives the 0–100 score.
- signed (-1..1): directional vote (+ bullish / − bearish); 0 means attention-only
  (volume surges and Trump mentions raise the score but never vote on direction).
- reason: a short human chip for the board.

`score_stock` (next task) blends these by weight.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.alerts.rules import evaluate_rules
from app.models.schemas import Mention, ScreenerConfig, StockData


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class _Sig:
    intensity: float = 0.0
    signed: float = 0.0
    reason: str = ""


def _last(points) -> float | None:
    return points[-1].value if points else None


def _return(candles, lookback: int) -> float | None:
    if len(candles) <= lookback:
        return None
    prev = candles[-1 - lookback].close
    if prev == 0:
        return None
    return candles[-1].close / prev - 1.0


def _rsi_signal(stock: StockData, cfg: ScreenerConfig) -> _Sig:
    rsi = _last(stock.indicators.rsi14)
    if rsi is None:
        return _Sig()
    if rsi <= cfg.rsi_low:
        inten = _clamp((cfg.rsi_low - rsi) / cfg.rsi_low)
        return _Sig(inten, inten, f"RSI {rsi:.0f} (oversold)")
    if rsi >= cfg.rsi_high:
        inten = _clamp((rsi - cfg.rsi_high) / (100.0 - cfg.rsi_high))
        return _Sig(inten, -inten, f"RSI {rsi:.0f} (overbought)")
    return _Sig()


def _low_proximity_signal(stock: StockData) -> _Sig:
    low = stock.fundamentals.week52_low
    price = stock.price.current
    if not low or low <= 0:
        return _Sig()
    dist = (price - low) / low
    if dist <= 0.10:
        inten = _clamp(1.0 - dist / 0.10)
        return _Sig(inten, inten, "near 52-wk low")
    return _Sig()


def _cross_signal(stock: StockData, cfg: ScreenerConfig) -> _Sig:
    for hit in evaluate_rules(stock, cfg.rsi_low, cfg.rsi_high):
        if hit.rule_id == "golden_cross":
            return _Sig(1.0, 1.0, "golden cross")
        if hit.rule_id == "death_cross":
            return _Sig(1.0, -1.0, "death cross")
    return _Sig()


def _trend_signal(stock: StockData) -> _Sig:
    price = stock.price.current
    s50 = _last(stock.indicators.sma50)
    s200 = _last(stock.indicators.sma200)
    if s50 is None or s200 is None:
        return _Sig()
    if price > s50 > s200:
        return _Sig(0.6, 0.6, "uptrend (price>SMA50>SMA200)")
    if price < s50 < s200:
        return _Sig(0.6, -0.6, "downtrend (price<SMA50<SMA200)")
    if price > s50:
        return _Sig(0.3, 0.3, "above SMA50")
    if price < s50:
        return _Sig(0.3, -0.3, "below SMA50")
    return _Sig()


def _momentum_signal(stock: StockData) -> _Sig:
    r = _return(stock.candles, 21)  # ~1 trading month
    if r is None:
        return _Sig()
    inten = _clamp(abs(r) / 0.15)  # a 15% move = full intensity
    sign = 1.0 if r >= 0 else -1.0
    return _Sig(inten, sign * inten, f"{r * 100:+.0f}% 1mo")


def _breakout_signal(stock: StockData) -> _Sig:
    dist = stock.indicators.dist_from_52wk_high_pct
    if dist is None:
        return _Sig()
    if dist >= -2.0:  # within 2% of the 52-wk high
        return _Sig(0.6, 0.6, "near 52-wk high (breakout)")
    return _Sig()


def _volume_signal(stock: StockData) -> _Sig:
    vols = [c.volume for c in stock.candles[-21:-1]]  # the prior 20 bars
    if len(vols) < 20:
        return _Sig()
    avg = sum(vols) / len(vols)
    if avg <= 0:
        return _Sig()
    ratio = stock.candles[-1].volume / avg
    if ratio >= 1.5:
        return _Sig(_clamp((ratio - 1.0) / 2.0), 0.0, f"volume {ratio:.1f}x avg")
    return _Sig()


def _catalyst_signal(mentions: list[Mention]) -> _Sig:
    if not mentions:
        return _Sig()
    inten = _clamp(0.5 * len(mentions))
    label = "Trump mention" if len(mentions) == 1 else f"Trump mention x{len(mentions)}"
    return _Sig(inten, 0.0, label)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scoring.py -q`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/scoring.py backend/tests/test_scoring.py
git commit   # feat(backend): pure opportunity-scoring signal helpers
```

---

## Task 4: Scoring engine — `score_stock` aggregation

**Files:**
- Modify: `backend/app/analysis/scoring.py`
- Test: `backend/tests/test_scoring.py`

- [ ] **Step 1: Write the failing tests** (append to `test_scoring.py`)

```python
from app.analysis.scoring import score_stock


def test_strong_bull_scores_high_and_buys():
    stock = _stock(rsi_series=(40, 25), price=52, week52_low=50,
                   sma50_series=(99, 101), sma200_series=(100, 100),
                   closes=[100.0] * 29 + [115.0], dist_high=-1.0)
    s = score_stock(stock, [], CFG)
    assert s.direction == "buy"
    assert s.score > 50
    assert any("oversold" in r for r in s.reasons)


def test_strong_bear_sells():
    stock = _stock(rsi_series=(60, 80), price=100, week52_low=50,
                   sma50_series=(101, 99), sma200_series=(100, 100),
                   closes=[100.0] * 29 + [85.0], dist_high=-30.0)
    s = score_stock(stock, [], CFG)
    assert s.direction == "sell"


def test_flat_scores_low_and_holds():
    stock = _stock(rsi_series=(50, 50), price=100, week52_low=50,
                   sma50_series=(100, 100), sma200_series=(100, 100),
                   closes=[100.0] * 30, dist_high=-25.0)
    s = score_stock(stock, [], CFG)
    assert s.direction == "hold" and s.score < 20


def test_catalyst_raises_score_without_flipping_direction():
    stock = _stock(rsi_series=(50, 50), price=100, week52_low=50,
                   sma50_series=(100, 100), sma200_series=(100, 100),
                   closes=[100.0] * 30, dist_high=-25.0)
    m = [Mention(post_id="1", created_at="t", matched="$AAPL", excerpt="x", url="")]
    base = score_stock(stock, [], CFG)
    boosted = score_stock(stock, m, CFG)
    assert boosted.score > base.score
    assert boosted.direction == base.direction == "hold"


def test_score_bounded_and_components_complete():
    stock = _stock(rsi_series=(40, 20), price=51, week52_low=50,
                   sma50_series=(99, 101), sma200_series=(100, 100),
                   closes=[100.0] * 29 + [130.0], dist_high=0.0,
                   vols=[1_000_000.0] * 29 + [5_000_000.0])
    m = [Mention(post_id="1", created_at="t", matched="$AAPL", excerpt="x", url="")]
    s = score_stock(stock, m, CFG)
    assert 0.0 <= s.score <= 100.0
    assert set(s.components) == {"extremes", "trend", "momentum", "volume", "catalyst"}
    assert s.ticker == "AAPL" and s.name == "Apple Inc." and s.as_of == "2026-06-05T00:00:00Z"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scoring.py -q`
Expected: FAIL — `ImportError: cannot import name 'score_stock'`.

- [ ] **Step 3: Implement the aggregator** (append to `scoring.py`)

Add `StockScore` to the schemas import at the top of `scoring.py`:

```python
from app.models.schemas import Mention, ScreenerConfig, StockData, StockScore
```

Then append:

```python
_DIRECTIONAL = ("extremes", "trend", "momentum")  # families that vote on direction
_DIRECTION_THRESHOLD = 0.1


def _combine(sigs: list[_Sig]) -> _Sig:
    """Sum a family's sub-signals; cap intensity and the signed vote to their ranges."""
    firing = [s for s in sigs if s.intensity > 0]
    if not firing:
        return _Sig()
    intensity = _clamp(sum(s.intensity for s in firing))
    signed = _clamp(sum(s.signed for s in firing), -1.0, 1.0)
    reason = " · ".join(s.reason for s in firing if s.reason)
    return _Sig(intensity, signed, reason)


def score_stock(stock: StockData, mentions: list[Mention], cfg: ScreenerConfig) -> StockScore:
    families: dict[str, _Sig] = {
        "extremes": _combine([_rsi_signal(stock, cfg), _low_proximity_signal(stock)]),
        "trend": _combine([_cross_signal(stock, cfg), _trend_signal(stock)]),
        "momentum": _combine([_momentum_signal(stock), _breakout_signal(stock)]),
        "volume": _volume_signal(stock),
        "catalyst": _catalyst_signal(mentions),
    }
    w = cfg.weights
    total_w = sum(w.get(f, 0.0) for f in families) or 1.0
    score = 100.0 * sum(w.get(f, 0.0) * sig.intensity for f, sig in families.items()) / total_w

    dir_w = sum(w.get(f, 0.0) for f in _DIRECTIONAL) or 1.0
    net = sum(w.get(f, 0.0) * families[f].signed for f in _DIRECTIONAL) / dir_w
    direction = "buy" if net > _DIRECTION_THRESHOLD else "sell" if net < -_DIRECTION_THRESHOLD else "hold"

    ranked = sorted(families.items(), key=lambda kv: w.get(kv[0], 0.0) * kv[1].intensity, reverse=True)
    reasons = [sig.reason for _, sig in ranked if sig.reason]

    return StockScore(
        ticker=stock.ticker,
        name=stock.company_name,
        price=stock.price.current,
        change_pct=stock.price.change_pct,
        score=round(_clamp(score, 0.0, 100.0), 1),
        direction=direction,
        reasons=reasons,
        components={f: round(sig.intensity, 2) for f, sig in families.items()},
        as_of=stock.as_of,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scoring.py -q`
Expected: PASS (17 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/scoring.py backend/tests/test_scoring.py
git commit   # feat(backend): blend signals into a 0-100 score + direction + reasons
```

---

## Task 5: Scan service + snapshot store

**Files:**
- Create: `backend/app/screener/__init__.py`, `backend/app/screener/service.py`, `backend/app/screener/store.py`
- Test: `backend/tests/test_screener_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_screener_service.py`:

```python
import app.screener.service as service
from app.config.cache import Cache
from app.models.schemas import (
    Candle,
    Fundamentals,
    IndicatorPoint,
    Indicators,
    PriceSummary,
    ScreenBoard,
    Settings,
    StockData,
    StockScore,
    UniverseEntry,
)
from app.screener.store import load_snapshot, merge_sector, save_snapshot


def _stock(ticker, rsi_last=50.0, week52_low=50.0):
    rsi = [IndicatorPoint(time="d0", value=50.0), IndicatorPoint(time="d1", value=rsi_last)]
    sma = [IndicatorPoint(time="d0", value=100.0), IndicatorPoint(time="d1", value=100.0)]
    candles = [Candle(time=f"d{i}", open=100.0, high=100.0, low=100.0, close=100.0, volume=1e6)
               for i in range(30)]
    return StockData(
        ticker=ticker, company_name=f"{ticker} Inc.", as_of="2026-06-05T00:00:00Z",
        price=PriceSummary(current=100.0, change=0.0, change_pct=0.0, currency="USD"),
        candles=candles, fundamentals=Fundamentals(week52_low=week52_low, week52_high=150.0),
        indicators=Indicators(sma50=sma, sma200=sma, rsi14=rsi, dist_from_52wk_high_pct=-10.0),
    )


def test_run_scan_ranks_and_tags_sector(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "load_universe", lambda scope=None: [
        UniverseEntry(ticker="AAA", name="A", sector="Tech"),
        UniverseEntry(ticker="BBB", name="B", sector="Tech"),
    ])

    def fake_get(ticker, period, params, cache):
        # AAA is oversold + near its low -> a stronger setup than the neutral BBB.
        return _stock(ticker, rsi_last=20.0, week52_low=99.0) if ticker == "AAA" else _stock(ticker)

    monkeypatch.setattr(service, "get_stock_data", fake_get)
    board = service.run_scan(None, Settings(), Cache(str(tmp_path / "c.db")))
    assert board.scanned == 2 and board.skipped == 0
    assert [i.ticker for i in board.items][0] == "AAA"
    assert all(i.sector == "Tech" for i in board.items)
    assert board.scope == "all" and board.as_of


def test_run_scan_skips_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "load_universe", lambda scope=None: [
        UniverseEntry(ticker="OK", name="O", sector="Tech"),
        UniverseEntry(ticker="BAD", name="X", sector="Tech"),
    ])

    def fake_get(ticker, *a, **k):
        if ticker == "BAD":
            raise ValueError("no price history")
        return _stock(ticker)

    monkeypatch.setattr(service, "get_stock_data", fake_get)
    board = service.run_scan(None, Settings(), Cache(str(tmp_path / "c.db")))
    assert board.scanned == 2 and board.skipped == 1
    assert [i.ticker for i in board.items] == ["OK"]


def test_snapshot_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    board = ScreenBoard(as_of="t", scope="all", scanned=1, items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1.0, change_pct=0.0,
                   score=10.0, direction="hold")])
    save_snapshot(board, cache)
    assert load_snapshot(cache, "all").items[0].ticker == "AAA"
    assert load_snapshot(cache, "Energy") is None


def test_merge_sector_replaces_only_that_sector():
    full = ScreenBoard(scope="all", items=[
        StockScore(ticker="OLD", name="O", sector="Tech", price=1, change_pct=0, score=10, direction="hold"),
        StockScore(ticker="KEEP", name="K", sector="Energy", price=1, change_pct=0, score=20, direction="hold"),
    ])
    fresh = ScreenBoard(scope="Tech", items=[
        StockScore(ticker="NEW", name="N", sector="Tech", price=1, change_pct=0, score=99, direction="buy"),
    ])
    merged = merge_sector(full, fresh)
    tickers = [i.ticker for i in merged.items]
    assert "OLD" not in tickers and "NEW" in tickers and "KEEP" in tickers
    assert tickers[0] == "NEW"  # re-ranked by score desc
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_screener_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.screener'`.

- [ ] **Step 3: Create the package + store**

Create `backend/app/screener/__init__.py` (empty file).

Create `backend/app/screener/store.py`:

```python
"""Persist the latest ranked board in the existing Cache (SQLite KV).

Keyed `screen_snapshot:<scope>` with a long TTL; the daily job refreshes it well within that, so
expiry only ever yields the empty state. No new table — reuses the cache injected via get_cache.
"""
from __future__ import annotations

from app.config.cache import Cache
from app.models.schemas import ScreenBoard

_SNAPSHOT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _key(scope: str) -> str:
    return f"screen_snapshot:{scope}"


def save_snapshot(board: ScreenBoard, cache: Cache) -> None:
    cache.set(_key(board.scope), board.model_dump_json(), _SNAPSHOT_TTL_SECONDS)


def load_snapshot(cache: Cache, scope: str = "all") -> ScreenBoard | None:
    raw = cache.get(_key(scope))
    return ScreenBoard.model_validate_json(raw) if raw is not None else None


def merge_sector(full: ScreenBoard, fresh: ScreenBoard) -> ScreenBoard:
    """Replace the rows belonging to fresh.scope inside the full board, then re-rank by score."""
    kept = [i for i in full.items if i.sector != fresh.scope]
    items = kept + list(fresh.items)
    items.sort(key=lambda s: s.score, reverse=True)
    return full.model_copy(update={"items": items})
```

- [ ] **Step 4: Create the scan service**

Create `backend/app/screener/service.py`:

```python
"""Run the scorer across the universe and return a ranked board (no persistence here)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.analysis import political
from app.analysis.scoring import score_stock
from app.config.cache import Cache
from app.data import truth_social
from app.data.universe import load_universe
from app.models.schemas import ScreenBoard, Settings
from app.services.stock_service import get_stock_data

SCAN_PERIOD = "1y"  # enough history for SMA200, RSI, 1-month momentum, 52-wk extremes


def run_scan(scope: str | None, settings: Settings, cache: Cache) -> ScreenBoard:
    entries = load_universe(scope)
    ts = settings.truth_signal
    posts = (
        truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
        if ts.enabled else []
    )

    items = []
    scanned = 0
    skipped = 0
    for entry in entries:
        scanned += 1
        try:
            stock = get_stock_data(entry.ticker, SCAN_PERIOD, settings.indicator_params, cache)
            mentions = political.find_mentions(posts, entry.ticker, stock.company_name)
            score = score_stock(stock, mentions, settings.screener)
            score.sector = entry.sector
            items.append(score)
        except Exception:  # noqa: BLE001 — a bad ticker must never abort the whole scan
            skipped += 1
            continue

    items.sort(key=lambda s: s.score, reverse=True)
    return ScreenBoard(
        as_of=datetime.now(timezone.utc).isoformat(),
        scope=scope or "all",
        scanned=scanned,
        skipped=skipped,
        items=items,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_screener_service.py -q`
Expected: PASS (4 passed). (The autouse conftest stub makes `posts` empty, so `find_mentions`
returns `[]` and the catalyst signal is 0 — rankings here come from the technicals.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/screener/__init__.py backend/app/screener/service.py backend/app/screener/store.py backend/tests/test_screener_service.py
git commit   # feat(backend): universe scan service + cached board snapshot store
```

---

## Task 6: Scheduled runner (`python -m app.screener`)

**Files:**
- Create: `backend/app/screener/runner.py`, `backend/app/screener/__main__.py`
- Test: `backend/tests/test_screener_runner.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_screener_runner.py`:

```python
import app.screener.runner as runner
from app.config.cache import Cache
from app.models.schemas import ScreenBoard, Settings, StockScore
from app.screener.store import load_snapshot


def test_run_saves_snapshot(tmp_path, monkeypatch):
    board = ScreenBoard(as_of="t", scope="all", scanned=1, items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=5, direction="hold")])
    monkeypatch.setattr(runner, "run_scan", lambda scope, settings, cache: board)
    cache = Cache(str(tmp_path / "c.db"))
    summary = runner.run(Settings(), cache)
    assert summary["scanned"] == 1
    assert load_snapshot(cache, "all").items[0].ticker == "AAA"


def test_run_disabled_skips_scan(tmp_path, monkeypatch):
    settings = Settings()
    settings.screener.enabled = False
    called = {"scan": False}
    monkeypatch.setattr(runner, "run_scan", lambda *a, **k: called.__setitem__("scan", True))
    summary = runner.run(settings, Cache(str(tmp_path / "c.db")))
    assert summary == {"enabled": False, "scanned": 0}
    assert called["scan"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_screener_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.screener.runner'`.

- [ ] **Step 3: Implement the runner**

Create `backend/app/screener/runner.py`:

```python
from __future__ import annotations

import logging

from app.config.cache import Cache
from app.models.schemas import Settings
from app.screener.service import run_scan
from app.screener.store import save_snapshot

logger = logging.getLogger("screener")


def run(settings: Settings, cache: Cache, scope: str | None = None) -> dict:
    if not settings.screener.enabled:
        logger.info("Screener disabled; nothing to do.")
        return {"enabled": False, "scanned": 0}
    board = run_scan(scope, settings, cache)
    save_snapshot(board, cache)
    logger.info("Scan complete: scope=%s scanned=%d skipped=%d",
                board.scope, board.scanned, board.skipped)
    return {"enabled": True, "scope": board.scope, "scanned": board.scanned, "skipped": board.skipped}
```

- [ ] **Step 4: Implement the CLI entry point**

Create `backend/app/screener/__main__.py`:

```python
from __future__ import annotations

import argparse
import logging
import os
import sys

from app.deps import DATA_DIR, get_cache, get_settings_store
from app.screener.runner import run
from app.screener.service import run_scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.screener",
        description="Scan the universe and store a ranked opportunity board.",
    )
    parser.add_argument("--sector", default=None, help="Limit the scan to one GICS sector (default: all).")
    parser.add_argument("--dry-run", action="store_true", help="Scan and log the top names, but do not save.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA_DIR, exist_ok=True)

    settings = get_settings_store().load()
    cache = get_cache()
    log = logging.getLogger("screener")
    if args.dry_run:
        board = run_scan(args.sector, settings, cache)
        log.info("Dry run: scope=%s scanned=%d skipped=%d top=%s",
                 board.scope, board.scanned, board.skipped, [i.ticker for i in board.items[:10]])
        return 0
    log.info("Done: %s", run(settings, cache, args.sector))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_screener_runner.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/screener/runner.py backend/app/screener/__main__.py backend/tests/test_screener_runner.py
git commit   # feat(backend): scheduled screener runner (python -m app.screener)
```

---

## Task 7: API routes

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_screen.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_screen.py`:

```python
from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.main import app
from app.models.schemas import ScreenBoard, Settings, StockScore
from app.screener.store import save_snapshot


class _Store:
    def load(self):
        return Settings()


def _client(cache):
    app.dependency_overrides[routes.get_settings_store] = lambda: _Store()
    app.dependency_overrides[routes.get_cache] = lambda: cache
    return TestClient(app)


def _board():
    return ScreenBoard(as_of="t", scope="all", scanned=3, skipped=0, items=[
        StockScore(ticker="AAA", name="A", sector="Tech", price=1, change_pct=0, score=90, direction="buy"),
        StockScore(ticker="BBB", name="B", sector="Energy", price=1, change_pct=0, score=80, direction="sell"),
        StockScore(ticker="CCC", name="C", sector="Tech", price=1, change_pct=0, score=70, direction="hold"),
    ])


def test_screen_empty_when_no_snapshot(tmp_path):
    client = _client(Cache(str(tmp_path / "c.db")))
    body = client.get("/api/screen").json()
    app.dependency_overrides.clear()
    assert body["items"] == [] and body["as_of"] == ""


def test_screen_returns_and_filters(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    client = _client(cache)
    all_items = client.get("/api/screen").json()["items"]
    tech = client.get("/api/screen?sector=Tech").json()["items"]
    buys = client.get("/api/screen?direction=buy").json()["items"]
    app.dependency_overrides.clear()
    assert [i["ticker"] for i in all_items] == ["AAA", "BBB", "CCC"]
    assert {i["ticker"] for i in tech} == {"AAA", "CCC"}
    assert [i["ticker"] for i in buys] == ["AAA"]


def test_screen_respects_limit(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    save_snapshot(_board(), cache)
    client = _client(cache)
    body = client.get("/api/screen?limit=2").json()
    app.dependency_overrides.clear()
    assert len(body["items"]) == 2


def test_rescan_persists_and_returns(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "c.db"))
    monkeypatch.setattr(routes, "run_scan", lambda scope, settings, cache: _board())
    client = _client(cache)
    body = client.post("/api/screen/rescan").json()
    assert body["scanned"] == 3
    again = client.get("/api/screen").json()
    app.dependency_overrides.clear()
    assert len(again["items"]) == 3  # persisted snapshot is read back


def test_sectors_endpoint(tmp_path):
    client = _client(Cache(str(tmp_path / "c.db")))
    body = client.get("/api/screen/sectors").json()
    app.dependency_overrides.clear()
    assert "Information Technology" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_screen.py -q`
Expected: FAIL — 404 (routes not defined) / `AttributeError: ... has no attribute 'run_scan'`.

- [ ] **Step 3: Add imports**

In `backend/app/api/routes.py`, add the screener imports near the existing ones (below
`from app.services.stock_service import get_stock_data`):

```python
from app.data.universe import list_sectors
from app.screener.service import run_scan
from app.screener.store import load_snapshot, merge_sector, save_snapshot
```

Add `ScreenBoard` to the existing `app.models.schemas` import block:

```python
from app.models.schemas import (
    DEFAULT_MODELS,
    AnalysisResult,
    ScreenBoard,
    Settings,
    StockData,
)
```

- [ ] **Step 4: Append the routes**

At the end of `backend/app/api/routes.py`:

```python
@router.get("/screen", response_model=ScreenBoard)
def screen(
    sector: str | None = None,
    direction: str | None = None,
    limit: int | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    board = load_snapshot(cache, "all")
    if board is None:
        return ScreenBoard()  # empty -> frontend prompts a first scan
    items = board.items
    if sector:
        items = [i for i in items if i.sector == sector]
    if direction:
        items = [i for i in items if i.direction == direction]
    return board.model_copy(update={"items": items[: (limit or settings.screener.top_n)]})


@router.post("/screen/rescan", response_model=ScreenBoard)
def screen_rescan(
    sector: str | None = None,
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> ScreenBoard:
    settings = store.load()
    board = run_scan(sector, settings, cache)
    if sector:
        full = load_snapshot(cache, "all")
        # Merge fresh sector rows into the full board if one exists; else persist as-is.
        save_snapshot(merge_sector(full, board) if full else board, cache)
    else:
        save_snapshot(board, cache)
    return board


@router.get("/screen/sectors", response_model=list[str])
def screen_sectors() -> list[str]:
    return list_sectors()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_screen.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_screen.py
git commit   # feat(backend): screen, rescan, and sectors API routes
```

---

## Task 8: Frontend — types + client + hooks

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`, `frontend/src/hooks/queries.ts`

- [ ] **Step 1: Write the failing client test**

Paste this `it(...)` block inside the existing `describe('api client', ...)` in
`frontend/src/api/client.test.ts`:

```ts
  it('getScreen builds a filtered query string', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getScreen('Energy', 'buy', 10);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/screen?');
    expect(url).toContain('sector=Energy');
    expect(url).toContain('direction=buy');
    expect(url).toContain('limit=10');
  });
```

- [ ] **Step 2: Run to verify it fails**

Run (from `frontend/`): `npm run test -- client`
Expected: FAIL — `api.getScreen is not a function`.

- [ ] **Step 3: Add the types**

In `frontend/src/types.ts`, add after `TruthSignalConfig` (the `Recommendation` type already exists):

```ts
export interface StockScore {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  change_pct: number;
  score: number;
  direction: Recommendation;
  reasons: string[];
  components: Record<string, number>;
  as_of: string;
}
export interface ScreenBoard {
  as_of: string;
  scope: string;
  scanned: number;
  skipped: number;
  items: StockScore[];
}
```

- [ ] **Step 4: Add the client methods**

In `frontend/src/api/client.ts`, add `ScreenBoard` to the type import, then add these methods to
the `api` object (after `getMood`):

```ts
  getScreen: (sector?: string, direction?: string, limit?: number) => {
    const q = new URLSearchParams();
    if (sector) q.set('sector', sector);
    if (direction) q.set('direction', direction);
    if (limit != null) q.set('limit', String(limit));
    const qs = q.toString();
    return http<ScreenBoard>(`/screen${qs ? `?${qs}` : ''}`);
  },
  rescan: (sector?: string) =>
    http<ScreenBoard>(`/screen/rescan${sector ? `?sector=${encodeURIComponent(sector)}` : ''}`, {
      method: 'POST',
    }),
  getSectors: () => http<string[]>('/screen/sectors'),
```

- [ ] **Step 5: Run the client test to verify it passes**

Run: `npm run test -- client`
Expected: PASS.

- [ ] **Step 6: Add the query hooks**

In `frontend/src/hooks/queries.ts`, append the three hooks below. No new type import is needed —
the return types are inferred from `api.getScreen` / `api.getSectors` (adding an unused
`ScreenBoard` import would fail the tsc build under `noUnusedLocals`):

```ts
export function useSectors() {
  return useQuery({ queryKey: ['sectors'], queryFn: api.getSectors });
}

export function useScreen(sector?: string, direction?: string) {
  return useQuery({
    queryKey: ['screen', sector ?? '', direction ?? ''],
    queryFn: () => api.getScreen(sector, direction),
  });
}

export function useRescan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sector?: string) => api.rescan(sector),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['screen'] }),
  });
}
```

- [ ] **Step 7: Typecheck**

Run (from `frontend/`): `npm run build`
Expected: tsc passes; vite build succeeds.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/hooks/queries.ts
git commit   # feat(frontend): screen board types, client methods, and query hooks
```

---

## Task 9: Frontend — Discover page + board + route + styles

**Files:**
- Create: `frontend/src/pages/Discover.tsx`, `frontend/src/components/DiscoverBoard.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/styles.css`

> Verified by `npm run build` (tsc) + the existing `smoke.test.ts`, matching this repo's
> frontend-verification pattern (pages have no component test today).

- [ ] **Step 1: Create the board component**

Create `frontend/src/components/DiscoverBoard.tsx`:

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

export function DiscoverBoard({ items, onAdd }: { items: StockScore[]; onAdd: (t: string) => void }) {
  const navigate = useNavigate();
  if (!items.length) return <p className="muted">No matches. Try a different sector, or hit Rescan.</p>;
  return (
    <div className="board-wrap">
      <table className="board">
        <thead>
          <tr>
            <th>#</th><th>Ticker</th><th>Company</th><th>Sector</th><th>Price</th>
            <th>Score</th><th>Call</th><th>Why</th><th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((s, i) => (
            <tr key={s.ticker} className="board-row"
                onClick={() => navigate(`/?ticker=${encodeURIComponent(s.ticker)}`)}>
              <td className="muted">{i + 1}</td>
              <td className="mono">{s.ticker}</td>
              <td>{s.name}</td>
              <td className="muted">{s.sector}</td>
              <td className="mono">{s.price.toFixed(2)}</td>
              <td>
                <div className="score-cell"><ScoreBar score={s.score} /><span>{s.score.toFixed(0)}</span></div>
              </td>
              <td><span className={`badge ${s.direction}`}>{s.direction.toUpperCase()}</span></td>
              <td>
                <div className="reasons">
                  {s.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
                </div>
              </td>
              <td>
                <button className="secondary" onClick={(e) => { e.stopPropagation(); onAdd(s.ticker); }}>
                  + Watch
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Create the Discover page**

Create `frontend/src/pages/Discover.tsx`:

```tsx
import { useState } from 'react';
import { DiscoverBoard } from '../components/DiscoverBoard';
import { useRescan, useSaveSettings, useScreen, useSectors, useSettings } from '../hooks/queries';

export default function Discover() {
  const [sector, setSector] = useState('');
  const [direction, setDirection] = useState('');
  const sectors = useSectors();
  const board = useScreen(sector || undefined, direction || undefined);
  const rescan = useRescan();
  const settings = useSettings();
  const saveSettings = useSaveSettings();

  const addToWatch = (t: string) => {
    const s = settings.data;
    if (!s || s.watchlist.includes(t)) return;
    saveSettings.mutate({ ...s, watchlist: [...s.watchlist, t] });
  };

  const data = board.data;
  const empty = data && data.items.length === 0 && data.as_of === '';

  return (
    <>
      <div className="panel commandbar">
        <div className="board-controls">
          <label>Sector
            <select value={sector} onChange={(e) => setSector(e.target.value)}>
              <option value="">All sectors</option>
              {(sectors.data ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Call
            <select value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="">Any</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
              <option value="hold">Hold</option>
            </select>
          </label>
          <span className="spacer" />
          {data && (
            <span className="muted board-asof">
              {data.as_of ? `As of ${new Date(data.as_of).toLocaleString()}` : 'No scan yet'}
              {data.scanned ? ` · ${data.scanned} scanned` : ''}
              {data.skipped ? `, ${data.skipped} skipped` : ''}
            </span>
          )}
          <button onClick={() => rescan.mutate(sector || undefined)} disabled={rescan.isPending}>
            {rescan.isPending ? 'Scanning…' : sector ? `Rescan ${sector}` : 'Rescan all'}
          </button>
        </div>
      </div>

      {board.isLoading && <p className="muted">Loading board…</p>}
      {board.isError && <p className="error">Could not load the board: {(board.error as Error).message}</p>}
      {rescan.isError && <p className="error">Rescan failed: {(rescan.error as Error).message}</p>}
      {empty && (
        <p className="muted">
          No snapshot yet — hit <b>Rescan all</b> to build today's board (scans the S&amp;P 500; a
          few minutes cold, near-instant once cached).
        </p>
      )}

      <section className="panel">
        <div className="panel-head">
          <span className="section-label">Opportunity board — click a row to deep-dive</span>
        </div>
        {data && <DiscoverBoard items={data.items} onAdd={addToWatch} />}
      </section>
    </>
  );
}
```

- [ ] **Step 3: Wire the route + nav**

In `frontend/src/App.tsx`:

Add the import:

```tsx
import Discover from './pages/Discover';
```

Add the nav link (after the Dashboard `NavLink`, before Settings):

```tsx
          <NavLink to="/discover" className={navClass}>Discover</NavLink>
```

Add the route (after the `/` route):

```tsx
          <Route path="/discover" element={<Discover />} />
```

- [ ] **Step 4: Add the board styles**

Append to `frontend/src/styles.css`:

```css
/* ----- Discover board ------------------------------------------------------ */
.board-controls { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; width: 100%; }
.board-controls > label {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--ink-faint);
}
.board-controls .spacer { flex: 1; }
.board-asof { font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.04em; }

.board-wrap { overflow-x: auto; }
.board { width: 100%; border-collapse: collapse; font-size: 13px; }
.board thead th {
  text-align: left; white-space: nowrap;
  font-family: var(--mono); font-size: 9.5px; font-weight: 500;
  letter-spacing: 0.16em; text-transform: uppercase; color: var(--ink-faint);
  padding: 8px 10px; border-bottom: 1px solid var(--hairline);
}
.board tbody td { padding: 10px; border-bottom: 1px solid var(--hairline); color: var(--ink-soft); vertical-align: middle; }
.board tbody tr:last-child td { border-bottom: 0; }
.board .mono { font-family: var(--mono); color: var(--ink); letter-spacing: 0.04em; }
.board-row { cursor: pointer; transition: background 0.15s ease; }
.board-row:hover { background: var(--gold-tint); }

.score-cell { display: flex; align-items: center; gap: 9px; }
.score-cell > span { font-family: var(--mono); font-size: 12px; color: var(--ink); min-width: 22px; }
.score-bar { position: relative; width: 70px; height: 6px; border-radius: 999px; background: rgba(255, 255, 255, 0.07); overflow: hidden; }
.score-bar > span { position: absolute; inset: 0 auto 0 0; background: linear-gradient(90deg, var(--gold-deep), var(--gold)); border-radius: 999px; }

.reasons { display: flex; flex-wrap: wrap; gap: 5px; max-width: 340px; }
.reason-chip {
  font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.02em;
  color: var(--ink-soft); background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--panel-brd); border-radius: 999px;
  padding: 2px 9px; white-space: nowrap;
}
```

- [ ] **Step 5: Typecheck + build + tests**

Run (from `frontend/`): `npm run build && npm run test`
Expected: tsc passes; vite build succeeds; existing vitest tests still pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Discover.tsx frontend/src/components/DiscoverBoard.tsx frontend/src/App.tsx frontend/src/styles.css
git commit   # feat(frontend): Discover opportunity-board page, route, and styles
```

---

## Task 10: Frontend — Dashboard deep-link from the board

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Read the query param**

In `frontend/src/pages/Dashboard.tsx`, extend the react-router import (it currently imports nothing
from the router; add it):

```tsx
import { useSearchParams } from 'react-router-dom';
```

Replace the `ticker` state initialization:

```tsx
  const [ticker, setTicker] = useState('');
```

with:

```tsx
  const [searchParams] = useSearchParams();
  const urlTicker = (searchParams.get('ticker') ?? '').toUpperCase();
  const [ticker, setTicker] = useState(urlTicker);
```

- [ ] **Step 2: React to later param changes**

Add this effect next to the existing watchlist-default effect (the one that sets
`watchlist[0]`):

```tsx
  // Select the ticker from a ?ticker= deep-link (e.g. clicked from the Discover board).
  useEffect(() => {
    if (urlTicker) setTicker(urlTicker);
  }, [urlTicker]);
```

(The existing `if (!ticker && watchlist.length) setTicker(watchlist[0])` effect still handles the
no-param case; when a `?ticker=` is present, `ticker` initializes truthy so the watchlist default
does not override it.)

- [ ] **Step 3: Typecheck + build + tests**

Run (from `frontend/`): `npm run build && npm run test`
Expected: tsc passes; build succeeds; tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit   # feat(frontend): deep-link Dashboard to a ?ticker= from the board
```

---

## Task 11: Docs + full verification

**Files:**
- Modify: `README.md` and/or `backend/README.md` (whichever documents data sources / running jobs).

- [ ] **Step 1: Document the feature**

Add a short README subsection covering:
- **Discover board** — auto-ranked S&P 500 opportunity screen (0–100 score + buy/sell/hold +
  reasons), no LLM in the board; clicking a row opens the existing per-ticker analysis.
- **The scorer** — extremes (RSI, 52-wk low), trend (golden/death cross, SMA alignment), momentum
  (1-mo return, 52-wk-high breakout), volume surge, and a Trump-mention boost; weights in
  `Settings.screener.weights`, thresholds in `rsi_low`/`rsi_high`.
- **Universe** — `app/data/sp500.json` (static; ships a starter subset across all 11 sectors;
  refresh manually, e.g. quarterly).
- **Daily snapshot** — schedule `python -m app.screener` post-close (same mechanism as
  `python -m app.alerts`); `--sector X` to scan one sector, `--dry-run` to preview. On Windows,
  add a Task Scheduler entry running the venv interpreter:
  `backend\.venv\Scripts\python.exe -m app.screener` with `Start in = backend\`.
- **API** — `GET /api/screen?sector=&direction=&limit=`, `POST /api/screen/rescan?sector=`,
  `GET /api/screen/sectors`.
- **Caveats** — decision support only (the board is a screen, not a recommendation); ranking ≠
  prediction; daily cadence (not intraday); a Trump mention boosts attention, not direction.

- [ ] **Step 2: Full backend suite**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest -q`
Expected: all green (existing 112 + the new universe/schema/scoring/service/runner/api tests).

- [ ] **Step 3: Full frontend build + tests**

Run (from `frontend/`): `npm run build && npm run test`
Expected: build clean; all vitest tests pass.

- [ ] **Step 4: Live smoke (manual, optional)**

With the backend running (`uvicorn app.main:app --reload --port 8000`):
- `python -m app.screener --dry-run` logs a ranked top-10 over the starter universe.
- `POST http://localhost:8000/api/screen/rescan` returns a populated `ScreenBoard`; a following
  `GET /api/screen?sector=Information%20Technology` returns only Tech rows, ranked.
- In the UI (`npm run dev`, port 5173): the **Discover** tab shows the board; the sector/direction
  filters work; **Rescan** refreshes; clicking a row lands on the Dashboard for that ticker;
  **+ Watch** adds it to the watchlist (visible in Settings).

- [ ] **Step 5: Commit**

```bash
git add README.md backend/README.md
git commit   # docs: document the Discover opportunity board + screener runner
```

---

## Self-review notes (coverage vs spec)

- **S&P 500 universe, sector-filterable, static file** → Task 1 (`sp500.json` + `universe.py`;
  `load_universe(sector)` + `list_sectors`). Starter subset documented; size-agnostic loader. ✅
- **0–100 score + buy/sell/hold + plain reasons, pure & no-LLM** → Tasks 3–4
  (`scoring.py`; `score_stock` blends weighted family intensities; direction from net signed). ✅
- **Signal families: extremes + trend/momentum + catalyst (Trump); news excluded; no fundamentals**
  → Task 3 helpers (RSI/52-wk-low, cross/SMA, momentum/breakout, volume, Trump mention). News is
  not fetched in the scan; fundamentals are not weighted. ✅
- **Catalyst = attention only, not a direction vote** → `_catalyst_signal`/`_volume_signal` return
  `signed=0`; `_DIRECTIONAL` excludes them; proven by
  `test_catalyst_raises_score_without_flipping_direction`. ✅
- **Daily snapshot + on-demand rescan; sector rescan merges** → Task 5 (`run_scan`, store),
  Task 6 (`python -m app.screener`), Task 7 (`POST /screen/rescan` with `merge_sector`). ✅
- **Instant board read; empty-state when no snapshot** → Task 7 `GET /screen` reads the snapshot,
  returns an empty `ScreenBoard` if none; Task 9 renders the first-scan prompt. ✅
- **Row → existing deep-dive; add-to-watchlist** → Task 9 (`navigate('/?ticker=')`, `+ Watch`),
  Task 10 (Dashboard reads `?ticker=`). The only LLM cost stays on the opened stock. ✅
- **Config (weights/thresholds/top_n), no secrets/masking** → Task 2 (`ScreenerConfig` on
  `Settings`; `merge_settings` carries it via `deepcopy`, no change needed). ✅
- **Graceful degradation: per-ticker failures skipped + counted** → Task 5
  (`test_run_scan_skips_failures`). ✅
- **Caveats / honesty** → Task 11 docs.

**Type consistency check:** `score_stock(stock, mentions, cfg) -> StockScore`,
`run_scan(scope, settings, cache) -> ScreenBoard`, `load_snapshot(cache, scope)`,
`save_snapshot(board, cache)`, and `merge_sector(full, fresh)` are called with identical
signatures in the service (Task 5), runner (Task 6), and routes (Task 7). `StockScore` /
`ScreenBoard` field names match across backend (Task 2) and frontend types (Task 8). The API
methods `getScreen`/`rescan`/`getSectors` (Task 8) match the routes `GET /screen` /
`POST /screen/rescan` / `GET /screen/sectors` (Task 7).
```