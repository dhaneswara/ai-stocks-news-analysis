# Portfolio Watch-State Stars + Split Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shared `ScoreBoard` show a `★`/`☆` watch toggle that reflects watchlist membership, and split the Portfolio board into a *Watchlist* board and an *Extended via ontology* board.

**Architecture:** Frontend-only. `ScoreBoard` gains `watched?: string[]` + `onUnwatch?` props and renders the existing `star-btn` idiom per row (case-insensitive match). `Portfolio` partitions the scanned `data.items` by membership in `watch.list` into two `ScoreBoard` sections, each rendered only when non-empty. Discover passes the new props so it inherits the fix. No backend/API/scoring changes.

**Tech Stack:** React + TypeScript, Vitest + @testing-library/react. Tests run from `frontend/` with `npx vitest run <path>`.

**Branch:** Do this work on `feat/portfolio-watch-split` (created off `master`), ff-merged to `master` locally per repo convention. Conventional Commits, **no** `Co-Authored-By: Claude` trailer.

**Spec:** `docs/superpowers/specs/2026-06-14-portfolio-watch-stars-and-split-board-design.md`

---

## File Structure

- `frontend/src/components/ScoreBoard.tsx` — add watch-aware star toggle (shared by Discover + Portfolio).
- `frontend/src/components/ScoreBoard.test.tsx` — new tests for star state + click routing.
- `frontend/src/pages/Discover.tsx` — pass `watched`/`onUnwatch` (wiring only).
- `frontend/src/pages/Portfolio.tsx` — partition into two boards.
- `frontend/src/pages/Portfolio.test.tsx` — new tests for the split + empty-board hiding.

No backend files. The `star-btn` CSS class already exists at `frontend/src/styles.css:428` — reuse it, add no CSS.

---

## Task 1: `ScoreBoard` — watch-aware `★`/`☆` toggle

**Files:**
- Modify: `frontend/src/components/ScoreBoard.tsx`
- Test: `frontend/src/components/ScoreBoard.test.tsx`

- [ ] **Step 1: Write the failing tests**

Edit `frontend/src/components/ScoreBoard.test.tsx`. Change the first import line to add `vi`:

```tsx
import { expect, it, vi } from 'vitest';
```

Then append these two tests to the end of the file:

```tsx
it('shows a filled ★ for watched rows and a hollow ☆ otherwise (case-insensitive)', () => {
  const items = [row({ ticker: 'AAPL' }), row({ ticker: 'TSLA', name: 'Tesla' })];
  render(
    <MemoryRouter>
      <ScoreBoard items={items} onAdd={() => {}} watched={['aapl']} onUnwatch={() => {}} />
    </MemoryRouter>,
  );
  expect(screen.getByTitle(/remove AAPL from watchlist/i)).toHaveTextContent('★');
  expect(screen.getByTitle(/add TSLA to watchlist/i)).toHaveTextContent('☆');
});

it('routes a ☆ click to onAdd and a ★ click to onUnwatch', () => {
  const onAdd = vi.fn();
  const onUnwatch = vi.fn();
  const items = [row({ ticker: 'AAPL' }), row({ ticker: 'TSLA', name: 'Tesla' })];
  render(
    <MemoryRouter>
      <ScoreBoard items={items} onAdd={onAdd} watched={['AAPL']} onUnwatch={onUnwatch} />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByTitle(/add TSLA to watchlist/i));
  fireEvent.click(screen.getByTitle(/remove AAPL from watchlist/i));
  expect(onAdd).toHaveBeenCalledWith('TSLA');
  expect(onUnwatch).toHaveBeenCalledWith('AAPL');
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/components/ScoreBoard.test.tsx`
Expected: FAIL — the new `getByTitle(/.../)` queries find nothing (the current button title is "Add this company to your watchlist" and renders the text "+ Watch", not `★`/`☆`).

- [ ] **Step 3: Implement the star toggle in `ScoreBoard.tsx`**

In `frontend/src/components/ScoreBoard.tsx`, extend the `Props` interface (currently lines 6–11) to:

```tsx
interface Props {
  items: StockScore[];
  onAdd: (t: string) => void;
  /** Tickers currently in the watchlist; matching rows render a filled ★ (case-insensitive). */
  watched?: string[];
  /** Remove from the watchlist — the ★ action. Omit to render watched rows as a non-acting ★. */
  onUnwatch?: (t: string) => void;
  /** When given, custom rows (`in_sp500 === false`) get a × remove button. */
  onRemove?: (t: string) => void;
}
```

Update the function signature to destructure the new props:

```tsx
export function ScoreBoard({ items, onAdd, watched, onUnwatch, onRemove }: Props) {
```

Immediately after the existing `const shown = ...` block (right before the `return (`), add the watched set:

```tsx
  const watchedSet = new Set((watched ?? []).map((t) => t.toUpperCase()));
```

Change the rows `.map(...)` from an implicit-return arrow to a block body so `saved` can be computed per row, and replace the final `<td>` (the `+ Watch` / `×` cell). Replace the current block (lines 43–82, from `{shown.map((s, i) => (` through `))}`) with:

```tsx
            {shown.map((s, i) => {
              const saved = watchedSet.has(s.ticker.toUpperCase());
              return (
                <tr key={s.ticker} className="board-row"
                    onClick={() => navigate(`/?ticker=${encodeURIComponent(s.ticker)}`)}>
                  <td className="muted">{i + 1}</td>
                  <td className="mono">{s.ticker}</td>
                  <td>{s.name}</td>
                  <td className="muted">{s.exchange || '—'}</td>
                  <td className="muted">{s.sector || '—'}</td>
                  <td className="mono">{s.price.toFixed(2)}</td>
                  <td>
                    {s.in_sp500
                      ? <span className="badge sp" title="S&P 500 member">S&amp;P 500</span>
                      : <span className="badge custom" title="Not in the S&P 500 (custom company)">Custom</span>}
                  </td>
                  <td>
                    <div className="score-cell"><ScoreBar score={s.score} /><span>{s.score.toFixed(0)}</span></div>
                  </td>
                  <td><span className={`badge ${s.direction}`}>{s.direction.toUpperCase()}</span></td>
                  <td>
                    <div className="reasons">
                      {s.network && s.network.reasons.length > 0 && (
                        <span className="reason-chip net" title="company-network influence">🔗</span>
                      )}
                      {s.reasons.slice(0, 3).map((r) => <span className="reason-chip" key={r}>{r}</span>)}
                    </div>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="star-btn"
                      aria-label={saved ? 'Remove from watchlist' : 'Add to watchlist'}
                      title={saved ? `Remove ${s.ticker} from watchlist` : `Add ${s.ticker} to watchlist`}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (saved) onUnwatch?.(s.ticker);
                        else onAdd(s.ticker);
                      }}
                    >
                      {saved ? '★' : '☆'}
                    </button>
                    {onRemove && !s.in_sp500 && (
                      <button className="secondary" title="Remove this custom company"
                              onClick={(e) => { e.stopPropagation(); onRemove(s.ticker); }}>
                        ×
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/components/ScoreBoard.test.tsx`
Expected: PASS — all tests in the file (the three pre-existing tests still pass; the `×` custom-remove test is unaffected because `onRemove` is untouched).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ScoreBoard.tsx frontend/src/components/ScoreBoard.test.tsx
git commit -m "feat(frontend): watch-aware ★/☆ toggle in ScoreBoard rows"
```

---

## Task 2: Wire Discover to the new props

**Files:**
- Modify: `frontend/src/pages/Discover.tsx`

(No test file exists for Discover; this is a wiring change. `watch` is already in scope via `useWatchlist()`.)

- [ ] **Step 1: Pass `watched`/`onUnwatch` to ScoreBoard**

In `frontend/src/pages/Discover.tsx`, change the ScoreBoard line (currently line 113):

```tsx
        {data && <ScoreBoard items={data.items} onAdd={watch.add} onRemove={(t) => delCustom.mutate(t)} />}
```

to:

```tsx
        {data && (
          <ScoreBoard
            items={data.items}
            onAdd={watch.add}
            watched={watch.list}
            onUnwatch={watch.remove}
            onRemove={(t) => delCustom.mutate(t)}
          />
        )}
```

- [ ] **Step 2: Verify the build/tests are clean**

Run: `npx vitest run` (full frontend suite — there is no Discover-specific test, so this confirms nothing regressed).
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Discover.tsx
git commit -m "feat(frontend): reflect watchlist state on the Discover board"
```

---

## Task 3: `Portfolio` — split into Watchlist + Extended boards

**Files:**
- Modify: `frontend/src/pages/Portfolio.tsx`
- Test: `frontend/src/pages/Portfolio.test.tsx`

- [ ] **Step 1: Make the test's `useWatchlist` mock controllable + write failing tests**

In `frontend/src/pages/Portfolio.test.tsx`, change the `useWatchlist` mock (line 10) from a fixed function to a `vi.fn()`:

```tsx
vi.mock('../hooks/queries', () => ({
  useScreen: vi.fn(),
  usePortfolioTickers: vi.fn(),
  useWatchlist: vi.fn(),
}));
```

Update the import (line 21) to also import `useWatchlist`:

```tsx
import { useScreen, usePortfolioTickers, useWatchlist } from '../hooks/queries';
```

Replace the `beforeEach` (line 29) so every test has a default watchlist that individual tests can override:

```tsx
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: [] } as never);
});
```

Append these three tests to the end of the file:

```tsx
it('splits scored rows into Watchlist and Extended boards', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
      price: 1, change_pct: 0, score: 80, direction: 'buy', net: 0, reasons: [], components: {}, as_of: 't' },
    { ticker: 'TSM', name: 'TSMC', sector: 'Tech', exchange: 'NYSE', in_sp500: true,
      price: 1, change_pct: 0, score: 70, direction: 'hold', net: 0, reasons: [], components: {}, as_of: 't' },
  ], as_of: 't', scanned: 2 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['AAPL', 'TSM'] } } as never);
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: ['AAPL'] } as never);
  wrap(<Portfolio />);
  expect(screen.getByText(/Watchlist \(1\)/i)).toBeInTheDocument();
  expect(screen.getByText(/Extended via ontology \(1\)/i)).toBeInTheDocument();
  expect(screen.getByText('AAPL')).toBeInTheDocument();
  expect(screen.getByText('TSM')).toBeInTheDocument();
});

it('hides the Extended board when every scored ticker is in the watchlist', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', exchange: 'NASDAQ', in_sp500: true,
      price: 1, change_pct: 0, score: 80, direction: 'buy', net: 0, reasons: [], components: {}, as_of: 't' },
  ], as_of: 't', scanned: 1 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['AAPL'] } } as never);
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: ['AAPL'] } as never);
  wrap(<Portfolio />);
  expect(screen.getByText(/Watchlist \(1\)/i)).toBeInTheDocument();
  expect(screen.queryByText(/Extended via ontology/i)).not.toBeInTheDocument();
});

it('hides the Watchlist board when no scored ticker is in the watchlist', () => {
  vi.mocked(useScreen).mockReturnValue({ data: { items: [
    { ticker: 'TSM', name: 'TSMC', sector: 'Tech', exchange: 'NYSE', in_sp500: true,
      price: 1, change_pct: 0, score: 70, direction: 'hold', net: 0, reasons: [], components: {}, as_of: 't' },
  ], as_of: 't', scanned: 1 } } as never);
  vi.mocked(usePortfolioTickers).mockReturnValue({ data: { tickers: ['TSM'] } } as never);
  vi.mocked(useWatchlist).mockReturnValue({ add: vi.fn(), remove: vi.fn(), list: [] } as never);
  wrap(<Portfolio />);
  expect(screen.queryByText(/Watchlist \(/i)).not.toBeInTheDocument();
  expect(screen.getByText(/Extended via ontology \(1\)/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/pages/Portfolio.test.tsx`
Expected: FAIL — the section labels `Watchlist (1)` / `Extended via ontology (1)` do not exist yet (the page renders a single "Portfolio board" section).

- [ ] **Step 3: Implement the split in `Portfolio.tsx`**

In `frontend/src/pages/Portfolio.tsx`, after the existing `const data = board.data;` line (line 12), add the partition:

```tsx
  const items = data?.items ?? [];
  const watchSet = new Set(watch.list.map((t) => t.toUpperCase()));
  const mine = items.filter((s) => watchSet.has(s.ticker.toUpperCase()));
  const extended = items.filter((s) => !watchSet.has(s.ticker.toUpperCase()));
```

Replace the single board `<section>` (currently lines 63–68) with two conditional sections:

```tsx
      {data && mine.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <span className="section-label">Watchlist ({mine.length}) — click a row to deep-dive</span>
          </div>
          <ScoreBoard items={mine} onAdd={watch.add} watched={watch.list} onUnwatch={watch.remove} />
        </section>
      )}
      {data && extended.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <span className="section-label">
              Extended via ontology ({extended.length}) — related companies pulled in by your active graph
            </span>
          </div>
          <ScoreBoard items={extended} onAdd={watch.add} watched={watch.list} onUnwatch={watch.remove} />
        </section>
      )}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/pages/Portfolio.test.tsx`
Expected: PASS — all five tests (the two pre-existing tests still pass: the empty-portfolio hint test is unaffected, and the "renders the board" test now renders AAPL in the Extended board since the default mock watchlist is empty).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Portfolio.tsx frontend/src/pages/Portfolio.test.tsx
git commit -m "feat(frontend): split portfolio into watchlist and ontology-extended boards"
```

---

## Task 4: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire frontend test suite**

Run: `npx vitest run`
Expected: PASS — all tests green (253+ existing + the 5 new). Watch for any test that asserted the old `+ Watch` text; if one fails, update that assertion to the `★`/`☆` star (grep first: `git grep -n "+ Watch" -- frontend/src`).

- [ ] **Step 2: Lint**

Run: `npm run lint`
Expected: clean (no `no-unused-expressions` from the star `onClick` — it uses `if/else`, not a ternary statement).

- [ ] **Step 3: Type-check / build**

Run: `npm run build`
Expected: `tsc -b` passes (the new optional props are typed; no `any` introduced).

- [ ] **Step 4: Browser sanity check (dev server)**

Start the dev server and verify on `/portfolio`: watched rows show `★`, ontology-only rows show `☆` under a separate "Extended via ontology" heading; clicking `★` un-watches (row moves to the Extended board) and `☆` watches (row moves to the Watchlist board). Confirm Discover still works. Use coordinate-based `preview_click` (not `element.click()`) when verifying the star buttons — per the repo gotcha, `element.click()` bypasses hit-testing.

---

## Self-Review Notes

- **Spec coverage:** ScoreBoard star toggle (Task 1) ✓; Discover inherits fix (Task 2) ✓; Portfolio two-board split with hide-when-empty for both boards (Task 3) ✓; case-insensitive match (Tasks 1 & 3 use `.toUpperCase()`) ✓; no backend changes ✓.
- **Type consistency:** `watched?: string[]`, `onUnwatch?: (t: string) => void`, and `watch.list`/`watch.add`/`watch.remove` (from `useWatchlist`) are used identically across Tasks 1–3.
- **No placeholders:** every code step shows complete code.
