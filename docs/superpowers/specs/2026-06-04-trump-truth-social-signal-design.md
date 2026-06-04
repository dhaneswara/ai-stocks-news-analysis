# Trump / Truth Social Signal — Design

- **Date:** 2026-06-04
- **Status:** Approved (v1 scope)
- **Builds on:** the backend on `master` (data/indicators/analysis/settings/cache layers),
  specifically the news → analyzer pipeline (`data/news.py`, `analysis/analyzer.py`,
  `services/analysis_service.py`).

## Overview

A new **data signal** that reads Donald Trump's recent Truth Social posts and feeds them
into the existing per-ticker LLM analysis as two compact, auditable inputs:

1. **Market mood** — a *shared* risk-on / risk-off read derived **once** from the recent
   posts (covers macro themes: tariffs, Fed, war/ceasefire), reused across every ticker.
2. **Direct mentions** — a *per-ticker* deterministic scan for posts that name the company
   being analyzed (ticker, `$CASHTAG`, company name + aliases).

Both are injected into `build_user_prompt` alongside the existing news/technicals/
fundamentals, and the LLM weighs them as it already weighs headlines. The signal informs
the **current** recommendation/sentiment/confidence and `key_factors` only — it does **not**
fabricate historical dated buy/sell chart markers.

This is **decision support, not financial advice.** Political-post inference is noisy, so
it stays one weighted input among many — never an auto-trigger, never an auto-trade.

## Locked decisions

| Decision | Choice |
|---|---|
| Scope | Feeds the existing per-ticker analysis (no new alert/panel in v1) |
| Targeting | Both: shared **market mood** + per-ticker **direct mentions** |
| Source | `https://ix.cnn.io/data/truth-social/truth_archive.json` (live, ~5-min, no auth) |
| Format | `.json` variant (no new deps); `.parquet` noted as a future size optimization |
| Lookback | 48 hours (configurable) |
| Effect | Informs the *current* recommendation only — **no** historical chart markers |
| Delivery | A Settings toggle (`enabled`), **on** by default once built |
| Interpretation | LLM reads target + sentiment (not keyword rules); mentions matched deterministically |

## Data source

The CNN-hosted mirror of the `stilesdata/trump-truth-social-archive` project is the **full**
archive in one file, refreshed ~every 5 minutes, no auth. Each record carries:
`id`, `created_at`, `content` (may contain HTML — we strip tags), `url`, `media`, and
engagement counts. We pull the `.json` variant, filter to the lookback window, and cache the
pull so we are not re-downloading the whole history on every analysis.

The fetcher is isolated behind one function so the source is **swappable** — if the mirror
ever goes away, `truthbrush` or a paid scraper API drops in behind the same interface.

> Not the stale `stilesdata.com/.../truth_archive.json` (its updater was disabled 2025-10-26).

## New data models (`models/schemas.py`)

```jsonc
// TruthPost — one parsed post within the lookback window
{ "id": "111...", "created_at": "2026-06-04T13:10:00Z",
  "content": "...$AAPL should build in America...", "url": "https://truthsocial.com/..." }

// MoodTheme — one driver behind the mood
{ "label": "Tariff escalation vs China", "lean": "bearish",
  "quote": "massive increase of Tariffs", "post_url": "https://...", "created_at": "..." }

// MarketMood — shared, ticker-independent
{ "lean": "risk_off", "confidence": 0.7, "summary": "1–2 sentences",
  "themes": [ /* MoodTheme */ ], "as_of": "2026-06-04T...", "post_count": 12 }

// Mention — per-ticker, deterministic
{ "post_id": "111...", "created_at": "...", "matched": "$AAPL",
  "excerpt": "...build $AAPL in America...", "url": "https://..." }
```

Extensions to existing models:
- `StockData` gains `market_mood: Optional[MarketMood] = None` and
  `trump_mentions: list[Mention] = []`.
- `AnalysisResult` gains `market_mood: Optional[MarketMood] = None` (so the frontend can
  show the "why").
- `Settings` gains `truth_signal: TruthSignalConfig`.

```jsonc
// TruthSignalConfig — no secrets (public source), so no masking needed
"truth_signal": {
  "enabled": true,
  "source_url": "https://ix.cnn.io/data/truth-social/truth_archive.json",
  "lookback_hours": 48
}
```

## Components

```
backend/app/data/truth_social.py
  fetch_recent_posts(lookback_hours, cache, *, now=None) -> list[TruthPost]
      # httpx GET (cached ~30 min) -> parse -> strip HTML -> filter to window.
      # On any error: return []  (graceful, mirrors news.get_news)
  filter_recent(posts, hours, now) -> list[TruthPost]   # pure, testable

backend/app/analysis/political.py
  find_mentions(posts, ticker, company_name, aliases=None) -> list[Mention]
      # pure, deterministic: ticker / $CASHTAG / company name + aliases,
      # case-insensitive, word-boundary (no "CAT" inside "locate"); excerpt window.
  build_mood_prompt(posts) -> tuple[str, str]           # (system, user) for the summary
  summarize_market_mood(posts, provider, model, cache) -> MarketMood
      # ONE LLM call, cached under a ticker-INDEPENDENT key (provider+model+day),
      # so analyzing AAPL then MSFT the same day reuses it. Empty posts / LLM error
      # -> neutral MarketMood with empty themes (never raises).
```

Plus edits to existing files:
- `analysis/analyzer.py` — `build_user_prompt` adds two sections (**MARKET MOOD**,
  **TRUMP MENTIONS OF THIS COMPANY**) and a few instruction lines; `_to_result`/`analyze`
  copy `stock.market_mood` onto the result.
- `services/analysis_service.py` — `run_analysis` wires it in (see Data flow).
- `models/schemas.py` — the new models + the three extensions above.
- `api/routes.py` — optional `GET /api/truth/mood` preview (debug / Settings "it works").
- Frontend — `types.ts`, `api/client.ts`, a **Settings → Truth Social** toggle, and an
  optional small "policy/market mood" line in the dashboard reasoning area.

## Data flow (`run_analysis`)

```
run_analysis(ticker, period, settings, cache):
  ... existing cache check (analysis:{ticker}:{provider}:{model}:{period}:{today}) ...
  stock    = get_stock_data(...)                      # unchanged: price/indicators/news
  provider = build_provider(settings)
  if settings.truth_signal.enabled:
      posts = truth_social.fetch_recent_posts(lookback_hours, cache)   # cached pull
      stock.trump_mentions = political.find_mentions(posts, ticker, stock.company_name)
      stock.market_mood    = political.summarize_market_mood(posts, provider, model, cache)
  result = analyze(stock, provider, model, provider_id)  # reads the two new fields
  ... cache + return (result now carries market_mood) ...
```

The mood is computed **once per provider per day** (its own cache key, shared across all
tickers); `find_mentions` is pure and cheap (no LLM). A disabled signal or a failed fetch
leaves `market_mood=None` / `trump_mentions=[]`, so `analyze` behaves exactly as today.

## Prompt changes (`build_user_prompt`)

Two compact sections appended before the JSON schema hint:

```
MARKET MOOD (recent Trump / Truth Social posts, last {lookback}h):
- Lean: risk_off (confidence 0.70)
- Why: threatened a "massive increase of Tariffs" on China; ...
- Themes: tariff escalation (bearish); rate-cut pressure on Fed (bullish)
   (or "- (Trump signal disabled or no recent posts)")

TRUMP MENTIONS OF THIS COMPANY (last {lookback}h):
- [2026-06-04T13:10Z] "...$AAPL should build in America..."  (https://...)
   (or "- (none)")
```

Instruction additions:
- Weigh **MARKET MOOD** as a macro overlay and **TRUMP MENTIONS** as a stock-specific
  factor, together with the news/technicals/fundamentals.
- When material, add a `key_factor` citing it and labeling macro vs stock-specific with the
  lean — e.g. `"Trump: 'massive tariff increase on China' (macro, bearish)"`.
- Treat political-post inference as **noisy / low-certainty**; do not let it override strong
  technical or fundamental evidence.
- Do **not** create historical dated buy/sell signals from these posts — they inform the
  current recommendation only.

## Caching

| Key | Holds | TTL |
|---|---|---|
| `truth_posts:{lookback}` | the filtered post pull (JSON) | ~30 min |
| `truth_mood:{provider}:{model}:{lookback}:{YYYY-MM-DD}` | the `MarketMood` | 24 h |

Reuses the existing `Cache` (SQLite key/value with TTL). The posts pull is shared so
multiple tickers in one session download the archive once; the mood is day-keyed so the
summary LLM call happens at most once per provider per day.

## Configuration & frontend

- `truth_signal` added to `Settings` (SQLite store). No secret → no masking, simpler than
  `AlertConfig`. (If a paid source with a key is added later, add a masked `api_key`,
  reusing the provider-key mask/merge mechanism.)
- **Settings → Truth Social** section: an **Enabled** toggle and a **lookback (hours)**
  input. Reuses the existing settings save/merge flow.
- Dashboard (optional, small): a one-line "policy / market mood" chip from
  `AnalysisResult.market_mood`; the `key_factors` already carry the specifics.

## Error handling / degradation

- Fetch failure (network, bad JSON, source moved) → `fetch_recent_posts` returns `[]`;
  no mood, no mentions; analysis proceeds exactly as today.
- `summarize_market_mood` LLM failure → neutral `MarketMood` (empty themes); never raises,
  never blocks the analysis.
- `enabled=false` → the whole block is skipped.
- The Trump layer is **never** on the critical path for producing an analysis.

## Testing (TDD)

- **truth_social.py** — parse an archive-JSON fixture → `TruthPost`s; `filter_recent` keeps
  only in-window posts (fixed injected `now`); HTML stripped from `content`; fetch error →
  `[]`; cached pull avoids a second httpx call (mocked httpx + `Cache`).
- **political.find_mentions** — matches ticker, `$AAPL`, company name + alias;
  case-insensitive; **word-boundary** guard (no `CAT` inside `locate`/`category`); excerpt
  window; no-match → `[]`; multiple matches.
- **political.summarize_market_mood** — prompt includes the posts; mocked LLM JSON →
  `MarketMood`; empty posts / malformed JSON → neutral mood; **cache hit avoids the second
  LLM call** across two tickers.
- **analyzer.build_user_prompt** — includes both sections when present; graceful
  placeholders when absent; result carries `market_mood`.
- **run_analysis** (integration, mocked fetch/mood) — enabled: stock gets mood + mentions,
  result carries `market_mood`; disabled: byte-identical to today; fetch failure: degrades
  to today's behavior.
- **settings** — `TruthSignalConfig` defaults; round-trips through the store.
- **api** — `GET /api/truth/mood` ok + degraded paths (if the endpoint is included).
- **frontend** — `types.ts` + the Settings toggle render/save.

## Build order

1. Schema: `TruthPost`, `MoodTheme`, `MarketMood`, `Mention`, `TruthSignalConfig`;
   `StockData` / `AnalysisResult` / `Settings` extensions.
2. `data/truth_social.py` — `filter_recent` (TDD) then `fetch_recent_posts` (mocked httpx).
3. `analysis/political.py` — `find_mentions` (TDD), then `build_mood_prompt` +
   `summarize_market_mood` (TDD, mocked LLM + cache).
4. `analyzer.build_user_prompt` + `analyze` wiring (TDD).
5. `services/analysis_service.run_analysis` integration (TDD, mocked deps).
6. `GET /api/truth/mood` route (optional; TDD).
7. Frontend: `types.ts` + `api/client.ts` + Settings → Truth Social section
   + optional dashboard mood chip.

## Caveats

- **Not financial advice.** The `DISCLAIMER` still rides on every `AnalysisResult`. Political
  posts are a soft, noisy overlay the LLM weighs — not a validated per-stock predictor.
- **Attribution is fuzzy.** Most market-moving posts are macro (tariffs/Fed/war) and move
  *indices/sectors*, not one stock — hence the shared mood overlay plus explicit mentions,
  rather than a deterministic per-ticker rule.
- **Intraday is out of scope (v1).** Honoring the existing per-day analysis cache, the Trump
  read is effectively "as of the day's first analysis per ticker." Real-time reaction to a
  breaking post is the job of the *future* Telegram-alert extension, not this scope.
- **Single hosted source.** We consume a public, third-party-hosted archive (no scraping on
  our side). If it disappears, swap the fetcher (`truthbrush` / paid API). Don't redistribute
  the data.
- **Cost.** One extra LLM call per provider per day (the mood, shared across tickers) plus an
  archive download at most every ~30 min. `find_mentions` adds no LLM cost.
