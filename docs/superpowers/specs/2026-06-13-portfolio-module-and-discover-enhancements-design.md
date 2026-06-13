# Portfolio module + Discover enhancements — design

**Date:** 2026-06-13

**Problem:** A full S&P 500 rescan is slow and mostly irrelevant to the handful of companies
the user actually tracks. The broad Discover board leaks in as the *primary* data source for
scoring even though the user only acts on their watchlist + ontology. The user wants a fast,
focused workspace over the companies they care about, plus several Discover quality-of-life
features (exchange / S&P-membership columns, adding non-S&P companies with auto-filled info,
a search filter, button tooltips).

## Architecture

One unifying concept:

```
portfolio_universe(settings, cache)  =  watchlist  ∪  active-ontology tickers
```

A single backend function returns this ticker set, which feeds:

1. **The Portfolio board scan** — fast, only these names (`screen_snapshot:portfolio`).
2. **Base-index precedence** — wherever scoring needs neighbour states, prefer the portfolio
   snapshot and fall back to the Discover (`all`) snapshot.
3. **The Evaluation runs** — snapshot + fast/deep LLM batches repointed from watchlist-only to
   this set.

**Why the "rewire" is small.** The only place the full S&P board acts as *primary* is the
network base index: `score_one` reads `screen_snapshot:all`, and `apply_network` blends a board
against its own rows. So "make Dashboard/Graph/Evaluation use the portfolio instead" reduces to
(a) one base-index helper and (b) repointing the Evaluation runs — **not** rewriting those
pages. Signals already come from the source-agnostic `PredictionStore`, so they follow
automatically once the portfolio set is what gets recorded. Discover stays as the broad S&P
explorer + custom-company search + the fallback for tickers not yet in the portfolio.

**New page, shared components.** The Portfolio page is a thin shell that reuses the existing
board, scan stream, and scoring — only the universe differs. No duplicated scan/score logic.

Rejected alternatives (from brainstorming): a "scope toggle on Discover" with no separate page
(muddier mental model — Discover should stay isolated for *new* company discovery); a "hard
replace" where the other pages read only the portfolio with no Discover fallback (loses the
graceful degrade for un-scanned tickers).

## Data model (`app/models/schemas.py`)

- `StockScore` gains `exchange: str = ""` and `in_sp500: bool = True`. Defaults keep every
  existing cached board valid on read (old S&P rows are correctly `in_sp500=True`).
- `UniverseEntry` gains `exchange: str = ""` (optional; populated for custom companies at
  add-time, blank for committed S&P rows whose exchange is filled live during a scan).
- Scan **scope `"portfolio"`** — the snapshot store already keys by scope
  (`screen_snapshot:<scope>`); we simply start writing/reading `screen_snapshot:portfolio`.

## Phase 1 — Portfolio module + base-index precedence (the core)

Delivers the headline value: a fast focused board that becomes the primary scoring source.

### Backend

- `app/data/universe.py`: `portfolio_universe(settings, cache)` returns the de-duplicated,
  upper-cased ticker list = `settings.watchlist` ∪ active-ontology ticker nodes. Ontology
  ticker nodes = native nodes (no `ext:` / `man:` prefix) from `active_graph(cache).nodes`.
- `app/screener/service.py`:
  - Generalize the scan to resolve a **scope → entry list**: a sector name → the S&P subset
    (today's behaviour); `"portfolio"` → a synthesized `UniverseEntry` per portfolio ticker
    (name/sector from `load_universe()` when the ticker is in the universe, otherwise filled
    from fetched `info` during the scan — an ontology/custom ticker need not be in `sp500.json`).
    Keep `iter_scan(scope, ...)` yielding `ScanProgress` + final `ScreenBoard`.
  - Populate `score.exchange` (friendly name — `NMS`/`NGM`→`NASDAQ`, `NYQ`→`NYSE`, else raw
    `fullExchangeName`/code) and `score.in_sp500` (`is_sp500_member(ticker)`) for every scanned
    row. Exchange comes from the `info` dict already fetched via `get_stock_data`/`fetch_info`.
  - `score_one`: build its neighbour base index from a new `combined_base_index(cache)` (see
    below) instead of `load_snapshot(cache, "all")`.
- `app/analysis/network.py`: `apply_network(board, graph, settings, base_override=None)` — when
  `base_override` is given, neighbour lookups consult `base_override` for tickers not in the
  board's own rows (board rows still win, preserving idempotency and the "blend from base"
  invariant). The Discover `"all"` scan passes no override (unchanged); the portfolio scan
  passes the `all`-board index so portfolio rows still see S&P neighbours.
- `app/screener/store.py` (or a small `base_index.py`): `combined_base_index(cache)` = the
  `all` board's `{ticker: StockScore}` overlaid by the `portfolio` board (portfolio wins).
- `app/api/routes.py`:
  - `GET /screen?scope=portfolio` reads `screen_snapshot:portfolio` (else the existing
    `all`-snapshot + sector/direction filter path). `_persist_rescan` handles the `"portfolio"`
    scope by saving under that key and blending with `apply_network(..., base_override=all)`.
  - `GET /screen/rescan/stream?scope=portfolio` rescans the portfolio set (reuses `iter_scan`).

### Frontend

- Refactor `components/DiscoverBoard.tsx` into a shared **`ScoreBoard`** used by both pages:
  - New **Exchange** and **S&P** columns (S&P renders a small badge: `S&P 500` vs `Custom`).
  - A **client-side search filter** input (case-insensitive match on ticker or company name)
    above the table.
  - `title` tooltips on board-level buttons (＋ Watch, etc.).
- `title` **tooltips on every button across the Discover page** (the original request): the
  page-level toolbar too — Update S&P 500 list, Rescan all / Rescan `<sector>`, Stop — plus the
  Portfolio page's toolbar buttons. Native `title` matches the existing pattern (e.g. the
  Evaluation command bar's button tooltips and the board's reason chips).
- `pages/Portfolio.tsx` + `/portfolio` route + nav entry, placed **after Dashboard**
  (Dashboard · Portfolio · Discover · Graph · Evaluation · Settings). Renders the `ScoreBoard`
  over `GET /screen?scope=portfolio`, a **"Rescan portfolio"** button (fast; via the app-level
  run provider, scope `"portfolio"`), the as-of / scanned line, and an empty state prompting
  the user to add to their watchlist or activate an ontology. Rows click through to the
  existing Dashboard deep-dive (`/?ticker=`).
- `hooks/queries.ts` / `api/client.ts`: `getScreen`/`useScreen` accept a `scope`; the rescan
  stream + `useRescanRun` accept a scope (generalize the existing `sector` param).
- `state/watchlistRunState.tsx`: the app-level rescan run takes a scope so a portfolio rescan
  survives navigation like the existing sector/all rescan.
- Discover reuses `ScoreBoard`, so it gains the columns / search / tooltips with no extra work.

## Phase 2 — Evaluation repoint + Graph colouring

- `app/evaluation/signals.py`: `snapshot_watchlist` iterates `portfolio_universe(settings,
  cache)` instead of `settings.watchlist` (rename/comment to "snapshot_portfolio" semantics;
  keep the function name or alias to avoid churn).
- `app/api/routes.py`: `analyze_watchlist_stream` builds `tickers` from `portfolio_universe`.
- `components/EvaluationCommandBar.tsx`: the "Full Discover rescan" button becomes a fast
  **"Rescan portfolio"** (scope `"portfolio"`); labels change from "watchlist (N)" to
  "portfolio (N: watchlist + ontology)". Tooltips updated to match.
- Graph node colouring prefers the portfolio board, falling back to `all` (frontend: read both
  boards / scores and merge, portfolio winning). Dashboard already inherits the precedence via
  `score_one` from Phase 1, so no Dashboard change is required.

## Phase 3 — Discover custom companies

- `app/data/universe.py` (or a `custom_store.py`): a `custom_universe` cache key holding a JSON
  list of `UniverseEntry` (with `exchange`), ~10y TTL like ontologies. `load_universe()` merges
  committed S&P + custom (custom appended, de-duplicated by ticker). `is_sp500_member(ticker)`
  checks the **committed** set only, so merged custom rows read `in_sp500=False`.
- `app/api/routes.py`:
  - `POST /universe/custom {ticker}` — resolves the ticker via `get_stock_data` / `fetch_info`
    (validates it has price history; 422 on an unknown/empty ticker), builds a `UniverseEntry`
    with auto-filled name/sector/exchange + a current price, persists it, returns the entry.
  - `GET /universe/custom` (list) and `DELETE /universe/custom/{ticker}` (remove).
- Discover UI: a **"＋ Add company"** form (ticker input → submit → inline success showing the
  resolved name/exchange/sector/price, or an inline validation error) and a remove (×)
  affordance on custom rows. Custom companies are then scanned in the broad `all` board and
  flagged `Custom` in the S&P column (the Phase 1 columns now carry real data). A note that a
  custom company only enters the **portfolio** if added to the watchlist or referenced by the
  active ontology.

## Testing

Follows the repo's TDD convention (pytest + vitest).

- **Backend:** `portfolio_universe` (watchlist ∪ ontology tickers, prefix filtering, dedup);
  scope-scan resolution (`"portfolio"` synthesizes entries for tickers outside `sp500.json`);
  `combined_base_index` precedence; `apply_network(base_override=)` neighbour fallback +
  idempotency preserved; `exchange`/`in_sp500` population (incl. friendly-name mapping);
  `GET /screen?scope=portfolio` + portfolio rescan stream; repointed `snapshot_watchlist` /
  `analyze_watchlist_stream` cover the portfolio set; custom store CRUD + endpoints (valid /
  invalid ticker, `load_universe` merge, membership flag).
- **Frontend:** `Portfolio` page (board render, empty state, rescan, row click-through);
  `ScoreBoard` (Exchange/S&P columns, search filter, tooltips) shared by both pages;
  `useScreen`/rescan scope plumbing; repointed `EvaluationCommandBar` labels/action; custom
  add-company flow (success + validation error + remove).

## Notes / constraints

- Dev servers run `--reload`/HMR — edits go live immediately. Verify with a separate untracked
  Vite config + `/api` proxy, never an `.env` the running Vite watches (per repo gotcha).
- Verify interactive UI with coordinate-based `preview_click` + state/`activeElement` checks —
  `element.click()` bypasses hit-testing (per repo gotcha).
- The user's real DB may have **no active ontology** yet → `portfolio_universe` degrades to the
  watchlist alone, and the Portfolio board is watchlist-only until an ontology is activated.
