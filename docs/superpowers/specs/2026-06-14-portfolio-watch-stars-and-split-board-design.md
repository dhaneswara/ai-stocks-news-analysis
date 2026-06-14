# Portfolio: watch-state stars + split board (watchlist vs ontology-extended)

**Date:** 2026-06-14
**Status:** Approved, ready for implementation plan

## Problem

On the Portfolio page (`/portfolio`):

1. **Stale "+ Watch" button.** The board renders a `+ Watch` button on every row, even
   for tickers already in the watchlist. The button has no knowledge of watchlist
   membership. Because `ScoreBoard` is shared with the Discover page, the same stale
   button appears there too.
2. **One undifferentiated board.** The portfolio universe is, by definition,
   `watchlist ∪ active-ontology ticker nodes` (`backend/app/screener/service.py:portfolio_universe`).
   The user wants these visually separated: the names they actively watch vs. the names
   that are present *only* because an active-ontology relationship pulled them in.

## Goals

- A row already in the watchlist shows it, and lets the user un-watch from the board.
- The portfolio board is split into two clearly-labelled boards: **Watchlist** and
  **Extended via ontology**.
- No regression to Discover; in fact Discover inherits the watch-state fix.

## Non-goals

- No backend / API changes. The `/api/screen?scope=portfolio` payload is unchanged.
- No change to scoring, the network signal, or the portfolio universe definition.
- No change to the Dashboard `TickerBar` (already has a working star toggle).

## Approach

**Client-side partition (chosen).** The scanned universe is exactly
`watchlist ∪ ontology`, so membership in `watch.list` is a complete, unambiguous
partition of `data.items`:

- in `watch.list` → **Watchlist** board
- not in `watch.list` → **Extended via ontology** board (present only via an ontology edge)

Matching is **case-insensitive** because universe tickers are upper-cased by
`portfolio_universe`, while `settings.watchlist` entries are stored as the user typed them.

Rejected alternative: tagging each `StockScore` with a backend `source` field. That adds
a payload field + tests for no extra correctness, and would not re-partition live when the
user toggles a watch within the session. The client-side partition is reactive to
`watch.list` for free.

## Design

### 1. `ScoreBoard` — watch-aware star toggle (shared component)

File: `frontend/src/components/ScoreBoard.tsx`

New optional props:

```ts
watched?: string[];            // tickers currently in the watchlist
onUnwatch?: (t: string) => void; // remove from watchlist
```

Behaviour:

- Build an upper-cased `Set` from `watched` once per render.
- Replace the per-row `+ Watch` button with a `star-btn` (reuse the existing class and the
  `TickerBar` idiom):
  - `★` when `watchedSet.has(s.ticker.toUpperCase())` → `onClick` calls `onUnwatch?.(s.ticker)`
  - `☆` otherwise → `onClick` calls `onAdd(s.ticker)`
  - `aria-label` / `title` mirror `TickerBar`: "Add `<ticker>` to watchlist" /
    "Remove `<ticker>` from watchlist".
- The custom-company remove `×` (`onRemove`, shown only for `!s.in_sp500`) is **unchanged
  and independent**. A custom, watched row can show both `★` and `×`.
- Backward compatible: if `watched` is omitted the set is empty, so every row shows `☆` and
  clicks route to `onAdd` (the prior add-only behaviour, now via a star glyph instead of
  text).

Callers updated to pass `watched={watch.list}` and `onUnwatch={watch.remove}`:

- `frontend/src/pages/Discover.tsx` (keeps its existing `onRemove={delCustom.mutate}`)
- `frontend/src/pages/Portfolio.tsx` (both boards)

### 2. `Portfolio` — two boards

File: `frontend/src/pages/Portfolio.tsx`

- Compute an upper-cased watch set from `watch.list`.
- Partition `data.items`:
  - `mine = items.filter(s => watchSet.has(s.ticker.toUpperCase()))`
  - `extended = items.filter(s => !watchSet.has(s.ticker.toUpperCase()))`
- Render each board as its own `<section className="panel">` wrapping one `ScoreBoard`,
  **only when it has at least one row** (symmetric rule):
  - **Watchlist (`mine.length`)** — shown when `mine.length > 0`.
  - **Extended via ontology (`extended.length`)** — shown when `extended.length > 0`.
  - When both are empty (no scan yet / every scanned ticker failed), neither board renders;
    the existing empty-portfolio hint and the "Rescan portfolio" CTA already guide the user.
    This is a strict improvement over the prior single board, which surfaced `ScoreBoard`'s
    search-oriented "No matches" state for a genuinely empty list.
- Each board keeps an independent search box. Both pass `onAdd={watch.add}`,
  `onUnwatch={watch.remove}`, `watched={watch.list}`.
- A ticker that is in *both* the watchlist and the ontology appears in the **Watchlist**
  board only (it is in `watch.list`).
- Reactivity: `☆`-adding an extended row mutates settings → `watch.list` changes → the
  partition re-runs → the row moves to the Watchlist board on the next render. No refetch
  required.

### 3. Tests (TDD)

`frontend/src/components/ScoreBoard.test.tsx`:
- Renders `★` for a ticker in `watched`, `☆` for one not in `watched`.
- Case-insensitive match (`watched={['aapl']}` marks the `AAPL` row as `★`).
- Clicking `☆` calls `onAdd`; clicking `★` calls `onUnwatch`.
- The `×` custom-remove behaviour is unchanged (existing test still passes).

`frontend/src/pages/Portfolio.test.tsx`:
- Given items spanning watchlist + ontology, two boards render with the right rows under
  the right headings.
- The Extended board is **not** rendered when every scanned ticker is in the watchlist.
- The Watchlist board is **not** rendered when no scanned ticker is in the watchlist
  (watchlist empty, ontology supplies the rows).

## Files touched

- `frontend/src/components/ScoreBoard.tsx` (+ test)
- `frontend/src/pages/Portfolio.tsx` (+ test)
- `frontend/src/pages/Discover.tsx` (pass `watched`/`onUnwatch`; test only if existing
  assertions reference the old button)

No backend files.
