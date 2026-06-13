# Pluggable news provider (MCP) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the news that powers Graph **Expand neighbours** come from a user-selectable provider — Google News RSS (default) or a Tavily/Exa/you.com **MCP** server — configured in Settings.

**Architecture:** A `NewsProvider` abstraction mirroring `app/llm/` (protocol + concrete providers + factory with env-key fallback + masked keys + a test-connection endpoint). MCP providers share one streamable-HTTP client helper (official `mcp` SDK) and differ only in endpoint/auth/tool/result-mapping. `build_company_graph` fetches via the active provider. Recency is enforced uniformly by a pure `recent_news` filter.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic / `mcp` SDK (new dep); React + TS + Vitest.

**Spec:** `docs/superpowers/specs/2026-06-13-pluggable-news-provider-design.md`

**Conventions:** Conventional Commits, **no `Co-Authored-By` trailer**. Backend tests: from `backend/`, `.venv/Scripts/python.exe -m pytest -q <path>`. Frontend: from `frontend/`, `./node_modules/.bin/vitest run <path>`. The whole suite is sandboxed by `tests/conftest.py` (temp `DATA_DIR`).

**Field mappings (verified against live docs 2026-06-13):**
- Tavily — URL `https://mcp.tavily.com/mcp/?tavilyApiKey=<key>`, tool `tavily_search`, args `{query, max_results, topic:"news", days}`; result `results[]` items `{title, url, content, published_date}`.
- Exa — URL `https://mcp.exa.ai/mcp`, header `x-api-key`, tool `web_search_exa`, args `{query, numResults}`; result `results[]` items `{title, url, text, publishedDate, author}`.
- you.com — URL `https://api.you.com/mcp`, header `Authorization: Bearer <key>` (env `YDC_API_KEY`), tool `you-search`, args `{query}`; result `{web:[…], news:[…]}` items `{title, url, description, snippets[], page_age}`.

**⚠️ Live-verification caveat:** the MCP adapters are unit-tested against these *documented* result shapes with the MCP transport **mocked** (no API keys needed to build). The exact text a live MCP tool returns can only be confirmed with real keys — **Task 17** is the human acceptance gate, and a provider whose live output differs will need a small tweak to its `_parse`.

---

## File Structure

**Backend**
- `backend/pyproject.toml` — add `mcp` dependency.
- `backend/app/data/news.py` — add pure `recent_news` + `_parse_date`.
- `backend/app/models/schemas.py` — `NewsProviderId`, `NEWS_DEFAULT_MCP_URLS`, `NewsProviderConfig`, `_default_news_providers`, `NewsConfig`; `Settings.news` + validator backfill.
- `backend/app/config/settings_store.py` — mask/merge news keys.
- `backend/app/news/__init__.py` — package marker.
- `backend/app/news/base.py` — `NewsProvider` protocol, `NewsError`, `host_of`.
- `backend/app/news/google.py` — `GoogleNewsProvider`.
- `backend/app/news/mcp_client.py` — `call_tool_text` streamable-HTTP helper.
- `backend/app/news/tavily.py` / `exa.py` / `you.py` — MCP adapters.
- `backend/app/news/factory.py` — registry, env keys, labels, `resolve_news_config`, `build_news_provider`.
- `backend/app/api/routes.py` — `GET /api/news/providers`, `GET /api/news/test`.
- `backend/app/network/service.py` — repoint `build_company_graph`.

**Frontend**
- `frontend/src/types.ts` — `NewsProviderId`, `NewsProviderConfig`, `NewsConfig`, `NewsProviderInfo`, `Settings.news`.
- `frontend/src/api/client.ts` — `getNewsProviders`, `testNews`.
- `frontend/src/hooks/queries.ts` — `useNewsProviders`.
- `frontend/src/pages/Settings.tsx` — "News source" section + `updateNews`.

---

## Task 1: `mcp` dependency + `recent_news` helper

**Files:** Modify `backend/pyproject.toml`; Modify `backend/app/data/news.py`; Test `backend/tests/test_news_recency.py`

- [ ] **Step 1: Add the dependency.** In `backend/pyproject.toml`, add `"mcp>=1.0"` to the `dependencies` array (next to `httpx`, `feedparser`). Then from `backend/`: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`. Expected: `mcp` installs (pure-Python; fine on Windows/ARM64).

- [ ] **Step 2: Write the failing test** — create `backend/tests/test_news_recency.py`:

```python
from datetime import datetime, timezone
from app.data.news import recent_news
from app.models.schemas import NewsItem

NOW = datetime(2026, 6, 13, tzinfo=timezone.utc)

def _item(title, published_at):
    return NewsItem(title=title, source="", published_at=published_at, url=f"http://x/{title}", summary="")

def test_drops_old_and_sorts_newest_first_rfc822():
    items = [
        _item("old", "Tue, 01 Jan 2026 12:00:00 GMT"),
        _item("fresh", "Wed, 10 Jun 2026 12:00:00 GMT"),
    ]
    out = recent_news(items, days=90, now=NOW)
    assert [i.title for i in out] == ["fresh"]

def test_parses_iso_dates():
    items = [_item("iso", "2026-06-10T12:00:00Z")]
    assert [i.title for i in recent_news(items, days=90, now=NOW)] == ["iso"]

def test_keeps_unparseable_dates_sorted_last():
    items = [_item("nodate", "garbage"), _item("fresh", "2026-06-12T00:00:00Z")]
    out = recent_news(items, days=90, now=NOW)
    assert [i.title for i in out] == ["fresh", "nodate"]

def test_days_zero_disables_cutoff():
    items = [_item("old", "Tue, 01 Jan 2020 12:00:00 GMT")]
    assert len(recent_news(items, days=0, now=NOW)) == 1
```

- [ ] **Step 3: Run — expect FAIL.** From `backend/`: `.venv/Scripts/python.exe -m pytest -q tests/test_news_recency.py`. Expected: ImportError (`recent_news` not defined).

- [ ] **Step 4: Implement** — append to `backend/app/data/news.py`:

```python
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    d = None
    try:
        d = parsedate_to_datetime(s)          # RFC-822 (Google News RSS)
    except Exception:  # noqa: BLE001
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))  # ISO-8601 (Exa/you.com)
        except Exception:  # noqa: BLE001
            return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def recent_news(items: list[NewsItem], *, days: int, now: datetime | None = None) -> list[NewsItem]:
    """Drop items older than `days`, newest-first; unparseable dates are kept and sorted last.
    `days <= 0` disables the cutoff (keep all, just sorted). Pure (pass `now` in tests)."""
    now = now or datetime.now(timezone.utc)
    kept = items
    if days and days > 0:
        cutoff = now.timestamp() - days * 86400
        kept = [it for it in items if (_parse_date(it.published_at) is None
                                       or _parse_date(it.published_at).timestamp() >= cutoff)]

    def _key(it: NewsItem) -> float:
        d = _parse_date(it.published_at)
        return d.timestamp() if d else float("-inf")

    return sorted(kept, key=_key, reverse=True)
```

- [ ] **Step 5: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_recency.py`. Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/data/news.py backend/tests/test_news_recency.py
git commit -m "feat(backend): mcp dependency + recent_news recency filter"
```

---

## Task 2: `NewsConfig` schema + validator backfill

**Files:** Modify `backend/app/models/schemas.py`; Test `backend/tests/test_news_config.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_news_config.py`:

```python
from app.models.schemas import NewsConfig, NewsProviderConfig, Settings

def test_news_defaults():
    n = NewsConfig()
    assert n.active_provider == "google"
    assert n.news_recency_days == 90
    assert set(n.providers) == {"google", "tavily", "exa", "you"}

def test_settings_has_news_and_validator_backfills_missing_providers():
    s = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key="k")}))
    assert set(s.news.providers) == {"google", "tavily", "exa", "you"}
    assert s.news.providers["tavily"].api_key == "k"

def test_settings_default_news_is_google():
    assert Settings().news.active_provider == "google"
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_config.py`. Expected: ImportError (`NewsConfig`).

- [ ] **Step 3: Implement** — in `backend/app/models/schemas.py`, after the `NetworkConfig` class add:

```python
NewsProviderId = Literal["google", "tavily", "exa", "you"]

NEWS_DEFAULT_MCP_URLS: dict[str, str] = {
    "tavily": "https://mcp.tavily.com/mcp/",
    "exa": "https://mcp.exa.ai/mcp",
    "you": "https://api.you.com/mcp",
}


class NewsProviderConfig(BaseModel):
    api_key: str = ""
    mcp_url: str = ""          # optional endpoint override; empty -> NEWS_DEFAULT_MCP_URLS


def _default_news_providers() -> dict[str, NewsProviderConfig]:
    return {pid: NewsProviderConfig() for pid in ("google", "tavily", "exa", "you")}


class NewsConfig(BaseModel):
    active_provider: NewsProviderId = "google"
    providers: dict[str, NewsProviderConfig] = Field(default_factory=_default_news_providers)
    news_recency_days: int = 90
```

Then add the field to `Settings` (after `network: NetworkConfig = …`):

```python
    news: NewsConfig = Field(default_factory=NewsConfig)
```

And extend the existing `_ensure_all_providers` validator body (before `return self`):

```python
        for pid, cfg in _default_news_providers().items():
            self.news.providers.setdefault(pid, cfg)
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_config.py`. Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_news_config.py
git commit -m "feat(backend): NewsConfig settings schema + validator backfill"
```

---

## Task 3: Mask + merge the news API keys

**Files:** Modify `backend/app/config/settings_store.py`; Test `backend/tests/test_settings_store.py` (add to it, or create if absent)

- [ ] **Step 1: Write the failing test** — add to `backend/tests/test_settings_store.py`:

```python
from app.config.settings_store import MASK, mask_settings, merge_settings
from app.models.schemas import NewsConfig, NewsProviderConfig, Settings

def test_mask_hides_news_keys():
    s = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key="secret")}))
    assert mask_settings(s).news.providers["tavily"].api_key == MASK

def test_merge_restores_masked_news_key():
    existing = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key="secret")}))
    incoming = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key=MASK)}))
    assert merge_settings(existing, incoming).news.providers["tavily"].api_key == "secret"
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_settings_store.py`. Expected: AssertionError (news key not masked).

- [ ] **Step 3: Implement** — in `backend/app/config/settings_store.py`, inside `mask_settings`, before `return masked`:

```python
    for cfg in masked.news.providers.values():
        if cfg.api_key:
            cfg.api_key = MASK
```

And inside `merge_settings`, before `return merged`:

```python
    for name, cfg in merged.news.providers.items():
        if cfg.api_key == MASK:
            cfg.api_key = existing.news.providers.get(name, type(cfg)()).api_key
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_settings_store.py`. Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config/settings_store.py backend/tests/test_settings_store.py
git commit -m "feat(backend): mask + merge news provider API keys"
```

---

## Task 4: News provider base (protocol, error, host_of)

**Files:** Create `backend/app/news/__init__.py`, `backend/app/news/base.py`; Test `backend/tests/test_news_base.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_news_base.py`:

```python
from app.news.base import NewsError, host_of

def test_host_of_strips_www():
    assert host_of("https://www.reuters.com/path") == "reuters.com"
    assert host_of("https://finance.yahoo.com/x") == "finance.yahoo.com"
    assert host_of("not a url") == ""

def test_news_error_is_exception():
    assert issubclass(NewsError, Exception)
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_base.py`. Expected: ModuleNotFoundError (`app.news`).

- [ ] **Step 3: Implement** — create `backend/app/news/__init__.py` (empty), and `backend/app/news/base.py`:

```python
"""News provider abstraction: one interface, many sources (Google RSS / MCP search servers)."""
from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from app.models.schemas import NewsItem


class NewsError(Exception):
    """Any news-fetch failure; callers degrade to an empty list."""


class NewsProvider(Protocol):
    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]: ...


def host_of(url: str) -> str:
    """The display host for a result URL ('www.' stripped); '' when unparseable."""
    try:
        net = urlparse(url).netloc
    except Exception:  # noqa: BLE001
        return ""
    return net[4:] if net.startswith("www.") else net
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_base.py`. Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/news/__init__.py backend/app/news/base.py backend/tests/test_news_base.py
git commit -m "feat(backend): NewsProvider base interface + host_of"
```

---

## Task 5: GoogleNewsProvider (default)

**Files:** Create `backend/app/news/google.py`; Test `backend/tests/test_news_google.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_news_google.py`:

```python
from app.models.schemas import NewsItem, NewsProviderConfig
from app.news import google as gmod
from app.news.google import GoogleNewsProvider

def test_google_provider_searches_and_applies_recency(monkeypatch):
    captured = {}
    def fake_search_news(query, limit):
        captured["query"], captured["limit"] = query, limit
        return [NewsItem(title="A", source="", published_at="2026-06-10T00:00:00Z", url="http://a", summary="s")]
    monkeypatch.setattr(gmod, "search_news", fake_search_news)
    out = GoogleNewsProvider(NewsProviderConfig()).search("NVDA stock", limit=7, recency_days=3650)
    assert captured == {"query": "NVDA stock", "limit": 7}
    assert [i.title for i in out] == ["A"]
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_google.py`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement** — create `backend/app/news/google.py`:

```python
"""Default provider: Google News RSS (reuses data/news.search_news) + the recency filter."""
from __future__ import annotations

from app.data.news import recent_news, search_news
from app.models.schemas import NewsItem, NewsProviderConfig


class GoogleNewsProvider:
    label = "Google News"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg  # Google needs no key

    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]:
        return recent_news(search_news(query, limit), days=recency_days)
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_google.py`. Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/news/google.py backend/tests/test_news_google.py
git commit -m "feat(backend): GoogleNewsProvider (default source)"
```

---

## Task 6: Shared MCP streamable-HTTP client helper

**Files:** Create `backend/app/news/mcp_client.py` (no unit test — thin transport glue; covered by Task 17 live verification)

- [ ] **Step 1: Implement** — create `backend/app/news/mcp_client.py`:

```python
"""One helper to call a single tool on a hosted streamable-HTTP MCP server and return its text.

Sync wrapper: the explorer fetch path is a sync FastAPI route (runs in Starlette's threadpool,
so no event loop is running in this thread) -> asyncio.run is safe. `mcp` is imported lazily so
modules that monkeypatch this helper in tests don't require the SDK at import time."""
from __future__ import annotations

import asyncio

from app.news.base import NewsError


def call_tool_text(
    url: str, tool: str, arguments: dict, *, headers: dict | None = None, timeout: float = 20.0
) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def _run() -> str:
        async with streamablehttp_client(url, headers=headers or {}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments=arguments)
                parts = [
                    getattr(c, "text", "")
                    for c in (result.content or [])
                    if getattr(c, "type", "") == "text"
                ]
                return "\n".join(p for p in parts if p)

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout))
    except Exception as e:  # noqa: BLE001 — any transport/protocol/timeout error -> NewsError
        raise NewsError(f"MCP call failed: {e}") from e
```

- [ ] **Step 2: Sanity import.** From `backend/`: `.venv/Scripts/python.exe -c "import app.news.mcp_client"`. Expected: no output (imports clean; `mcp` is only imported when called).

- [ ] **Step 3: Commit**

```bash
git add backend/app/news/mcp_client.py
git commit -m "feat(backend): shared streamable-HTTP MCP client helper"
```

---

## Task 7: TavilyNewsProvider

**Files:** Create `backend/app/news/tavily.py`; Test `backend/tests/test_news_tavily.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_news_tavily.py`:

```python
import json
import pytest
from app.models.schemas import NewsProviderConfig
from app.news import tavily as tmod
from app.news.base import NewsError
from app.news.tavily import TavilyNewsProvider

SAMPLE = json.dumps({"results": [
    {"title": "NVDA partners with X", "url": "https://www.reuters.com/a",
     "content": "snippet text", "published_date": "2026-06-12T00:00:00Z"},
    {"title": "no url skipped"},
]})

def test_tavily_parses_results_and_maps_fields(monkeypatch):
    captured = {}
    def fake_call(url, tool, arguments, *, headers=None, timeout=20.0):
        captured.update(url=url, tool=tool, arguments=arguments)
        return SAMPLE
    monkeypatch.setattr(tmod, "call_tool_text", fake_call)
    cfg = NewsProviderConfig(api_key="key", mcp_url="https://mcp.tavily.com/mcp/")
    out = TavilyNewsProvider(cfg).search("NVDA", limit=5, recency_days=3650)
    assert captured["tool"] == "tavily_search"
    assert "tavilyApiKey=key" in captured["url"]
    assert captured["arguments"] == {"query": "NVDA", "max_results": 5, "topic": "news", "days": 3650}
    assert len(out) == 1
    item = out[0]
    assert (item.title, item.url, item.summary, item.source) == (
        "NVDA partners with X", "https://www.reuters.com/a", "snippet text", "reuters.com")

def test_tavily_requires_key():
    with pytest.raises(NewsError):
        TavilyNewsProvider(NewsProviderConfig()).search("x", limit=5, recency_days=90)
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_tavily.py`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement** — create `backend/app/news/tavily.py`:

```python
"""Tavily MCP adapter — tool `tavily_search`, key in the URL query, result `results[]`."""
from __future__ import annotations

import json

from app.data.news import recent_news
from app.models.schemas import NewsItem, NewsProviderConfig
from app.news.base import NewsError, host_of
from app.news.mcp_client import call_tool_text


class TavilyNewsProvider:
    label = "Tavily"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg

    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]:
        if not self._cfg.api_key:
            raise NewsError("Tavily API key is not set")
        url = f"{self._cfg.mcp_url.rstrip('/')}/?tavilyApiKey={self._cfg.api_key}"
        args = {"query": query, "max_results": limit, "topic": "news", "days": recency_days}
        items = _parse(call_tool_text(url, "tavily_search", args))
        return recent_news(items, days=recency_days)


def _parse(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    rows = data.get("results", []) if isinstance(data, dict) else []
    out: list[NewsItem] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        url = str(r.get("url", ""))
        out.append(NewsItem(
            title=str(r.get("title", "")), url=url, source=host_of(url),
            published_at=str(r.get("published_date", "")), summary=str(r.get("content", "")),
        ))
    return out
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_tavily.py`. Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/news/tavily.py backend/tests/test_news_tavily.py
git commit -m "feat(backend): Tavily MCP news provider"
```

---

## Task 8: ExaNewsProvider

**Files:** Create `backend/app/news/exa.py`; Test `backend/tests/test_news_exa.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_news_exa.py`:

```python
import json
import pytest
from app.models.schemas import NewsProviderConfig
from app.news import exa as emod
from app.news.base import NewsError
from app.news.exa import ExaNewsProvider

SAMPLE = json.dumps({"results": [
    {"title": "Exa hit", "url": "https://bloomberg.com/a", "text": "body text",
     "publishedDate": "2026-06-11T00:00:00Z", "author": "Reporter"},
    {"title": "no url"},
]})

def test_exa_parses_and_maps(monkeypatch):
    captured = {}
    def fake_call(url, tool, arguments, *, headers=None, timeout=20.0):
        captured.update(url=url, tool=tool, arguments=arguments, headers=headers)
        return SAMPLE
    monkeypatch.setattr(emod, "call_tool_text", fake_call)
    cfg = NewsProviderConfig(api_key="exakey", mcp_url="https://mcp.exa.ai/mcp")
    out = ExaNewsProvider(cfg).search("NVDA", limit=4, recency_days=3650)
    assert captured["tool"] == "web_search_exa"
    assert captured["headers"] == {"x-api-key": "exakey"}
    assert captured["arguments"] == {"query": "NVDA", "numResults": 4}
    assert len(out) == 1
    assert (out[0].title, out[0].url, out[0].summary, out[0].source) == (
        "Exa hit", "https://bloomberg.com/a", "body text", "Reporter")

def test_exa_requires_key():
    with pytest.raises(NewsError):
        ExaNewsProvider(NewsProviderConfig()).search("x", limit=4, recency_days=90)
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_exa.py`.

- [ ] **Step 3: Implement** — create `backend/app/news/exa.py`:

```python
"""Exa MCP adapter — tool `web_search_exa`, key in the `x-api-key` header, result `results[]`."""
from __future__ import annotations

import json

from app.data.news import recent_news
from app.models.schemas import NewsItem, NewsProviderConfig
from app.news.base import NewsError, host_of
from app.news.mcp_client import call_tool_text


class ExaNewsProvider:
    label = "Exa"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg

    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]:
        if not self._cfg.api_key:
            raise NewsError("Exa API key is not set")
        text = call_tool_text(
            self._cfg.mcp_url, "web_search_exa", {"query": query, "numResults": limit},
            headers={"x-api-key": self._cfg.api_key},
        )
        return recent_news(_parse(text), days=recency_days)


def _parse(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    rows = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    out: list[NewsItem] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        url = str(r.get("url", ""))
        out.append(NewsItem(
            title=str(r.get("title", "")), url=url,
            source=str(r.get("author", "")) or host_of(url),
            published_at=str(r.get("publishedDate", "")), summary=str(r.get("text", "")),
        ))
    return out
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_exa.py`. Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/news/exa.py backend/tests/test_news_exa.py
git commit -m "feat(backend): Exa MCP news provider"
```

---

## Task 9: YouNewsProvider

**Files:** Create `backend/app/news/you.py`; Test `backend/tests/test_news_you.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_news_you.py`:

```python
import json
import pytest
from app.models.schemas import NewsProviderConfig
from app.news import you as ymod
from app.news.base import NewsError
from app.news.you import YouNewsProvider

SAMPLE = json.dumps({
    "news": [{"title": "deal news", "url": "https://www.ft.com/n",
              "snippets": ["NVDA to acquire", "Y"], "page_age": "2026-06-12T00:00:00Z"}],
    "web": [{"title": "web hit", "url": "https://example.com/w",
             "description": "desc only", "page_age": "2026-06-11T00:00:00Z"}],
})

def test_you_parses_news_then_web_and_joins_snippets(monkeypatch):
    captured = {}
    def fake_call(url, tool, arguments, *, headers=None, timeout=20.0):
        captured.update(url=url, tool=tool, arguments=arguments, headers=headers)
        return SAMPLE
    monkeypatch.setattr(ymod, "call_tool_text", fake_call)
    cfg = NewsProviderConfig(api_key="ydc", mcp_url="https://api.you.com/mcp")
    out = YouNewsProvider(cfg).search("NVDA", limit=5, recency_days=3650)
    assert captured["tool"] == "you-search"
    assert captured["headers"] == {"Authorization": "Bearer ydc"}
    assert captured["arguments"] == {"query": "NVDA"}
    assert [i.title for i in out] == ["deal news", "web hit"]  # news bucket first
    assert out[0].summary == "NVDA to acquire Y"
    assert out[1].summary == "desc only"

def test_you_requires_key():
    with pytest.raises(NewsError):
        YouNewsProvider(NewsProviderConfig()).search("x", limit=5, recency_days=90)
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_you.py`.

- [ ] **Step 3: Implement** — create `backend/app/news/you.py`:

```python
"""you.com MCP adapter — tool `you-search`, Bearer auth, result {web:[…], news:[…]}."""
from __future__ import annotations

import json

from app.data.news import recent_news
from app.models.schemas import NewsItem, NewsProviderConfig
from app.news.base import NewsError, host_of
from app.news.mcp_client import call_tool_text


class YouNewsProvider:
    label = "you.com"

    def __init__(self, cfg: NewsProviderConfig) -> None:
        self._cfg = cfg

    def search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]:
        if not self._cfg.api_key:
            raise NewsError("you.com API key is not set")
        text = call_tool_text(
            self._cfg.mcp_url, "you-search", {"query": query},
            headers={"Authorization": f"Bearer {self._cfg.api_key}"},
        )
        return recent_news(_parse(text), days=recency_days)[:limit]


def _parse(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict):
        return []
    out: list[NewsItem] = []
    for bucket in ("news", "web"):                       # news first
        for r in data.get(bucket, []) or []:
            if not isinstance(r, dict) or not r.get("url"):
                continue
            url = str(r.get("url", ""))
            snippets = [s for s in (r.get("snippets") or []) if isinstance(s, str)]
            summary = " ".join(snippets) or str(r.get("description", ""))
            out.append(NewsItem(
                title=str(r.get("title", "")), url=url, source=host_of(url),
                published_at=str(r.get("page_age", "")), summary=summary,
            ))
    return out
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_you.py`. Expected: 2 passed.

> Note: `recent_news[:limit]` is applied after recency-sort because `you-search` has no result-count argument; the slice keeps the freshest `limit`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/news/you.py backend/tests/test_news_you.py
git commit -m "feat(backend): you.com MCP news provider"
```

---

## Task 10: News provider factory

**Files:** Create `backend/app/news/factory.py`; Test `backend/tests/test_news_factory.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_news_factory.py`:

```python
from app.models.schemas import NewsConfig, NewsProviderConfig, Settings
from app.news.exa import ExaNewsProvider
from app.news.google import GoogleNewsProvider
from app.news.factory import build_news_provider, resolve_news_config

def test_build_returns_active_provider_class():
    s = Settings(news=NewsConfig(active_provider="google"))
    assert isinstance(build_news_provider(s), GoogleNewsProvider)

def test_build_by_explicit_id():
    s = Settings(news=NewsConfig(providers={"exa": NewsProviderConfig(api_key="k")}))
    assert isinstance(build_news_provider(s, "exa"), ExaNewsProvider)

def test_resolve_fills_key_from_env_and_default_url(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "env-key")
    resolved = resolve_news_config("exa", NewsProviderConfig())
    assert resolved.api_key == "env-key"
    assert resolved.mcp_url == "https://mcp.exa.ai/mcp"
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_factory.py`.

- [ ] **Step 3: Implement** — create `backend/app/news/factory.py`:

```python
"""Build a NewsProvider from settings, mirroring app/llm/factory.py (env-key fallback)."""
from __future__ import annotations

import os

from app.models.schemas import NEWS_DEFAULT_MCP_URLS, NewsProviderConfig, Settings
from app.news.base import NewsError, NewsProvider
from app.news.exa import ExaNewsProvider
from app.news.google import GoogleNewsProvider
from app.news.tavily import TavilyNewsProvider
from app.news.you import YouNewsProvider

_REGISTRY = {
    "google": GoogleNewsProvider,
    "tavily": TavilyNewsProvider,
    "exa": ExaNewsProvider,
    "you": YouNewsProvider,
}
_NEWS_ENV_KEYS = {"tavily": "TAVILY_API_KEY", "exa": "EXA_API_KEY", "you": "YDC_API_KEY"}
_NEWS_LABELS = {"google": "Google News", "tavily": "Tavily", "exa": "Exa", "you": "you.com"}


def resolve_news_config(provider_id: str, cfg: NewsProviderConfig) -> NewsProviderConfig:
    resolved = cfg.model_copy()
    if not resolved.api_key and provider_id in _NEWS_ENV_KEYS:
        resolved.api_key = os.environ.get(_NEWS_ENV_KEYS[provider_id], "")
    if not resolved.mcp_url and provider_id in NEWS_DEFAULT_MCP_URLS:
        resolved.mcp_url = NEWS_DEFAULT_MCP_URLS[provider_id]
    return resolved


def build_news_provider(settings: Settings, provider_id: str | None = None) -> NewsProvider:
    pid = provider_id or settings.news.active_provider
    cls = _REGISTRY.get(pid)
    if cls is None:
        raise NewsError(f"Unknown news provider '{pid}'")
    cfg = settings.news.providers.get(pid, NewsProviderConfig())
    return cls(resolve_news_config(pid, cfg))
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_news_factory.py`. Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/news/factory.py backend/tests/test_news_factory.py
git commit -m "feat(backend): news provider factory + env-key fallback"
```

---

## Task 11: API routes — /api/news/providers + /api/news/test

**Files:** Modify `backend/app/api/routes.py`; Test `backend/tests/test_api_news.py`

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_api_news.py`:

```python
from app.news.base import NewsError

def test_news_providers_lists_four_with_configured_flag(client):
    rows = client.get("/api/news/providers").json()
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"google", "tavily", "exa", "you"}
    assert by_id["google"]["configured"] is True
    assert by_id["google"]["label"] == "Google News"

def test_news_test_ok(client, monkeypatch):
    from app.api import routes
    class Fake:
        def search(self, q, *, limit, recency_days): return []
    monkeypatch.setattr(routes, "build_news_provider", lambda s, pid: Fake())
    body = client.get("/api/news/test?provider=tavily").json()
    assert body == {"ok": True, "message": "Tavily OK"}

def test_news_test_error(client, monkeypatch):
    from app.api import routes
    def boom(s, pid): raise NewsError("bad key")
    monkeypatch.setattr(routes, "build_news_provider", boom)
    body = client.get("/api/news/test?provider=exa").json()
    assert body["ok"] is False and "bad key" in body["message"]
```

> Uses the existing `client` fixture in `backend/tests/conftest.py` (the sandboxed TestClient).

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_api_news.py`. Expected: 404s (routes missing).

- [ ] **Step 3: Implement** — in `backend/app/api/routes.py`, add `NewsProviderConfig` to the existing `from app.models.schemas import (...)` block, and add this import near the other service imports:

```python
from app.news.factory import _NEWS_LABELS, build_news_provider, resolve_news_config
```

then add these routes (next to the other `/graph`-area routes):

```python
@router.get("/news/providers")
def list_news_providers(store: SettingsStore = Depends(get_settings_store)) -> list[dict]:
    news = store.load().news
    out = []
    for pid, label in _NEWS_LABELS.items():
        cfg = news.providers.get(pid) or NewsProviderConfig()
        # Google needs no key; the others are "configured" when a key is set (stored or env).
        configured = pid == "google" or bool(resolve_news_config(pid, cfg).api_key)
        out.append({"id": pid, "label": label, "configured": configured})
    return out


@router.get("/news/test")
def test_news_provider(
    provider: str = Query(...), store: SettingsStore = Depends(get_settings_store)
) -> dict:
    label = _NEWS_LABELS.get(provider, provider)
    try:
        build_news_provider(store.load(), provider).search("test", limit=1, recency_days=3650)
        return {"ok": True, "message": f"{label} OK"}
    except Exception as e:  # noqa: BLE001 — resilient: never 500
        return {"ok": False, "message": str(e)}
```

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_api_news.py`. Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_news.py
git commit -m "feat(backend): /api/news/providers + /api/news/test endpoints"
```

---

## Task 12: Repoint build_company_graph at the active provider

**Files:** Modify `backend/app/network/service.py`; Test `backend/tests/test_network_service.py` (add a case)

- [ ] **Step 1: Write the failing test** — add to `backend/tests/test_network_service.py`:

```python
def test_build_company_graph_uses_news_provider(monkeypatch, tmp_path):
    from app.config.cache import Cache
    from app.models.schemas import NewsConfig, NewsItem, Settings
    from app.network import service

    captured = {}
    class FakeProvider:
        def search(self, query, *, limit, recency_days):
            captured.update(query=query, recency_days=recency_days)
            return [NewsItem(title="deal", source="", published_at="", url="http://x", summary="")]

    class FakeStock:
        ticker, company_name, news = "AAPL", "Apple Inc.", []

    monkeypatch.setattr(service, "build_news_provider", lambda s: FakeProvider())
    monkeypatch.setattr(service, "get_stock_data", lambda *a, **k: FakeStock())
    monkeypatch.setattr(service, "extract_relationships",
                        lambda stock, *a, **k: list(getattr(stock, "news", [])) and [])
    s = Settings(news=NewsConfig(news_recency_days=45))
    service.build_company_graph("AAPL", s, Cache(str(tmp_path / "c.db")))
    assert captured["query"] == "Apple Inc. (AAPL) stock"
    assert captured["recency_days"] == 45
```

- [ ] **Step 2: Run — expect FAIL.** `.venv/Scripts/python.exe -m pytest -q tests/test_network_service.py::test_build_company_graph_uses_news_provider`. Expected: AttributeError (`build_news_provider` not in module) / KeyError.

- [ ] **Step 3: Implement** — in `backend/app/network/service.py`:

Add the import:

```python
from app.news.factory import build_news_provider
```

Add a constant near `NETWORK_PERIOD`:

```python
NEWS_LIMIT = 10
```

In `build_company_graph`, inside the existing `try:` that calls `get_stock_data` + `extract_relationships`, set the stock's news from the provider before extraction:

```python
    try:
        stock = get_stock_data(t, NETWORK_PERIOD, settings.indicator_params, cache)
        query = f"{stock.company_name} ({t}) stock"
        stock.news = build_news_provider(settings).search(
            query, limit=NEWS_LIMIT, recency_days=settings.news.news_recency_days
        )
        edges = extract_relationships(stock, resolver, provider, model, provider_id, cache, ncfg, now=now)
    except Exception:  # noqa: BLE001 — no data / provider / extraction error -> lone node
        return KnowledgeGraph(as_of=now.isoformat(), scope=scope, nodes=[t])
```

(The provider's `NewsError` is an `Exception`, so it is already caught by this block → lone-root degrade.)

- [ ] **Step 4: Run — expect PASS.** `.venv/Scripts/python.exe -m pytest -q tests/test_network_service.py`. Expected: all passed (existing cases + the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/app/network/service.py backend/tests/test_network_service.py
git commit -m "feat(backend): Expand neighbours fetches news via the active provider"
```

---

## Task 13: Frontend types

**Files:** Modify `frontend/src/types.ts` (no test; covered by `tsc -b` in Task 16)

- [ ] **Step 1: Add types** — in `frontend/src/types.ts`, near `NetworkConfig`:

```ts
export type NewsProviderId = 'google' | 'tavily' | 'exa' | 'you';
export interface NewsProviderConfig { api_key: string; mcp_url: string; }
export interface NewsConfig {
  active_provider: NewsProviderId;
  providers: Record<NewsProviderId, NewsProviderConfig>;
  news_recency_days: number;
}
export interface NewsProviderInfo { id: NewsProviderId; label: string; configured: boolean; }
```

Add `news: NewsConfig;` to the `Settings` interface.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types.ts
git commit -m "feat(frontend): NewsConfig types"
```

---

## Task 14: Frontend API client + hook

**Files:** Modify `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`; Test `frontend/src/api/client.test.ts` (add a case)

- [ ] **Step 1: Write the failing test** — add to `frontend/src/api/client.test.ts` (follow the file's existing fetch-mock pattern):

```ts
it('getNewsProviders calls /news/providers', async () => {
  const spy = mockFetchOnce([{ id: 'google', label: 'Google News', configured: true }]);
  await api.getNewsProviders();
  expect(spy).toHaveBeenCalledWith(expect.stringContaining('/news/providers'), expect.anything());
});
```

> Use whatever fetch-mock helper the file already defines (e.g. `mockFetchOnce`); match the existing tests' style for asserting the URL.

- [ ] **Step 2: Run — expect FAIL.** From `frontend/`: `./node_modules/.bin/vitest run src/api/client.test.ts`. Expected: `api.getNewsProviders is not a function`.

- [ ] **Step 3: Implement** — in `frontend/src/api/client.ts`, add to the `api` object:

```ts
  getNewsProviders: () => http<NewsProviderInfo[]>('/news/providers'),
  testNews: (provider: string) => http<TestResult>(`/news/test?provider=${encodeURIComponent(provider)}`),
```

and import the types: add `NewsProviderInfo` (and `TestResult` if not already imported) to the `import type { … } from '../types'` block.

In `frontend/src/hooks/queries.ts`, add:

```ts
export function useNewsProviders() {
  return useQuery({ queryKey: ['newsProviders'], queryFn: api.getNewsProviders });
}
```

- [ ] **Step 4: Run — expect PASS.** `./node_modules/.bin/vitest run src/api/client.test.ts`. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/api/client.test.ts
git commit -m "feat(frontend): news provider client + useNewsProviders hook"
```

---

## Task 15: Settings "News source" section

**Files:** Modify `frontend/src/pages/Settings.tsx`; Test `frontend/src/pages/Settings.test.tsx` (add a case)

- [ ] **Step 1: Write the failing test** — add to `frontend/src/pages/Settings.test.tsx` (mirror its existing render + mock setup; the default settings have `news.active_provider === 'google'`):

```tsx
it('switches news provider and shows the API key field + recency', async () => {
  renderSettings(); // the file's existing render helper
  const select = await screen.findByLabelText(/news source/i);
  fireEvent.change(select, { target: { value: 'tavily' } });
  expect(screen.getByLabelText(/news api key/i)).toBeInTheDocument();
  const recency = screen.getByLabelText(/news recency/i);
  fireEvent.change(recency, { target: { value: '30' } });
  expect((recency as HTMLInputElement).value).toBe('30');
});
```

> If the existing Settings test fixture omits `news`, add `news: { active_provider: 'google', providers: { google: {api_key:'',mcp_url:''}, tavily: {api_key:'',mcp_url:''}, exa: {api_key:'',mcp_url:''}, you: {api_key:'',mcp_url:''} }, news_recency_days: 90 }` to its `SETTINGS` literal.

- [ ] **Step 2: Run — expect FAIL.** `./node_modules/.bin/vitest run src/pages/Settings.test.tsx -t "switches news provider"`. Expected: cannot find the "News source" control.

- [ ] **Step 3: Implement** — in `frontend/src/pages/Settings.tsx`:

Add the type import (extend the existing `import type {...}` from `../types`): add `NewsConfig`.

Add the helper next to `updateTruth`:

```tsx
  const updateNews = (patch: Partial<NewsConfig>) => update({ news: { ...form.news, ...patch } });
  const updateNewsKey = (key: string) =>
    updateNews({ providers: { ...form.news.providers, [form.news.active_provider]: { ...form.news.providers[form.news.active_provider], api_key: key } } });
```

Add state + handler near the other test-status state:

```tsx
  const [newsTest, setNewsTest] = useState<TestResult | null>(null);
  const onTestNews = async () => {
    setNewsTest(null);
    await save.mutateAsync(form);
    setNewsTest(await api.testNews(form.news.active_provider));
  };
```

Add the section before `<div className="settings-actions">`:

```tsx
      <h3>News source</h3>
      <div className="field">
        <label htmlFor="news-source">News source</label>
        <select id="news-source" value={form.news.active_provider}
                onChange={(e) => updateNews({ active_provider: e.target.value as NewsConfig['active_provider'] })}>
          <option value="google">Google News (default)</option>
          <option value="tavily">Tavily (MCP)</option>
          <option value="exa">Exa (MCP)</option>
          <option value="you">you.com (MCP)</option>
        </select>
        <p className="muted">Where Expand neighbours reads news to build the ontology.</p>
      </div>
      {form.news.active_provider !== 'google' && (
        <>
          <div className="field">
            <label htmlFor="news-key">News API key</label>
            <input id="news-key" type="password"
                   value={form.news.providers[form.news.active_provider].api_key}
                   onChange={(e) => updateNewsKey(e.target.value)} placeholder="****" />
          </div>
          <button className="secondary" onClick={onTestNews} disabled={save.isPending}>Test connection</button>
          {newsTest && <span className={`note ${newsTest.ok ? 'muted' : 'error'}`} style={{ marginLeft: 8 }}>{newsTest.ok ? '✓ ' : '✗ '}{newsTest.message}</span>}
        </>
      )}
      <div className="field">
        <label htmlFor="news-recency">News recency (days)</label>
        <input id="news-recency" type="number" value={form.news.news_recency_days}
               onChange={(e) => updateNews({ news_recency_days: Number(e.target.value) })} />
      </div>
```

- [ ] **Step 4: Run — expect PASS.** `./node_modules/.bin/vitest run src/pages/Settings.test.tsx`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(frontend): Settings News source section (provider, key, recency, test)"
```

---

## Task 16: Full automated verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite.** From `backend/`: `.venv/Scripts/python.exe -m pytest -q`. Expected: all pass (existing + new news tests).
- [ ] **Step 2: Frontend suite.** From `frontend/`: `./node_modules/.bin/vitest run`. Expected: all pass.
- [ ] **Step 3: Typecheck + build.** From `frontend/`: `./node_modules/.bin/tsc -b`. Expected: exit 0.
- [ ] **Step 4: Lint changed FE files.** From `frontend/`: `./node_modules/.bin/eslint src/pages/Settings.tsx src/api/client.ts src/types.ts`. Expected: no new errors.

---

## Task 17: Live verification (human acceptance — needs API keys)

**Files:** none. This is the acceptance gate the automated tests cannot cover (the live MCP tool-result text shape is only knowable with real keys). The user runs this.

- [ ] **Step 1:** Start backend + frontend dev servers. In **Settings → News source**, pick a provider (Tavily/Exa/you.com), paste its API key, **Save**, click **Test connection** → expect `✓ <Provider> OK`.
- [ ] **Step 2:** With that provider active, open **Graph**, add a company (e.g. NVDA), click **Expand neighbours** → confirm neighbours appear and the relationships look richer than Google.
- [ ] **Step 3:** If a provider connects but yields **no edges**, capture the raw tool output (temporarily log `text` in that adapter's `_parse`) and compare to the documented shape in this plan; adjust that adapter's `_parse` field names to match the live JSON, add a fixture test from the captured payload, and re-run its test.
- [ ] **Step 4:** Repeat Steps 1–2 for the other two providers. Switch back to **Google News** and confirm Expand still works (regression check).

---

## Notes for the executor
- The 6 backend provider/adapter modules are intentionally small and parallel; **do not** collapse them with a metaclass/loop — the per-provider auth/tool/result differences are the whole point, and explicit modules keep each testable in isolation.
- `recent_news` is the single recency authority; every provider routes through it, so the `news_recency_days` setting works uniformly.
- Nothing here touches scoring, the active ontology, `RelationType`, or the graph legend.
