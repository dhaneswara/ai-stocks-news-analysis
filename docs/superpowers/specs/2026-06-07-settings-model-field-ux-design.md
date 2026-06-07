# Settings Model Field UX — Design

- **Date:** 2026-06-07
- **Status:** Approved
- **Scope:** Frontend-only refinement of the provider Settings (`frontend/src/pages/Settings.tsx`
  + its test). No backend / API / type changes. Follows on the model-listing feature.

## Overview

Two UX refinements to the Provider settings:

1. **Reorder** so the credential field (**API key**, or **Base URL** for Ollama) appears
   **above** the Model field. Fetching models calls the provider API, which needs the key
   (Ollama needs the base URL), so the natural top-to-bottom flow is *provider → credential →
   model*.
2. **Merge** the Model free-text input and the separate fetched-models dropdown into a **single
   control**: a text input backed by a `<datalist>` (type a name *or* pick a fetched one). This
   removes the second control that appeared after fetching.

## Locked decisions

| Decision | Choice |
|---|---|
| Field order | Active provider → **API key / Base URL** → Model → Watchlist. |
| Model control | One `<input list="model-options">` + a `<datalist id="model-options">` populated from the fetched list. Type a custom name or pick a fetched one. **No separate `<select>`.** |
| Fetch workflow | Unchanged: the **Fetch models** button (save-first, inline ✓/✗ status) populates the datalist. |
| Scope | Frontend-only; the backend endpoint, hooks, types, and per-provider fetch state are unchanged. |

## Current state

`frontend/src/pages/Settings.tsx` renders, in order: **Active provider** → **Model** (a
`.model-row` with the input + Fetch-models button + status, then a conditional `<select>` of
fetched models) → **credential** (Ollama Base URL, else API key) → **Watchlist**. The fetched
list lives in per-provider state (`models: Record<string,string[]>`, `fetched = models[active]`);
`onFetchModels` saves the form then calls `listModels.mutate(active)`. `Settings.test.tsx`
clicks **Fetch models** and asserts the fetched options render.

## Design

In `frontend/src/pages/Settings.tsx` only:

1. **Move the credential block** — the `active === 'ollama' ? <Base URL field> : <API key field>`
   conditional — to immediately **after** the Active-provider field and **before** the Model
   field. Its contents are unchanged.

2. **Merge the Model control.** In the Model `<div className="field">`:
   - Add `list="model-options"` to the Model `<input>`.
   - **Remove** the separate `{fetched.length > 0 && <select>…</select>}` block.
   - Add a `<datalist id="model-options">` whose options come from `fetched`:
     ```tsx
     <datalist id="model-options">
       {fetched.map((m) => <option key={m} value={m} />)}
     </datalist>
     ```
   - Keep the `.model-row` (input + **Fetch models** button + `modelsMsg` status) exactly as is,
     and keep the `models` / `fetched` state and `onFetchModels` handler unchanged.

No CSS changes — `.model-row` stays; the `<datalist>` is native and renders no visible box of its
own (the input gains a dropdown affordance).

## UI layout

```
Active provider   ▼
API key           [ password ]            (Base URL for Ollama)
Model             [ deepseek-chat   ▾ ]  [ Fetch models ]   ✓ 2 models
                    ↑ type a name, or pick a fetched one from the dropdown
Watchlist         [ … ]
```

## Edge cases

- **Before fetch:** the datalist is empty → the Model field behaves as a plain text input.
- **After fetch:** the input offers the fetched models as dropdown suggestions; typing a custom
  model name is still allowed (a `<datalist>` does not restrict the input value).
- **Switching provider:** `fetched = models[active]`, so the datalist reflects the active
  provider's fetched list (empty until that provider is fetched).
- **Ollama:** the credential field is the Base URL (now above Model); Fetch uses it.

## Testing

- Update `frontend/src/pages/Settings.test.tsx`: after clicking **Fetch models**, assert
  `api.listModels` was called with `'anthropic'` **and** the datalist `#model-options` contains
  options with values `['claude-a', 'claude-b']`. Query via
  `document.querySelectorAll('#model-options option')` and read each `value` — datalist options
  are not exposed as ARIA listbox options, so `getByRole('option', …)` is not used here.
- Gates: `tsc --noEmit`, `vitest run`, `vite build` — all green.

## Out of scope

- A strict pick-only dropdown (the chosen control is the type-or-pick datalist).
- Any backend / endpoint / hook / type change.
- Reordering fields outside the Provider settings section (Alerts / Truth Social / actions stay).

## Files

- Modify: `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Settings.test.tsx`
