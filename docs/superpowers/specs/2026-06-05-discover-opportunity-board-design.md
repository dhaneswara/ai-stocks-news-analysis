# Discover — Auto-ranked Opportunity Board — Design

- **Date:** 2026-06-05
- **Status:** Approved (Phase 1 scope)
- **Builds on:** the backend on `master` (data/indicators/analysis/settings/cache layers)
  and the scheduled-alerts infrastructure (`app/alerts/` runner + state + OS scheduler).
  Reuses `services/stock_service.get_stock_data`, `analysis/indicators`,
  `alerts/rules.evaluate_rules`, and `analysis/political.find_mentions`.

## Overview

A new **Discover** feature that stops the stock-by-stock grind. Instead of loading and
LLM-analyzing tickers one at a time, the app screens the **entire S&P 500** with a cheap,
deterministic **scoring engine** and presents an **auto-ranked opportunity board**: every
constituent gets a **0–100 opportunity score** plus a **buy / sell / hold** tag, ranked
highest-first, filterable by **sector** and **direction**.

Each row shows its **reasons** in plain language ("RSI 28 · near 52-wk low · Trump mention")
so the ranking is transparent, not a black box. Clicking a row jumps to the **existing**
Dashboard deep-dive (chart + full LLM analysis) — so the **paid LLM cost stays exactly where
it is today**, on the one stock you actually open. The board itself uses **no LLM**.

A full 500-name scan is the only expensive step, so it runs as a **daily post-close
scheduled job** (mirroring the alerts runner) that stores a ranked snapshot the board reads
**instantly**; a **Rescan** button refreshes on demand.

This is **decision support, not financial advice.** The score is a transparent heuristic
that surfaces *attention-worthy setups* — a ranking, not a prediction, and never an
auto-trade.

### Phasing

This is **Phase 1 (Discovery)** of a two-part effort. **Phase 2 (Triage)** will point the
*same* scoring engine at the user's existing `watchlist` to rank what they already track.
Discovery is built first by request; the scorer is designed to be reused unchanged.

## Locked decisions

| Decision | Choice |
|---|---|
| Phase | Discovery first (Phase 1); watchlist triage = Phase 2, reuses the scorer |
| Universe | S&P 500, shipped as a static sector-tagged data file |
| Interaction | Auto-ranked **opportunity board** (the app decides), sector + direction filters |
| Signals | Extremes/reversal + trend/momentum + catalyst (Trump + news). **No fundamentals.** |
| News | Reserved for the **deep-dive** — **not** in the bulk score (a per-ticker news fetch ×500 is too costly) |
| Catalyst direction | A Trump mention is an **attention/score boost only**, *not* a directional vote (we can't cheaply judge its sentiment — the deep-dive LLM does) |
| Score | 0–100 weighted blend of normalized signal **intensities**; direction = net **signed** balance; reasons listed |
| Scan timing | Daily post-close **scheduled snapshot** + on-demand **Rescan** |
| LLM | **None** in the board; the existing `/analyze/{ticker}` runs only on the opened stock |
| Weights | Sensible **documented defaults**, tunable via `ScreenerConfig` (no per-user tuning UI in v1) |
| Add to watchlist | **Included** in Phase 1 (per-row action) |

## The universe (`app/data/universe.py` + `app/data/sp500.json`)

A static snapshot of the ~500 S&P 500 constituents is committed to the repo as
`app/data/sp500.json`:

```jsonc
[
  { "ticker": "AAPL", "name": "Apple Inc.",        "sector": "Information Technology" },
  { "ticker": "XOM",  "name": "Exxon Mobil Corp.", "sector": "Energy" },
  // ... ~500 rows, GICS sector tags
]
```

```python
# app/data/universe.py
load_universe(sector: str | None = None) -> list[UniverseEntry]
    # parse the bundled JSON (once, module-cached); optionally filter by sector.
list_sectors() -> list[str]        # distinct, sorted — powers the filter dropdown
```

Static file, deliberately: no fragile scraping on the request path. A short doc note
(`app/data/README` or a module docstring) records where the list came from and how to
refresh it. Survivorship/drift is acceptable — we screen the *current* snapshot, and a
quarterly manual refresh is enough.

## New data models (`models/schemas.py`)

```jsonc
// UniverseEntry — one constituent from the bundled file
{ "ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology" }

// StockScore — the scorer's verdict for one ticker
{
  "ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology",
  "price": 201.34, "change_pct": 1.2,
  "score": 78.0,                       // 0–100 opportunity (how much is firing)
  "direction": "buy",                  // buy | sell | hold (net signed balance)
  "reasons": ["RSI 28 (oversold)", "near 52-wk low", "Trump mention"],
  "components": { "extremes": 0.81, "trend": 0.40, "momentum": 0.55,
                  "volume": 0.30, "catalyst": 1.0 },   // per-family intensities, for transparency/tests
  "as_of": "2026-06-05T21:08:00Z"      // when THIS row was scored (supports incremental rescan)
}

// ScreenBoard — a ranked snapshot
{
  "as_of": "2026-06-05T21:10:00Z",     // last full scan
  "scope": "all",                      // "all" or a sector name (for a sector rescan)
  "scanned": 503, "skipped": 4,        // skipped = per-ticker fetch failures
  "items": [ /* StockScore, sorted by score desc */ ]
}

// ScreenerConfig — added to Settings (no secrets -> no masking)
{
  "enabled": true,
  "top_n": 25,                         // board size returned to the UI
  "default_sector": null,
  "rsi_low": 30.0, "rsi_high": 70.0,   // reversal thresholds (match AlertConfig defaults)
  "weights": { "extremes": 1.0, "trend": 1.0, "momentum": 0.8,
               "volume": 0.4, "catalyst": 0.5 }
}
```

`Settings` gains `screener: ScreenerConfig = Field(default_factory=ScreenerConfig)`.

## The scoring engine (`app/analysis/scoring.py`) — the heart

A **pure, deterministic, no-LLM** function — the reusable primitive for both phases:

```python
score_stock(stock: StockData,
            mentions: list[Mention],
            cfg: ScreenerConfig) -> StockScore
```

Each signal produces an **intensity** in `[0, 1]` (how strongly it is firing) and, where it
implies direction, a **sign** (`+` bullish / `−` bearish). Within a family, sub-signals
combine into one family intensity (the strongest dominates, capped at 1). Two aggregates fall
out:

- **Opportunity score** = `100 × Σ(wᵢ · intensityᵢ) / Σ(wᵢ)` over the families below
  (bounded 0–100). "How much is happening here, weighted." A quiet mid-range stock scores
  low; one that is oversold *and* near its 52-wk low *and* Trump-mentioned scores high.
- **Direction** = sign of `Σ(signed directional intensities)`. `buy` if net `> +δ`,
  `sell` if net `< −δ`, else `hold` (δ ≈ 0.15). **Catalyst and volume add to the score but
  do not vote on direction** — they raise attention, not conviction.
- **reasons** = the firing signals, strongest-first, rendered as short human chips.

### Signal families (all computed from data we already fetch)

**1. Extremes / reversal** (`extremes`)
- *RSI:* `rsi ≤ rsi_low` → bullish, intensity `(rsi_low − rsi)/rsi_low`;
  `rsi ≥ rsi_high` → bearish, intensity `(rsi − rsi_high)/(100 − rsi_high)` (clamped).
- *Near 52-wk low:* `(price − low)/low` small → bullish reversal; intensity decays with
  distance (from `fundamentals.week52_low`).

**2. Trend & momentum** (`trend` + `momentum`)
- *Golden/death cross:* reuse `alerts.rules.evaluate_rules` on the latest bar → strong
  bullish / bearish event.
- *SMA alignment:* `price > SMA50 > SMA200` bullish / `price < SMA50 < SMA200` bearish;
  partial alignment → weaker.
- *Return:* 1-month (and 1-week) % change from candles → momentum, signed by direction.
- *52-wk-high breakout:* `dist_from_52wk_high_pct ≈ 0` while making highs → bullish momentum.

**3. Volume** (`volume`, attention-only)
- latest volume ÷ 20-day average; a surge raises the score and adds a "volume surge" reason;
  its sign follows the day's price change but it does **not** drive `direction`.

**4. Catalyst** (`catalyst`, attention-only)
- `find_mentions(posts, ticker, company_name)` non-empty → intensity from mention count,
  adds a "Trump mention" reason. **Direction-neutral** — we don't cheaply infer whether the
  mention is positive or negative; the deep-dive LLM judges that.
- *News volume* is **deferred to the deep-dive**, not the bulk score (a per-ticker news fetch
  ×500 is the one prohibitively heavy signal — and news already lives on the deep-dive).
  Noted in Caveats.

Default weights live in `ScreenerConfig.weights` (above), documented and tunable; no per-user
tuning UI in v1. Helper functions (`_rsi_signal`, `_trend_signal`, `_momentum_signal`,
`_volume_signal`, `_catalyst_signal`) are each pure and unit-tested in isolation.

## Scan orchestration & persistence (`app/screener/`)

Mirrors the cohesive `app/alerts/` package.

```python
# app/screener/service.py
run_scan(scope: str | None, settings: Settings, cache: Cache) -> ScreenBoard
    # scope=None -> full universe; scope="Energy" -> just that sector.
    # posts = truth_social.fetch_recent_posts_cached(...)   # ONCE per scan
    # for entry in load_universe(scope):
    #     try: stock = get_stock_data(entry.ticker, "1y", settings.indicator_params, cache)
    #          mentions = political.find_mentions(posts, entry.ticker, stock.company_name)
    #          items.append(score_stock(stock, mentions, settings.screener))
    #     except Exception: skipped += 1; continue     # never abort the whole scan
    # sort items by score desc; return ScreenBoard(...)

# app/screener/store.py — "latest snapshot" stored in the existing Cache (SQLite KV),
#   keyed `screen_snapshot:all`, long TTL (e.g. 7d) refreshed by the daily job; expiry just
#   yields the empty-state. Reuses the cache already injected via get_cache (no new table).
save_snapshot(board: ScreenBoard, cache: Cache) -> None    # upsert by scope
load_snapshot(cache: Cache) -> ScreenBoard | None          # the full "all" board
merge_sector(board: ScreenBoard, fresh: ScreenBoard) -> ScreenBoard  # replace that sector's rows + per-item as_of

# app/screener/runner.py + __main__.py — the scheduled job (mirror app/alerts.__main__)
#   python -m app.screener [--sector X] [--dry-run]
#   run(): board = run_scan(None, settings, cache); save_snapshot(board)
```

**Snapshot model:** the scheduled job scans **all 500 once** and stores **one full board**.
Sector filtering for `GET` is a cheap **read-time filter** of that stored board — no
per-sector snapshots. A **sector Rescan** does a fast live scan of just that sector and
**merges** the fresh rows back into the stored board (replacing those tickers, bumping their
per-item `as_of`), so freshness is visible per row while the board stays whole.

## API (`api/routes.py`)

```
GET  /api/screen?sector=&direction=&limit=   -> ScreenBoard (read-time filter of the snapshot)
       # no snapshot yet -> 200 with items:[] and as_of:null (frontend prompts a first scan)
POST /api/screen/rescan?sector=              -> ScreenBoard (live scan; sector=fast, all=slow)
       # runs run_scan synchronously, persists (full overwrite or sector-merge), returns board
GET  /api/screen/sectors                     -> ["Communication Services", "Energy", ...]
```

`GET /api/screen` is instant (reads the snapshot). `POST .../rescan` is the only slow call —
a sector rescan touches ~30–70 names; an all-sectors rescan warns the user it scans ~500.

## Data flow

```
# Daily (OS scheduler, post-close) — the normal path that populates the board:
python -m app.screener
  -> run_scan(None) -> [get_stock_data (cached) -> find_mentions -> score_stock] ×500
  -> sort -> save_snapshot(full board)

# Interactive:
GET /api/screen?sector=Tech  -> load_snapshot -> filter sector+direction -> top_n  (instant)
click row  -> navigate to Dashboard?ticker=NVDA  -> existing /analyze/{ticker}  (the only LLM)
"Add to watchlist"  -> PUT /api/settings (watchlist + [ticker])
"Rescan" (sector)   -> POST /api/screen/rescan?sector=Tech -> live scan -> merge -> return
```

The scheduled scan does the heavy yfinance pull **once/day**; within the yfinance cache TTL,
reads and rescans are cheap. `find_mentions` adds no LLM cost; the mood/news LLM work is
**not** invoked by the board at all.

## Frontend

- **Route + nav:** new **Discover** entry alongside Dashboard / Settings (`App.tsx`,
  react-router v7), `pages/Discover.tsx`.
- **Board** (`components/DiscoverBoard.tsx`): a ranked table — ticker · company · sector ·
  price/Δ · **score bar** · **buy/sell/hold tag** · **reason chips**. Header controls: sector
  dropdown (`/api/screen/sectors`), direction filter, "as of" + skipped count, **Rescan**
  button (spinner; warns on all-sectors). Reuses existing panel/CSS styling.
- **Row click → deep-dive:** navigate to the Dashboard for that ticker. Dashboard gains a
  small enhancement to **preselect a ticker from a `?ticker=` query param** (today it only
  defaults to `watchlist[0]`).
- **Per-row "Add to watchlist":** `PUT /api/settings` with `watchlist + [ticker]` (delta
  merge); reuses the settings flow.
- **Plumbing:** `types.ts` (`StockScore`, `ScreenBoard`), `api/client.ts`
  (`getScreen`, `rescan`, `getSectors`), `hooks/queries.ts` (`useScreen`, `useRescan`,
  `useSectors`).

## Error handling / degradation

- Per-ticker fetch/parse failure during a scan → **skip + count** (`skipped`); never abort.
- No snapshot yet → board renders an empty state prompting a first **Rescan**.
- Truth Social fetch failure → mentions empty; scoring proceeds (catalyst just contributes 0).
- yfinance throttling → sequential + cached; a partial board is acceptable and labeled.
- The board is **never** on the critical path of producing an LLM analysis (that's unchanged).

## Testing (TDD, repo's hermetic conventions)

- **scoring.py (the bulk):** each `_*_signal` helper pure-tested — RSI oversold/overbought
  boundaries, near-52wk-low decay, golden/death cross, SMA alignment, 1-mo return sign,
  volume surge, catalyst boost. `score_stock` end-to-end on synthetic `StockData`: a
  strong-bull fixture → high score + `buy` + expected reasons; a strong-bear fixture →
  `sell`; a flat fixture → low score + `hold`; catalyst/volume raise score **without**
  flipping direction; weights respected; output bounded 0–100.
- **universe.py:** loads the bundled JSON; `sector` filter; `list_sectors` distinct+sorted.
- **screener/service.run_scan:** stubbed `get_stock_data` (hermetic, like the conftest
  stubs) over a tiny fixture universe → ranked board; a raising ticker is **skipped** and
  counted; posts fetched once.
- **screener/store:** `save`/`load` round-trip; `merge_sector` replaces only that sector's
  rows and updates their `as_of`.
- **api:** `GET /api/screen` (empty + populated + sector/direction filter + limit);
  `POST /api/screen/rescan` (full + sector); `GET /api/screen/sectors`.
- **frontend:** board renders/sorts/filters; row-click routes to `?ticker=`; Rescan calls
  the API; Add-to-watchlist PUTs the delta; Dashboard preselects from `?ticker=`.

## Build order

1. `data/sp500.json` + `data/universe.py` (TDD).
2. Schemas: `UniverseEntry`, `StockScore`, `ScreenBoard`, `ScreenerConfig`; `Settings` ext.
3. `analysis/scoring.py` — signal helpers then `score_stock` (TDD — the largest test surface).
4. `screener/service.run_scan` (stubbed deps) + `screener/store` (TDD).
5. `screener/runner.py` + `__main__.py` (mirror `app/alerts`); document the OS schedule.
6. API routes: `GET /screen`, `POST /screen/rescan`, `GET /screen/sectors` (TDD).
7. Frontend: `types` + `client` + `hooks` + `Discover` page/board + nav/route +
   Dashboard `?ticker=` deep-link + Add-to-watchlist (vitest).

## Caveats

- **Not financial advice.** The board is a **screen**, not a recommendation. The `DISCLAIMER`
  still rides on every `AnalysisResult` produced by the deep-dive.
- **Ranking ≠ prediction.** The score is a transparent heuristic that surfaces
  *attention-worthy* setups; it is **not** a backtested alpha model. Score backtesting /
  performance metrics are explicitly deferred.
- **Catalyst is attention-only.** A Trump mention raises the score and flags the row, but
  **direction comes from price/technicals** — the deep-dive LLM judges whether the mention is
  bullish or bearish. This avoids a cheap, wrong sentiment guess across 500 names.
- **Daily cadence, not intraday.** The board is "as of the last scan," matching daily-candle
  swing trading. Intraday/real-time reaction is out of scope.
- **News excluded from the bulk score** for cost (a per-ticker news fetch ×500). It returns
  on the deep-dive, where it already lives.
- **yfinance scale.** ~500 sequential fetches per full scan; mitigated by caching and the
  off-peak schedule. Concurrency/threading is a future optimization (YAGNI in v1). Expect a
  full scan to take a few minutes cold, near-instant warm.
- **Universe maintenance.** The S&P 500 list drifts (adds/drops); the static file needs an
  occasional manual refresh. Documented at the data file.
- **Cost.** The board adds **no** LLM cost and at most one Truth Social archive pull per scan
  (cached). The only LLM spend remains the existing per-stock analysis on the row you open.
```