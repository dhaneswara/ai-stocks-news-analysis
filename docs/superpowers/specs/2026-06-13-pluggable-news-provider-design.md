# Pluggable news provider (with MCP client) — design

**Date:** 2026-06-13
**Status:** Approved (pending spec review)

## Context

The Graph page's **Expand neighbours** (and **Start from a company**) extracts inter-company
relationships from a company's news via one LLM call ([`extract_relationships`](../../../backend/app/analysis/relationships.py)).
Today the only news source is **Google News RSS** ([`data/news.py`](../../../backend/app/data/news.py)),
which returns headline + source + a low-value HTML summary — thin fuel for the LLM to reason
over. The user wants to optionally switch the news source, in Settings, to a richer
**MCP-based search provider** (Tavily / Exa / you.com), which returns extracted article content,
publish dates, and native recency filtering.

This is the first of **two sub-projects**:

1. **This spec — pluggable news provider (infrastructure).** A `NewsProvider` abstraction with
   Google News as the default and Tavily/Exa/you.com as MCP-client providers, selectable in
   Settings, and Expand neighbours repointed to the active provider.
2. **Follow-up (separate spec) — richer extraction.** A deal-focused query, snippet inclusion in
   the extraction prompt, and an M&A → owner/subsidiary prompt mapping. Out of scope here.

**Boundary:** this sub-project owns *where the news comes from* — the provider, recency, and
snippet *data*. Sub-project #2 owns *how the LLM reasons over it*.

## Architecture

A `NewsProvider` abstraction mirroring the existing **LLM provider system** (`app/llm/`): a
protocol, concrete providers, a factory with env-key fallback, masked API keys in settings, and a
test-connection endpoint. New package `backend/app/news/`.

```
build_company_graph (explorer)
        │  settings.news.active_provider
        ▼
build_news_provider(settings) ──► NewsProvider.search(query, *, limit, recency_days) ──► list[NewsItem]
        │                               ├── GoogleNewsProvider  (RSS + recent_news post-filter)
        │                               ├── TavilyNewsProvider  ┐
        │                               ├── ExaNewsProvider     ├─ via shared MCP streamable-HTTP client
        │                               └── YouNewsProvider     ┘
        ▼
extract_relationships(stock-with-provider-news, …)  (unchanged here)
```

### Components

**`backend/app/news/base.py`**
- `NewsProvider` Protocol: `search(self, query: str, *, limit: int, recency_days: int) -> list[NewsItem]`.
- `NewsError(Exception)` — raised by adapters; callers degrade to `[]`.
- A module-level `label: str` convention per provider class (for the test endpoint's messages),
  mirroring `OpenAIProvider.label`.

**`backend/app/news/google.py` — `GoogleNewsProvider` (default)**
- Wraps the existing `parse_feed`/`search_news` RSS logic (reused, not duplicated).
- RSS has no recency parameter, so it applies a pure `recent_news(items, *, days, now)` post-filter:
  parse `published_at` (RFC-822 via `email.utils.parsedate_to_datetime`), drop items older than
  `days`, sort newest-first; items with an unparseable date are kept (benefit of the doubt) and
  sorted last; `days <= 0` disables the cutoff (keep all, just sorted). `recent_news` lives in
  `data/news.py` (pure, reusable).

**`backend/app/news/mcp_client.py` — shared MCP transport**
- One helper that connects to a hosted **streamable-HTTP** MCP server using the official `mcp`
  Python SDK, initializes a session, calls one tool, and returns its text content:
  `call_tool(url: str, tool: str, args: dict, *, timeout: float) -> str`.
- The SDK client is async; the explorer fetch path is synchronous (the FastAPI route is a sync
  `def`, so it runs in Starlette's threadpool). The helper therefore runs the async client via
  `asyncio.run(...)` — safe because no event loop runs in that worker thread.
- Any transport/protocol/timeout failure raises `NewsError`.

**`backend/app/news/tavily.py`, `exa.py`, `you.py` — MCP adapters**
- Each builds its hosted endpoint URL with the API key and calls its search tool through
  `mcp_client.call_tool`, then parses the tool's JSON result into `NewsItem`s
  (`title`, `url`, `source`, `published_at`, and the extracted **content → `summary`**).
- Endpoints / tools / recency mapping (verified against live docs 2026-06-13):
  - **Tavily** — `https://mcp.tavily.com/mcp/?tavilyApiKey=<key>`, tool `tavily_search`,
    args include `query`, `max_results`, `topic="news"`, `days=<recency_days>`.
  - **Exa** — `https://mcp.exa.ai/mcp?exaApiKey=<key>`, tool `web_search_exa`, args include
    `query`, `num_results`, and a start-published-date derived from `recency_days`.
  - **you.com** — `https://api.you.com/mcp`, tool `you-search`, args include the query and a
    result count (key via the documented header/param).
- The **exact result field names** for each tool are confirmed against the live tool output while
  writing the implementation plan (each adapter parses defensively and skips malformed items).
- An optional `mcp_url` override per provider (in settings) lets the endpoint be repointed without
  a code change; empty → the documented default above.

**`backend/app/news/factory.py`**
- `build_news_provider(settings) -> NewsProvider` — picks the class for
  `settings.news.active_provider` from a `_REGISTRY`, passing the resolved config (mirrors
  `llm.factory.build_provider`). Unknown id → `NewsError`.
- `resolve_news_config(provider_id, cfg)` — fills `api_key` from an environment variable when the
  stored key is empty (`_NEWS_ENV_KEYS = {tavily: "TAVILY_API_KEY", exa: "EXA_API_KEY",
  you: "YDC_API_KEY"}`), mirroring `llm.factory.resolve_config`.
- `_NEWS_LABELS = {google: "Google News", tavily: "Tavily", exa: "Exa", you: "you.com"}`.

### Settings (`schemas.py`)

```python
NewsProviderId = Literal["google", "tavily", "exa", "you"]

class NewsProviderConfig(BaseModel):
    api_key: str = ""
    mcp_url: str = ""        # optional endpoint override; empty -> documented default

class NewsConfig(BaseModel):
    active_provider: NewsProviderId = "google"
    providers: dict[NewsProviderId, NewsProviderConfig] = (default: one entry per id)
    news_recency_days: int = 90
```

- `Settings` gains `news: NewsConfig = Field(default_factory=NewsConfig)`.
- A `@model_validator(mode="after")` backfills any missing provider entry (self-heals legacy
  persisted settings), mirroring the existing `_ensure_all_providers` validator.
- **Masking:** `mask_settings` masks every non-empty `news.providers[*].api_key` to `****`
  (Google has no key). **Merge:** `merge_settings` restores a `****` news key from the stored
  settings — identical sentinel handling to the LLM provider keys and the Telegram token.
- `news_recency_days` is the single recency control shared by all providers (Google post-filters;
  the MCP providers map it to their native recency parameter).

### API (`routes.py`)

- `GET /api/news/providers` → `[{id, label, configured}]` where `configured` reflects a stored
  key (Google is always `configured=true`). Mirrors `GET /api/providers`.
- `GET /api/news/test?provider=<id>` → `{ok: bool, message: str}`: builds the provider and runs a
  trivial search; catches all failures into `{ok: false, message}` at HTTP 200 (resilient, never
  500). Mirrors `GET /api/providers/{id}/test`.

### Expand-neighbours repoint (`network/service.py`)

`build_company_graph` fetches news through the active provider:
`build_news_provider(settings).search(query, limit=…, recency_days=settings.news.news_recency_days)`,
then hands those `NewsItem`s to `extract_relationships`. The `query` is the literal search string
each provider sends to its backend; in this sub-project it stays the current company-news form
**`f"{company_name} ({ticker}) stock"`** (the same string `get_news` builds today) — the
deal-focused query is sub-project #2. So with Google (the default) the only change is the
`recent_news` recency filter; `GoogleNewsProvider.search` sends `query` to RSS unchanged, while the
MCP providers send the same `query` to their search tool and return richer content. Provider failure → `NewsError` → the existing degrade path (lone root
node). No scoring/ontology/schema-for-edges change.

### Frontend

- `types.ts`: `NewsConfig` / `NewsProviderConfig` / `NewsProviderId`; `Settings.news`.
- `api/client.ts` + hooks: `getNewsProviders` / `testNews(provider)` + `useNewsProviders` /
  `useTestNews`, mirroring the LLM provider hooks.
- `Settings.tsx`: a new **"News source"** section — a provider `<select>` (Google / Tavily / Exa /
  you.com), a masked **API key** field shown for the selected non-Google provider, a
  **News recency (days)** number input bound to `news.news_recency_days`, and a **Test connection**
  button that saves the form first (like the LLM **Test connection** / **Fetch models** buttons)
  then calls `/api/news/test`, showing `✓`/`✗ message`. An `updateNews` helper mirrors
  `updateTruth`.

### Dependency

Add `mcp` (the official Model Context Protocol Python SDK) to `backend/pyproject.toml`. It is
pure-Python (httpx/anyio/pydantic deps), so it installs on Windows/ARM64 without native wheels.

## Error handling & degradation

- Adapter/transport failures raise `NewsError`; `build_company_graph` already catches and returns
  the lone-root graph, so the explorer never breaks because a provider is down/misconfigured.
- `/api/news/test` converts failures to a readable `{ok:false, message}` (HTTP 200) so the Settings
  UI can show why a provider didn't connect.
- A missing key for the active MCP provider surfaces as a failed search → `NewsError` → degrade;
  the user sees it explicitly via Test connection.

## Testing

- **Factory:** `build_news_provider` returns the right class per `active_provider`;
  `resolve_news_config` fills keys from env when the stored key is empty.
- **Adapters:** each MCP adapter parses a captured sample tool-result fixture into the expected
  `NewsItem`s with the **MCP client helper monkeypatched** (no network); malformed items skipped.
- **Google provider:** parses an RSS fixture and `recent_news` drops stale items, sorts
  newest-first, keeps unparseable-date items, and `days <= 0` disables the cutoff.
- **Settings:** `NewsConfig` defaults; the validator backfills a missing provider; `mask_settings`
  masks news keys; `merge_settings` restores a `****` news key; full round-trip through save/load.
- **API:** `/api/news/providers` shape + `configured` flag; `/api/news/test` ok and error paths
  (provider build monkeypatched).
- **Explorer:** `build_company_graph` calls `build_news_provider(...).search(...)` and feeds the
  result to extraction (factory monkeypatched).
- **Frontend:** the Settings "News source" section renders, switches provider, edits recency, and
  runs Test connection (client mocked) — added to `pages/Settings.test.tsx`.

## Out of scope (explicit)

- The deal-focused query, snippet-in-prompt, and M&A→owner/subsidiary prompt (sub-project #2).
- Repointing the Dashboard news list or the deep-analysis agent's `fetch_news` tool at the new
  provider (possible later; this sub-project repoints only Expand neighbours / Start-from-company).
- Any change to scoring, the active ontology, `RelationType`, or the graph legend.
