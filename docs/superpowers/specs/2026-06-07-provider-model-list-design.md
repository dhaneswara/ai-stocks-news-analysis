# Provider Model Listing — Design

- **Date:** 2026-06-07
- **Status:** Approved
- **Scope:** Add a per-provider **Fetch models** action that queries the provider's API for
  its available models and surfaces them as a dropdown in Settings. Backend (a `list_models`
  method on every provider + one endpoint) and frontend (client + hook + Settings UI). All 5
  providers.

## Overview

In **Settings**, next to the Model field, a **Fetch models** button queries the active
provider's API for its model list and shows the results in a dropdown the user can pick from.
The Model field stays free-text (any name can still be typed). The button mirrors the existing
**Test connection** workflow: it saves the form first (so the just-entered key / base URL is
persisted), then calls the endpoint, and shows an inline ✓/✗ status.

## Locked decisions

| Decision | Choice |
|---|---|
| Scope | All 5 providers (anthropic, openai, gemini, ollama, deepseek). |
| List content | **Full raw list, sorted + de-duped.** No filtering. |
| Provider calls | OpenAI/DeepSeek & Anthropic: `client.models.list().data[].id`; Gemini: `client.models.list()` → `.name` with the `models/` prefix stripped; Ollama: `GET {base_url}/api/tags` model names. |
| Endpoint | `GET /api/providers/{id}/models` → `{ "models": [...], "error": "" }` on success; `{ "models": [], "error": "<msg>" }` on failure (HTTP 200, resilient like `/test`). |
| UI | Keep the free-text Model input; add a **Fetch models** secondary button + a `<select>` that fills the input on choose. Fetched lists kept per-provider in session (component) state. |
| Workflow | Fetch `await save.mutateAsync(form)` first, then calls the endpoint; inline `✓ N models` / `✗ <error>`. |
| Persistence | Session-only (component state); not written to settings. |

## Current state (verified by reading the code)

- Providers live in `backend/app/llm/<id>_provider.py`. The `LLMProvider` Protocol
  (`backend/app/llm/base.py`) currently declares only `name` + `complete(system, user)`.
  `factory.build_provider(settings)` constructs the class for `settings.active_provider`.
  `DeepSeekProvider` subclasses `OpenAIProvider`.
- SDK calls available (pyproject): `anthropic>=0.39` (`client.models.list()`),
  `openai>=1.40` (`client.models.list()`), `google-genai>=0.3` (`client.models.list()`),
  `httpx` (Ollama `GET /api/tags`).
- `routes.py`: `POST /api/providers/{provider_id}/test` sets `settings.active_provider =
  provider_id` then `build_provider(settings)` and returns `{ok, message}` (it catches all
  exceptions and reports them). `GET /api/providers` lists from `_PROVIDER_LABELS`.
- Frontend: `Settings.tsx` Model field is a plain text input; `onTest` does
  `await save.mutateAsync(form)` then `api.testProvider(active)` and shows an inline note.
  `api.testProvider` + `useProviders` already exist. `http<T>` throws on non-OK responses.

## Design — changes per file

### Backend

1. **`backend/app/llm/base.py`** — add to the `LLMProvider` Protocol:
   ```python
   def list_models(self) -> list[str]: ...
   ```

2. **`backend/app/llm/openai_provider.py`** — add (DeepSeek inherits it):
   ```python
   def list_models(self) -> list[str]:
       try:
           return sorted({m.id for m in self.client.models.list().data})
       except Exception as exc:  # noqa: BLE001
           raise LLMError(f"{self.label} model list failed: {exc}") from exc
   ```

3. **`backend/app/llm/anthropic_provider.py`** — add:
   ```python
   def list_models(self) -> list[str]:
       try:
           return sorted({m.id for m in self.client.models.list().data})
       except Exception as exc:  # noqa: BLE001
           raise LLMError(f"Anthropic model list failed: {exc}") from exc
   ```

4. **`backend/app/llm/gemini_provider.py`** — add (strip the `models/` prefix):
   ```python
   def list_models(self) -> list[str]:
       try:
           return sorted({m.name.split("/")[-1] for m in self.client.models.list()})
       except Exception as exc:  # noqa: BLE001
           raise LLMError(f"Gemini model list failed: {exc}") from exc
   ```

5. **`backend/app/llm/ollama_provider.py`** — add (local tags):
   ```python
   def list_models(self) -> list[str]:
       try:
           resp = httpx.get(f"{self.base_url}/api/tags", timeout=30)
           resp.raise_for_status()
           return sorted({m["name"] for m in resp.json().get("models", [])})
       except Exception as exc:  # noqa: BLE001
           raise LLMError(f"Ollama model list failed: {exc}") from exc
   ```

6. **`backend/app/api/routes.py`** — new endpoint (mirrors the `/test` build pattern):
   ```python
   @router.get("/providers/{provider_id}/models")
   def list_provider_models(
       provider_id: str, store: SettingsStore = Depends(get_settings_store)
   ) -> dict:
       settings = store.load()
       if provider_id not in settings.providers:
           raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
       settings.active_provider = provider_id  # type: ignore[assignment]
       try:
           return {"models": build_provider(settings).list_models(), "error": ""}
       except Exception as exc:  # noqa: BLE001
           return {"models": [], "error": str(exc)}
   ```

### Frontend

7. **`frontend/src/api/client.ts`** — add:
   ```typescript
   listModels: (id: string) =>
     http<{ models: string[]; error: string }>(`/providers/${encodeURIComponent(id)}/models`),
   ```

8. **`frontend/src/hooks/queries.ts`** — add:
   ```typescript
   export function useListModels() {
     return useMutation({ mutationFn: (id: string) => api.listModels(id) });
   }
   ```

9. **`frontend/src/pages/Settings.tsx`** — rework the Model field:
   - State: `const [models, setModels] = useState<Record<string, string[]>>({})` and
     `const [modelsMsg, setModelsMsg] = useState<TestResult | null>(null)`; `const listModels =
     useListModels();`.
   - `const fetched = models[active] ?? [];`
   - Handler:
     ```tsx
     const onFetchModels = async () => {
       setModelsMsg(null);
       await save.mutateAsync(form);
       const res = await api.listModels(active);
       if (res.error) setModelsMsg({ ok: false, message: res.error });
       else { setModels((m) => ({ ...m, [active]: res.models })); setModelsMsg({ ok: true, message: `${res.models.length} models` }); }
     };
     ```
     (Implementation may use the `useListModels` mutation instead of `api.listModels` directly,
     matching how `onTest` is written; either is acceptable as long as the form is saved first.)
   - Render (the "Model" field block):
     ```tsx
     <div className="field">
       <label>Model</label>
       <div className="row">
         <input value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
         <button className="secondary" onClick={onFetchModels} disabled={save.isPending || listModels.isPending}>
           {listModels.isPending ? 'Fetching…' : 'Fetch models'}
         </button>
         {modelsMsg && <span className={`note ${modelsMsg.ok ? 'muted' : 'error'}`}>{modelsMsg.ok ? `✓ ${modelsMsg.message}` : `✗ ${modelsMsg.message}`}</span>}
       </div>
       {fetched.length > 0 && (
         <select value={fetched.includes(cfg.model) ? cfg.model : ''} onChange={(e) => e.target.value && updateCfg({ model: e.target.value })}>
           <option value="">Choose a fetched model…</option>
           {fetched.map((m) => <option key={m} value={m}>{m}</option>)}
         </select>
       )}
     </div>
     ```

## UI layout (Settings → Model field)

```
Model
[ deepseek-chat ............ ]  [ Fetch models ]   ✓ 2 models
[ Choose a fetched model…              ▼ ]   ← only after a successful fetch
```

- **Fetch models** is a `secondary` button beside the input; status note inline.
- The `<select>` appears only when `fetched.length > 0`; its value reflects the current model
  when that model is in the fetched list.

## Edge cases / error handling

- **No key** (cloud providers) → the provider's list call raises → endpoint returns
  `{models: [], error}` → inline `✗ <error>`; the field stays free-text.
- **0 models returned** → `✓ 0 models`, no dropdown shown.
- **Unknown provider id** → 404.
- **Switching active provider** shows that provider's fetched list (or none yet) — state is keyed by provider id.
- Ollama uses the saved `base_url` (no key); the save-first step persists it before the call.

## Testing

**Backend** — in `backend/tests/test_providers.py` (unit) and `backend/tests/test_api_provider_test.py` (endpoint):
- `list_models` per provider, monkeypatching the SDK client / `httpx.get`, asserting the
  result is **sorted + de-duped**:
  - OpenAI: fake `client.models.list().data` = objects with `.id` `"b"`, `"a"`, `"a"` → `["a", "b"]`.
  - DeepSeek: a quick test that `DeepSeekProvider.list_models()` works through a monkeypatched client (it inherits the OpenAI method).
  - Anthropic: fake `client.models.list().data` → sorted ids.
  - Gemini: fake `client.models.list()` = objects with `.name` `"models/g2"`, `"models/g1"` → `["g1", "g2"]`.
  - Ollama: monkeypatch `app.llm.ollama_provider.httpx.get` → `{"models": [{"name": "b"}, {"name": "a"}]}` → `["a", "b"]`.
- Endpoint: `GET /api/providers/{id}/models` success (monkeypatch `routes.build_provider` to a
  fake whose `list_models` returns a list) → `{"models": [...], "error": ""}`; error path
  (fake `list_models` raises) → `{"models": [], "error": "<msg>"}`; unknown id → 404.

**Frontend** — new `frontend/src/pages/Settings.test.tsx`:
- Mock `../api/client` (getSettings, saveSettings, listProviders, listModels, plus the
  handlers Settings can call: testProvider, testAlert, getMood). Render `<Settings />` in a
  `QueryClientProvider`. Click **Fetch models** → assert `api.listModels` was called with the
  active provider id and that the returned model options render in the dropdown.
- `tsc --noEmit`, `vitest run`, and `vite build` stay green.

**Gates:** `pytest -q`, `tsc --noEmit`, `vitest run`, `vite build` — all green.

## Out of scope

- Persisting fetched lists to disk (session-only).
- Auto-fetching on page load (explicit button; each fetch is a real API call).
- Filtering the lists (the full raw, sorted list was chosen).
- A separate models cache on the backend (the call is user-triggered and infrequent).

## Files

- Modify: `backend/app/llm/base.py`, `backend/app/llm/openai_provider.py`,
  `backend/app/llm/anthropic_provider.py`, `backend/app/llm/gemini_provider.py`,
  `backend/app/llm/ollama_provider.py`, `backend/app/api/routes.py`,
  `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`,
  `frontend/src/pages/Settings.tsx`
- Add: `frontend/src/pages/Settings.test.tsx`
- Tests: extend `backend/tests/test_providers.py` and `backend/tests/test_api_provider_test.py`
