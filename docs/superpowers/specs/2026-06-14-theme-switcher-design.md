# Theme switcher — Gold (Quiet Luxury) ↔ Neon Terminal

**Date:** 2026-06-14
**Status:** Design — approved, pre-plan

## Context

The frontend just shipped a full visual retheme from the original champagne-gold
**"Quiet Luxury"** look to a retro-futuristic **"Neon Terminal"** synthwave look
(merged at `31c12a0`). Both designs are token-driven: the entire UI keys off
CSS-variable tokens (`--gold*` / `--serif` / `--sans` / `--mono` and the
`--buy`/`--sell` signal colors), plus a handful of **JavaScript** color literals
for the `<canvas>`-drawn price chart (lightweight-charts) and knowledge-graph
(react-force-graph-2d), which do **not** read CSS variables.

The user wants both looks available as a **user-selectable theme**, defaulting to
the original gold, with neon as an opt-in alternative.

## Goal

Let the user switch between two complete themes — **gold** and **neon** — from a
new Appearance control. The switch is **full-fidelity**: every surface follows the
theme, including the chart and graph canvases. The choice is remembered
per-device and applies instantly with no flash.

## Decisions (settled during brainstorming)

| Decision | Choice |
|---|---|
| Storage | **Browser `localStorage`** (per-device; instant; no backend/API/DB change) |
| Fidelity | **Full** — chart + graph canvas colors switch too |
| Default theme | **Gold (Quiet Luxury)** — neon is opt-in |
| Controls | **Appearance section in Settings** + a **quick masthead toggle** |
| Canvas-color architecture | **Approach A** — a shared JS palette module (not `getComputedStyle`) |

## Non-goals (YAGNI)

- No system / auto (OS `prefers-color-scheme`) theme.
- No more than the two themes; no per-component theme overrides.
- No cross-device sync (deliberate consequence of localStorage storage).
- No backend, API, schema, or DB changes whatsoever.

## Architecture

### 1. Theme core — `frontend/src/lib/theme.ts` (new)

The single source of truth for theme state and for the **canvas** colors.

- `export type ThemeName = 'gold' | 'neon'`
- `export const DEFAULT_THEME: ThemeName = 'gold'`
- `export interface Palette { … }` — the canvas-only colors (CSS surfaces are
  handled entirely in CSS, see §3). Fields:
  - Chart: `chartBg`, `chartText`, `chartGridV`, `chartGridH`, `chartBorder`,
    `crosshair`, `crosshairLabel`, `candleUp`, `candleDown`, `sma50`, `sma200`,
    `markerBuy`, `markerSell`
  - Graph: `nodeBuy`, `nodeSell`, `nodeHold`, `nodeUnknown`, `nodeExternal`,
    `focusRing`, `focusGlow`, `nodeLabel`, `sentimentPos`, `sentimentNeg`,
    `sentimentNeutral`, `fadedLink`
- `export const PALETTES: Record<ThemeName, Palette>` — two complete entries.
  - **gold** = the exact pre-neon values restored from git history
    (e.g. candles `#3f9d77`/`#cf6f6a`, sma50 `#e8c87e`, sma200 `#9c8246`,
    markers `#00e676`/`#ff5252`, graph buy `#3fb950` / sell `#f85149` /
    hold `#e8c87e` / unknown `#484f58` / external `#ab9df2`, focus `#58a6ff`,
    sentiment neutral `#6e7681`, label `#e6edf3`, faded link
    `rgba(110,118,129,0.18)`, chart bg `#0b0b0d`, text `#8b8780`, etc.).
  - **neon** = the current values (cyan/magenta/violet/mint/rose).
- State + side effects:
  - `readStoredTheme(): ThemeName` — reads `localStorage['mc-theme']`; returns
    `DEFAULT_THEME` if absent/invalid.
  - `applyTheme(name)` — sets `document.documentElement.dataset.theme = name`
    **and** writes localStorage. The one function that mutates global theme state.
  - `getTheme()` / subscribe primitives backing a `useTheme()` hook implemented
    with `useSyncExternalStore`, returning `{ theme, setTheme }`. Components that
    need the palette call `useTheme()` then index `PALETTES[theme]`.
- localStorage key: `mc-theme`.

### 2. No-flash boot — `index.html`

- A tiny **inline `<script>` in `<head>`** (before the stylesheet/app load) sets
  `document.documentElement.dataset.theme` from `localStorage['mc-theme']`,
  falling back to `gold`, so the correct theme paints on first frame even when
  the user has chosen neon. Kept inline (no import) specifically to run before
  paint.
- The Google-Fonts `<link>` loads **both** font sets (Fraunces + Hanken Grotesk
  + IBM Plex Mono **and** Chakra Petch + Exo 2 + JetBrains Mono).
- `main.tsx` also calls `applyTheme(readStoredTheme())` defensively (idempotent
  with the inline script) so a non-HTML entry (tests) is consistent.

### 3. CSS — `frontend/src/styles.css`

The current single `:root` token block becomes a **default-plus-override** pair
(gold is the default, so it has no separate attribute block — this keeps gold
defined in exactly one place and is also the no-JS / no-attribute fallback):

- **Bare `:root` = gold + shared.** Holds the original gold tokens (canvas bg,
  inks, `--gold*` champagne values, `--buy`/`--sell` greens/corals, glass
  surfaces, `--serif: Fraunces` / `--sans: Hanken Grotesk` / `--mono: IBM Plex
  Mono`, `--radius: 16px`) **and** the structural tokens (`--maxw`). So
  `<html>` with no attribute, with `data-theme="gold"`, or with JS disabled all
  render gold.
- **`:root[data-theme="neon"] { … }` = neon overrides.** Redefines every token
  gold sets, to its neon value (indigo bg, cool inks, the `--neon*` source vars
  + the `--gold*` aliases pointing at them, mint/rose, Chakra Petch / Exo 2 /
  JetBrains Mono, `--radius: 12px`). Because it overrides the full token set,
  nothing gold-specific leaks into neon.

Per-theme **atmosphere**: the bare `body::before` / `body::after` render the gold
atmosphere (champagne halo + film-grain); `[data-theme="neon"] body::before` /
`::after` override with the neon corner glows + perspective grid + CRT scanlines.
Signature treatments that read tokens (panel sheen, masthead beam, score bars)
follow automatically via `var(--…)`; any that hardcode neon rgba (panel rim glow,
brand flicker, masthead-beam glow) move under the `[data-theme="neon"]` scope so
gold doesn't inherit a neon glow.

### 4. Canvas consumers become theme-aware

- `components/PriceChart.tsx` — call `useTheme()`, resolve `PALETTES[theme]`,
  use it for layout/grid/crosshair/candles/SMA/markers, and **add `theme`
  (or the palette) to the build effect's dependency array** so switching theme
  rebuilds the chart.
- `lib/graphView.ts` — `directionColor(d, palette)` and
  `sentimentColor(s, palette)` take the palette (or the specific fields) as a
  parameter instead of hardcoding hex. Pure and testable.
- `components/GraphCanvas.tsx` — `useTheme()`; pass palette colors to
  `nodeColor`/`linkColor`/focus-ring stroke+glow/label fill.
- `components/GraphLegend.tsx` — render swatches from the active palette
  (via `directionColor`/`sentimentColor` + palette) instead of hardcoded hex.
- `pages/Dashboard.tsx` — the SMA 50 / SMA 200 legend dots read
  `palette.sma50` / `palette.sma200`.

### 5. Controls

- **Settings — Appearance section** (`pages/Settings.tsx`): a labeled segmented
  control / radio pair **Gold (Quiet Luxury)** | **Neon Terminal**. Calls
  `setTheme(name)` → applies **instantly** and persists; it is **independent of
  the Save button** (theme is a localStorage display pref, not part of the
  server `Settings` form blob). Placed as its own `.settings-card`.
- **Masthead toggle** (`App.tsx`): a small always-visible control in the
  masthead (near the brand / run-indicator) that flips gold↔neon in one click
  via `useTheme().setTheme`. Styled subtly (a `.theme-toggle` button, e.g.
  shows the target/current theme label or a glyph); `aria-label` set for a11y.

## Data flow

1. First load: inline `<head>` script reads `localStorage['mc-theme']`
   (default `gold`) → sets `<html data-theme="…">` → CSS paints the right theme
   with no flash.
2. React mounts; `useTheme()` reads the same value via `useSyncExternalStore`.
3. User flips the masthead toggle or picks in Settings → `setTheme` →
   `applyTheme` updates the `<html>` attribute (CSS surfaces re-skin instantly)
   **and** localStorage; the external store notifies subscribers → `useTheme`
   consumers (PriceChart, GraphCanvas, GraphLegend, Dashboard dots) re-render
   with the new palette; PriceChart rebuilds via its theme dep.

## Error handling / edge cases

- Invalid/absent localStorage value → `DEFAULT_THEME` (gold).
- `localStorage` access throwing (privacy mode) → `try/catch`, fall back to
  in-memory default; the toggle still works for the session.
- Tests run in jsdom with no inline script → `main.tsx`'s `applyTheme` (or the
  hook's lazy init) ensures `document.documentElement` gets the attribute.

## Testing

- `lib/theme.test.ts` — `readStoredTheme` default + persisted + invalid;
  `applyTheme` sets attribute + writes localStorage; localStorage-throws
  fallback; `PALETTES` has both themes with identical key sets (completeness).
- `lib/graphView.test.ts` — color tests reworked to assert against **both**
  palettes via the new palette param (replacing the single-theme hex asserts).
- `pages/Settings.test.tsx` — Appearance control renders; selecting Neon calls
  `applyTheme`/sets the attribute and persists.
- A small **masthead toggle** test (in an `App`/component test) — clicking flips
  the attribute.
- Existing chart/graph tests stay green (palette is injected, not asserted on
  canvas pixels).
- Target: full suite green, ~272 → ~+10 frontend tests; `tsc -b` + `npm run
  build` clean.

## Files touched

New: `frontend/src/lib/theme.ts`, `frontend/src/lib/theme.test.ts`.
Edited: `frontend/index.html`, `frontend/src/main.tsx`,
`frontend/src/styles.css`, `frontend/src/pages/Settings.tsx`,
`frontend/src/App.tsx`, `frontend/src/components/PriceChart.tsx`,
`frontend/src/lib/graphView.ts` (+ test), `frontend/src/components/GraphCanvas.tsx`,
`frontend/src/components/GraphLegend.tsx`, `frontend/src/pages/Dashboard.tsx`.
Test fixtures that build a `Settings` literal are unaffected (theme isn't in
`Settings`).
