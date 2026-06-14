# Theme Switcher (Gold ↔ Neon) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user switch the whole UI between the original **gold** ("Quiet Luxury") and the new **neon** ("Neon Terminal") themes, defaulting to gold, persisted per-device in localStorage, applied with no flash, including the canvas-drawn chart and graph.

**Architecture:** A single token layer drives everything. CSS surfaces switch via a `data-theme` attribute on `<html>` (gold = bare `:root` default, neon = `:root[data-theme="neon"]` override). Canvas colors (chart, graph) switch via a shared JS palette module (`lib/theme.ts`) consumed through a `useTheme()` hook. An inline boot script applies the saved theme before first paint. No backend/API/DB changes.

**Tech Stack:** React 18 (`useSyncExternalStore`), TypeScript, Vite, Vitest + Testing Library, lightweight-charts v4, react-force-graph-2d.

---

## File Structure

**New:**
- `frontend/src/lib/theme.ts` — `ThemeName`, `DEFAULT_THEME`, `Palette`, `PALETTES`, `readStoredTheme`, `applyTheme`, `getTheme`, `useTheme`. Single source of truth for theme state + canvas colors.
- `frontend/src/lib/theme.test.ts` — unit tests for the pure functions + palette completeness.
- `frontend/src/components/ThemeToggle.tsx` — the masthead one-click flip control.
- `frontend/src/components/ThemeToggle.test.tsx` — render + click test.

**Modified:**
- `frontend/index.html` — no-flash boot script + load both font sets.
- `frontend/src/main.tsx` — defensive `applyTheme(readStoredTheme())` on boot.
- `frontend/src/styles.css` — split `:root` into gold-default + neon-override; per-theme atmosphere; theme-scope the neon-only signature rules; `.theme-toggle` / `.theme-seg` styles.
- `frontend/src/lib/graphView.ts` — `directionColor`/`sentimentColor` take a `Palette`.
- `frontend/src/lib/graphView.test.ts` — assert both palettes.
- `frontend/src/components/PriceChart.tsx` — read palette via `useTheme`; rebuild on theme change.
- `frontend/src/lib/markers.ts` — optional `colors` param for marker buy/sell.
- `frontend/src/components/GraphCanvas.tsx` — read palette; pass to node/link/focus/label.
- `frontend/src/components/GraphLegend.tsx` — swatches from the active palette.
- `frontend/src/pages/Dashboard.tsx` — SMA legend dots from the palette.
- `frontend/src/pages/Settings.tsx` — Appearance section (theme picker).
- `frontend/src/App.tsx` — render `<ThemeToggle />` in the masthead.

**Conventions:** run all commands from `frontend/`. Test runner: `npm test` (vitest run, whole suite) or `npx vitest run <path>` for one file. Type/build check: `npm run build` (`tsc -b && vite build`). No backend involved.

---

## Task 1: Theme core module (`lib/theme.ts`)

**Files:**
- Create: `frontend/src/lib/theme.ts`
- Test: `frontend/src/lib/theme.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/theme.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_THEME,
  PALETTES,
  applyTheme,
  getTheme,
  readStoredTheme,
} from './theme';

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  applyTheme(DEFAULT_THEME); // reset module state between tests
  localStorage.clear();
});

describe('readStoredTheme', () => {
  it('defaults to gold when nothing is stored', () => {
    localStorage.clear();
    expect(readStoredTheme()).toBe('gold');
    expect(DEFAULT_THEME).toBe('gold');
  });

  it('returns a valid stored theme', () => {
    localStorage.setItem('mc-theme', 'neon');
    expect(readStoredTheme()).toBe('neon');
  });

  it('falls back to gold for an invalid stored value', () => {
    localStorage.setItem('mc-theme', 'banana');
    expect(readStoredTheme()).toBe('gold');
  });

  it('falls back to gold when localStorage throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readStoredTheme()).toBe('gold');
    spy.mockRestore();
  });
});

describe('applyTheme', () => {
  it('sets the html data-theme attribute, persists, and updates getTheme', () => {
    applyTheme('neon');
    expect(document.documentElement.getAttribute('data-theme')).toBe('neon');
    expect(localStorage.getItem('mc-theme')).toBe('neon');
    expect(getTheme()).toBe('neon');
  });

  it('does not throw when localStorage.setItem throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => applyTheme('gold')).not.toThrow();
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
    spy.mockRestore();
  });
});

describe('PALETTES', () => {
  it('defines both themes with identical key sets', () => {
    const gold = Object.keys(PALETTES.gold).sort();
    const neon = Object.keys(PALETTES.neon).sort();
    expect(gold).toEqual(neon);
    expect(gold.length).toBeGreaterThan(0);
  });

  it('has distinct primary colors per theme', () => {
    expect(PALETTES.gold.sma50).not.toBe(PALETTES.neon.sma50);
    expect(PALETTES.gold.nodeHold).not.toBe(PALETTES.neon.nodeHold);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/lib/theme.test.ts`
Expected: FAIL — cannot resolve `./theme`.

- [ ] **Step 3: Implement `lib/theme.ts`**

Create `frontend/src/lib/theme.ts`:

```ts
import { useSyncExternalStore } from 'react';

export type ThemeName = 'gold' | 'neon';
export const DEFAULT_THEME: ThemeName = 'gold';

const STORAGE_KEY = 'mc-theme';

/** Canvas-only colors (CSS surfaces are themed entirely in styles.css). */
export interface Palette {
  // price chart (lightweight-charts)
  chartBg: string;
  chartText: string;
  chartGridV: string;
  chartGridH: string;
  chartBorder: string;
  crosshair: string;
  crosshairLabel: string;
  candleUp: string;
  candleDown: string;
  sma50: string;
  sma200: string;
  markerBuy: string;
  markerSell: string;
  // knowledge graph (react-force-graph-2d canvas)
  nodeBuy: string;
  nodeSell: string;
  nodeHold: string;
  nodeUnknown: string;
  nodeExternal: string;
  focusRing: string;
  focusGlow: string;
  nodeLabel: string;
  sentimentPos: string;
  sentimentNeg: string;
  sentimentNeutral: string;
  fadedLink: string;
}

export const PALETTES: Record<ThemeName, Palette> = {
  gold: {
    chartBg: '#0b0b0d',
    chartText: '#8b8780',
    chartGridV: 'rgba(244,241,234,0.04)',
    chartGridH: 'rgba(244,241,234,0.045)',
    chartBorder: 'rgba(244,241,234,0.09)',
    crosshair: 'rgba(232,200,126,0.40)',
    crosshairLabel: '#caa86a',
    candleUp: '#3f9d77',
    candleDown: '#cf6f6a',
    sma50: '#e8c87e',
    sma200: '#9c8246',
    markerBuy: '#00e676',
    markerSell: '#ff5252',
    nodeBuy: '#3fb950',
    nodeSell: '#f85149',
    nodeHold: '#e8c87e',
    nodeUnknown: '#484f58',
    nodeExternal: '#ab9df2',
    focusRing: '#58a6ff',
    focusGlow: 'rgba(88, 166, 255, 0.9)',
    nodeLabel: '#e6edf3',
    sentimentPos: '#3fb950',
    sentimentNeg: '#f85149',
    sentimentNeutral: '#6e7681',
    fadedLink: 'rgba(110, 118, 129, 0.18)',
  },
  neon: {
    chartBg: '#08080f',
    chartText: '#7d8ab5',
    chartGridV: 'rgba(150,175,255,0.05)',
    chartGridH: 'rgba(150,175,255,0.055)',
    chartBorder: 'rgba(150,175,255,0.10)',
    crosshair: 'rgba(34,224,255,0.45)',
    crosshairLabel: '#0a93b8',
    candleUp: '#27c98b',
    candleDown: '#e0517a',
    sma50: '#22e0ff',
    sma200: '#a96bff',
    markerBuy: '#2bff9e',
    markerSell: '#ff3b6b',
    nodeBuy: '#2bff9e',
    nodeSell: '#ff3b6b',
    nodeHold: '#22e0ff',
    nodeUnknown: '#4a5280',
    nodeExternal: '#a96bff',
    focusRing: '#ff2bd6',
    focusGlow: 'rgba(255, 43, 214, 0.9)',
    nodeLabel: '#eaf0ff',
    sentimentPos: '#2bff9e',
    sentimentNeg: '#ff3b6b',
    sentimentNeutral: '#5f6b91',
    fadedLink: 'rgba(95, 110, 160, 0.16)',
  },
};

function isTheme(v: unknown): v is ThemeName {
  return v === 'gold' || v === 'neon';
}

export function readStoredTheme(): ThemeName {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return isTheme(v) ? v : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

let current: ThemeName = readStoredTheme();
const listeners = new Set<() => void>();

export function getTheme(): ThemeName {
  return current;
}

/** The ONE function that mutates global theme state. */
export function applyTheme(name: ThemeName): void {
  current = name;
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = name;
  }
  try {
    localStorage.setItem(STORAGE_KEY, name);
  } catch {
    /* private mode / blocked storage — keep the in-memory + DOM state */
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function useTheme(): { theme: ThemeName; setTheme: (n: ThemeName) => void } {
  const theme = useSyncExternalStore(subscribe, getTheme, getTheme);
  return { theme, setTheme: applyTheme };
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run src/lib/theme.test.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/theme.ts frontend/src/lib/theme.test.ts
git commit -m "feat(frontend): add theme core (gold/neon palette + useTheme)"
```

---

## Task 2: Make graph color functions + canvas palette-aware

`directionColor`/`sentimentColor` currently hardcode neon hex. Make them take a
`Palette`, and update the two canvas consumers in the SAME task so the tree stays
green (this is a shared-signature change).

**Files:**
- Modify: `frontend/src/lib/graphView.ts`
- Modify: `frontend/src/lib/graphView.test.ts`
- Modify: `frontend/src/components/GraphCanvas.tsx`
- Modify: `frontend/src/components/GraphLegend.tsx`

- [ ] **Step 1: Update the failing test (graphView.test.ts)**

Replace the color assertions block (the `it('maps colours and radius', …)` body's color lines) with palette-driven assertions. The current lines are:

```ts
    expect(directionColor('buy')).toBe('#2bff9e');
    expect(directionColor('hold')).toBe('#22e0ff');
    expect(directionColor('hold')).not.toBe(directionColor('unknown'));
    expect(directionColor('unknown')).toBe('#4a5280');
    expect(sentimentColor('negative')).toBe('#ff3b6b');
```

Replace with:

```ts
    expect(directionColor('buy', PALETTES.neon)).toBe('#2bff9e');
    expect(directionColor('hold', PALETTES.neon)).toBe('#22e0ff');
    expect(directionColor('buy', PALETTES.gold)).toBe('#3fb950');
    expect(directionColor('hold', PALETTES.gold)).toBe('#e8c87e');
    expect(directionColor('hold', PALETTES.gold)).not.toBe(
      directionColor('unknown', PALETTES.gold),
    );
    expect(directionColor('unknown', PALETTES.neon)).toBe('#4a5280');
    expect(sentimentColor('negative', PALETTES.neon)).toBe('#ff3b6b');
    expect(sentimentColor('negative', PALETTES.gold)).toBe('#f85149');
```

And add `PALETTES` to the import at the top of the file:

```ts
import { PALETTES } from './theme';
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/lib/graphView.test.ts`
Expected: FAIL — `directionColor` called with 2 args but takes 1 / type error.

- [ ] **Step 3: Update `graphView.ts`**

Add a type-only import at the top (near the other imports):

```ts
import type { Palette } from './theme';
```

Replace the two color functions:

```ts
export function directionColor(d: NodeDirection, palette: Palette): string {
  return d === 'buy'
    ? palette.nodeBuy
    : d === 'sell'
      ? palette.nodeSell
      : d === 'hold'
        ? palette.nodeHold
        : palette.nodeUnknown;
}

export function sentimentColor(s: ViewLink['sentiment'], palette: Palette): string {
  return s === 'positive'
    ? palette.sentimentPos
    : s === 'negative'
      ? palette.sentimentNeg
      : palette.sentimentNeutral;
}
```

- [ ] **Step 4: Update `GraphCanvas.tsx`**

Add the import (with the existing imports):

```ts
import { PALETTES, useTheme } from '../lib/theme';
```

Inside the component body (near the top, before the returned JSX), resolve the palette:

```ts
  const { theme } = useTheme();
  const palette = PALETTES[theme];
```

Replace the node/link color props and the canvas focus-ring/label colors:

```tsx
        nodeColor={(n: FGNode) => (n.external ? palette.nodeExternal : directionColor(n.direction, palette))}
```

```tsx
            ctx.strokeStyle = palette.focusRing;             // theme focus ring — distinct from every node state
            ctx.shadowColor = palette.focusGlow;
            ctx.shadowBlur = 11 / scale;
            ctx.stroke();
            ctx.shadowBlur = 0;                            // reset so the label isn't blurred
          }
          ctx.fillStyle = palette.nodeLabel;
```

```tsx
        linkColor={(l: FGLink) => (!selectedId || isIncident(l) ? sentimentColor(l.sentiment, palette) : palette.fadedLink)}
```

(The `ctx.font = … "Exo 2", sans-serif` line stays as-is.)

- [ ] **Step 5: Update `GraphLegend.tsx`**

Make the component read the active palette. Add at the top of the file:

```tsx
import { PALETTES, useTheme } from '../lib/theme';
```

Inside `GraphLegend`, after `const [open, setOpen] = useState(true);`:

```tsx
  const p = PALETTES[useTheme().theme];
```

Replace the "Company" group swatches:

```tsx
            <span><i className="dot" style={{ background: p.nodeBuy }} />buy</span>
            <span><i className="dot" style={{ background: p.nodeSell }} />sell</span>
            <span><i className="dot" style={{ background: p.nodeHold }} />hold</span>
            <span><i className="dot" style={{ background: p.nodeUnknown }} />unknown</span>
            <span><i className="dot" style={{ background: p.nodeExternal }} />external</span>
            <span><i className="dot" style={{ background: 'transparent', border: `2px solid ${p.focusRing}`, boxSizing: 'border-box' }} />selected</span>
```

Replace the "Line colour · news effect" swatches:

```tsx
            <span><i className="bar" style={{ background: p.sentimentPos }} />positive</span>
            <span><i className="bar" style={{ background: p.sentimentNeg }} />negative</span>
            <span><i className="bar" style={{ background: p.sentimentNeutral }} />neutral</span>
```

- [ ] **Step 6: Run the affected tests**

Run: `npx vitest run src/lib/graphView.test.ts src/components/GraphCanvas.test.tsx src/components/GraphLegend.test.tsx`
Expected: PASS (these tests don't assert canvas pixels; they verify rendering/structure).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/graphView.ts frontend/src/lib/graphView.test.ts frontend/src/components/GraphCanvas.tsx frontend/src/components/GraphLegend.tsx
git commit -m "feat(frontend): make graph colors palette-aware"
```

---

## Task 3: Make the price chart + markers palette-aware

**Files:**
- Modify: `frontend/src/lib/markers.ts`
- Modify: `frontend/src/lib/markers.test.ts`
- Modify: `frontend/src/components/PriceChart.tsx`

- [ ] **Step 1: Add a failing test for the markers color override**

In `frontend/src/lib/markers.test.ts`, add this test inside the existing `describe`:

```ts
  it('uses provided colors for buy/sell markers', () => {
    const signals = [
      { date: '2024-01-02', action: 'buy', price: 10, reason: 'x' },
      { date: '2024-01-03', action: 'sell', price: 11, reason: 'y' },
    ] as Parameters<typeof signalsToMarkers>[0];
    const markers = signalsToMarkers(signals, { buy: '#111111', sell: '#222222' });
    expect(markers.find((m) => m.text.startsWith('BUY'))?.color).toBe('#111111');
    expect(markers.find((m) => m.text.startsWith('SELL'))?.color).toBe('#222222');
  });
```

(If `signalsToMarkers` is imported already, reuse it; otherwise add it to the existing import from `./markers`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/lib/markers.test.ts`
Expected: FAIL — `signalsToMarkers` ignores the 2nd arg / type error.

- [ ] **Step 3: Update `markers.ts`**

Change the signature to accept an optional colors pair (default keeps current neon so existing callers/tests are unaffected):

```ts
export function signalsToMarkers(
  signals: Signal[],
  colors: { buy: string; sell: string } = { buy: '#2bff9e', sell: '#ff3b6b' },
): ChartMarker[] {
  return [...signals]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((s) => ({
      time: s.date,
      position: s.action === 'buy' ? 'belowBar' : 'aboveBar',
      // Vivid markers stand apart from the muted candle bodies so buys aren't camouflaged.
      color: s.action === 'buy' ? colors.buy : colors.sell,
      shape: s.action === 'buy' ? 'arrowUp' : 'arrowDown',
      text: `${s.action.toUpperCase()} @ ${s.price}`,
    }));
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run src/lib/markers.test.ts`
Expected: PASS.

- [ ] **Step 5: Update `PriceChart.tsx`**

Add the import:

```ts
import { PALETTES, useTheme } from '../lib/theme';
```

Inside `PriceChart`, before the first `useEffect`:

```ts
  const { theme } = useTheme();
```

In the build effect, resolve the palette once at the top of the effect body:

```ts
    const p = PALETTES[theme];
```

Replace the hardcoded color literals in `createChart` / series with palette fields:

```ts
      layout: {
        background: { type: ColorType.Solid, color: p.chartBg },
        textColor: p.chartText,
        fontFamily: '"JetBrains Mono", ui-monospace, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: p.chartGridV },
        horzLines: { color: p.chartGridH },
      },
      rightPriceScale: { borderColor: p.chartBorder },
      timeScale: { borderColor: p.chartBorder },
      crosshair: {
        vertLine: { color: p.crosshair, width: 1, labelBackgroundColor: p.crosshairLabel },
        horzLine: { color: p.crosshair, width: 1, labelBackgroundColor: p.crosshairLabel },
      },
```

```ts
    const candles = chart.addCandlestickSeries({
      upColor: p.candleUp, downColor: p.candleDown, borderVisible: false,
      wickUpColor: p.candleUp, wickDownColor: p.candleDown,
    });
```

```ts
      const s = chart.addLineSeries({ color: p.sma50, lineWidth: 2, priceLineVisible: false, crosshairMarkerVisible: false });
```

```ts
      const s = chart.addLineSeries({ color: p.sma200, lineWidth: 2, priceLineVisible: false, crosshairMarkerVisible: false });
```

Update the `setMarkers` call to pass palette marker colors:

```ts
    candles.setMarkers(
      signalsToMarkers(signals, { buy: p.markerBuy, sell: p.markerSell }).map((m) => ({
        time: m.time,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text,
        size: 2,
      })),
    );
```

Add `theme` to the build effect's dependency array so a theme switch rebuilds the chart:

```ts
  }, [data, signals, onSelectSignal, theme]);
```

(The `fontFamily` stays JetBrains Mono for both themes — acceptable; the chart font is a minor detail and switching it would force a heavier change. The SMA legend dots in the Dashboard, Task 4, do follow the theme.)

- [ ] **Step 6: Run the build + chart-adjacent tests**

Run: `npx vitest run src/lib/markers.test.ts src/pages/Dashboard.test.tsx`
Expected: PASS (Dashboard renders PriceChart; the lightweight-charts canvas is mocked/handled by the existing test setup).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/markers.ts frontend/src/lib/markers.test.ts frontend/src/components/PriceChart.tsx
git commit -m "feat(frontend): make price chart + markers palette-aware"
```

---

## Task 4: Dashboard SMA legend dots follow the theme

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Add the palette import**

In `frontend/src/pages/Dashboard.tsx`, add:

```ts
import { PALETTES, useTheme } from '../lib/theme';
```

- [ ] **Step 2: Resolve the palette in the component**

Inside the `Dashboard` component body, near the other hooks (e.g. just after the existing `useState`/context lines):

```ts
  const p = PALETTES[useTheme().theme];
```

- [ ] **Step 3: Use palette colors for the SMA dots**

Replace:

```tsx
                  <span><i className="dot" style={{ background: '#22e0ff' }} />SMA 50</span>
                  <span><i className="dot" style={{ background: '#a96bff' }} />SMA 200</span>
```

with:

```tsx
                  <span><i className="dot" style={{ background: p.sma50 }} />SMA 50</span>
                  <span><i className="dot" style={{ background: p.sma200 }} />SMA 200</span>
```

- [ ] **Step 4: Run the Dashboard test**

Run: `npx vitest run src/pages/Dashboard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(frontend): theme the Dashboard SMA legend dots"
```

---

## Task 5: No-flash boot script + dual fonts (`index.html`)

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Load both font sets**

Replace the single Google-Fonts `<link href="…">` line with one that includes both families:

```html
    <link
      href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=Exo+2:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Fraunces:ital,opsz,wght@0,9..144,300..600;1,9..144,400..500&family=Hanken+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
```

- [ ] **Step 2: Add the no-flash boot script**

Immediately after the opening `<body>` tag (before `<div id="root">`), add:

```html
    <script>
      // Apply the saved theme before first paint to avoid a flash. Default: gold.
      (function () {
        try {
          var t = localStorage.getItem('mc-theme');
          document.documentElement.dataset.theme = t === 'neon' ? 'neon' : 'gold';
        } catch (e) {
          document.documentElement.dataset.theme = 'gold';
        }
      })();
    </script>
```

- [ ] **Step 3: Verify the dev server boots and applies a theme**

Run: `npm run build`
Expected: build succeeds (this is a static HTML change; the build just bundles it).

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "feat(frontend): no-flash theme boot script + load both font sets"
```

---

## Task 6: Defensive theme apply in `main.tsx`

So non-HTML entry points (and any case the inline script didn't run) still get the attribute set.

**Files:**
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Apply the stored theme before render**

Add the import and a call before `ReactDOM.createRoot(...)`:

```ts
import { applyTheme, readStoredTheme } from './theme';
```

Wait — `theme.ts` is in `./lib/theme`. Use:

```ts
import { applyTheme, readStoredTheme } from './lib/theme';
```

Then, after the imports and before `ReactDOM.createRoot(...).render(...)`:

```ts
applyTheme(readStoredTheme());
```

- [ ] **Step 2: Verify**

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/main.tsx
git commit -m "feat(frontend): apply stored theme on app boot"
```

---

## Task 7: Dual-theme CSS (`styles.css`)

This is the bulk visual change: gold becomes the default (bare `:root`), neon the
override. Self-contained — no tests; verified by build + the browser check in
Task 10.

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Replace the `:root` block with gold-default + neon-override**

Find the current `:root { … }` block (the neon tokens) and replace the ENTIRE
block with:

```css
:root {
  /* ===== Default theme = GOLD ("Quiet Luxury"). data-theme="neon" overrides below. ===== */
  --bg:        #0a0a0b;
  --bg-2:      #0d0d10;
  --ink:       #f4f1ea;
  --ink-soft:  #b6b1a7;
  --ink-faint: #76726a;
  --ink-ghost: #4b4842;

  --gold:       #e8c87e;
  --gold-bright:#f3d99a;
  --gold-deep:  #a9863f;
  --gold-tint:  rgba(232, 200, 126, 0.10);
  --gold-line:  rgba(232, 200, 126, 0.22);

  /* RGB triplet for monochrome accent glows: rgba(var(--accent-rgb), a). */
  --accent-rgb: 232, 200, 126;

  --buy:  #5fd39b;
  --sell: #f0817c;
  --buy-tint:  rgba(95, 211, 155, 0.12);
  --sell-tint: rgba(240, 129, 124, 0.12);

  --panel:      rgba(255, 255, 255, 0.022);
  --panel-2:    rgba(255, 255, 255, 0.04);
  --panel-brd:  rgba(255, 255, 255, 0.07);
  --hairline:   rgba(244, 241, 234, 0.08);

  --shadow: 0 30px 60px -36px rgba(0, 0, 0, 0.85);
  --radius: 16px;

  --serif: "Fraunces", Georgia, "Times New Roman", serif;
  --sans:  "Hanken Grotesk", system-ui, -apple-system, Segoe UI, sans-serif;
  --mono:  "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;

  --maxw: 1880px;
}

:root[data-theme="neon"] {
  /* ===== NEON ("Neon Terminal") override ===== */
  --bg:        #08080f;
  --bg-2:      #0c0c18;
  --ink:       #eaf0ff;
  --ink-soft:  #9fb0d8;
  --ink-faint: #5f6b91;
  --ink-ghost: #363c63;

  --neon:         #22e0ff;
  --neon-bright:  #7af2ff;
  --neon-deep:    #0a93b8;
  --neon-magenta: #ff2bd6;
  --neon-violet:  #a96bff;
  --neon-grid:    rgba(120, 90, 220, 0.07);

  --gold:       var(--neon);
  --gold-bright:var(--neon-bright);
  --gold-deep:  var(--neon-deep);
  --gold-tint:  rgba(34, 224, 255, 0.10);
  --gold-line:  rgba(34, 224, 255, 0.26);

  --accent-rgb: 34, 224, 255;

  --buy:  #2bff9e;
  --sell: #ff3b6b;
  --buy-tint:  rgba(43, 255, 158, 0.12);
  --sell-tint: rgba(255, 59, 107, 0.12);

  --panel:      rgba(120, 150, 230, 0.035);
  --panel-2:    rgba(120, 150, 230, 0.065);
  --panel-brd:  rgba(130, 165, 255, 0.13);
  --hairline:   rgba(150, 175, 255, 0.10);

  --shadow: 0 30px 60px -34px rgba(0, 0, 0, 0.92);
  --radius: 12px;

  --display: "Chakra Petch", "Segoe UI", system-ui, sans-serif;
  --serif:  var(--display);
  --sans:   "Exo 2", system-ui, -apple-system, Segoe UI, sans-serif;
  --mono:   "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
```

- [ ] **Step 2: Convert the 6 monochrome accent glows to use `--accent-rgb`**

Make these exact replacements (each is currently a hardcoded cyan rgba):

`::selection`:
```css
::selection { background: rgba(var(--accent-rgb), 0.25); color: var(--ink); }
```

`.section-label::before` box-shadow:
```css
  box-shadow: 0 0 8px rgba(var(--accent-rgb), 0.6);
```

`button` box-shadow:
```css
  box-shadow: 0 8px 22px -10px rgba(var(--accent-rgb), 0.6);
```

`button:hover` box-shadow (within the existing rule):
```css
button:hover { transform: translateY(-1px); box-shadow: 0 12px 30px -10px rgba(var(--accent-rgb), 0.7); filter: brightness(1.04); }
```

`.range-tab.active` box-shadow:
```css
.range-tab.active { color: #021016; background: linear-gradient(180deg, var(--gold-bright), var(--gold)); box-shadow: 0 4px 12px -6px rgba(var(--accent-rgb), 0.7); }
```

`.trace-head:hover` background:
```css
.trace-head:hover { color: var(--ink); background: rgba(var(--accent-rgb), 0.06); }
```

- [ ] **Step 3: Theme-scope the brand mark + name (neon-only flourishes)**

Replace the current neon `.brand-mark` rule + `@keyframes brand-flicker` + `.brand-name` block with a gold default followed by neon overrides:

```css
.brand-mark {
  font-size: 12px;
  color: var(--gold);
  transform: translateY(-2px);
  text-shadow: 0 0 14px rgba(var(--accent-rgb), 0.55);
}
:root[data-theme="neon"] .brand-mark {
  color: var(--neon-magenta);
  text-shadow: 0 0 6px var(--neon-magenta), 0 0 18px rgba(255, 43, 214, 0.7);
  animation: brand-flicker 6s steps(1) infinite;
}
@keyframes brand-flicker {
  0%, 92%, 96%, 100% { opacity: 1; }
  94% { opacity: 0.55; }
}
:root[data-theme="neon"] .brand-name {
  background: linear-gradient(92deg, var(--ink), var(--neon-bright));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
```

- [ ] **Step 4: Theme-scope the masthead beam**

Replace the current `.masthead-rule` rule with a gold default + neon override:

```css
.masthead-rule {
  height: 1px;
  border: 0;
  margin: 0 0 12px;
  background: linear-gradient(90deg, transparent, var(--gold-line) 18%, var(--gold) 50%, var(--gold-line) 82%, transparent);
  opacity: 0.7;
}
:root[data-theme="neon"] .masthead-rule {
  background: linear-gradient(90deg, transparent, var(--gold-line) 12%, var(--neon) 38%, var(--neon-magenta) 64%, var(--gold-line) 88%, transparent);
  box-shadow: 0 0 12px rgba(34, 224, 255, 0.35);
  opacity: 0.85;
}
```

- [ ] **Step 5: Theme-scope the nav active state**

Replace the current `.nav-link.active` + `.nav-link.active::after` rules with:

```css
.nav-link.active { color: var(--ink); }
.nav-link.active::after { right: 0; box-shadow: 0 0 10px rgba(var(--accent-rgb), 0.6); }
:root[data-theme="neon"] .nav-link.active { color: var(--neon-bright); text-shadow: 0 0 14px rgba(34, 224, 255, 0.45); }
:root[data-theme="neon"] .nav-link.active::after { box-shadow: 0 0 10px var(--neon), 0 0 18px rgba(34, 224, 255, 0.6); }
```

- [ ] **Step 6: Theme-scope the panel glass (sheen + glow + blur)**

Replace the current `.panel` box-shadow/backdrop lines and the `.panel::before` rule. The `.panel` rule's tail becomes the gold default, with a neon override after `.panel::before`:

In `.panel { … }` set the backdrop + shadow to the gold original:
```css
  backdrop-filter: blur(14px) saturate(120%);
  -webkit-backdrop-filter: blur(14px) saturate(120%);
  box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
```

`.panel::before` (gold default sheen):
```css
.panel::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 1px;
  margin: 0 18px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.18), transparent);
  opacity: 0.6;
}
```

Add the neon overrides right after:
```css
:root[data-theme="neon"] .panel {
  backdrop-filter: blur(16px) saturate(135%);
  -webkit-backdrop-filter: blur(16px) saturate(135%);
  box-shadow:
    var(--shadow),
    inset 0 1px 0 rgba(180, 215, 255, 0.06),
    0 0 0 1px rgba(34, 224, 255, 0.03),
    0 0 28px -16px rgba(34, 224, 255, 0.25);
}
:root[data-theme="neon"] .panel::before {
  margin: 0 16px;
  background: linear-gradient(90deg, transparent, rgba(34, 224, 255, 0.55) 35%, rgba(255, 43, 214, 0.45) 65%, transparent);
  opacity: 0.55;
}
```

- [ ] **Step 7: Theme-scope the hero name/price + verdict word**

Replace `.hero-name`, `.hero-price`, and `.verdict-word` with gold defaults + neon overrides:

```css
.hero-name {
  font-family: var(--serif);
  font-optical-sizing: auto;
  font-weight: 500;
  font-size: clamp(24px, 2.6vw, 34px);
  line-height: 1.04;
  letter-spacing: -0.018em;
  margin: 0;
  color: var(--ink);
}
:root[data-theme="neon"] .hero-name { font-weight: 600; letter-spacing: 0.004em; text-shadow: 0 0 22px rgba(122, 242, 255, 0.18); }
```

```css
.hero-price {
  font-family: var(--serif);
  font-weight: 500;
  font-size: clamp(34px, 3.6vw, 46px);
  line-height: 0.95;
  letter-spacing: -0.025em;
  font-feature-settings: "tnum" 1, "lnum" 1;
  color: var(--ink);
}
:root[data-theme="neon"] .hero-price { font-family: var(--mono); font-weight: 600; letter-spacing: -0.015em; text-shadow: 0 0 20px rgba(34, 224, 255, 0.28); }
```

```css
.verdict-word {
  font-family: var(--serif);
  font-weight: 500;
  font-size: 32px;
  line-height: 1;
  letter-spacing: -0.01em;
}
:root[data-theme="neon"] .verdict-word { font-weight: 700; letter-spacing: 0.01em; text-transform: uppercase; text-shadow: 0 0 20px color-mix(in srgb, currentColor 55%, transparent); }
```

- [ ] **Step 8: Theme-scope the score bar**

Replace the current `.score-bar` + `.score-bar > span` rules with gold defaults + neon overrides:

```css
.score-bar { position: relative; width: 70px; height: 6px; border-radius: 999px; background: rgba(255, 255, 255, 0.07); overflow: hidden; }
.score-bar > span { position: absolute; inset: 0 auto 0 0; background: linear-gradient(90deg, var(--gold-deep), var(--gold)); border-radius: 999px; }
:root[data-theme="neon"] .score-bar { background: rgba(130, 165, 255, 0.10); box-shadow: inset 0 0 0 1px rgba(34, 224, 255, 0.08); }
:root[data-theme="neon"] .score-bar > span { background: linear-gradient(90deg, var(--neon-deep), var(--neon) 60%, var(--neon-magenta)); box-shadow: 0 0 8px rgba(34, 224, 255, 0.6); }
```

- [ ] **Step 9: Theme-scope the winner chip glow**

Replace the current `.signal-chip.winner` rule with:

```css
.signal-chip.winner { border-color: var(--gold-line); background: var(--gold-tint); }
:root[data-theme="neon"] .signal-chip.winner { box-shadow: 0 0 14px -4px var(--neon); }
```

- [ ] **Step 10: Theme-scope the body atmosphere**

Replace the current neon `body::before` and `body::after` rules with the gold default (champagne halo + film grain), then add neon overrides:

```css
body::before {
  background:
    radial-gradient(120% 80% at 50% -25%, rgba(232, 200, 126, 0.10), transparent 55%),
    radial-gradient(90% 60% at 100% 0%, rgba(120, 150, 200, 0.05), transparent 50%);
}
body::after {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E");
  opacity: 0.025;
  mix-blend-mode: screen;
}
:root[data-theme="neon"] body::before {
  background:
    radial-gradient(115% 70% at 50% -18%, rgba(34, 224, 255, 0.11), transparent 55%),
    radial-gradient(80% 60% at 100% 0%, rgba(255, 43, 214, 0.07), transparent 52%),
    radial-gradient(95% 85% at 0% 112%, rgba(169, 107, 255, 0.09), transparent 55%),
    linear-gradient(var(--neon-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--neon-grid) 1px, transparent 1px);
  background-size: 100% 100%, 100% 100%, 100% 100%, 46px 46px, 46px 46px;
  background-position: 0 0, 0 0, 0 0, center, center;
}
:root[data-theme="neon"] body::after {
  background-image: repeating-linear-gradient(
    0deg, rgba(0, 0, 0, 0.22) 0px, rgba(0, 0, 0, 0.22) 1px, transparent 1px, transparent 3px);
  opacity: 0.22;
  mix-blend-mode: multiply;
}
```

(The shared `body::before, body::after { content:""; position:fixed; inset:0; pointer-events:none; z-index:0; }` rule stays.)

- [ ] **Step 11: Repoint the few `var(--neon)` uses that live in SHARED rules**

These rules apply in BOTH themes but reference `--neon`, which is undefined under
gold. Switch them to `--gold` (defined in both: gold hex under gold, cyan alias
under neon) so they're always valid:

`.graph-tabs .tab.active`:
```css
.graph-tabs .tab.active { color: var(--ink); border-bottom-color: var(--gold); box-shadow: 0 1px 8px -2px var(--gold); }
```

`.graph-save-row .linklike` (color):
```css
.graph-save-row .linklike { background: none; border: none; color: var(--gold); cursor: pointer; padding: 0; text-align: left; flex: 1; }
```

`.unsaved-hint`:
```css
.unsaved-hint { color: var(--gold); }
```

- [ ] **Step 12: Theme-scope the S&P badge**

The S&P badge is violet under neon but was blue under gold. Replace `.badge.sp` with a gold default + neon override:

```css
.badge.sp     { background: rgba(88, 166, 255, 0.10); color: #58a6ff; border-color: rgba(88, 166, 255, 0.25); }
:root[data-theme="neon"] .badge.sp { background: rgba(169, 107, 255, 0.12); color: var(--neon-violet); border-color: rgba(169, 107, 255, 0.30); }
```

- [ ] **Step 13: Add the theme-control styles**

Append to the end of `styles.css`:

```css
/* ----- Theme controls (masthead toggle + Settings picker) ----------------- */
.theme-toggle {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--ink-faint);
  background: transparent;
  border: 1px solid var(--panel-brd);
  border-radius: 999px;
  padding: 5px 11px;
  box-shadow: none;
  white-space: nowrap;
  align-self: center;
}
.theme-toggle:hover { color: var(--gold); border-color: var(--gold-line); background: var(--gold-tint); transform: none; box-shadow: none; filter: none; }

.theme-seg { display: inline-flex; gap: 2px; background: rgba(0, 0, 0, 0.25); border: 1px solid var(--panel-brd); border-radius: 9px; padding: 3px; }
.theme-seg button {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: none;
  color: var(--ink-faint);
  background: transparent;
  border: 0;
  border-radius: 6px;
  padding: 5px 12px;
  cursor: pointer;
  box-shadow: none;
}
.theme-seg button:hover { color: var(--ink-soft); background: transparent; transform: none; box-shadow: none; filter: none; }
.theme-seg button.active { color: #021016; background: linear-gradient(180deg, var(--gold-bright), var(--gold)); }
```

- [ ] **Step 14: Verify no neon vars leak into the gold (default) scope**

Grep the file and confirm EVERY remaining `--neon` source-var usage and every
hardcoded neon rgba lives inside a `:root[data-theme="neon"]` rule (or was
repointed to `--gold`/`--accent-rgb`):

Run: `npx rg "var\(--neon|rgba\(34, 224, 255|rgba\(255, 43, 214|rgba\(169, 107, 255|rgba\(122, 242, 255" src/styles.css`
Expected: every match is within a `:root[data-theme="neon"]` block (brand-mark,
masthead-rule, panel/::before, hero-name/price, verdict-word, score-bar, nav
active, badge.sp, body atmosphere). If any match is in a SHARED rule, fix it
(repoint to `--gold` / `rgba(var(--accent-rgb), …)` or move it under the neon
scope). The gold default (`--accent-rgb: 232, 200, 126`) must never resolve a
`--neon*` variable.

- [ ] **Step 15: Build and eyeball both themes**

Run: `npm run build`
Expected: build succeeds.
(Full visual verification happens in Task 10.)

- [ ] **Step 16: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat(frontend): dual-theme CSS (gold default + neon override)"
```

---

## Task 8: Masthead theme toggle (`ThemeToggle` + App)

**Files:**
- Create: `frontend/src/components/ThemeToggle.tsx`
- Test: `frontend/src/components/ThemeToggle.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ThemeToggle.test.tsx`:

```tsx
import { afterEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ThemeToggle } from './ThemeToggle';
import { applyTheme } from '../lib/theme';

afterEach(() => {
  applyTheme('gold');
  localStorage.clear();
});

describe('ThemeToggle', () => {
  it('shows the current theme and flips it on click', () => {
    applyTheme('gold');
    render(<ThemeToggle />);
    const btn = screen.getByRole('button', { name: /theme/i });
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
    fireEvent.click(btn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('neon');
    fireEvent.click(btn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/ThemeToggle.test.tsx`
Expected: FAIL — cannot resolve `./ThemeToggle`.

- [ ] **Step 3: Implement `ThemeToggle.tsx`**

Create `frontend/src/components/ThemeToggle.tsx`:

```tsx
import { useTheme, type ThemeName } from '../lib/theme';

const NEXT: Record<ThemeName, ThemeName> = { gold: 'neon', neon: 'gold' };
const LABEL: Record<ThemeName, string> = { gold: 'Gold', neon: 'Neon' };

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[NEXT[theme]]}.`}
      title={`Switch to ${LABEL[NEXT[theme]]} theme`}
      onClick={() => setTheme(NEXT[theme])}
    >
      ◑ {LABEL[theme]}
    </button>
  );
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run src/components/ThemeToggle.test.tsx`
Expected: PASS.

- [ ] **Step 5: Wire it into the masthead**

In `frontend/src/App.tsx`, add the import:

```tsx
import { ThemeToggle } from './components/ThemeToggle';
```

In the `<header className="masthead">`, add the toggle as the last child after the `</nav>`:

```tsx
          <nav className="nav">
            <NavLink to="/" end className={navClass}>Dashboard</NavLink>
            <NavLink to="/portfolio" className={navClass}>Portfolio</NavLink>
            <NavLink to="/discover" className={navClass}>Discover</NavLink>
            <NavLink to="/graph" className={navClass}>Graph</NavLink>
            <NavLink to="/evaluation" className={navClass}>Evaluation</NavLink>
            <NavLink to="/chat" className={navClass}>Chat</NavLink>
            <NavLink to="/settings" className={navClass}>Settings</NavLink>
          </nav>
          <ThemeToggle />
```

- [ ] **Step 6: Run the broader suite to confirm nothing regressed**

Run: `npx vitest run src/components/ThemeToggle.test.tsx src/pages/Dashboard.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ThemeToggle.tsx frontend/src/components/ThemeToggle.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): masthead theme toggle"
```

---

## Task 9: Settings "Appearance" section

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/pages/Settings.test.tsx`

- [ ] **Step 1: Write the failing test**

The file already imports `fireEvent`, `screen`, `waitFor` and defines a
`renderSettings()` helper. The only new import needed is `applyTheme` — add it
near the top (after the existing `import { api } from '../api/client';` line):

```tsx
import { applyTheme } from '../lib/theme';
```

Add a new top-level `describe` block at the END of the file (after the
`'Settings fetch models'` describe):

```tsx
describe('Settings appearance', () => {
  it('switches theme from the Appearance picker', async () => {
    applyTheme('gold');
    renderSettings();
    const neonBtn = await screen.findByRole('button', { name: /^neon/i });
    fireEvent.click(neonBtn);
    expect(document.documentElement.getAttribute('data-theme')).toBe('neon');
    applyTheme('gold'); // reset module + DOM state for other tests
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/pages/Settings.test.tsx`
Expected: FAIL — no button named "Neon".

- [ ] **Step 3: Add the Appearance section to `Settings.tsx`**

Add the import:

```tsx
import { useTheme } from '../lib/theme';
```

Inside the `Settings` component body, after the existing hook calls (e.g. after
`const listModels = useListModels();`):

```tsx
  const { theme, setTheme } = useTheme();
```

Add the Appearance card as the FIRST `.settings-card` inside the returned
`.settings` container (before the provider card):

```tsx
        <section className="settings-card">
          <h3>Appearance</h3>
          <div className="field">
            <label>Theme</label>
            <div className="theme-seg" role="group" aria-label="Theme">
              <button
                type="button"
                className={theme === 'gold' ? 'active' : ''}
                aria-pressed={theme === 'gold'}
                onClick={() => setTheme('gold')}
              >
                Gold · Quiet Luxury
              </button>
              <button
                type="button"
                className={theme === 'neon' ? 'active' : ''}
                aria-pressed={theme === 'neon'}
                onClick={() => setTheme('neon')}
              >
                Neon · Terminal
              </button>
            </div>
            <p className="note muted">Applies instantly and is saved on this device.</p>
          </div>
        </section>
```

> The button text starts with "Gold"/"Neon" so the test's `/^neon/i` name match
> works (accessible name = button text). `setTheme` applies + persists
> immediately; it is independent of the Save button.

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run src/pages/Settings.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(frontend): Settings Appearance theme picker"
```

---

## Task 10: Full verification + browser check both themes

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `npm test`
Expected: all tests PASS (≈272 + the new theme/graph/markers/toggle/settings tests).

- [ ] **Step 2: Type + production build**

Run: `npm run build`
Expected: `tsc -b` clean, `vite build` succeeds.

- [ ] **Step 3: Lint the changed files (no NEW errors)**

Run: `npx eslint src/lib/theme.ts src/components/ThemeToggle.tsx src/components/PriceChart.tsx src/components/GraphCanvas.tsx src/components/GraphLegend.tsx src/pages/Settings.tsx src/App.tsx`
Expected: no errors on these files. (NOTE: `master` already fails `npm run lint`
on PRE-EXISTING debt in `GraphCanvas.tsx` `no-explicit-any` and `graphView.ts`
regex escapes — that's unrelated; just confirm THESE changes add no new errors.
`GraphCanvas.tsx` is in the list because we edit it — its pre-existing `any`
warnings are not ours to fix here; confirm no NEW ones were introduced.)

- [ ] **Step 4: Browser check — default (gold)**

Start the dev server (preview MCP `preview_start` on the `frontend` config, or
`npm run dev`). With no `mc-theme` stored (or set to gold), confirm: the
masthead shows the gold wordmark + gold diamond, gold masthead beam, Fraunces
headings, champagne accents; the chart (load a ticker if a backend is up, else
the chrome) and graph empty-state read gold. The masthead toggle reads "Gold".

- [ ] **Step 5: Browser check — switch to neon**

Click the masthead toggle (or pick Neon in Settings → Appearance). Confirm the
WHOLE UI flips to neon instantly with no reload — indigo bg, cyan/magenta,
Chakra Petch/Exo 2, neon grid + scanlines, and (with data) cyan/violet SMA lines
+ neon candles/markers + neon graph nodes. Reload the page: it stays neon (no
flash of gold). Toggle back to gold; reload: stays gold.

- [ ] **Step 6: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "test(frontend): theme switcher verification fixups"
```

(Skip if Step 1–5 needed no changes.)

---

## Notes for the implementer

- **Keep the tree green per task.** Task 2 changes a shared function signature; it
  updates all call sites in the same commit on purpose.
- **No backend, API, schema, or DB changes** anywhere in this plan.
- **Gold values are the originals** restored from git history (pre-`31c12a0`);
  neon values are the current ones. The palette module and the CSS token blocks
  must agree on these (the ~10 colors that appear in both are intentionally
  duplicated — JS can't read CSS vars for the canvas).
- **localStorage key:** `mc-theme`. **Default:** `gold`.
