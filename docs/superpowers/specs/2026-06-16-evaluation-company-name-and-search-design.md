# Evaluation page: company name + search — design

**Date:** 2026-06-16
**Status:** approved

## Problem

The Evaluation board lists tracked companies by **ticker only**, and there's no way to filter the
list. The user wants (1) the company name shown beside the ticker, and (2) a search box to filter the
board's companies.

## Goal & scope

- Show the company **name in a dedicated "Company" column** immediately right of the Ticker column on
  the Evaluation board (and in the expanded per-company detail header, for consistency).
- Add a **search input** on the Evaluation page that filters the board's companies by ticker OR name
  (case-insensitive substring); empty = show all.
- The company name has no existing source on the evaluation data (the predictions store carries only
  `ticker`), so the backend resolves it from the universe (`load_universe`, which covers S&P 500 +
  the user's custom companies) at board-build time.

**Out of scope (YAGNI):** no fuzzy/ranked search, no storing the name in the predictions store, no
filtering of the top per-source scoreboard (it's global aggregates), no other Evaluation changes.

## Design

### 1. Backend — name on the rollup

- `CompanyRollup` (schemas.py) gains `name: str = ""`. Default `""` so existing constructors and the 8
  `build_board(store, Settings())` test calls are unaffected.
- `build_board(store, settings, cache=None)` — add an **optional** `cache` param (keeps every existing
  call site working). Build a ticker→name index once and set each rollup's name:
  ```python
  names = {e.ticker: e.name for e in load_universe(cache=cache)}
  ...
  rollup = CompanyRollup(ticker=ticker, name=names.get(ticker, ""), n_calls=..., ...)
  ```
  `load_universe(cache=cache)` returns S&P entries (from the bundled `sp500.json`) merged with custom
  companies when `cache` is provided; with `cache=None` it degrades to S&P-only names. An unknown
  ticker → `""` (the row shows ticker only).
- The evaluation-board route (`routes.py:869`, currently `build_board(prediction_store, settings)`)
  passes the request cache: add `cache: Cache = Depends(get_cache)` to that route and call
  `build_board(prediction_store, settings, cache)`. (`Cache`/`get_cache` are already imported and used
  by other routes.)

### 2. Frontend — Company column

- `CompanyRollup` type (`types.ts`) gains `name?: string` (optional, so existing partial-literal test
  fixtures in `EvaluationBoard.test.tsx` don't all need updating; the API always sends it).
- `EvaluationBoard.tsx`: insert `<th>Company</th>` right after `<th>Ticker</th>`, and a
  `<td className="muted">{r.name}</td>` cell right after the ticker `<td>`. The header row now has **8**
  columns; bump the detail row's `colSpan` from 7 to **8**.
- `Evaluation.tsx` `CompanyDetail`: the detail header becomes
  `{company.rollup.ticker}{company.rollup.name ? ` · ${company.rollup.name}` : ''} — calls` (name shown
  only when present).

### 3. Frontend — search bar

- `Evaluation.tsx` gains a `query` state (string) and a small text input rendered above the
  `EvaluationBoard` (inside the existing panel, e.g. after the panel head). Placeholder: "Filter by
  ticker or company…".
- Filter the `companies` array before passing to `EvaluationBoard`:
  ```ts
  const q = query.trim().toLowerCase();
  const shown = q
    ? companies.filter((c) =>
        c.rollup.ticker.toLowerCase().includes(q) ||
        (c.rollup.name ?? '').toLowerCase().includes(q))
    : companies;
  ```
- Empty query → all companies. The filter is purely client-side over already-loaded data; the
  per-source `SourceScoreboard` (global aggregates) is not filtered. When the filter yields nothing,
  `EvaluationBoard` already renders its "No tracked calls yet…" empty state — acceptable (a more
  specific "no matches" message is a nice-to-have, not required).

### Error handling / degradation

Name resolution is best-effort: any ticker missing from the universe → `""` (ticker-only row). The
search is local and cannot fail. No new error paths.

## Testing (TDD)

- **Backend** (`test_evaluation_board.py`): a known S&P ticker (e.g. AAPL) → `rollup.name` is non-empty
  and matches the universe name; an unknown ticker (e.g. "ZZZZ") → `rollup.name == ""`. (Pass a real or
  None cache; S&P names resolve without cache.)
- **Frontend**
  - `EvaluationBoard.test.tsx`: renders the "Company" header and the name cell for a company with a
    name; header/detail use 8 columns (detail `colSpan=8`).
  - `Evaluation.test.tsx`: typing in the search box filters rows by ticker and by name (case-insensitive),
    and clearing it restores all rows.

## Non-goals

No fuzzy search, no predictions-store schema change, no scoreboard filtering, no change to the
per-call detail rows beyond the header name.
