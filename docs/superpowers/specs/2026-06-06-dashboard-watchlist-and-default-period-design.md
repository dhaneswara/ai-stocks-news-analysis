# Dashboard Watchlist Add/Remove + 1Y Default Chart Period — Design

- **Date:** 2026-06-06
- **Status:** Approved
- **Scope:** Frontend-only. No API, schema, or backend changes. Reuses the existing
  `Settings.watchlist` storage and `PUT /settings`.

## Overview

Two small Dashboard improvements:

1. **Add/remove watchlist from the Dashboard.** Today the watchlist (a `string[]` in
   `Settings.watchlist`) is editable only in the Settings page (a comma-separated text box) and via
   the Discover board's "+ Watch" button. The Dashboard's `TickerBar` only *shows* the watchlist as
   clickable chips. This adds in-place editing: a **star toggle** on the currently loaded ticker
   (add/remove) and a small **×** on each chip (remove).

2. **Default chart period 1Y.** The chart range default is `2Y`; change it to `1Y`.

Changes persist through the existing settings round-trip (`PUT /settings`); no new endpoints, no DB
changes.

## Locked decisions

| Decision | Choice |
|---|---|
| Add mechanism | **Star the current ticker.** A ☆/★ toggle next to the loaded ticker; ☆ adds, ★ removes. No star when no ticker is loaded. |
| Remove mechanism | A small **×** on each watchlist chip; click removes (and does not also select the chip — the click is stopped from propagating). |
| Persistence | Reuse `Settings.watchlist` + `PUT /settings` (same pattern as Discover "+ Watch"). No optimistic UI — the `['settings']` query updates on save success, as it does today. |
| Dedup / safety | Add is a no-op if the ticker is already listed or settings haven't loaded; remove is a no-op if absent or settings haven't loaded. |
| DRY | Extract a shared **`useWatchlist()`** hook (`list` / `add` / `remove` / `error` / `isError`); Dashboard uses it (new) and Discover is refactored onto it (drops its duplicated `addToWatch`). |
| Default period | `1Y`, set in one source of truth (`dashboardState`), with `PriceChart`'s own default param aligned. Backend `'2y'` defaults untouched (never hit from the Dashboard). |
| Scope | Frontend-only; no backend/API/DB changes. |

## Current state

- `Settings.watchlist: list[str]` (default `["AAPL","MSFT"]`), stored in backend SQLite settings;
  fetched via `useSettings()` / `GET /settings`, saved via `useSaveSettings()` / `PUT /settings`
  (its `onSuccess` writes the returned settings into the `['settings']` query cache).
- `frontend/src/components/TickerBar.tsx` — props `{ watchlist, onSelect, onAnalyze, analyzing,
  canAnalyze }`. Renders a Load form, watchlist chips (`onClick → onSelect(t)`), and the Analyze
  button.
- `frontend/src/pages/Dashboard.tsx` — owns `ticker` (the loaded symbol) via `useDashboardState()`;
  renders `<TickerBar watchlist=… onSelect={setTicker} … />`; already shows inline error lines for
  `stock.isError` / `analyze.isError`.
- `frontend/src/pages/Discover.tsx` — has a local `addToWatch(t)` calling
  `saveSettings.mutate({ ...s, watchlist:[...s.watchlist, t] })`; passes it to `DiscoverBoard` as
  `onAdd`.
- Chart range: `dashboardState.tsx` `useState<ChartRange>('2Y')`; `PriceChart` prop default
  `range = '2Y'`. Range only zooms the chart client-side (`setVisibleRange`) and sets the LLM
  analysis window. The chart's candles come from `useStock(ticker)` (hook default `'5y'`), so the
  backend `'2y'` default is never exercised from the Dashboard.

## Design

### `useWatchlist()` hook (new — in `frontend/src/hooks/queries.ts`)

Wraps `useSettings()` + `useSaveSettings()`:

```ts
export function useWatchlist() {
  const settings = useSettings();
  const save = useSaveSettings();
  const list = settings.data?.watchlist ?? [];
  const add = (t: string) => {
    const s = settings.data;
    if (!s || s.watchlist.includes(t)) return;
    save.mutate({ ...s, watchlist: [...s.watchlist, t] });
  };
  const remove = (t: string) => {
    const s = settings.data;
    if (!s || !s.watchlist.includes(t)) return;
    save.mutate({ ...s, watchlist: s.watchlist.filter((x) => x !== t) });
  };
  return { list, add, remove, error: save.error, isError: save.isError };
}
```

### `TickerBar` (modified)

New props: `current: string`, `onAdd: (t: string) => void`, `onRemove: (t: string) => void`.
Compute `const saved = !!current && watchlist.includes(current)` internally.

- Star button (rendered only when `current` is truthy):

```tsx
<button type="button" className="icon-btn star"
  aria-label={saved ? 'Remove from watchlist' : 'Add to watchlist'}
  title={saved ? `Remove ${current} from watchlist` : `Add ${current} to watchlist`}
  onClick={() => (saved ? onRemove(current) : onAdd(current))}>
  {saved ? '★' : '☆'}
</button>
```

- Chips with a remove ×:

```tsx
<span className="chip" key={t} onClick={() => onSelect(t)}>
  {t}
  <button type="button" className="chip-x" aria-label={`Remove ${t}`}
    onClick={(e) => { e.stopPropagation(); onRemove(t); }}>×</button>
</span>
```

### `Dashboard` (modified)

Replace `const settings = useSettings(); const watchlist = settings.data?.watchlist ?? []` with
`const watch = useWatchlist();` and use `watch.list` (the default-on-load effect reads `watch.list`).
Pass `current={ticker}`, `onAdd={watch.add}`, `onRemove={watch.remove}` to `TickerBar`. Add an
inline error line near the other ones:

```tsx
{watch.isError && <p className="error">Couldn't update watchlist: {(watch.error as Error).message}</p>}
```

### `Discover` (modified)

Replace the local `useSettings`/`useSaveSettings`/`addToWatch` with `const watch = useWatchlist();`
and pass `onAdd={watch.add}` to `DiscoverBoard`.

### Default period (modified)

- `dashboardState.tsx`: `useState<ChartRange>('1Y')`.
- `PriceChart.tsx`: default param `range = '1Y'`.

### Styles (`frontend/src/styles.css`)

Star reuses `.icon-btn` (gold `★`). Chip gains room for the ×; `.chip-x` is a borderless, dimmed
button that turns red on hover. (Exact pixel values finalized in the plan.)

## Edge cases

- No ticker loaded → no star (nothing to add); chips remain removable.
- Removing the currently-viewed ticker → it stays loaded/viewed; star flips ★→☆.
- Re-adding after emptying the watchlist → load a ticker, star it.
- Duplicate add prevented by the `has`/`includes` guard.
- Ticker casing — symbols are uppercased on load and stored uppercase; comparisons are exact.

## Error handling

- Save failure surfaces as an inline error line on the Dashboard (mirrors
  `stock.isError`/`analyze.isError`); it clears on the next successful save. Discover keeps its
  current behavior (no extra error line) — out of scope to change.

## Out of scope

- Backend/API/DB changes; new endpoints.
- Optimistic UI, reordering, or drag-sort of the watchlist.
- Persisting the chart range across full page reloads (it already survives in-app navigation via the
  `DashboardStateProvider`).
- Confirmation dialogs for removal (reversible).

## Testing

- **New `frontend/src/components/TickerBar.test.tsx`:**
  - ☆ shown and `onAdd(current)` called when `current` not in `watchlist`.
  - ★ shown and `onRemove(current)` called when `current` in `watchlist`.
  - chip `×` calls `onRemove(t)` and does **not** call `onSelect`.
  - chip body still calls `onSelect(t)`.
  - no star rendered when `current === ''`.
- **Default range:** assert the `1Y` range tab is active by default on the Dashboard; update any
  existing test that asserts `2Y`.
- Verify existing `Dashboard`/`Discover` tests (if any) still pass; mock `saveSettings`/settings as
  needed.
- Gate: `tsc --noEmit`, `vitest run`, and `vite build` all green.

## Files

- Modify: `frontend/src/hooks/queries.ts` (add `useWatchlist`)
- Modify: `frontend/src/components/TickerBar.tsx` (star + chip ×, new props)
- Modify: `frontend/src/pages/Dashboard.tsx` (use `useWatchlist`, wire star/×, error line)
- Modify: `frontend/src/pages/Discover.tsx` (use `useWatchlist`)
- Modify: `frontend/src/state/dashboardState.tsx` (`'2Y'` → `'1Y'`)
- Modify: `frontend/src/components/PriceChart.tsx` (default param `'2Y'` → `'1Y'`)
- Modify: `frontend/src/styles.css` (`.chip-x`, `.icon-btn.star`)
- Add: `frontend/src/components/TickerBar.test.tsx`
