# Update S&P 500 List — Design

- **Date:** 2026-06-05
- **Status:** Approved
- **Builds on:** the Discover feature (`backend/app/data/universe.py` static universe + loader;
  `app/screener/*`; the Discover page). Reuses the exact scrape approach used to expand
  `sp500.json` by hand on 2026-06-05.

## Overview

A one-click **"Update S&P 500 list"** action on the Discover page that scrapes the current
S&P 500 constituents from Wikipedia and rewrites `backend/app/data/sp500.json` in place, so the
screen universe can be refreshed without editing files or restarting the server.

The board's universe is a static file; this feature automates keeping it current. It does **not**
re-score anything — after the list is updated the user hits **Rescan** to rebuild the board when
ready (a full scan is slow, so it stays an explicit, separate step).

## Locked decisions

| Decision | Choice |
|---|---|
| Scrape method | `urllib` fetch (browser UA) → `pandas.read_html` → `lxml` (new runtime dep) |
| Source | `https://en.wikipedia.org/wiki/List_of_S%26P_500_companies` (swappable fetcher) |
| Symbols | class shares normalized to yfinance form (`BRK.B` → `BRK-B`); upper-cased |
| Write | **atomic** (`sp500.json.tmp` → `os.replace`); only after validation passes |
| Cache | `_all_entries.cache_clear()` after write → effect with **no server restart** |
| After update | **no auto-rescan** (full scan is slow); refresh the sector dropdown + nudge to Rescan |
| Confirmation | **none** (validated + atomic write is low-risk) |
| Failure | raise → API `502`, **existing file untouched** |

## Components

### Backend (`backend/app/data/universe.py`)

```python
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

_fetch_sp500_html(url: str = WIKI_SP500_URL) -> str
    # urllib GET with a browser User-Agent. Isolated so tests inject HTML
    # (mirrors data/truth_social._fetch_archive).

parse_sp500(html: str) -> list[UniverseEntry]
    # pure: pandas.read_html(StringIO(html)) -> pick the table with
    # {Symbol, Security, GICS Sector} -> ticker.replace('.','-').upper(),
    # name=Security, sector=GICS Sector -> de-dupe by ticker. Deterministic.

_MIN_SP500_ROWS = 450   # module constant; tests monkeypatch it to use a small fixture

refresh_universe(url: str = WIKI_SP500_URL) -> dict
    # fetch -> parse -> VALIDATE (>= _MIN_SP500_ROWS rows AND an AAPL row with sector
    # "Information Technology") -> sort by (sector,ticker) -> atomic write to
    # _DATA_FILE (tmp + os.replace) using the existing one-object-per-line format
    # -> _all_entries.cache_clear() -> return {"count", "sectors": {name: n}, "source"}.
    # On any failure: raise; never write a partial/empty file.
```

`_DATA_FILE` and `_all_entries` (the `@lru_cache`'d loader) already exist. The one-object-per-line
JSON formatting is factored into a small `_dump_entries(entries) -> str` helper reused by the
writer (and available to tests).

### API (`backend/app/api/routes.py`)

```
POST /api/universe/refresh
  -> universe.refresh_universe()
  -> 200 {"count": 503, "sectors": {...}, "source": "<url>"}
  -> on Exception: HTTPException 502 "Could not update the S&P 500 list: <reason>"
```

(`GET /api/screen/sectors` already exists; the frontend re-fetches it after a refresh.)

### Dependency

Add `lxml` to `pyproject.toml` `[project].dependencies` (pandas is already a runtime dep;
`read_html` needs an HTML parser). Already present in `backend/.venv`.

### Frontend

- `api/client.ts`: `refreshUniverse()` → `POST /universe/refresh`, returns `{count, sectors, source}`.
- `hooks/queries.ts`: `useRefreshUniverse()` (`useMutation`); `onSuccess` → `invalidateQueries(['sectors'])`.
- `pages/Discover.tsx`: an **"Update S&P 500 list"** `button.secondary` in the command bar. While
  pending shows "Updating…"; on success shows a muted line *"S&P 500 list updated — N names.
  Rescan to rebuild the board."*; on error shows the message.

## Data flow

```
click "Update S&P 500 list"
  -> POST /api/universe/refresh
       -> _fetch_sp500_html(WIKI_SP500_URL)         # urllib + browser UA
       -> parse_sp500(html)                         # pandas.read_html -> UniverseEntry[]
       -> validate (>=450 rows, AAPL/Information Technology present)
       -> atomic write sp500.json + _all_entries.cache_clear()
       -> {count, sectors, source}
  -> frontend: show "updated — N names"; invalidate ['sectors'] (dropdown refreshes)
  -> user clicks Rescan when ready (separate, existing action)
```

## Error handling / degradation

- Network/HTTP error, constituents-table-not-found, or validation failure (<450 rows / no
  AAPL-IT row) → `refresh_universe` raises → route returns **502** with a readable message →
  the **existing `sp500.json` is left untouched** (write happens only after validation, via
  `os.replace`).
- Atomic write (temp file + `os.replace`) means a crash mid-write cannot corrupt the file.
- The feature never runs automatically and is never on the board's read path.

## Testing (hermetic, TDD)

- **`parse_sp500`** — a small static HTML fixture (a 3-row table incl. a `BRK.B` row) →
  asserts the `UniverseEntry` list, `BRK.B` → `BRK-B`, name + sector preserved, de-dupe.
- **`refresh_universe`** — monkeypatch `universe._fetch_sp500_html` → fixture HTML,
  `universe._DATA_FILE` → a `tmp_path` file, and `universe._MIN_SP500_ROWS` → a small value
  (so a 3-row fixture that includes an AAPL/Information-Technology row passes validation).
  Asserts: file written in the expected format; `_all_entries` cache cleared so
  `load_universe()` returns the new data; summary `count`/`sectors` correct. Plus a
  **validation test**: with the default floor, a too-small parse → raises AND an existing
  `_DATA_FILE` is left unchanged (no partial write).
- **API** — monkeypatch `routes.universe.refresh_universe`: success → 200 + summary; raising →
  **502**.
- **Frontend** — client test asserts `refreshUniverse` POSTs `/universe/refresh`; `npm run build`
  typechecks the page/hook.

## Out of scope (YAGNI)

Scheduling the refresh; change preview/diff; auto-rescan after update; keeping a backup of the
previous file (git history covers it); sources other than Wikipedia.

## Caveats

- **Third-party source.** Wikipedia's table layout can change; the swappable `_fetch_sp500_html`
  + the table-by-columns lookup absorb minor changes, and validation refuses to overwrite on a
  bad parse. If the page structure changes materially, the fetch/parse may need an update.
- **Not financial data.** This only maintains the *list of tickers to screen*; it pulls no
  prices and changes no scores.
