# Backend (FastAPI) Implementation Plan — AI Stocks & News Analysis

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested FastAPI service that serves US-stock price/indicator/news data and a structured, multi-provider LLM analysis (buy/sell signals + reasoning) for a swing-trading dashboard.

**Architecture:** A single Python package (`app`) with focused modules: pure indicator math, a yfinance-backed market-data layer, a Google-News-RSS news layer, a 4-provider LLM abstraction (Anthropic / OpenAI / Gemini / Ollama) behind one `complete()` interface, a central analyzer that builds the prompt and validates the LLM's JSON into a typed `AnalysisResult`, SQLite-backed settings + TTL cache, and a thin FastAPI layer exposing everything as JSON. Blocking I/O runs in FastAPI's threadpool via plain `def` routes.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, pandas/numpy, yfinance, feedparser, httpx, `anthropic`, `openai`, `google-genai`, pytest.

**Reference spec:** `docs/superpowers/specs/2026-06-02-ai-stocks-news-analysis-design.md`

---

## File Structure

All paths under `backend/`.

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, runtime + dev deps, pytest config (makes `app` importable). |
| `.env.example` | Documents `DATA_DIR` and optional provider API-key env fallbacks. |
| `app/__init__.py` | Marks package. |
| `app/main.py` | FastAPI app, CORS, router include, `/api/health`. |
| `app/models/schemas.py` | All Pydantic models + provider model defaults. The shared contract. |
| `app/analysis/indicators.py` | Pure indicator functions (SMA, RSI, 52-wk distance) + `compute_indicators`. |
| `app/data/market.py` | yfinance fetch wrappers + pure builders (candles, price, fundamentals). |
| `app/data/news.py` | Google News RSS fetch + `feedparser` parsing → `NewsItem`s. |
| `app/config/cache.py` | SQLite TTL cache (`get`/`set`). |
| `app/config/settings_store.py` | SQLite settings load/save + key masking/merge helpers. |
| `app/llm/base.py` | `LLMProvider` protocol + `LLMError`. |
| `app/llm/anthropic_provider.py` | Anthropic `complete()`. |
| `app/llm/openai_provider.py` | OpenAI `complete()`. |
| `app/llm/gemini_provider.py` | Gemini `complete()`. |
| `app/llm/ollama_provider.py` | Ollama `complete()` via httpx. |
| `app/llm/factory.py` | `build_provider(settings)` → active provider. |
| `app/analysis/analyzer.py` | Prompt building, JSON extraction, validation + repair → `AnalysisResult`. |
| `app/services/stock_service.py` | Composes market + indicators + news into `StockData`, with caching. |
| `app/deps.py` | FastAPI dependency singletons (`get_cache`, `get_settings_store`). |
| `app/api/routes.py` | All `/api/*` endpoints. |
| `tests/…` | One test module per source module above. |

---

## Task 1: Backend scaffold + health endpoint

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py` (empty)
- Test: `backend/tests/test_health.py`

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "stocks-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic>=2.6",
    "yfinance>=0.2.40",
    "pandas>=2.0",
    "numpy>=1.26",
    "feedparser>=6.0",
    "httpx>=0.27",
    "anthropic>=0.39",
    "openai>=1.40",
    "google-genai>=0.3",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI Stocks & News Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 3: Create empty `backend/app/__init__.py` and `backend/tests/__init__.py`**

Both files are empty (just create them).

- [ ] **Step 4: Write the failing test — `backend/tests/test_health.py`**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 5: Install and run**

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest tests/test_health.py -v
```
Expected: `test_health_ok PASSED`.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app backend/tests
git commit -m "feat(backend): scaffold FastAPI app with health endpoint"
```

---

## Task 2: Pydantic schemas (the shared contract)

**Files:**
- Create: `backend/app/models/__init__.py` (empty)
- Create: `backend/app/models/schemas.py`
- Test: `backend/tests/test_schemas.py`

- [ ] **Step 1: Create `backend/app/models/schemas.py`**

```python
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ProviderId = Literal["anthropic", "openai", "gemini", "ollama"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "ollama": "llama3.1",
}
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DISCLAIMER = "Not financial advice. For educational use only."


class Candle(BaseModel):
    time: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorPoint(BaseModel):
    time: str
    value: float


class Indicators(BaseModel):
    sma50: list[IndicatorPoint] = Field(default_factory=list)
    sma200: list[IndicatorPoint] = Field(default_factory=list)
    rsi14: list[IndicatorPoint] = Field(default_factory=list)
    dist_from_52wk_high_pct: Optional[float] = None


class Fundamentals(BaseModel):
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None


class PriceSummary(BaseModel):
    current: float
    change: float
    change_pct: float
    currency: str = "USD"


class NewsItem(BaseModel):
    title: str
    source: str = ""
    published_at: str = ""
    url: str = ""
    summary: str = ""


class StockData(BaseModel):
    ticker: str
    company_name: str
    as_of: str
    price: PriceSummary
    candles: list[Candle]
    fundamentals: Fundamentals
    indicators: Indicators
    news: list[NewsItem] = Field(default_factory=list)


class Signal(BaseModel):
    date: str
    action: Literal["buy", "sell"]
    price: float
    confidence: float
    reasoning: str


class AnalysisResult(BaseModel):
    ticker: str
    provider: str
    model: str
    generated_at: str
    overall_summary: str
    news_analysis: str
    sentiment: Literal["bullish", "neutral", "bearish"]
    current_recommendation: Literal["buy", "sell", "hold"]
    confidence: float
    signals: list[Signal] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class ProviderConfig(BaseModel):
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class IndicatorParams(BaseModel):
    sma_windows: list[int] = Field(default_factory=lambda: [50, 200])
    rsi_length: int = 14


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "anthropic": ProviderConfig(model=DEFAULT_MODELS["anthropic"]),
        "openai": ProviderConfig(model=DEFAULT_MODELS["openai"]),
        "gemini": ProviderConfig(model=DEFAULT_MODELS["gemini"]),
        "ollama": ProviderConfig(
            model=DEFAULT_MODELS["ollama"], base_url=DEFAULT_OLLAMA_BASE_URL
        ),
    }


class Settings(BaseModel):
    active_provider: ProviderId = "anthropic"
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)
    watchlist: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT"])
    indicator_params: IndicatorParams = Field(default_factory=IndicatorParams)
```

- [ ] **Step 2: Write the test — `backend/tests/test_schemas.py`**

```python
from app.models.schemas import Settings, Signal, StockData


def test_settings_defaults():
    s = Settings()
    assert s.active_provider == "anthropic"
    assert set(s.providers) == {"anthropic", "openai", "gemini", "ollama"}
    assert s.providers["ollama"].base_url == "http://localhost:11434"
    assert s.indicator_params.sma_windows == [50, 200]


def test_signal_round_trip():
    sig = Signal(date="2026-04-15", action="buy", price=10.0, confidence=0.7, reasoning="x")
    assert sig.model_dump()["action"] == "buy"


def test_stockdata_requires_price():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StockData(ticker="AAPL", company_name="Apple", as_of="2026-06-02")  # missing price
```

- [ ] **Step 3: Run**

Run: `cd backend && pytest tests/test_schemas.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models backend/tests/test_schemas.py
git commit -m "feat(backend): add Pydantic schemas and defaults"
```

---

## Task 3: Indicator math (pure functions)

**Files:**
- Create: `backend/app/analysis/__init__.py` (empty)
- Create: `backend/app/analysis/indicators.py`
- Test: `backend/tests/test_indicators.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_indicators.py`**

```python
import pandas as pd

from app.analysis.indicators import (
    compute_indicators,
    dist_from_52wk_high_pct,
    rsi,
    sma,
)
from app.models.schemas import IndicatorParams


def _close(values):
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


def test_sma_last_value():
    s = _close([1, 2, 3, 4, 5])
    result = sma(s, 3)
    assert result.iloc[-1] == 4.0  # mean(3,4,5)


def test_rsi_all_gains_is_100():
    s = _close(list(range(1, 40)))  # strictly increasing
    assert rsi(s, 14).iloc[-1] > 99.9


def test_rsi_all_losses_is_0():
    s = _close(list(range(40, 1, -1)))  # strictly decreasing
    assert rsi(s, 14).iloc[-1] < 0.1


def test_dist_from_52wk_high():
    highs = _close([50, 80, 100, 90])
    assert dist_from_52wk_high_pct(highs, last_close=90.0) == -10.0


def test_compute_indicators_shape():
    idx = pd.date_range("2024-01-01", periods=260, freq="D")
    df = pd.DataFrame(
        {
            "Open": range(260),
            "High": [v + 1 for v in range(260)],
            "Low": [v - 1 for v in range(260)],
            "Close": range(260),
            "Volume": [1000] * 260,
        },
        index=idx,
    ).astype("float64")
    ind = compute_indicators(df, IndicatorParams())
    assert len(ind.sma50) > 0
    assert len(ind.sma200) > 0
    assert all(0 <= p.value <= 100 for p in ind.rsi14)
    assert ind.dist_from_52wk_high_pct is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_indicators.py -v`
Expected: FAIL (`ModuleNotFoundError: app.analysis.indicators`).

- [ ] **Step 3: Create `backend/app/analysis/indicators.py`**

```python
from __future__ import annotations

import pandas as pd

from app.models.schemas import IndicatorParams, IndicatorPoint, Indicators


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    # All-gains => avg_loss 0 => rs inf => out 100 (NaN only where avg_loss is NaN too).
    out = out.where(avg_loss != 0, 100.0)
    return out


def dist_from_52wk_high_pct(high: pd.Series, last_close: float) -> float:
    window = high.tail(252)
    high_val = float(window.max())
    if high_val == 0:
        return 0.0
    return round((last_close - high_val) / high_val * 100, 2)


def _series_to_points(series: pd.Series) -> list[IndicatorPoint]:
    points: list[IndicatorPoint] = []
    for ts, value in series.dropna().items():
        points.append(
            IndicatorPoint(time=pd.Timestamp(ts).strftime("%Y-%m-%d"), value=round(float(value), 4))
        )
    return points


def compute_indicators(df: pd.DataFrame, params: IndicatorParams) -> Indicators:
    close = df["Close"].astype("float64")
    sma50_win = params.sma_windows[0] if len(params.sma_windows) > 0 else 50
    sma200_win = params.sma_windows[1] if len(params.sma_windows) > 1 else 200
    last_close = float(close.iloc[-1])
    return Indicators(
        sma50=_series_to_points(sma(close, sma50_win)),
        sma200=_series_to_points(sma(close, sma200_win)),
        rsi14=_series_to_points(rsi(close, params.rsi_length)),
        dist_from_52wk_high_pct=dist_from_52wk_high_pct(df["High"].astype("float64"), last_close),
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_indicators.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/__init__.py backend/app/analysis/indicators.py backend/tests/test_indicators.py
git commit -m "feat(backend): add pure indicator functions (SMA, RSI, 52wk distance)"
```

---

## Task 4: Market data layer (yfinance)

**Files:**
- Create: `backend/app/data/__init__.py` (empty)
- Create: `backend/app/data/market.py`
- Test: `backend/tests/test_market.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_market.py`**

```python
import pandas as pd

from app.data.market import build_candles, build_fundamentals, build_price, company_name


def _df():
    idx = pd.date_range("2026-05-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [10.5, 11.5, 12.5],
            "Low": [9.5, 10.5, 11.5],
            "Close": [10.2, 11.0, 12.0],
            "Volume": [100, 200, 300],
        },
        index=idx,
    )


def test_build_candles():
    candles = build_candles(_df())
    assert len(candles) == 3
    assert candles[0].time == "2026-05-01"
    assert candles[-1].close == 12.0


def test_build_price_change():
    price = build_price(_df())
    assert price.current == 12.0
    assert price.change == 1.0  # 12.0 - 11.0
    assert round(price.change_pct, 2) == 9.09


def test_build_fundamentals_uses_get():
    info = {"marketCap": 1000, "trailingPE": 25.0, "fiftyTwoWeekHigh": 15.0}
    f = build_fundamentals(info)
    assert f.market_cap == 1000
    assert f.pe_ratio == 25.0
    assert f.week52_high == 15.0
    assert f.eps is None


def test_company_name_fallback():
    assert company_name({"longName": "Apple Inc."}, "AAPL") == "Apple Inc."
    assert company_name({}, "AAPL") == "AAPL"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_market.py -v`
Expected: FAIL (`ModuleNotFoundError: app.data.market`).

- [ ] **Step 3: Create `backend/app/data/market.py`**

```python
from __future__ import annotations

import pandas as pd
import yfinance as yf

from app.models.schemas import Candle, Fundamentals, PriceSummary

# --- Network boundary (monkeypatched in tests) ---------------------------------


def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)


def fetch_info(ticker: str) -> dict:
    try:
        return dict(yf.Ticker(ticker).info)
    except Exception:
        return {}


# --- Pure builders -------------------------------------------------------------


def build_candles(df: pd.DataFrame) -> list[Candle]:
    candles: list[Candle] = []
    for ts, row in df.iterrows():
        candles.append(
            Candle(
                time=pd.Timestamp(ts).strftime("%Y-%m-%d"),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
        )
    return candles


def build_price(df: pd.DataFrame) -> PriceSummary:
    close = df["Close"].astype("float64")
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    change = current - prev
    change_pct = (change / prev * 100) if prev else 0.0
    return PriceSummary(current=round(current, 4), change=round(change, 4), change_pct=change_pct)


def build_fundamentals(info: dict) -> Fundamentals:
    return Fundamentals(
        market_cap=info.get("marketCap"),
        pe_ratio=info.get("trailingPE"),
        eps=info.get("trailingEps"),
        dividend_yield=info.get("dividendYield"),
        week52_high=info.get("fiftyTwoWeekHigh"),
        week52_low=info.get("fiftyTwoWeekLow"),
    )


def company_name(info: dict, ticker: str) -> str:
    return info.get("longName") or info.get("shortName") or ticker
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_market.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/__init__.py backend/app/data/market.py backend/tests/test_market.py
git commit -m "feat(backend): add yfinance market-data layer with pure builders"
```

---

## Task 5: News layer (Google News RSS)

**Files:**
- Create: `backend/app/data/news.py`
- Test: `backend/tests/test_news.py`

> Decision: Google News RSS is the primary news source (free, reliable, per-ticker). yfinance `.news` is intentionally not used due to format instability.

- [ ] **Step 1: Write the failing test — `backend/tests/test_news.py`**

```python
from app.data.news import get_news, parse_feed

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Apple hits new high - Reuters</title>
  <link>https://example.com/a</link>
  <pubDate>Mon, 01 Jun 2026 12:00:00 GMT</pubDate>
  <source url="https://reuters.com">Reuters</source>
  <description>Apple shares rose.</description>
</item>
<item>
  <title>Apple earnings preview - CNBC</title>
  <link>https://example.com/b</link>
  <pubDate>Sun, 31 May 2026 09:00:00 GMT</pubDate>
  <source url="https://cnbc.com">CNBC</source>
  <description>Preview text.</description>
</item>
</channel></rss>"""


def test_parse_feed_extracts_items():
    items = parse_feed(SAMPLE_RSS, limit=10)
    assert len(items) == 2
    assert items[0].title == "Apple hits new high - Reuters"
    assert items[0].url == "https://example.com/a"
    assert items[0].source == "Reuters"


def test_parse_feed_respects_limit():
    assert len(parse_feed(SAMPLE_RSS, limit=1)) == 1


def test_get_news_returns_empty_on_fetch_error(monkeypatch):
    def boom(_query):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.data.news._fetch_feed", boom)
    assert get_news("AAPL", "Apple Inc.") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_news.py -v`
Expected: FAIL (`ModuleNotFoundError: app.data.news`).

- [ ] **Step 3: Create `backend/app/data/news.py`**

```python
from __future__ import annotations

from urllib.parse import quote_plus

import feedparser
import httpx

from app.models.schemas import NewsItem

_RSS_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _fetch_feed(query: str) -> str:
    url = _RSS_URL.format(q=quote_plus(query))
    resp = httpx.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text


def parse_feed(xml: str, limit: int = 10) -> list[NewsItem]:
    feed = feedparser.parse(xml)
    items: list[NewsItem] = []
    for entry in feed.entries[:limit]:
        src = entry.get("source")
        source = src.get("title", "") if src else ""
        items.append(
            NewsItem(
                title=entry.get("title", ""),
                source=source,
                published_at=entry.get("published", ""),
                url=entry.get("link", ""),
                summary=entry.get("summary", ""),
            )
        )
    return items


def get_news(ticker: str, company_name: str = "", limit: int = 10) -> list[NewsItem]:
    query = f"{company_name} ({ticker}) stock" if company_name else f"{ticker} stock"
    try:
        return parse_feed(_fetch_feed(query), limit)
    except Exception:
        return []
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_news.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/news.py backend/tests/test_news.py
git commit -m "feat(backend): add Google News RSS news layer"
```

---

## Task 6: SQLite TTL cache

**Files:**
- Create: `backend/app/config/__init__.py` (empty)
- Create: `backend/app/config/cache.py`
- Test: `backend/tests/test_cache.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_cache.py`**

```python
from app.config.cache import Cache


def test_set_get_round_trip(tmp_path):
    cache = Cache(str(tmp_path / "app.db"))
    cache.set("k", "v", ttl_seconds=60)
    assert cache.get("k") == "v"


def test_missing_key_returns_none(tmp_path):
    cache = Cache(str(tmp_path / "app.db"))
    assert cache.get("nope") is None


def test_expired_key_returns_none(tmp_path):
    cache = Cache(str(tmp_path / "app.db"))
    cache.set("k", "v", ttl_seconds=-1)  # already expired
    assert cache.get("k") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_cache.py -v`
Expected: FAIL (`ModuleNotFoundError: app.config.cache`).

- [ ] **Step 3: Create `backend/app/config/cache.py`**

```python
from __future__ import annotations

import sqlite3
import time
from typing import Optional


class Cache:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at <= time.time():
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, value, expires_at),
        )
        self._conn.commit()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_cache.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config/__init__.py backend/app/config/cache.py backend/tests/test_cache.py
git commit -m "feat(backend): add SQLite TTL cache"
```

---

## Task 7: Settings store (SQLite) + masking/merge

**Files:**
- Create: `backend/app/config/settings_store.py`
- Test: `backend/tests/test_settings_store.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_settings_store.py`**

```python
from app.config.settings_store import SettingsStore, mask_settings, merge_settings
from app.models.schemas import ProviderConfig, Settings


def test_load_returns_defaults_when_empty(tmp_path):
    store = SettingsStore(str(tmp_path / "app.db"))
    s = store.load()
    assert s.active_provider == "anthropic"
    assert "ollama" in s.providers


def test_save_then_load_round_trip(tmp_path):
    store = SettingsStore(str(tmp_path / "app.db"))
    s = store.load()
    s.active_provider = "openai"
    s.providers["openai"].api_key = "sk-secret"
    store.save(s)
    reloaded = store.load()
    assert reloaded.active_provider == "openai"
    assert reloaded.providers["openai"].api_key == "sk-secret"


def test_mask_hides_keys():
    s = Settings()
    s.providers["anthropic"].api_key = "sk-secret"
    masked = mask_settings(s)
    assert masked.providers["anthropic"].api_key == "****"
    # original untouched
    assert s.providers["anthropic"].api_key == "sk-secret"


def test_merge_keeps_existing_key_when_masked():
    existing = Settings()
    existing.providers["anthropic"].api_key = "sk-real"
    incoming = Settings()
    incoming.providers["anthropic"].api_key = "****"  # sentinel: unchanged
    incoming.providers["openai"].api_key = "sk-new"
    merged = merge_settings(existing, incoming)
    assert merged.providers["anthropic"].api_key == "sk-real"
    assert merged.providers["openai"].api_key == "sk-new"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_settings_store.py -v`
Expected: FAIL (`ModuleNotFoundError: app.config.settings_store`).

- [ ] **Step 3: Create `backend/app/config/settings_store.py`**

```python
from __future__ import annotations

import copy
import sqlite3

from app.models.schemas import Settings

MASK = "****"


class SettingsStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL)"
        )
        self._conn.commit()

    def load(self) -> Settings:
        row = self._conn.execute("SELECT json FROM settings WHERE id = 1").fetchone()
        if row is None:
            return Settings()
        return Settings.model_validate_json(row[0])

    def save(self, settings: Settings) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (id, json) VALUES (1, ?)",
            (settings.model_dump_json(),),
        )
        self._conn.commit()


def mask_settings(settings: Settings) -> Settings:
    masked = copy.deepcopy(settings)
    for cfg in masked.providers.values():
        if cfg.api_key:
            cfg.api_key = MASK
    return masked


def merge_settings(existing: Settings, incoming: Settings) -> Settings:
    merged = copy.deepcopy(incoming)
    for name, cfg in merged.providers.items():
        if cfg.api_key == MASK:
            cfg.api_key = existing.providers.get(name, type(cfg)()).api_key
    return merged
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_settings_store.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config/settings_store.py backend/tests/test_settings_store.py
git commit -m "feat(backend): add SQLite settings store with key masking/merge"
```

---

## Task 8: LLM provider abstraction + 4 adapters + factory

**Files:**
- Create: `backend/app/llm/__init__.py` (empty)
- Create: `backend/app/llm/base.py`
- Create: `backend/app/llm/anthropic_provider.py`
- Create: `backend/app/llm/openai_provider.py`
- Create: `backend/app/llm/gemini_provider.py`
- Create: `backend/app/llm/ollama_provider.py`
- Create: `backend/app/llm/factory.py`
- Test: `backend/tests/test_providers.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_providers.py`**

```python
import pytest

from app.llm.factory import build_provider
from app.llm.ollama_provider import OllamaProvider
from app.models.schemas import ProviderConfig, Settings


def test_factory_builds_active_provider():
    s = Settings()
    s.active_provider = "ollama"
    provider = build_provider(s)
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"


def test_factory_unknown_provider_raises():
    from app.llm.base import LLMError

    s = Settings()
    s.active_provider = "anthropic"
    s.providers.pop("anthropic")  # simulate missing config
    with pytest.raises(LLMError):
        build_provider(s)


def test_ollama_complete_parses_message(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"ok": true}'}}

    def fake_post(url, json, timeout):
        assert url.endswith("/api/chat")
        assert json["model"] == "llama3.1"
        return FakeResp()

    monkeypatch.setattr("app.llm.ollama_provider.httpx.post", fake_post)
    provider = OllamaProvider(ProviderConfig(model="llama3.1", base_url="http://localhost:11434"))
    assert provider.complete("sys", "user") == '{"ok": true}'


def test_anthropic_complete_joins_text_blocks(monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    class Block:
        type = "text"
        text = "hello"

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["model"] == "claude-x"
            class R:
                content = [Block()]
            return R()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(
        "app.llm.anthropic_provider.Anthropic", lambda api_key: FakeClient()
    )
    provider = AnthropicProvider(ProviderConfig(model="claude-x", api_key="k"))
    assert provider.complete("sys", "user") == "hello"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_providers.py -v`
Expected: FAIL (`ModuleNotFoundError: app.llm.factory`).

- [ ] **Step 3: Create `backend/app/llm/base.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Raised when a provider cannot be built or a completion fails."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...
```

- [ ] **Step 4: Create `backend/app/llm/anthropic_provider.py`**

```python
from __future__ import annotations

from anthropic import Anthropic

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = Anthropic(api_key=cfg.api_key)

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self.client.messages.create(
                model=self.cfg.model,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Anthropic request failed: {exc}") from exc
```

- [ ] **Step 5: Create `backend/app/llm/openai_provider.py`**

```python
from __future__ import annotations

from openai import OpenAI

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class OpenAIProvider:
    name = "openai"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = OpenAI(api_key=cfg.api_key)

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"OpenAI request failed: {exc}") from exc
```

- [ ] **Step 6: Create `backend/app/llm/gemini_provider.py`**

```python
from __future__ import annotations

from google import genai
from google.genai import types

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class GeminiProvider:
    name = "gemini"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = genai.Client(api_key=cfg.api_key)

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self.client.models.generate_content(
                model=self.cfg.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                ),
            )
            return resp.text or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini request failed: {exc}") from exc
```

- [ ] **Step 7: Create `backend/app/llm/ollama_provider.py`**

```python
from __future__ import annotations

import httpx

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class OllamaProvider:
    name = "ollama"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.base_url = (cfg.base_url or "http://localhost:11434").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.cfg.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": "json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama request failed: {exc}") from exc
```

- [ ] **Step 8: Create `backend/app/llm/factory.py`**

```python
from __future__ import annotations

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMError, LLMProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_provider import OpenAIProvider
from app.models.schemas import Settings

_REGISTRY = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def build_provider(settings: Settings) -> LLMProvider:
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise LLMError(f"No configuration for provider '{provider_id}'")
    cls = _REGISTRY.get(provider_id)
    if cls is None:
        raise LLMError(f"Unknown provider '{provider_id}'")
    return cls(cfg)
```

- [ ] **Step 9: Run to verify it passes**

Run: `cd backend && pytest tests/test_providers.py -v`
Expected: 4 passed.

- [ ] **Step 10: Commit**

```bash
git add backend/app/llm backend/tests/test_providers.py
git commit -m "feat(backend): add LLM provider abstraction, 4 adapters, factory"
```

---

## Task 9: Analyzer (prompt build, JSON extract, validate + repair)

**Files:**
- Create: `backend/app/analysis/analyzer.py`
- Test: `backend/tests/test_analyzer.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_analyzer.py`**

```python
import json

from app.analysis.analyzer import analyze, build_user_prompt, extract_json
from app.models.schemas import (
    Fundamentals,
    Indicators,
    PriceSummary,
    Settings,
    StockData,
)

VALID_PAYLOAD = {
    "overall_summary": "Solid uptrend.",
    "news_analysis": "Positive earnings coverage.",
    "sentiment": "bullish",
    "current_recommendation": "buy",
    "confidence": 0.72,
    "signals": [
        {"date": "2026-04-15", "action": "buy", "price": 150.0, "confidence": 0.7, "reasoning": "Breakout."}
    ],
    "risks": ["Macro headwinds."],
}


def _stock():
    return StockData(
        ticker="AAPL",
        company_name="Apple Inc.",
        as_of="2026-06-02",
        price=PriceSummary(current=150.0, change=1.0, change_pct=0.7),
        candles=[],
        fundamentals=Fundamentals(pe_ratio=25.0),
        indicators=Indicators(dist_from_52wk_high_pct=-5.0),
        news=[],
    )


class FakeProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def test_extract_json_handles_code_fence():
    raw = "Here:\n```json\n{\"a\": 1}\n```\nthanks"
    assert extract_json(raw) == {"a": 1}


def test_build_user_prompt_mentions_ticker_and_json():
    prompt = build_user_prompt(_stock())
    assert "AAPL" in prompt
    assert "JSON" in prompt


def test_analyze_parses_valid_result():
    provider = FakeProvider([json.dumps(VALID_PAYLOAD)])
    result = analyze(_stock(), provider, model="m", provider_name="fake")
    assert result.current_recommendation == "buy"
    assert result.signals[0].date == "2026-04-15"
    assert result.ticker == "AAPL"
    assert result.provider == "fake"
    assert provider.calls == 1


def test_analyze_retries_once_on_bad_json():
    provider = FakeProvider(["not json at all", json.dumps(VALID_PAYLOAD)])
    result = analyze(_stock(), provider, model="m", provider_name="fake")
    assert result.sentiment == "bullish"
    assert provider.calls == 2


def test_analyze_raises_after_two_failures():
    import pytest

    from app.llm.base import LLMError

    provider = FakeProvider(["nope", "still nope"])
    with pytest.raises(LLMError):
        analyze(_stock(), provider, model="m", provider_name="fake")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_analyzer.py -v`
Expected: FAIL (`ModuleNotFoundError: app.analysis.analyzer`).

- [ ] **Step 3: Create `backend/app/analysis/analyzer.py`**

```python
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from app.llm.base import LLMError, LLMProvider
from app.models.schemas import DISCLAIMER, AnalysisResult, StockData

_SYSTEM_PROMPT = (
    "You are a cautious equity research assistant for a swing trader. "
    "You analyze price action, simple indicators, fundamentals, and recent news. "
    "You are NOT a guaranteed predictor; you provide reasoned decision support. "
    "Respond with ONLY a single JSON object, no prose, no code fences."
)

_JSON_SCHEMA_HINT = """Return JSON with exactly these fields:
{
  "overall_summary": string,
  "news_analysis": string,
  "sentiment": "bullish" | "neutral" | "bearish",
  "current_recommendation": "buy" | "sell" | "hold",
  "confidence": number between 0 and 1,
  "signals": [ { "date": "YYYY-MM-DD", "action": "buy" | "sell", "price": number, "confidence": number, "reasoning": string } ],
  "risks": [ string ]
}
Signal dates MUST fall within the provided price history range."""


def build_user_prompt(stock: StockData) -> str:
    rsi_latest = stock.indicators.rsi14[-1].value if stock.indicators.rsi14 else None
    sma50_latest = stock.indicators.sma50[-1].value if stock.indicators.sma50 else None
    sma200_latest = stock.indicators.sma200[-1].value if stock.indicators.sma200 else None
    date_range = (
        f"{stock.candles[0].time} to {stock.candles[-1].time}" if stock.candles else "n/a"
    )
    headlines = "\n".join(
        f"- [{n.published_at}] {n.title} ({n.source})" for n in stock.news[:10]
    ) or "- (no recent headlines found)"

    return f"""Analyze {stock.company_name} ({stock.ticker}) for a swing trader.

PRICE HISTORY: {len(stock.candles)} daily candles, {date_range}.
CURRENT PRICE: {stock.price.current} ({stock.price.change_pct:.2f}% vs prev close).

INDICATORS (latest):
- RSI(14): {rsi_latest}
- SMA50: {sma50_latest}
- SMA200: {sma200_latest}
- Distance from 52-week high: {stock.indicators.dist_from_52wk_high_pct}%

FUNDAMENTALS:
- Market cap: {stock.fundamentals.market_cap}
- P/E: {stock.fundamentals.pe_ratio}
- EPS: {stock.fundamentals.eps}
- 52wk high/low: {stock.fundamentals.week52_high} / {stock.fundamentals.week52_low}

RECENT NEWS HEADLINES:
{headlines}

{_JSON_SCHEMA_HINT}"""


def extract_json(raw: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    if not fenced:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    return json.loads(candidate)


def _to_result(payload: dict, ticker: str, provider_name: str, model: str) -> AnalysisResult:
    if not isinstance(payload, dict):
        raise TypeError("LLM response was not a JSON object")
    # Drop any reserved keys the model may have echoed, so they don't collide
    # with the values we set explicitly below.
    reserved = {"ticker", "provider", "model", "generated_at", "disclaimer"}
    fields = {k: v for k, v in payload.items() if k not in reserved}
    return AnalysisResult(
        ticker=ticker,
        provider=provider_name,
        model=model,
        generated_at=datetime.now(timezone.utc).isoformat(),
        disclaimer=DISCLAIMER,
        **fields,
    )


def analyze(
    stock: StockData, provider: LLMProvider, model: str, provider_name: str
) -> AnalysisResult:
    system = _SYSTEM_PROMPT
    user = build_user_prompt(stock)

    raw = provider.complete(system, user)
    try:
        return _to_result(extract_json(raw), stock.ticker, provider_name, model)
    except (json.JSONDecodeError, ValidationError, TypeError):
        pass  # fall through to one repair attempt

    repair = (
        user
        + "\n\nYour previous reply was not valid JSON for the schema. "
        "Reply with ONLY the corrected JSON object."
    )
    raw2 = provider.complete(system, repair)
    try:
        return _to_result(extract_json(raw2), stock.ticker, provider_name, model)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise LLMError(f"Model did not return valid analysis JSON: {exc}") from exc
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_analyzer.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/analyzer.py backend/tests/test_analyzer.py
git commit -m "feat(backend): add analyzer with prompt build, JSON extraction, repair retry"
```

---

## Task 10: Stock-data service (compose + cache)

**Files:**
- Create: `backend/app/services/__init__.py` (empty)
- Create: `backend/app/services/stock_service.py`
- Test: `backend/tests/test_stock_service.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_stock_service.py`**

```python
import pandas as pd

from app.config.cache import Cache
from app.models.schemas import IndicatorParams
from app.services import stock_service


def _df():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    return pd.DataFrame(
        {
            "Open": range(60),
            "High": [v + 1 for v in range(60)],
            "Low": [v - 1 for v in range(60)],
            "Close": range(60),
            "Volume": [1000] * 60,
        },
        index=idx,
    ).astype("float64")


def test_get_stock_data_composes_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple Inc."})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])

    cache = Cache(str(tmp_path / "app.db"))
    data = stock_service.get_stock_data("AAPL", "2y", IndicatorParams(), cache)

    assert data.ticker == "AAPL"
    assert data.company_name == "Apple Inc."
    assert len(data.candles) == 60
    assert len(data.indicators.sma50) > 0
    # Second call should hit cache even if fetch now raises.
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: (_ for _ in ()).throw(RuntimeError("no net")))
    again = stock_service.get_stock_data("AAPL", "2y", IndicatorParams(), cache)
    assert again.ticker == "AAPL"


def test_get_stock_data_empty_history_raises(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: pd.DataFrame())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    cache = Cache(str(tmp_path / "app.db"))
    with pytest.raises(ValueError):
        stock_service.get_stock_data("BADTICKER", "2y", IndicatorParams(), cache)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_stock_service.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.stock_service`).

- [ ] **Step 3: Create `backend/app/services/stock_service.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.indicators import compute_indicators
from app.config.cache import Cache
from app.data.market import (
    build_candles,
    build_fundamentals,
    build_price,
    company_name,
    fetch_history,
    fetch_info,
)
from app.data.news import get_news
from app.models.schemas import IndicatorParams, StockData

STOCK_TTL_SECONDS = 30 * 60  # 30 minutes


def get_stock_data(
    ticker: str,
    period: str,
    params: IndicatorParams,
    cache: Cache,
) -> StockData:
    ticker = ticker.upper().strip()
    cache_key = f"stock:{ticker}:{period}"
    cached = cache.get(cache_key)
    if cached is not None:
        return StockData.model_validate_json(cached)

    df = fetch_history(ticker, period)
    if df is None or df.empty:
        raise ValueError(f"No price history for ticker '{ticker}'")

    info = fetch_info(ticker)
    name = company_name(info, ticker)
    data = StockData(
        ticker=ticker,
        company_name=name,
        as_of=datetime.now(timezone.utc).isoformat(),
        price=build_price(df),
        candles=build_candles(df),
        fundamentals=build_fundamentals(info),
        indicators=compute_indicators(df, params),
        news=get_news(ticker, name, limit=10),
    )
    cache.set(cache_key, data.model_dump_json(), STOCK_TTL_SECONDS)
    return data
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_stock_service.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services backend/tests/test_stock_service.py
git commit -m "feat(backend): add stock-data service composing market+indicators+news with cache"
```

---

## Task 11: Dependencies + analyze service helper

**Files:**
- Create: `backend/app/deps.py`
- Create: `backend/app/services/analysis_service.py`
- Test: `backend/tests/test_analysis_service.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_analysis_service.py`**

```python
import json

from app.config.cache import Cache
from app.models.schemas import (
    Fundamentals,
    Indicators,
    PriceSummary,
    Settings,
    StockData,
)
from app.services import analysis_service

PAYLOAD = {
    "overall_summary": "ok",
    "news_analysis": "ok",
    "sentiment": "neutral",
    "current_recommendation": "hold",
    "confidence": 0.5,
    "signals": [],
    "risks": [],
}


def _stock():
    return StockData(
        ticker="AAPL",
        company_name="Apple Inc.",
        as_of="2026-06-02",
        price=PriceSummary(current=1.0, change=0.0, change_pct=0.0),
        candles=[],
        fundamentals=Fundamentals(),
        indicators=Indicators(),
        news=[],
    )


class FakeProvider:
    name = "fake"

    def complete(self, system, user):
        return json.dumps(PAYLOAD)


def test_run_analysis_uses_provider_and_caches(tmp_path, monkeypatch):
    settings = Settings()
    settings.active_provider = "anthropic"
    settings.providers["anthropic"].model = "claude-x"
    settings.providers["anthropic"].api_key = "k"  # key-check passes before cache path

    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())

    cache = Cache(str(tmp_path / "app.db"))
    result = analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert result.current_recommendation == "hold"
    assert result.provider == "anthropic"
    assert result.model == "claude-x"

    # Cached: even if provider now blows up, cached value returns.
    def boom(_s):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(analysis_service, "build_provider", boom)
    again = analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert again.current_recommendation == "hold"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_analysis_service.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.analysis_service`).

- [ ] **Step 3: Create `backend/app/deps.py`**

```python
from __future__ import annotations

import os
from functools import lru_cache

from app.config.cache import Cache
from app.config.settings_store import SettingsStore

DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "app.db")


@lru_cache
def get_cache() -> Cache:
    os.makedirs(DATA_DIR, exist_ok=True)
    return Cache(DB_PATH)


@lru_cache
def get_settings_store() -> SettingsStore:
    os.makedirs(DATA_DIR, exist_ok=True)
    return SettingsStore(DB_PATH)
```

- [ ] **Step 4: Create `backend/app/services/analysis_service.py`**

```python
from __future__ import annotations

from datetime import date

from app.analysis.analyzer import analyze
from app.config.cache import Cache
from app.llm.base import LLMError
from app.llm.factory import build_provider
from app.models.schemas import AnalysisResult, Settings
from app.services.stock_service import get_stock_data

ANALYSIS_TTL_SECONDS = 24 * 60 * 60  # 1 day


def run_analysis(ticker: str, period: str, settings: Settings, cache: Cache) -> AnalysisResult:
    ticker = ticker.upper().strip()
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise LLMError(f"No configuration for provider '{provider_id}'")
    if provider_id != "ollama" and not cfg.api_key:
        raise LLMError(f"Missing API key for provider '{provider_id}'. Set it in Settings.")

    cache_key = f"analysis:{ticker}:{provider_id}:{cfg.model}:{date.today().isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return AnalysisResult.model_validate_json(cached)

    stock = get_stock_data(ticker, period, settings.indicator_params, cache)
    provider = build_provider(settings)
    result = analyze(stock, provider, model=cfg.model, provider_name=provider_id)
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    return result
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && pytest tests/test_analysis_service.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/deps.py backend/app/services/analysis_service.py backend/tests/test_analysis_service.py
git commit -m "feat(backend): add deps and analysis orchestration service"
```

---

## Task 12: API routes — stock, analyze, settings, providers

**Files:**
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/api/routes.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Create `backend/app/api/routes.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.config.cache import Cache
from app.config.settings_store import SettingsStore, mask_settings, merge_settings
from app.deps import get_cache, get_settings_store
from app.llm.base import LLMError
from app.models.schemas import (
    DEFAULT_MODELS,
    AnalysisResult,
    Settings,
    StockData,
)
from app.services.analysis_service import run_analysis
from app.services.stock_service import get_stock_data

router = APIRouter(prefix="/api")

_PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "ollama": "Ollama (local)",
}


@router.get("/stock/{ticker}", response_model=StockData)
def stock(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> StockData:
    settings = store.load()
    try:
        return get_stock_data(ticker, period, settings.indicator_params, cache)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/analyze/{ticker}", response_model=AnalysisResult)
def analyze_ticker(
    ticker: str,
    period: str = "2y",
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> AnalysisResult:
    settings = store.load()
    try:
        return run_analysis(ticker, period, settings, cache)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/settings", response_model=Settings)
def read_settings(store: SettingsStore = Depends(get_settings_store)) -> Settings:
    return mask_settings(store.load())


@router.put("/settings", response_model=Settings)
def update_settings(
    incoming: Settings, store: SettingsStore = Depends(get_settings_store)
) -> Settings:
    merged = merge_settings(store.load(), incoming)
    store.save(merged)
    return mask_settings(merged)


@router.get("/providers")
def list_providers(store: SettingsStore = Depends(get_settings_store)) -> list[dict]:
    settings = store.load()
    out = []
    for pid, label in _PROVIDER_LABELS.items():
        cfg = settings.providers.get(pid)
        configured = bool(cfg and (cfg.api_key or pid == "ollama"))
        out.append(
            {
                "id": pid,
                "label": label,
                "configured": configured,
                "default_model": DEFAULT_MODELS[pid],
            }
        )
    return out
```

- [ ] **Step 2: Modify `backend/app/main.py` to include the router**

Add the import and `include_router` call (place the import with the others, and the include after `add_middleware`):

```python
from app.api.routes import router as api_router

# ... after app.add_middleware(...):
app.include_router(api_router)
```

- [ ] **Step 3: Write the test — `backend/tests/test_api.py`**

```python
import json

import pandas as pd
from fastapi.testclient import TestClient

from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_settings_store
from app.main import app
from app.services import analysis_service, stock_service


def _client(tmp_path):
    cache = Cache(str(tmp_path / "cache.db"))
    store = SettingsStore(str(tmp_path / "settings.db"))
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_settings_store] = lambda: store
    return TestClient(app), store


def _df():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    return pd.DataFrame(
        {
            "Open": range(60),
            "High": [v + 1 for v in range(60)],
            "Low": [v - 1 for v in range(60)],
            "Close": range(60),
            "Volume": [1000] * 60,
        },
        index=idx,
    ).astype("float64")


def teardown_function():
    app.dependency_overrides.clear()


def test_get_stock(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple Inc."})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    client, _ = _client(tmp_path)

    resp = client.get("/api/stock/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert len(body["candles"]) == 60


def test_get_stock_bad_ticker_404(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: pd.DataFrame())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    client, _ = _client(tmp_path)
    assert client.get("/api/stock/NOPE").status_code == 404


def test_settings_put_masks_keys_and_persists(tmp_path):
    client, store = _client(tmp_path)
    payload = client.get("/api/settings").json()
    payload["active_provider"] = "openai"
    payload["providers"]["openai"]["api_key"] = "sk-secret"

    resp = client.put("/api/settings", json=payload)
    assert resp.status_code == 200
    assert resp.json()["providers"]["openai"]["api_key"] == "****"
    # Persisted real key is retrievable from the store directly.
    assert store.load().providers["openai"].api_key == "sk-secret"


def test_settings_put_keeps_existing_key_when_masked(tmp_path):
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["openai"].api_key = "sk-real"
    store.save(s)

    payload = client.get("/api/settings").json()  # openai key comes back as "****"
    payload["active_provider"] = "openai"
    client.put("/api/settings", json=payload)
    assert store.load().providers["openai"].api_key == "sk-real"


def test_analyze_missing_key_returns_502(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple"})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    client, store = _client(tmp_path)
    # default active_provider=anthropic with empty key -> 502
    assert client.post("/api/analyze/AAPL").status_code == 502


def test_analyze_success(tmp_path, monkeypatch):
    payload = {
        "overall_summary": "ok",
        "news_analysis": "ok",
        "sentiment": "neutral",
        "current_recommendation": "hold",
        "confidence": 0.5,
        "signals": [],
        "risks": [],
    }

    class FakeProvider:
        name = "fake"

        def complete(self, system, user):
            return json.dumps(payload)

    monkeypatch.setattr(stock_service, "fetch_history", lambda t, period: _df())
    monkeypatch.setattr(stock_service, "fetch_info", lambda t: {"longName": "Apple"})
    monkeypatch.setattr(stock_service, "get_news", lambda t, c, limit=10: [])
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())

    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.post("/api/analyze/AAPL")
    assert resp.status_code == 200
    assert resp.json()["current_recommendation"] == "hold"


def test_list_providers(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert ids == {"anthropic", "openai", "gemini", "ollama"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_api.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_api.py
git commit -m "feat(backend): add stock/analyze/settings/providers API routes"
```

---

## Task 13: Provider connection-test endpoint

**Files:**
- Modify: `backend/app/api/routes.py` (add `POST /api/providers/{provider_id}/test`)
- Test: `backend/tests/test_api_provider_test.py`

- [ ] **Step 1: Write the failing test — `backend/tests/test_api_provider_test.py`**

```python
from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.config.settings_store import SettingsStore
from app.deps import get_cache, get_settings_store
from app.main import app


def _client(tmp_path):
    app.dependency_overrides[get_cache] = lambda: Cache(str(tmp_path / "c.db"))
    store = SettingsStore(str(tmp_path / "s.db"))
    app.dependency_overrides[get_settings_store] = lambda: store
    return TestClient(app), store


def teardown_function():
    app.dependency_overrides.clear()


def test_provider_test_ok(tmp_path, monkeypatch):
    class FakeProvider:
        name = "anthropic"

        def __init__(self, cfg):
            pass

        def complete(self, system, user):
            return "pong"

    monkeypatch.setattr(routes, "build_provider", lambda s: FakeProvider(None))
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.post("/api/providers/anthropic/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_provider_test_failure_reports_message(tmp_path, monkeypatch):
    from app.llm.base import LLMError

    def boom(_s):
        raise LLMError("bad key")

    monkeypatch.setattr(routes, "build_provider", boom)
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.post("/api/providers/anthropic/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "bad key" in resp.json()["message"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_api_provider_test.py -v`
Expected: FAIL (404 — route not defined yet).

- [ ] **Step 3: Edit `backend/app/api/routes.py`**

Add `build_provider` to the imports near the top:

```python
from app.llm.factory import build_provider
```

Then append this route at the end of the file:

```python
@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: str, store: SettingsStore = Depends(get_settings_store)
) -> dict:
    settings = store.load()
    if provider_id not in settings.providers:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    settings.active_provider = provider_id  # type: ignore[assignment]
    try:
        provider = build_provider(settings)
        provider.complete("You are a connection test.", "Reply with the single word: ok")
        return {"ok": True, "message": "Connection succeeded."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_api_provider_test.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_provider_test.py
git commit -m "feat(backend): add provider connection-test endpoint"
```

---

## Task 14: Env example, README, full test run, manual smoke

**Files:**
- Create: `backend/.env.example`
- Create: `backend/README.md`

- [ ] **Step 1: Create `backend/.env.example`**

```bash
# Where the SQLite settings + cache DB lives (relative to backend/). Default: data
DATA_DIR=data

# Optional fallbacks — normally you set these in the app's Settings page instead.
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# GEMINI_API_KEY=
# OLLAMA_BASE_URL=http://localhost:11434
```

- [ ] **Step 2: Create `backend/README.md`**

```markdown
# Backend — AI Stocks & News Analysis

FastAPI service: US-stock data + indicators + news + multi-provider LLM analysis.

## Setup

    cd backend
    python -m venv .venv
    .venv\Scripts\Activate.ps1      # PowerShell  (macOS/Linux: source .venv/bin/activate)
    pip install -e ".[dev]"

## Run

    uvicorn app.main:app --reload --port 8000

Open http://localhost:8000/docs for interactive API docs.

## Test

    pytest -v

## Configure providers

Provider keys/models are set via `PUT /api/settings` (the frontend Settings page),
stored in SQLite under `DATA_DIR` (gitignored). For local Ollama, run `ollama serve`
and pull a model (e.g. `ollama pull llama3.1`); no API key needed.

## Endpoints

- `GET  /api/health`
- `GET  /api/stock/{ticker}?period=2y`
- `POST /api/analyze/{ticker}?period=2y`
- `GET  /api/settings` · `PUT /api/settings`
- `GET  /api/providers` · `POST /api/providers/{id}/test`
```

- [ ] **Step 3: Run the entire backend test suite**

Run: `cd backend && pytest -v`
Expected: all tests from Tasks 1–13 pass (≈ 45 tests), zero failures.

- [ ] **Step 4: Manual smoke test (real network — optional but recommended)**

```bash
cd backend
uvicorn app.main:app --port 8000
# In a second terminal:
curl "http://localhost:8000/api/health"
curl "http://localhost:8000/api/stock/AAPL?period=6mo"
```
Expected: health returns `{"status":"ok"}`; stock returns JSON with `candles`, `indicators`, `news`. (Analysis requires a configured provider key.)

- [ ] **Step 5: Commit**

```bash
git add backend/.env.example backend/README.md
git commit -m "docs(backend): add env example and README"
```

---

## Done — backend complete

At this point the backend is a working, fully-tested REST API. The frontend
(Plan 2) will be written against this running service so its TypeScript types and
API calls match the real responses. Run the backend with `uvicorn app.main:app
--reload --port 8000` while building the frontend.
