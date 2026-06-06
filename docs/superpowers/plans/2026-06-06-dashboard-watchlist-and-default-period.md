# Dashboard Watchlist Add/Remove + 1Y Default Chart Period Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users add/remove watchlist tickers directly on the Dashboard (☆/★ star on the loaded ticker + `×` on each chip), and default the chart range to 1Y.

**Architecture:** Frontend-only. A new `useWatchlist()` hook centralizes the existing "mutate `Settings.watchlist` → `PUT /settings`" logic (Discover is refactored onto it). `TickerBar` gains a star toggle and per-chip remove buttons wired through the Dashboard to the hook. The chart default moves from `2Y` to `1Y` in its single source of truth. No backend/API/DB changes.

**Tech Stack:** React 18, TypeScript 5.6, Vite 5, @tanstack/react-query v5, vitest 2, @testing-library/react 16.

---

## Conventions for this plan

- **All commands run from `frontend/`** (the Vite project root: `D:\workspace\ai-stocks-news-analysis\frontend`).
- Run one test file: `npm test -- <path>` (e.g. `npm test -- src/hooks/useWatchlist.test.tsx`).
- Run the whole suite: `npm test`.
- Type-check (project-reference build mode, no JS emitted): `npx tsc -b`.
- Full gate (type-check + production bundle): `npm run build`.
- **Commit style:** Conventional Commits. **Do NOT add a `Co-Authored-By: Claude` trailer** (repo rule).
- Current branch is `feat/dashboard-watchlist-and-1y-default` (already created).

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `frontend/src/hooks/queries.ts` | React Query hooks | **Modify** — add `useWatchlist()` |
| `frontend/src/hooks/useWatchlist.test.tsx` | Unit test for the hook | **Create** |
| `frontend/src/pages/Discover.tsx` | Discover page | **Modify** — adopt `useWatchlist()` (drop duplicated `addToWatch`) |
| `frontend/src/components/TickerBar.tsx` | Dashboard command bar | **Modify** — star toggle + per-chip `×` |
| `frontend/src/components/TickerBar.test.tsx` | Component test | **Create** |
| `frontend/src/pages/Dashboard.tsx` | Dashboard page | **Modify** — use `useWatchlist()`, wire star/×, add error line |
| `frontend/src/styles.css` | Styles | **Modify** — `.chip` flex, `.chip-x`, `.star-btn` |
| `frontend/src/state/dashboardState.tsx` | Dashboard view-state | **Modify** — default range `'2Y'`→`'1Y'` |
| `frontend/src/components/PriceChart.tsx` | Chart | **Modify** — default param `'2Y'`→`'1Y'` |
| `frontend/src/pages/Dashboard.test.tsx` | Page test | **Modify** — assert 1Y is the default range |

`TickerBar` is consumed only by `Dashboard.tsx`; Task 2 Step 1 grep-confirms this before its props change.

---

### Task 1: `useWatchlist()` hook + refactor Discover onto it

**Files:**
- Create: `frontend/src/hooks/useWatchlist.test.tsx`
- Modify: `frontend/src/hooks/queries.ts` (add `useWatchlist` after `useSaveSettings`, which ends at line 28)
- Modify: `frontend/src/pages/Discover.tsx:3` (imports) and `:11-20` (drop `addToWatch`), `:86` (`onAdd`)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useWatchlist.test.tsx`:

```tsx
import { beforeEach, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { Settings } from '../types';

vi.mock('../api/client', () => ({
  api: { getSettings: vi.fn(), saveSettings: vi.fn() },
}));
import { api } from '../api/client';
import { useWatchlist } from './queries';

const SETTINGS = {
  active_provider: 'anthropic', providers: {}, watchlist: ['AAPL', 'MSFT'],
  indicator_params: { sma_windows: [50, 200], rsi_length: 14 },
  alerts: { enabled: false, channel: 'log', telegram_bot_token: '', telegram_chat_id: '', rsi_low: 30, rsi_high: 70 },
  truth_signal: { enabled: true, source_url: '', lookback_hours: 48 },
  screener: { enabled: true, top_n: 25, default_sector: null, rsi_low: 30, rsi_high: 70, weights: {} },
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4 },
} as Settings;

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.saveSettings).mockImplementation(async (s) => s);
});

it('appends a ticker that is not already listed', async () => {
  const { result } = renderHook(() => useWatchlist(), { wrapper });
  await waitFor(() => expect(result.current.list).toEqual(['AAPL', 'MSFT']));
  act(() => result.current.add('TSLA'));
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(expect.objectContaining({ watchlist: ['AAPL', 'MSFT', 'TSLA'] })),
  );
});

it('does not append a duplicate', async () => {
  const { result } = renderHook(() => useWatchlist(), { wrapper });
  await waitFor(() => expect(result.current.list).toContain('AAPL'));
  act(() => result.current.add('AAPL'));
  expect(api.saveSettings).not.toHaveBeenCalled();
});

it('removes a ticker that is present', async () => {
  const { result } = renderHook(() => useWatchlist(), { wrapper });
  await waitFor(() => expect(result.current.list).toContain('AAPL'));
  act(() => result.current.remove('AAPL'));
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(expect.objectContaining({ watchlist: ['MSFT'] })),
  );
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- src/hooks/useWatchlist.test.tsx`
Expected: FAIL — `useWatchlist is not a function` (export does not exist yet).

- [ ] **Step 3: Implement `useWatchlist`**

In `frontend/src/hooks/queries.ts`, add this export immediately after the `useSaveSettings` function (after line 28):

```tsx
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

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- src/hooks/useWatchlist.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Refactor Discover onto the hook**

In `frontend/src/pages/Discover.tsx`:

Change the import on line 3 from:
```tsx
import { useRefreshUniverse, useRescan, useSaveSettings, useScreen, useSectors, useSettings } from '../hooks/queries';
```
to:
```tsx
import { useRefreshUniverse, useRescan, useScreen, useSectors, useWatchlist } from '../hooks/queries';
```

Replace the settings/saveSettings declarations and the `addToWatch` function (lines 11–20):
```tsx
  const rescan = useRescan();
  const settings = useSettings();
  const saveSettings = useSaveSettings();
  const refreshList = useRefreshUniverse();

  const addToWatch = (t: string) => {
    const s = settings.data;
    if (!s || s.watchlist.includes(t)) return;
    saveSettings.mutate({ ...s, watchlist: [...s.watchlist, t] });
  };
```
with:
```tsx
  const rescan = useRescan();
  const refreshList = useRefreshUniverse();
  const watch = useWatchlist();
```

Change the board usage (line 86) from `onAdd={addToWatch}` to `onAdd={watch.add}`:
```tsx
        {data && <DiscoverBoard items={data.items} onAdd={watch.add} />}
```

- [ ] **Step 6: Type-check and run the full suite**

Run: `npx tsc -b`
Expected: no output (success).

Run: `npm test`
Expected: all files pass (the existing `Dashboard.test.tsx` exercises the Discover page via navigation and must stay green).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/queries.ts frontend/src/hooks/useWatchlist.test.tsx frontend/src/pages/Discover.tsx
git commit -m "feat(frontend): add useWatchlist hook; refactor Discover onto it"
```

---

### Task 2: TickerBar star toggle + per-chip remove, wired through the Dashboard

**Files:**
- Create: `frontend/src/components/TickerBar.test.tsx`
- Modify: `frontend/src/components/TickerBar.tsx` (full rewrite below)
- Modify: `frontend/src/pages/Dashboard.tsx:9` (import), `:19-20` (hook), `:68-74` (TickerBar props), add error line after `:80`
- Modify: `frontend/src/styles.css` (`.chip` block at lines 406–417; append new rules after line 418)

- [ ] **Step 1: Confirm TickerBar's only consumer**

Run a search to confirm `Dashboard.tsx` is the only file importing `TickerBar` (so changing its props is safe):
Use Grep for `TickerBar` across `frontend/src`. Expected: matches only in `components/TickerBar.tsx` (definition), `components/TickerBar.test.tsx` (new), and `pages/Dashboard.tsx` (consumer).

- [ ] **Step 2: Write the failing component test**

Create `frontend/src/components/TickerBar.test.tsx`:

```tsx
import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { TickerBar } from './TickerBar';

function setup(over: { watchlist?: string[]; current?: string } = {}) {
  const onSelect = vi.fn();
  const onAdd = vi.fn();
  const onRemove = vi.fn();
  render(
    <TickerBar
      watchlist={over.watchlist ?? ['AAPL', 'MSFT']}
      current={over.current ?? 'AAPL'}
      onSelect={onSelect}
      onAdd={onAdd}
      onRemove={onRemove}
      onAnalyze={vi.fn()}
      analyzing={false}
      canAnalyze
    />,
  );
  return { onSelect, onAdd, onRemove };
}

it('adds the current ticker when it is not yet in the watchlist', () => {
  const { onAdd } = setup({ current: 'TSLA', watchlist: ['AAPL'] });
  fireEvent.click(screen.getByRole('button', { name: /add to watchlist/i }));
  expect(onAdd).toHaveBeenCalledWith('TSLA');
});

it('removes the current ticker when it is already in the watchlist', () => {
  const { onRemove } = setup({ current: 'AAPL', watchlist: ['AAPL'] });
  fireEvent.click(screen.getByRole('button', { name: /remove from watchlist/i }));
  expect(onRemove).toHaveBeenCalledWith('AAPL');
});

it('removes a chip via its × without also selecting it', () => {
  const { onRemove, onSelect } = setup({ watchlist: ['AAPL', 'MSFT'], current: '' });
  fireEvent.click(screen.getByRole('button', { name: /remove MSFT/i }));
  expect(onRemove).toHaveBeenCalledWith('MSFT');
  expect(onSelect).not.toHaveBeenCalled();
});

it('selects a ticker when its chip body is clicked', () => {
  const { onSelect } = setup({ watchlist: ['AAPL', 'MSFT'], current: '' });
  fireEvent.click(screen.getByText('MSFT'));
  expect(onSelect).toHaveBeenCalledWith('MSFT');
});

it('shows no star when no ticker is loaded', () => {
  setup({ current: '' });
  expect(screen.queryByRole('button', { name: /watchlist/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npm test -- src/components/TickerBar.test.tsx`
Expected: FAIL — TickerBar does not yet accept `current/onAdd/onRemove`; queries like `/add to watchlist/i` find no element ("Unable to find role=button").

- [ ] **Step 4: Rewrite `TickerBar.tsx`**

Replace the entire contents of `frontend/src/components/TickerBar.tsx` with:

```tsx
import { useState } from 'react';

export function TickerBar({
  watchlist,
  current,
  onSelect,
  onAdd,
  onRemove,
  onAnalyze,
  analyzing,
  canAnalyze,
}: {
  watchlist: string[];
  current: string;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => void;
  onRemove: (ticker: string) => void;
  onAnalyze: () => void;
  analyzing: boolean;
  canAnalyze: boolean;
}) {
  const [input, setInput] = useState('');
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (t) onSelect(t);
  };
  const saved = !!current && watchlist.includes(current);
  return (
    <div className="tickerbar">
      <form onSubmit={submit}>
        <input
          aria-label="ticker"
          placeholder="Ticker · e.g. AAPL"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" className="secondary">Load</button>
      </form>
      {current && (
        <button
          type="button"
          className="star-btn"
          aria-label={saved ? 'Remove from watchlist' : 'Add to watchlist'}
          title={saved ? `Remove ${current} from watchlist` : `Add ${current} to watchlist`}
          onClick={() => (saved ? onRemove(current) : onAdd(current))}
        >
          {saved ? '★' : '☆'}
        </button>
      )}
      {watchlist.length > 0 && (
        <div className="watch">
          <span className="watch-label">Watchlist</span>
          {watchlist.map((t) => (
            <span className="chip" key={t} onClick={() => onSelect(t)}>
              <span className="chip-label">{t}</span>
              <button
                type="button"
                className="chip-x"
                aria-label={`Remove ${t}`}
                onClick={(e) => { e.stopPropagation(); onRemove(t); }}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <span className="spacer" />
      <button onClick={onAnalyze} disabled={!canAnalyze || analyzing}>
        {analyzing ? 'Analyzing…' : 'Analyze with LLM'}
      </button>
    </div>
  );
}
```

- [ ] **Step 5: Run the component test to verify it passes**

Run: `npm test -- src/components/TickerBar.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 6: Wire the Dashboard to the hook**

In `frontend/src/pages/Dashboard.tsx`:

Change the import on line 9 from:
```tsx
import { useAnalyze, useSettings, useStock } from '../hooks/queries';
```
to:
```tsx
import { useAnalyze, useStock, useWatchlist } from '../hooks/queries';
```

Replace lines 19–20:
```tsx
  const settings = useSettings();
  const watchlist = settings.data?.watchlist ?? [];
```
with:
```tsx
  const watch = useWatchlist();
  const watchlist = watch.list;
```

Replace the `<TickerBar .../>` usage (lines 68–74) with:
```tsx
        <TickerBar
          watchlist={watchlist}
          current={ticker}
          onSelect={setTicker}
          onAdd={watch.add}
          onRemove={watch.remove}
          onAnalyze={runAnalyze}
          analyzing={analyze.isPending}
          canAnalyze={!!stock.data}
        />
```

Add a watchlist error line immediately after the existing `analyze.isError` line (line 80):
```tsx
      {watch.isError && <p className="error">Couldn't update watchlist: {(watch.error as Error).message}</p>}
```

- [ ] **Step 7: Add styles**

In `frontend/src/styles.css`, edit the `.chip` rule (lines 406–417) to add three flex properties — the final block reads:

```css
.chip {
  background: transparent;
  border: 1px solid var(--panel-brd);
  color: var(--ink-soft);
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.06em;
  padding: 6px 13px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
```

Then add these rules immediately after the `.chip:hover { ... }` line (after line 418):

```css
.chip-x {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  font-size: 13px;
  line-height: 1;
  color: var(--ink-ghost);
}
.chip-x:hover { color: #cf6f6a; }
.star-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 2px;
  font-size: 17px;
  line-height: 1;
  color: var(--gold);
}
.star-btn:hover { filter: brightness(1.2); }
```

- [ ] **Step 8: Type-check and run the full suite**

Run: `npx tsc -b`
Expected: no output (success).

Run: `npm test`
Expected: all pass, including the existing `Dashboard.test.tsx` persistence test.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/TickerBar.tsx frontend/src/components/TickerBar.test.tsx frontend/src/pages/Dashboard.tsx frontend/src/styles.css
git commit -m "feat(frontend): add/remove watchlist from the Dashboard (star toggle + chip remove)"
```

---

### Task 3: Default chart range to 1Y

**Files:**
- Modify: `frontend/src/state/dashboardState.tsx:24`
- Modify: `frontend/src/components/PriceChart.tsx:45`
- Modify: `frontend/src/pages/Dashboard.test.tsx` (add a default-range test)

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/Dashboard.test.tsx`, add this new block after the existing `describe('Dashboard analysis persistence', ...)` block (it reuses the file's existing mocks and `renderApp` helper):

```tsx
describe('Dashboard chart range', () => {
  it('defaults the chart range to 1Y', async () => {
    renderApp();
    const oneY = await screen.findByRole('button', { name: '1Y' });
    expect(oneY).toHaveClass('active');
    expect(screen.getByRole('button', { name: '2Y' })).not.toHaveClass('active');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- src/pages/Dashboard.test.tsx`
Expected: FAIL — `1Y` does not have the `active` class yet (the default is still `2Y`).

- [ ] **Step 3: Change the default in `dashboardState.tsx`**

In `frontend/src/state/dashboardState.tsx`, line 24, change:
```tsx
  const [range, setRange] = useState<ChartRange>('2Y');
```
to:
```tsx
  const [range, setRange] = useState<ChartRange>('1Y');
```

- [ ] **Step 4: Align the `PriceChart` default param**

In `frontend/src/components/PriceChart.tsx`, line 45, change:
```tsx
  range = '2Y',
```
to:
```tsx
  range = '1Y',
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- src/pages/Dashboard.test.tsx`
Expected: PASS (both the persistence test and the new range test).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/state/dashboardState.tsx frontend/src/components/PriceChart.tsx frontend/src/pages/Dashboard.test.tsx
git commit -m "feat(frontend): default the chart range to 1Y"
```

---

### Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `npm test`
Expected: all test files pass (includes `useWatchlist`, `TickerBar`, `Dashboard`, `DiscoverBoard`, and the rest).

- [ ] **Step 2: Type-check + production build**

Run: `npm run build`
Expected: `tsc -b` clean, then `vite build` completes with no errors.

- [ ] **Step 3: Finish the branch**

Use the **superpowers:finishing-a-development-branch** skill to present merge/PR options for `feat/dashboard-watchlist-and-1y-default`.

---

## Notes for the implementer

- **No backend changes.** The watchlist already round-trips through `GET/PUT /settings`; you are only adding new callers of the existing `saveSettings` mutation.
- **Casing:** tickers are uppercased on load (`TickerBar.submit`) and stored uppercase; membership checks are exact string compares — do not add `.toUpperCase()` inside the hook.
- **Why a `.chip-label` span?** Wrapping the ticker text isolates it so a chip's accessible text isn't `"AAPL×"`; this keeps `getByText('AAPL')` (chip-body click test) unambiguous.
- **Star vs chip-× labels:** the star uses `…watchlist` aria-labels; chip removes use `Remove <TICKER>` — the tests rely on this distinction, keep both.
