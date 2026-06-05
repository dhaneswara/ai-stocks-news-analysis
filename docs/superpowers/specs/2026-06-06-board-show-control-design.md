# Discover Board "Show" Control — Design

- **Date:** 2026-06-06
- **Status:** Approved
- **Builds on:** the Discover board — `GET /api/screen` (which caps results at
  `Settings.screener.top_n`, default 25), the Discover command bar, the `useScreen` hook, and the
  `getScreen` client method.

## Overview

A **"Show"** dropdown (**25 / 50 / 100 / All**) in the Discover command bar controlling how many
ranked rows the board displays. Default stays **25**, so the first impression is unchanged; the
scan already scores and stores the whole universe, so raising the number just reveals more of the
already-ranked list. **"All"** returns the full filtered set (e.g. ~503 for All sectors, or every
name in a chosen sector).

## Locked decisions

| Decision | Choice |
|---|---|
| Options | `25 / 50 / 100 / All`; default **25** |
| "All" representation | `limit=0` → backend treats `0` as "no cap"; an **omitted** limit still = `top_n` |
| State | session-local (not persisted across reloads) |
| Backend | one-line logic change in `GET /api/screen`; **no schema change** |

## Components

**Backend — `backend/app/api/routes.py` (`screen` route):**
Today the final slice is `items[: (limit or settings.screener.top_n)]`, where `or` wrongly treats
`limit=0` as falsy. Replace with an explicit None-vs-0 distinction:

```python
n = settings.screener.top_n if limit is None else limit
shown = items if n <= 0 else items[:n]
return board.model_copy(update={"items": shown})
```

- `limit` omitted (`None`) → `top_n` (default 25) — **unchanged** for every current caller.
- `limit=0` → all (no cap) — what "All" sends.
- `limit=50/100` → top N.

**Frontend:**
- `api/client.ts` `getScreen(sector?, direction?, limit?)` — **already** sends `limit` when
  `!= null` (so `0` is sent). No change.
- `hooks/queries.ts` `useScreen` — gains a `limit?` param, includes it in the query key
  (`['screen', sector ?? '', direction ?? '', limit ?? '']`), and passes it to `getScreen`.
- `pages/Discover.tsx` — a `show` state (default `25`); a **"Show"** `<select>` in
  `.board-controls` with options `25 / 50 / 100 / All` (All → value `0`); `useScreen(sector || undefined, direction || undefined, show)`.

## Data flow

```
pick "Show" (e.g. All) → show=0 → useScreen(sector, direction, 0)
  → GET /api/screen?...&limit=0 → route: n=0 -> shown = all filtered items
  → board renders the full filtered set
```

## Error handling

None new. `limit` is an optional int query param; `0` (or any `<= 0`) means "all"; the snapshot
read path and filtering are unchanged. No snapshot → still the empty board.

## Testing

- **Backend** (`tests/test_api_screen.py`): a new test that `GET /api/screen?limit=0` returns the
  **full** filtered set (no cap). The existing `?limit=2` test and the no-limit default still pass
  (no-limit → `top_n`; the fixture board has 3 rows < 25, so it returns all 3 as before).
- **Frontend** (`api/client.test.ts`): assert `getScreen(undefined, undefined, 0)` puts `limit=0`
  in the query string; `npm run build` typechecks the hook/page wiring.

## Out of scope (YAGNI)

Persisting the choice across reloads; pagination; remembering a different count per sector.
