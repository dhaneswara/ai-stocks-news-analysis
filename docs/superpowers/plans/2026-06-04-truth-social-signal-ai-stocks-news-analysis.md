# Trump / Truth Social Signal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed Donald Trump's recent Truth Social posts into the existing per-ticker LLM analysis as two inputs — a shared market-mood read and a per-ticker direct-mention scan.

**Architecture:** A new data source (`data/truth_social.py`) pulls the public archive JSON and filters to a lookback window. A new analysis module (`analysis/political.py`) derives a *shared, cached* `MarketMood` (one LLM call/day, reused across tickers) and a *pure, deterministic* per-ticker mention list. `run_analysis` attaches both to `StockData`; `build_user_prompt` adds two compact sections; the LLM weighs them like news. The signal informs the **current** recommendation only — it never fabricates historical chart markers — and degrades to today's exact behavior on any failure.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, httpx, pytest (backend); React + TS + Vite + vitest (frontend). SQLite `Cache` for caching.

---

**Spec:** [docs/superpowers/specs/2026-06-04-trump-truth-social-signal-design.md](../specs/2026-06-04-trump-truth-social-signal-design.md)

**Conventions (apply to every task):**
- Run backend tests from `backend/` with the venv interpreter: `.venv/Scripts/python.exe -m pytest -q`.
- Run a single test: `.venv/Scripts/python.exe -m pytest tests/test_x.py::test_name -v`.
- Commits use Conventional Commits and **end with** the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Frontend: from `frontend/`, `npm run test` (vitest) and `npm run build` (tsc + vite).

---

## File structure

**Backend (create):**
- `backend/app/data/truth_social.py` — fetch + parse + recency-filter the archive (no LLM).
- `backend/app/analysis/political.py` — `find_mentions` (pure) + `summarize_market_mood` (LLM, cached).
- `backend/tests/test_truth_schema.py`, `test_truth_social.py`, `test_political.py`, `test_api_truth.py`.

**Backend (modify):**
- `backend/app/models/schemas.py` — new models + `StockData`/`AnalysisResult`/`Settings` extensions.
- `backend/app/analysis/analyzer.py` — two prompt sections + surface `market_mood` on the result.
- `backend/app/services/analysis_service.py` — wire the signal into `run_analysis`.
- `backend/app/api/routes.py` — `GET /api/truth/mood` preview.
- `backend/tests/test_analyzer.py`, `test_analysis_service.py` — extend.

**Frontend (modify):**
- `frontend/src/types.ts` — new interfaces + extensions.
- `frontend/src/pages/Settings.tsx` — Truth Social toggle + lookback.
- `frontend/src/api/client.ts` + `client.test.ts` — `getMood`.
- `frontend/src/components/ReasoningPanel.tsx` — optional mood line.

---

## Task 1: Schemas — new models + extensions

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_truth_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_truth_schema.py`:

```python
from app.models.schemas import (
    AnalysisResult,
    MarketMood,
    Mention,
    Settings,
    StockData,
    TruthPost,
    TruthSignalConfig,
)


def test_truth_signal_config_defaults():
    cfg = TruthSignalConfig()
    assert cfg.enabled is True
    assert cfg.lookback_hours == 48
    assert cfg.source_url.startswith("https://ix.cnn.io/")


def test_settings_includes_truth_signal_default():
    assert Settings().truth_signal.enabled is True


def test_market_mood_defaults_to_neutral():
    mood = MarketMood()
    assert mood.lean == "neutral"
    assert mood.themes == []
    assert mood.post_count == 0


def test_stockdata_truth_fields_default_empty():
    sd = StockData.model_construct(ticker="AAPL")
    # constructed minimally; defaults must be None / [] not required
    assert StockData.model_fields["market_mood"].default is None
    assert TruthPost(id="1", created_at="t", content="c").url == ""


def test_analysis_result_has_market_mood_field():
    assert "market_mood" in AnalysisResult.model_fields
    assert Mention.model_fields["url"].default == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_truth_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'TruthPost'`.

- [ ] **Step 3: Add the new models**

In `backend/app/models/schemas.py`, insert **after** `NewsItem` (after line 61) and **before** `class StockData`:

```python
class TruthPost(BaseModel):
    id: str
    created_at: str
    content: str
    url: str = ""


class MoodTheme(BaseModel):
    label: str
    lean: Literal["bullish", "bearish", "neutral"] = "neutral"
    quote: str = ""
    post_url: str = ""
    created_at: str = ""


class MarketMood(BaseModel):
    lean: Literal["risk_on", "neutral", "risk_off"] = "neutral"
    confidence: float = 0.0
    summary: str = ""
    themes: list[MoodTheme] = Field(default_factory=list)
    as_of: str = ""
    post_count: int = 0


class Mention(BaseModel):
    post_id: str
    created_at: str
    matched: str
    excerpt: str
    url: str = ""
```

- [ ] **Step 4: Extend `StockData`**

Add two fields to `class StockData` (after the `news` field):

```python
    market_mood: Optional[MarketMood] = None
    trump_mentions: list[Mention] = Field(default_factory=list)
```

- [ ] **Step 5: Extend `AnalysisResult`**

Add one field to `class AnalysisResult` (after `disclaimer`):

```python
    market_mood: Optional[MarketMood] = None
```

- [ ] **Step 6: Add `TruthSignalConfig` and extend `Settings`**

Add **after** `class AlertConfig` (and before `_default_providers`):

```python
class TruthSignalConfig(BaseModel):
    enabled: bool = True
    source_url: str = "https://ix.cnn.io/data/truth-social/truth_archive.json"
    lookback_hours: int = 48
```

Add one field to `class Settings` (after `alerts`):

```python
    truth_signal: TruthSignalConfig = Field(default_factory=TruthSignalConfig)
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_truth_schema.py -q`
Expected: PASS (5 passed).

- [ ] **Step 8: Run the full suite (no regressions)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all existing tests still pass (defaults keep `StockData`/`Settings` backward-compatible).

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_truth_schema.py
git commit   # feat(backend): add Truth Social signal schemas (mood, mentions, config)
```

---

## Task 2: `truth_social.py` — parse + recency filter

**Files:**
- Create: `backend/app/data/truth_social.py`
- Test: `backend/tests/test_truth_social.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_truth_social.py`:

```python
from datetime import datetime, timezone

from app.data.truth_social import filter_recent, parse_posts

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)

SAMPLE = [
    {"id": "1", "created_at": "2026-06-04T10:00:00Z",
     "content": "<p>Tariffs on China are <b>massive</b>!</p>", "url": "https://t/1"},
    {"id": "2", "created_at": "2026-06-01T09:00:00Z",
     "content": "<p>Old post</p>", "url": "https://t/2"},
]


def test_parse_posts_strips_html():
    posts = parse_posts(SAMPLE)
    assert posts[0].content == "Tariffs on China are massive!"
    assert posts[0].id == "1"
    assert posts[0].url == "https://t/1"


def test_filter_recent_keeps_only_in_window():
    recent = filter_recent(parse_posts(SAMPLE), hours=48, now=NOW)
    assert [p.id for p in recent] == ["1"]  # post 2 is >48h old


def test_filter_recent_drops_unparseable_dates():
    posts = parse_posts([{"id": "x", "created_at": "not-a-date", "content": "hi"}])
    assert filter_recent(posts, hours=48, now=NOW) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_truth_social.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.truth_social'`.

- [ ] **Step 3: Implement parse + filter**

Create `backend/app/data/truth_social.py`:

```python
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.config.cache import Cache
from app.models.schemas import TruthPost

ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
_PULL_TTL_SECONDS = 30 * 60
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def parse_posts(raw: list[dict]) -> list[TruthPost]:
    posts: list[TruthPost] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        posts.append(
            TruthPost(
                id=str(row.get("id", "")),
                created_at=str(row.get("created_at", "")),
                content=_strip_html(str(row.get("content", ""))),
                url=str(row.get("url", "")),
            )
        )
    return posts


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def filter_recent(posts: list[TruthPost], hours: int, now: datetime) -> list[TruthPost]:
    cutoff = now - timedelta(hours=hours)
    out = []
    for p in posts:
        dt = _parse_dt(p.created_at)
        if dt is not None and dt >= cutoff:
            out.append(p)
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_truth_social.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/truth_social.py backend/tests/test_truth_social.py
git commit   # feat(backend): parse + recency-filter Truth Social archive posts
```

---

## Task 3: `truth_social.py` — fetch + cached pull

**Files:**
- Modify: `backend/app/data/truth_social.py`
- Test: `backend/tests/test_truth_social.py`

- [ ] **Step 1: Write the failing tests** (append to `test_truth_social.py`)

```python
from app.config.cache import Cache
from app.data import truth_social


def test_fetch_recent_posts_filters(monkeypatch):
    monkeypatch.setattr(truth_social, "_fetch_archive", lambda url: SAMPLE)
    posts = truth_social.fetch_recent_posts(48, now=NOW)
    assert [p.id for p in posts] == ["1"]


def test_fetch_recent_posts_returns_empty_on_error(monkeypatch):
    def boom(_url):
        raise RuntimeError("network down")

    monkeypatch.setattr(truth_social, "_fetch_archive", boom)
    assert truth_social.fetch_recent_posts(48, now=NOW) == []


def test_cached_pull_avoids_second_fetch(tmp_path, monkeypatch):
    calls = {"n": 0}

    def counting(_url):
        calls["n"] += 1
        return SAMPLE

    monkeypatch.setattr(truth_social, "_fetch_archive", counting)
    cache = Cache(str(tmp_path / "c.db"))
    a = truth_social.fetch_recent_posts_cached(48, truth_social.ARCHIVE_URL, cache, now=NOW)
    b = truth_social.fetch_recent_posts_cached(48, truth_social.ARCHIVE_URL, cache, now=NOW)
    assert [p.id for p in a] == ["1"] and [p.id for p in b] == ["1"]
    assert calls["n"] == 1  # second call served from cache
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_truth_social.py -q`
Expected: FAIL — `AttributeError: module 'app.data.truth_social' has no attribute '_fetch_archive'`.

- [ ] **Step 3: Implement fetch + cached wrapper** (append to `truth_social.py`)

```python
def _fetch_archive(url: str) -> list[dict]:
    resp = httpx.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_recent_posts(
    lookback_hours: int, source_url: str = ARCHIVE_URL, *, now: datetime | None = None
) -> list[TruthPost]:
    now = now or datetime.now(timezone.utc)
    try:
        return filter_recent(parse_posts(_fetch_archive(source_url)), lookback_hours, now)
    except Exception:
        return []


def fetch_recent_posts_cached(
    lookback_hours: int,
    source_url: str,
    cache: Cache,
    *,
    ttl_seconds: int = _PULL_TTL_SECONDS,
    now: datetime | None = None,
) -> list[TruthPost]:
    key = f"truth_posts:{source_url}:{lookback_hours}"
    cached = cache.get(key)
    if cached is not None:
        return [TruthPost.model_validate(p) for p in json.loads(cached)]
    posts = fetch_recent_posts(lookback_hours, source_url, now=now)
    cache.set(key, json.dumps([p.model_dump() for p in posts]), ttl_seconds)
    return posts
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_truth_social.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/truth_social.py backend/tests/test_truth_social.py
git commit   # feat(backend): fetch Truth Social archive with a short-TTL cached pull
```

---

## Task 4: `political.py` — `find_mentions` (pure)

**Files:**
- Create: `backend/app/analysis/political.py`
- Test: `backend/tests/test_political.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_political.py`:

```python
from app.analysis.political import find_mentions
from app.models.schemas import TruthPost


def _post(pid, content):
    return TruthPost(id=pid, created_at="2026-06-04T10:00:00Z", content=content, url=f"https://t/{pid}")


def test_finds_cashtag_company_and_bare_ticker():
    posts = [
        _post("1", "I love $AAPL and what they do"),
        _post("2", "Apple should build in America"),
        _post("3", "AAPL is great"),
        _post("4", "nothing relevant here"),
    ]
    hits = find_mentions(posts, "AAPL", "Apple Inc.")
    ids = {m.post_id for m in hits}
    assert ids == {"1", "2", "3"}


def test_word_boundary_blocks_substring_false_positive():
    # "Apple" must not match inside "applesauce"; bare lowercase "aapl" is not a cashtag/ticker
    posts = [_post("1", "I bought applesauce and aapl-flavored candy")]
    assert find_mentions(posts, "AAPL", "Apple Inc.") == []


def test_bare_ticker_is_case_sensitive_to_avoid_common_words():
    # ticker "ON" must not match the english word "on"
    posts = [_post("1", "we are working on it")]
    assert find_mentions(posts, "ON", "ON Semiconductor") == []


def test_excerpt_and_one_mention_per_post():
    posts = [_post("1", "$AAPL $AAPL twice")]
    hits = find_mentions(posts, "AAPL", "Apple Inc.")
    assert len(hits) == 1 and "AAPL" in hits[0].excerpt
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_political.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.political'`.

- [ ] **Step 3: Implement `find_mentions`**

Create `backend/app/analysis/political.py`:

```python
from __future__ import annotations

import re

from app.models.schemas import Mention, TruthPost

_SUFFIX_RE = re.compile(
    r"\b(inc|corp|corporation|co|ltd|plc|company|companies|holdings|group)\b\.?", re.I
)


def _clean_company(name: str) -> str:
    return _SUFFIX_RE.sub("", name or "").strip(" ,.")


def _match_terms(ticker: str, company_name: str, aliases: list[str] | None):
    """(term, regex_flags) pairs. Cashtag + company + aliases are case-insensitive;
    the bare ticker is case-SENSITIVE so a ticker like 'ON' won't match the word 'on'."""
    terms: list[tuple[str, int]] = [(f"${ticker}", re.I), (ticker, 0)]
    name = _clean_company(company_name)
    if name:
        terms.append((name, re.I))
    for a in aliases or []:
        if a:
            terms.append((a, re.I))
    # Longest term first so '$AAPL' wins over 'AAPL' for the `matched` label.
    return sorted(terms, key=lambda t: len(t[0]), reverse=True)


def find_mentions(
    posts: list[TruthPost], ticker: str, company_name: str, aliases: list[str] | None = None
) -> list[Mention]:
    compiled = [
        (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags))
        for term, flags in _match_terms(ticker, company_name, aliases)
    ]
    out: list[Mention] = []
    for p in posts:
        for term, pattern in compiled:
            m = pattern.search(p.content)
            if m:
                start, end = max(0, m.start() - 40), min(len(p.content), m.end() + 40)
                out.append(
                    Mention(
                        post_id=p.id,
                        created_at=p.created_at,
                        matched=term,
                        excerpt=p.content[start:end].strip(),
                        url=p.url,
                    )
                )
                break  # one mention per post
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_political.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/political.py backend/tests/test_political.py
git commit   # feat(backend): deterministic Trump-mention scan for a ticker
```

---

## Task 5: `political.py` — `summarize_market_mood` (LLM, cached)

**Files:**
- Modify: `backend/app/analysis/political.py`
- Test: `backend/tests/test_political.py`

- [ ] **Step 1: Write the failing tests** (append to `test_political.py`)

```python
import json

from app.config.cache import Cache
from app.analysis.political import build_mood_prompt, summarize_market_mood

MOOD_JSON = json.dumps({
    "lean": "risk_off",
    "confidence": 0.7,
    "summary": "Tariff threats dominate.",
    "themes": [{"label": "Tariffs on China", "lean": "bearish", "quote": "massive"}],
})


class FakeProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)


def test_build_mood_prompt_includes_posts():
    system, user = build_mood_prompt([_post("1", "Tariffs on China")])
    assert "Tariffs on China" in user
    assert "JSON" in user


def test_summarize_returns_neutral_for_no_posts(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    mood = summarize_market_mood([], FakeProvider([MOOD_JSON]), "m", "fake", cache)
    assert mood.lean == "neutral" and mood.post_count == 0


def test_summarize_parses_llm_json(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    mood = summarize_market_mood([_post("1", "Tariffs")], FakeProvider([MOOD_JSON]), "m", "fake", cache)
    assert mood.lean == "risk_off"
    assert mood.themes[0].lean == "bearish"
    assert mood.post_count == 1


def test_summarize_is_cached_per_provider_day(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    provider = FakeProvider([MOOD_JSON])  # only ONE output available
    posts = [_post("1", "Tariffs")]
    a = summarize_market_mood(posts, provider, "m", "fake", cache)
    b = summarize_market_mood(posts, provider, "m", "fake", cache)  # must hit cache, not pop again
    assert a.lean == b.lean == "risk_off"
    assert provider.calls == 1


def test_summarize_falls_back_to_neutral_on_bad_json(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    mood = summarize_market_mood([_post("1", "x")], FakeProvider(["not json"]), "m", "fake", cache)
    assert mood.lean == "neutral"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_political.py -q`
Expected: FAIL — `ImportError: cannot import name 'summarize_market_mood'`.

- [ ] **Step 3: Implement the mood summarizer** (append to `political.py`)

Add imports at the top of `political.py` (below the existing `import re`):

```python
from datetime import datetime, timezone

from app.analysis.analyzer import extract_json
from app.config.cache import Cache
from app.llm.base import LLMProvider
from app.models.schemas import MarketMood, MoodTheme
```

Then append:

```python
_MOOD_TTL_SECONDS = 24 * 60 * 60

_MOOD_SYSTEM = (
    "You read recent social-media posts from a market-moving political figure and summarize "
    "their likely SHORT-TERM effect on US equities. Judge intent and target, not keywords: "
    "announcing a deal, tariff pause, or rate-cut pressure leans bullish; threatening tariffs, "
    "sanctions, or war leans bearish; praising a company is bullish for it, attacking one is "
    "bearish for it. Respond with ONLY a single JSON object, no prose, no code fences."
)

_MOOD_SCHEMA_HINT = """Return JSON with exactly these fields:
{
  "lean": "risk_on" | "neutral" | "risk_off",
  "confidence": number between 0 and 1,
  "summary": string (1-2 sentences on the NET market read),
  "themes": [ { "label": string, "lean": "bullish"|"bearish"|"neutral", "quote": string } ]
}
Base "lean" on the NET effect across all posts. Give 0-4 themes, each citing a concrete driver
(tariffs, Fed, war/ceasefire, a named company) with a short verbatim quote. If the posts carry no
clear market relevance, return lean "neutral", low confidence, and an empty themes list."""


def build_mood_prompt(posts: list[TruthPost]) -> tuple[str, str]:
    lines = "\n".join(f"- [{p.created_at}] {p.content[:280]}" for p in posts[:40])
    user = f"Recent posts:\n{lines or '- (none)'}\n\n{_MOOD_SCHEMA_HINT}"
    return _MOOD_SYSTEM, user


def _neutral_mood(post_count: int, as_of: str) -> MarketMood:
    return MarketMood(lean="neutral", confidence=0.0, summary="", themes=[],
                      as_of=as_of, post_count=post_count)


def summarize_market_mood(
    posts: list[TruthPost],
    provider: LLMProvider,
    model: str,
    provider_name: str,
    cache: Cache,
    *,
    now: datetime | None = None,
) -> MarketMood:
    now = now or datetime.now(timezone.utc)
    as_of = now.isoformat()
    if not posts:
        return _neutral_mood(0, as_of)

    key = f"truth_mood:{provider_name}:{model}:{now.date().isoformat()}"
    cached = cache.get(key)
    if cached is not None:
        return MarketMood.model_validate_json(cached)

    system, user = build_mood_prompt(posts)
    try:
        payload = extract_json(provider.complete(system, user))
        themes = [MoodTheme(**t) for t in payload.get("themes", []) if isinstance(t, dict)]
        mood = MarketMood(
            lean=payload.get("lean", "neutral"),
            confidence=float(payload.get("confidence", 0.0)),
            summary=str(payload.get("summary", "")),
            themes=themes,
            as_of=as_of,
            post_count=len(posts),
        )
    except Exception:
        mood = _neutral_mood(len(posts), as_of)

    cache.set(key, mood.model_dump_json(), _MOOD_TTL_SECONDS)
    return mood
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_political.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/political.py backend/tests/test_political.py
git commit   # feat(backend): cached, shared market-mood summary from recent posts
```

---

## Task 6: `analyzer.py` — prompt sections + surface `market_mood`

**Files:**
- Modify: `backend/app/analysis/analyzer.py`
- Test: `backend/tests/test_analyzer.py`

- [ ] **Step 1: Write the failing tests** (append to `test_analyzer.py`)

```python
from app.models.schemas import MarketMood, Mention, MoodTheme


def _stock_with_mood():
    s = _stock()
    s.market_mood = MarketMood(
        lean="risk_off", confidence=0.7, summary="Tariff threats.",
        themes=[MoodTheme(label="Tariffs on China", lean="bearish", quote="massive")],
        as_of="2026-06-04T12:00:00Z", post_count=3,
    )
    s.trump_mentions = [Mention(post_id="1", created_at="2026-06-04T10:00:00Z",
                                matched="$AAPL", excerpt="love $AAPL", url="https://t/1")]
    return s


def test_prompt_includes_mood_and_mentions():
    prompt = build_user_prompt(_stock_with_mood())
    assert "MARKET MOOD" in prompt
    assert "risk_off" in prompt
    assert "TRUMP MENTIONS" in prompt
    assert "$AAPL" in prompt


def test_prompt_has_placeholders_when_signal_absent():
    prompt = build_user_prompt(_stock())  # no mood, no mentions
    assert "TRUMP MENTIONS" in prompt
    assert "(none)" in prompt


def test_analyze_surfaces_market_mood_on_result():
    provider = FakeProvider([json.dumps(VALID_PAYLOAD)])
    result = analyze(_stock_with_mood(), provider, model="m", provider_name="fake")
    assert result.market_mood is not None
    assert result.market_mood.lean == "risk_off"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analyzer.py -q`
Expected: FAIL — `assert 'MARKET MOOD' in prompt` (and `result.market_mood is None`).

- [ ] **Step 3: Add the formatting helpers + prompt sections**

In `backend/app/analysis/analyzer.py`, update the schemas import (line 10) to add the new names:

```python
from app.models.schemas import DISCLAIMER, AnalysisResult, MarketMood, Mention, Signal, StockData
```

Add these helpers just above `build_user_prompt`:

```python
def _format_mood(mood: MarketMood | None) -> str:
    if mood is None or mood.post_count == 0:
        return "- (Trump / Truth Social signal disabled or no recent posts)"
    themes = "; ".join(f"{t.label} ({t.lean})" for t in mood.themes) or "(none)"
    return (
        f"- Lean: {mood.lean} (confidence {mood.confidence:.2f})\n"
        f"- Summary: {mood.summary}\n"
        f"- Themes: {themes}"
    )


def _format_mentions(mentions: list[Mention]) -> str:
    if not mentions:
        return "- (none)"
    return "\n".join(f'- [{m.created_at}] "{m.excerpt}" ({m.url})' for m in mentions[:8])
```

In `build_user_prompt`, insert the two sections into the returned f-string, **between** the `RECENT NEWS HEADLINES` block and the `{_JSON_SCHEMA_HINT}` line:

```python
RECENT NEWS HEADLINES:
{headlines}

MARKET MOOD (recent Trump / Truth Social posts):
{_format_mood(stock.market_mood)}

TRUMP MENTIONS OF THIS COMPANY:
{_format_mentions(stock.trump_mentions)}

Weigh MARKET MOOD as a macro overlay and TRUMP MENTIONS as a stock-specific factor, the same way
you weigh news — but treat political-post inference as noisy and low-certainty: it must not
override strong technical or fundamental evidence, and you must NOT create dated buy/sell signals
from these posts (they inform the current recommendation only).

{_JSON_SCHEMA_HINT}"""
```

- [ ] **Step 4: Surface `market_mood` on the result**

In `_to_result`, add `"market_mood"` to the `reserved` set so an echoed key never collides:

```python
    reserved = {"ticker", "provider", "model", "generated_at", "disclaimer", "market_mood"}
```

In `analyze`, set it inside `_finalize` (the closure already has `stock`):

```python
    def _finalize(text: str) -> AnalysisResult:
        result = _to_result(extract_json(text), stock.ticker, provider_name, model)
        result.market_mood = stock.market_mood
        return _filter_incoherent_signals(_snap_signals(result, stock), stock)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analyzer.py -q`
Expected: PASS (all analyzer tests, including the 3 new ones).

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/analyzer.py backend/tests/test_analyzer.py
git commit   # feat(backend): add mood + mention prompt sections; surface mood on result
```

---

## Task 7: `analysis_service.py` — wire into `run_analysis`

**Files:**
- Modify: `backend/app/services/analysis_service.py`
- Test: `backend/tests/test_analysis_service.py`

- [ ] **Step 1: Write the failing tests** (append to `test_analysis_service.py`)

```python
from app.models.schemas import MarketMood, Mention, TruthPost


def test_run_analysis_attaches_truth_signal(tmp_path, monkeypatch):
    settings = Settings()  # truth_signal.enabled defaults True
    settings.providers["anthropic"].api_key = "k"

    captured = {}

    def fake_analyze(stock, provider, model, provider_name):
        captured["mentions"] = stock.trump_mentions
        captured["mood"] = stock.market_mood
        from app.analysis.analyzer import analyze as real
        return real(stock, provider, model, provider_name)

    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(analysis_service, "analyze", fake_analyze)
    monkeypatch.setattr(
        analysis_service.truth_social, "fetch_recent_posts_cached",
        lambda *a, **k: [TruthPost(id="1", created_at="2026-06-04T10:00:00Z",
                                   content="$AAPL great", url="https://t/1")],
    )
    monkeypatch.setattr(
        analysis_service.political, "summarize_market_mood",
        lambda *a, **k: MarketMood(lean="risk_on", confidence=0.6, post_count=1),
    )

    cache = Cache(str(tmp_path / "app.db"))
    analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert captured["mood"].lean == "risk_on"
    assert any(m.matched == "$AAPL" for m in captured["mentions"])


def test_run_analysis_skips_signal_when_disabled(tmp_path, monkeypatch):
    settings = Settings()
    settings.truth_signal.enabled = False
    settings.providers["anthropic"].api_key = "k"

    called = {"fetch": False}

    def must_not_fetch(*a, **k):
        called["fetch"] = True
        return []

    monkeypatch.setattr(analysis_service, "get_stock_data", lambda *a, **k: _stock())
    monkeypatch.setattr(analysis_service, "build_provider", lambda s: FakeProvider())
    monkeypatch.setattr(analysis_service.truth_social, "fetch_recent_posts_cached", must_not_fetch)

    cache = Cache(str(tmp_path / "app.db"))
    result = analysis_service.run_analysis("aapl", "2y", settings, cache)
    assert result.current_recommendation == "hold"
    assert called["fetch"] is False  # disabled => no fetch
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analysis_service.py -q`
Expected: FAIL — `AttributeError: module 'app.services.analysis_service' has no attribute 'truth_social'`.

- [ ] **Step 3: Wire the signal into `run_analysis`**

In `backend/app/services/analysis_service.py`, add imports (below the existing `from app.analysis.analyzer import analyze`):

```python
from app.analysis import political
from app.data import truth_social
```

Replace the tail of `run_analysis` (the `stock = ...` / `provider = ...` / `result = ...` block) with:

```python
    stock = get_stock_data(ticker, period, settings.indicator_params, cache)
    provider = build_provider(settings)

    ts = settings.truth_signal
    if ts.enabled:
        posts = truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
        stock.trump_mentions = political.find_mentions(posts, ticker, stock.company_name)
        stock.market_mood = political.summarize_market_mood(
            posts, provider, cfg.model, provider_id, cache
        )

    result = analyze(stock, provider, model=cfg.model, provider_name=provider_id)
    cache.set(cache_key, result.model_dump_json(), ANALYSIS_TTL_SECONDS)
    return result
```

(`find_mentions` and `summarize_market_mood` never raise — the cached fetch returns `[]` on
failure and the summarizer returns a neutral mood — so the signal block cannot break analysis.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analysis_service.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/analysis_service.py backend/tests/test_analysis_service.py
git commit   # feat(backend): wire Truth Social mood + mentions into run_analysis
```

---

## Task 8: API — `GET /api/truth/mood` preview

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_truth.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_truth.py`:

```python
from fastapi.testclient import TestClient

from app.api import routes
from app.config.cache import Cache
from app.main import app
from app.models.schemas import MarketMood, Settings, TruthPost


def _client_with(store, cache):
    app.dependency_overrides[routes.get_settings_store] = lambda: store
    app.dependency_overrides[routes.get_cache] = lambda: cache
    return TestClient(app)


def test_truth_mood_disabled(tmp_path):
    class Store:
        def load(self):
            s = Settings()
            s.truth_signal.enabled = False
            return s

    client = _client_with(Store(), Cache(str(tmp_path / "c.db")))
    body = client.get("/api/truth/mood").json()
    app.dependency_overrides.clear()
    assert body == {"enabled": False, "post_count": 0, "mood": None}


def test_truth_mood_returns_mood(tmp_path, monkeypatch):
    class Store:
        def load(self):
            s = Settings()
            s.providers["anthropic"].api_key = "k"
            return s

    monkeypatch.setattr(
        routes.truth_social, "fetch_recent_posts_cached",
        lambda *a, **k: [TruthPost(id="1", created_at="2026-06-04T10:00:00Z", content="x", url="")],
    )
    monkeypatch.setattr(routes, "build_provider", lambda s: object())
    monkeypatch.setattr(
        routes.political, "summarize_market_mood",
        lambda *a, **k: MarketMood(lean="risk_off", confidence=0.7, post_count=1),
    )

    client = _client_with(Store(), Cache(str(tmp_path / "c.db")))
    body = client.get("/api/truth/mood").json()
    app.dependency_overrides.clear()
    assert body["enabled"] is True
    assert body["post_count"] == 1
    assert body["mood"]["lean"] == "risk_off"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_truth.py -q`
Expected: FAIL — 404 (route not defined) / `AttributeError` on `routes.truth_social`.

- [ ] **Step 3: Add the route**

In `backend/app/api/routes.py`, add imports near the others:

```python
from app.analysis import political
from app.data import truth_social
```

Append this route:

```python
@router.get("/truth/mood")
def truth_mood(
    cache: Cache = Depends(get_cache),
    store: SettingsStore = Depends(get_settings_store),
) -> dict:
    settings = store.load()
    ts = settings.truth_signal
    if not ts.enabled:
        return {"enabled": False, "post_count": 0, "mood": None}
    posts = truth_social.fetch_recent_posts_cached(ts.lookback_hours, ts.source_url, cache)
    try:
        provider = build_provider(settings)
        cfg = settings.providers[settings.active_provider]
        mood = political.summarize_market_mood(
            posts, provider, cfg.model, settings.active_provider, cache
        )
        return {"enabled": True, "post_count": len(posts), "mood": mood.model_dump()}
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "post_count": len(posts), "mood": None, "error": str(exc)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_truth.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_truth.py
git commit   # feat(backend): add GET /api/truth/mood preview endpoint
```

---

## Task 9: Frontend — types + Settings toggle

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/pages/Settings.tsx`

> UI is verified by `npm run build` (tsc typecheck) + the existing `smoke.test.ts`, matching this
> repo's pattern (Settings.tsx has no component test today).

- [ ] **Step 1: Add types**

In `frontend/src/types.ts`, add the new interfaces (after `NewsItem`):

```ts
export interface MoodTheme { label: string; lean: 'bullish' | 'bearish' | 'neutral'; quote: string; post_url: string; created_at: string; }
export interface MarketMood { lean: 'risk_on' | 'neutral' | 'risk_off'; confidence: number; summary: string; themes: MoodTheme[]; as_of: string; post_count: number; }
export interface Mention { post_id: string; created_at: string; matched: string; excerpt: string; url: string; }
export interface TruthSignalConfig { enabled: boolean; source_url: string; lookback_hours: number; }
```

Extend `StockData` (add two optional fields):

```ts
  news: NewsItem[];
  market_mood?: MarketMood | null;
  trump_mentions?: Mention[];
```

Extend `AnalysisResult` (add after `disclaimer`):

```ts
  disclaimer: string;
  market_mood?: MarketMood | null;
```

Extend `Settings` (add after `alerts`):

```ts
  alerts: AlertConfig;
  truth_signal: TruthSignalConfig;
```

- [ ] **Step 2: Add the Settings section**

In `frontend/src/pages/Settings.tsx`, extend the type import:

```ts
import type { AlertConfig, ProviderId, Settings as SettingsT, TestResult, TruthSignalConfig } from '../types';
```

Add an updater next to `updateAlerts` (after line 26):

```ts
  const updateTruth = (patch: Partial<TruthSignalConfig>) => update({ truth_signal: { ...form.truth_signal, ...patch } });
```

Add this section to the JSX, just **before** the `<div className="settings-actions">` block:

```tsx
      <h3>Truth Social signal</h3>
      <div className="field check">
        <label>
          <input
            type="checkbox"
            checked={form.truth_signal.enabled}
            onChange={(e) => updateTruth({ enabled: e.target.checked })}
          />
          Use Trump / Truth Social posts as a market-mood + mention signal
        </label>
      </div>
      {form.truth_signal.enabled && (
        <div className="field">
          <label>Lookback (hours)</label>
          <input
            type="number"
            value={form.truth_signal.lookback_hours}
            onChange={(e) => updateTruth({ lookback_hours: Number(e.target.value) })}
          />
        </div>
      )}
```

- [ ] **Step 3: Typecheck + build**

Run (from `frontend/`): `npm run build`
Expected: tsc passes (no type errors), vite build succeeds.

- [ ] **Step 4: Run the frontend tests**

Run: `npm run test`
Expected: existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/pages/Settings.tsx
git commit   # feat(frontend): Truth Social signal types + Settings toggle
```

---

## Task 10: Frontend — `getMood` client + mood line (optional polish)

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`, `frontend/src/components/ReasoningPanel.tsx`

- [ ] **Step 1: Write the failing client test**

Paste this `it(...)` block inside the existing `describe('api client', ...)` in `client.test.ts`:

```ts
  it('getMood GETs /truth/mood', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ enabled: true, post_count: 2, mood: null }) });
    vi.stubGlobal('fetch', fetchMock);
    const body = await api.getMood();
    expect(body.post_count).toBe(2);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/truth/mood'), expect.any(Object));
  });
```

- [ ] **Step 2: Run to verify it fails**

Run (from `frontend/`): `npm run test -- client`
Expected: FAIL — `api.getMood is not a function`.

- [ ] **Step 3: Add `getMood` to the client**

In `frontend/src/api/client.ts`, import the type and add the method:

```ts
import type { AnalysisResult, MarketMood, ProviderInfo, Settings, StockData, TestResult } from '../types';
```

Add inside the `api` object (after `testAlert`):

```ts
  getMood: () => http<{ enabled: boolean; post_count: number; mood: MarketMood | null }>('/truth/mood'),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- client`
Expected: PASS.

- [ ] **Step 5: Show the mood in the reasoning panel**

In `frontend/src/components/ReasoningPanel.tsx`, add a mood line just after the `verdict` `<div>` closes (before the `key_factors` block):

```tsx
      {result.market_mood && result.market_mood.post_count > 0 && (
        <p className="note muted">
          Policy / market mood: <b>{result.market_mood.lean.replace('_', ' ')}</b>
          {result.market_mood.summary ? ` — ${result.market_mood.summary}` : ''}
        </p>
      )}
```

- [ ] **Step 6: Typecheck, build, test**

Run (from `frontend/`): `npm run build && npm run test`
Expected: tsc passes; all vitest tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/components/ReasoningPanel.tsx
git commit   # feat(frontend): mood preview client + reasoning-panel mood line
```

---

## Task 11: Docs + full verification

**Files:**
- Modify: `README.md` and/or `backend/README.md` (whichever documents data sources / analysis).

- [ ] **Step 1: Document the signal**

Add a short subsection to the README describing: the Trump / Truth Social signal (market mood +
direct mentions), the `ix.cnn.io` source, the `truth_signal` Settings toggle (default on,
48h lookback), `GET /api/truth/mood`, and the **caveats** — decision support only, noisy
political inference, informs the *current* call (no historical markers), "as of the day's first
analysis" caching, single swappable source.

- [ ] **Step 2: Full backend suite**

Run (from `backend/`): `.venv/Scripts/python.exe -m pytest -q`
Expected: all green (the existing 82 + the new tests).

- [ ] **Step 3: Full frontend build + tests**

Run (from `frontend/`): `npm run build && npm run test`
Expected: build clean, all vitest tests pass.

- [ ] **Step 4: Live smoke (manual, optional)**

With a provider key configured and the backend running
(`uvicorn app.main:app --reload --port 8000`):
- `GET http://localhost:8000/api/truth/mood` returns a mood (or `enabled:false`).
- `POST http://localhost:8000/api/analyze/AAPL` returns an `AnalysisResult` whose
  `key_factors` reflect the mood/mentions when posts are relevant, and `market_mood` is populated.

- [ ] **Step 5: Commit**

```bash
git add README.md backend/README.md
git commit   # docs: document the Trump / Truth Social signal + caveats
```

---

## Self-review notes (coverage vs spec)

- **Data source + swappable fetcher** → Tasks 2–3 (`fetch_recent_posts` takes `source_url`; only
  `_fetch_archive` does I/O, so a different backend swaps in there). ✅
- **Shared mood (one LLM call/day) + per-ticker mentions** → Tasks 4–5; cache-sharing proven by
  `test_summarize_is_cached_per_provider_day`. ✅
- **Two prompt sections; current-call only, no historical markers** → Task 6 (prompt text +
  instruction line; no signal touches `signals`). ✅
- **Wired into `run_analysis`; graceful degradation; disabled = today's behavior** → Task 7
  (both new calls are non-raising; `enabled=False` short-circuits). ✅
- **Settings toggle (default on), no secret/masking** → Task 1 (`TruthSignalConfig`, no key →
  `merge_settings` needs no change) + Task 9 (UI). ✅
- **Optional preview endpoint + UI** → Tasks 8 and 10. ✅
- **Caveats / honesty** → Task 11 docs; disclaimer still rides on every `AnalysisResult`. ✅

**Type consistency check:** `fetch_recent_posts_cached(lookback_hours, source_url, cache)` and
`summarize_market_mood(posts, provider, model, provider_name, cache)` are called with the same
signatures in Tasks 7 and 8 as defined in Tasks 3 and 5. `find_mentions(posts, ticker,
company_name)` matches. `MarketMood` / `Mention` / `TruthPost` / `TruthSignalConfig` field names
are identical across backend (Task 1) and frontend (Task 9) types.
