# Settings Model Field UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the provider Settings, move the credential field above the Model field, and merge the Model free-text input + separate fetched-models dropdown into a single type-or-pick `<datalist>` control.

**Architecture:** Frontend-only edit to `frontend/src/pages/Settings.tsx` (reorder two existing field blocks; swap the post-fetch `<select>` for a `<datalist>` bound to the Model input) plus an assertion update in `frontend/src/pages/Settings.test.tsx`. No backend, hook, or type changes.

**Tech Stack:** React + TS, @tanstack/react-query, vitest + @testing-library/react.

**Conventions (Windows / PowerShell):**
- Frontend: `cd frontend; npx vitest run <file>`, `npx tsc --noEmit`, `npm run build` (use the PowerShell tool, not Bash).
- Conventional Commits, one per task. **Never** add a `Co-Authored-By: Claude` trailer.
- Work on branch `feat/settings-model-ux` (already created; the spec is committed there).

---

## File Structure

- **Modify** `frontend/src/pages/Settings.tsx` — reorder the credential block above Model; make the Model input a `<datalist>`-backed combo; remove the separate `<select>`.
- **Modify** `frontend/src/pages/Settings.test.tsx` — assert the datalist options instead of `<select>` options.

---

## Task 1: Reorder credential above Model + datalist combo

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/pages/Settings.test.tsx`

- [ ] **Step 1: Update the test to expect the datalist (failing first)**

In `frontend/src/pages/Settings.test.tsx`, the test currently clicks **Fetch models** and asserts
the fetched models render as `<select>` options via `getByRole('option', …)`. Replace those two
`option` assertions with a datalist-options check. The test body becomes:

```tsx
  it('fetches and renders the model dropdown', async () => {
    renderSettings();
    const btn = await screen.findByRole('button', { name: /fetch models/i });
    fireEvent.click(btn);
    await waitFor(() => expect(api.listModels).toHaveBeenCalledWith('anthropic'));
    await waitFor(() => {
      const opts = Array.from(document.querySelectorAll('#model-options option')).map((o) => o.getAttribute('value'));
      expect(opts).toEqual(['claude-a', 'claude-b']);
    });
  });
```

Leave the rest of the file (imports, the `vi.mock('../api/client', …)`, `SETTINGS`, `PROVIDERS`,
`beforeEach`, `renderSettings`) unchanged. If `waitFor` is not already imported from
`@testing-library/react` in this file, add it to that import.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend; npx vitest run src/pages/Settings.test.tsx`
Expected: FAIL — `#model-options` doesn't exist yet, so `opts` is `[]`, not `['claude-a','claude-b']`.

- [ ] **Step 3: Reorder + rework the fields in `Settings.tsx`**

In `frontend/src/pages/Settings.tsx`, replace the **Model field block followed by the credential
conditional** (the current Model `<div className="field">` through the end of the
`active === 'ollama' ? … : …` credential block — lines 72–103) with the block below. This puts the
**credential field first**, then the **Model field** using a `<datalist>` (and removes the old
separate `<select>`):

```tsx
      {active === 'ollama' ? (
        <div className="field">
          <label>Base URL</label>
          <input value={cfg.base_url} onChange={(e) => updateCfg({ base_url: e.target.value })} placeholder="http://localhost:11434" />
        </div>
      ) : (
        <div className="field">
          <label>API key (leave as **** to keep the saved key)</label>
          <input type="password" value={cfg.api_key} onChange={(e) => updateCfg({ api_key: e.target.value })} placeholder="paste API key" />
        </div>
      )}

      <div className="field">
        <label>Model</label>
        <div className="model-row">
          <input list="model-options" value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
          <button className="secondary" onClick={onFetchModels} disabled={save.isPending || listModels.isPending}>
            {listModels.isPending ? 'Fetching…' : 'Fetch models'}
          </button>
          {modelsMsg && (
            <span className={`note ${modelsMsg.ok ? 'muted' : 'error'}`}>
              {modelsMsg.ok ? `✓ ${modelsMsg.message}` : `✗ ${modelsMsg.message}`}
            </span>
          )}
        </div>
        <datalist id="model-options">
          {fetched.map((m) => <option key={m} value={m} />)}
        </datalist>
      </div>
```

Do not change the `onFetchModels` handler, the `models`/`fetched`/`modelsMsg` state, the Active
provider field above, or the Watchlist field below. (Net effect: credential now appears between
Active provider and Model; the Model field is a single datalist-backed input; the old
`{fetched.length > 0 && <select>…</select>}` block is gone.)

- [ ] **Step 4: Run the test + type check**

Run: `cd frontend; npx vitest run src/pages/Settings.test.tsx`
Expected: PASS (1 test).

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(settings): credential above Model + datalist model picker"
```

---

## Task 2: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Frontend type + tests + build**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

Run: `cd frontend; npx vitest run`
Expected: PASS (all suites, including `Settings.test.tsx`).

Run: `cd frontend; npm run build`
Expected: build succeeds.

- [ ] **Step 2: (Sanity) backend unaffected**

This change is frontend-only, but confirm nothing was disturbed:
Run: `cd backend; .venv\Scripts\python.exe -m pytest -q`
Expected: PASS (unchanged count).

- [ ] **Step 3: Finish the branch**

Use superpowers:finishing-a-development-branch to present completion options.

---

## Notes for the implementer

- **Datalist, not select:** `<datalist id="model-options">` with `<option value={m} />` (no text
  child). The Model `<input>` references it via `list="model-options"`. This is a native combo box
  — the user can type a custom model or pick a fetched one; it does not restrict the input value.
- **Why the test queries the DOM directly:** datalist `<option>`s are not exposed as ARIA listbox
  options, so `getByRole('option', …)` won't find them — query `#model-options option` and read
  each `value` attribute.
- **Order matters for the user's workflow:** the credential (API key / Base URL) must render
  *before* Model, because Fetch models needs the key (or base URL) — which the save-first handler
  persists before calling the endpoint.
- **No CSS change:** `.model-row` already exists; the datalist is unstyled/native.
