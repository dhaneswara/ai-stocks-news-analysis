# Provider Model Listing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-provider **Fetch models** action that lists the provider's available models from its API and lets the user pick one from a dropdown in Settings.

**Architecture:** Each LLM provider class gains a `list_models() -> list[str]` method (DeepSeek inherits OpenAI's), exposed by a resilient `GET /api/providers/{id}/models` endpoint that mirrors the existing `/test` build pattern. The Settings Model field keeps its free-text input and adds a **Fetch models** button (save-first, like Test connection) plus a dropdown of the sorted/de-duped results held in per-provider session state.

**Tech Stack:** FastAPI + provider SDKs (`anthropic`, `openai`, `google-genai`, `httpx`/Ollama), pytest; React + TS frontend (@tanstack/react-query, vitest, tsc).

**Conventions (Windows / PowerShell):**
- Backend tests: `cd backend; .venv\Scripts\python.exe -m pytest -q` (use the PowerShell tool, not Bash — Bash mangles the `.venv\Scripts\python.exe` path).
- Frontend: `cd frontend; npx tsc --noEmit`, `npx vitest run`, `npm run build`.
- Conventional Commits, one per task. **Never** add a `Co-Authored-By: Claude` trailer.
- Work on branch `feat/provider-model-list` (already created; the spec is committed there).

---

## File Structure

- **Modify** `backend/app/llm/base.py` — add `list_models` to the `LLMProvider` Protocol.
- **Modify** `backend/app/llm/openai_provider.py` — `list_models` (DeepSeek inherits).
- **Modify** `backend/app/llm/anthropic_provider.py` — `list_models`.
- **Modify** `backend/app/llm/gemini_provider.py` — `list_models`.
- **Modify** `backend/app/llm/ollama_provider.py` — `list_models`.
- **Modify** `backend/app/api/routes.py` — `GET /providers/{id}/models` endpoint.
- **Modify** `frontend/src/api/client.ts` — `listModels`.
- **Modify** `frontend/src/hooks/queries.ts` — `useListModels`.
- **Modify** `frontend/src/pages/Settings.tsx` — Model field rework.
- **Create** `frontend/src/pages/Settings.test.tsx`.
- **Tests** — extend `backend/tests/test_providers.py` and `backend/tests/test_api_provider_test.py`.

---

## Task 1: `list_models` on every provider

**Files:**
- Modify: `backend/app/llm/base.py`, `backend/app/llm/openai_provider.py`, `backend/app/llm/anthropic_provider.py`, `backend/app/llm/gemini_provider.py`, `backend/app/llm/ollama_provider.py`
- Test: `backend/tests/test_providers.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_providers.py`:

```python
def test_openai_list_models_sorted_deduped(monkeypatch):
    from app.llm.openai_provider import OpenAIProvider

    class M:
        def __init__(self, id):
            self.id = id

    class Resp:
        data = [M("gpt-b"), M("gpt-a"), M("gpt-a")]

    class FakeModels:
        def list(self):
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.openai_provider.OpenAI", lambda api_key: FakeClient())
    provider = OpenAIProvider(ProviderConfig(model="x", api_key="k"))
    assert provider.list_models() == ["gpt-a", "gpt-b"]


def test_deepseek_list_models_inherits(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    class M:
        def __init__(self, id):
            self.id = id

    class Resp:
        data = [M("deepseek-reasoner"), M("deepseek-chat")]

    class FakeModels:
        def list(self):
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", lambda **kwargs: FakeClient())
    provider = DeepSeekProvider(ProviderConfig(model="deepseek-chat", api_key="k"))
    assert provider.list_models() == ["deepseek-chat", "deepseek-reasoner"]


def test_anthropic_list_models_sorted(monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    class M:
        def __init__(self, id):
            self.id = id

    class Resp:
        data = [M("claude-b"), M("claude-a")]

    class FakeModels:
        def list(self):
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.anthropic_provider.Anthropic", lambda api_key: FakeClient())
    provider = AnthropicProvider(ProviderConfig(model="x", api_key="k"))
    assert provider.list_models() == ["claude-a", "claude-b"]


def test_gemini_list_models_strips_prefix(monkeypatch):
    from app.llm.gemini_provider import GeminiProvider

    class M:
        def __init__(self, name):
            self.name = name

    class FakeModels:
        def list(self):
            return [M("models/gemini-2.0-flash"), M("models/gemini-1.5-pro")]

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.gemini_provider.genai.Client", lambda api_key: FakeClient())
    provider = GeminiProvider(ProviderConfig(model="x", api_key="k"))
    assert provider.list_models() == ["gemini-1.5-pro", "gemini-2.0-flash"]


def test_ollama_list_models(monkeypatch):
    from app.llm.ollama_provider import OllamaProvider

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "llama3.1:latest"}, {"name": "mistral:latest"}]}

    def fake_get(url, timeout):
        assert url.endswith("/api/tags")
        return FakeResp()

    monkeypatch.setattr("app.llm.ollama_provider.httpx.get", fake_get)
    provider = OllamaProvider(ProviderConfig(model="x", base_url="http://localhost:11434"))
    assert provider.list_models() == ["llama3.1:latest", "mistral:latest"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_providers.py -k list_models -q`
Expected: FAIL with `AttributeError: '<Provider>' object has no attribute 'list_models'`.

- [ ] **Step 3a: Add `list_models` to the Protocol**

In `backend/app/llm/base.py`, add the method to the `LLMProvider` Protocol so the class becomes:

```python
@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...

    def list_models(self) -> list[str]: ...
```

- [ ] **Step 3b: OpenAI (DeepSeek inherits)**

In `backend/app/llm/openai_provider.py`, add this method to `OpenAIProvider` (after `complete`):

```python
    def list_models(self) -> list[str]:
        try:
            return sorted({m.id for m in self.client.models.list().data})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{self.label} model list failed: {exc}") from exc
```

- [ ] **Step 3c: Anthropic**

In `backend/app/llm/anthropic_provider.py`, add to `AnthropicProvider` (after `complete`):

```python
    def list_models(self) -> list[str]:
        try:
            return sorted({m.id for m in self.client.models.list().data})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Anthropic model list failed: {exc}") from exc
```

- [ ] **Step 3d: Gemini**

In `backend/app/llm/gemini_provider.py`, add to `GeminiProvider` (after `complete`):

```python
    def list_models(self) -> list[str]:
        try:
            return sorted({m.name.split("/")[-1] for m in self.client.models.list()})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini model list failed: {exc}") from exc
```

- [ ] **Step 3e: Ollama**

In `backend/app/llm/ollama_provider.py`, add to `OllamaProvider` (after `complete`):

```python
    def list_models(self) -> list[str]:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=30)
            resp.raise_for_status()
            return sorted({m["name"] for m in resp.json().get("models", [])})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama model list failed: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_providers.py -q`
Expected: PASS (the 5 new list_models tests + all existing provider tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/base.py backend/app/llm/openai_provider.py backend/app/llm/anthropic_provider.py backend/app/llm/gemini_provider.py backend/app/llm/ollama_provider.py backend/tests/test_providers.py
git commit -m "feat(models): add list_models to every LLM provider"
```

---

## Task 2: `/providers/{id}/models` endpoint

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api_provider_test.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_provider_test.py`:

```python
def test_list_models_endpoint_ok(tmp_path, monkeypatch):
    class FakeProvider:
        name = "anthropic"

        def __init__(self, cfg):
            pass

        def list_models(self):
            return ["m-a", "m-b"]

    monkeypatch.setattr(routes, "build_provider", lambda s: FakeProvider(None))
    client, store = _client(tmp_path)
    s = store.load()
    s.providers["anthropic"].api_key = "k"
    store.save(s)

    resp = client.get("/api/providers/anthropic/models")
    assert resp.status_code == 200
    assert resp.json()["models"] == ["m-a", "m-b"]
    assert resp.json()["error"] == ""


def test_list_models_endpoint_reports_error(tmp_path, monkeypatch):
    from app.llm.base import LLMError

    def boom(_s):
        raise LLMError("no key")

    monkeypatch.setattr(routes, "build_provider", boom)
    client, store = _client(tmp_path)

    resp = client.get("/api/providers/anthropic/models")
    assert resp.status_code == 200
    assert resp.json()["models"] == []
    assert "no key" in resp.json()["error"]


def test_list_models_unknown_provider_404(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/providers/bogus/models")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_provider_test.py -k list_models -q`
Expected: FAIL (404 for all — the route doesn't exist yet).

- [ ] **Step 3: Add the endpoint**

In `backend/app/api/routes.py`, add this route immediately after the existing `test_provider`
function (the `@router.post("/providers/{provider_id}/test")` handler):

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_provider_test.py -q`
Expected: PASS (the 3 new endpoint tests + the existing provider-endpoint tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api_provider_test.py
git commit -m "feat(models): add GET /providers/{id}/models endpoint"
```

---

## Task 3: Frontend — client, hook, Settings UI

**Files:**
- Modify: `frontend/src/api/client.ts`, `frontend/src/hooks/queries.ts`, `frontend/src/pages/Settings.tsx`
- Test: `frontend/src/pages/Settings.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/Settings.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Settings from './Settings';
import type { ProviderInfo, Settings as SettingsT } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
    listProviders: vi.fn(),
    listModels: vi.fn(),
    testProvider: vi.fn(),
    testAlert: vi.fn(),
    getMood: vi.fn(),
  },
}));

import { api } from '../api/client';

const SETTINGS: SettingsT = {
  active_provider: 'anthropic',
  providers: { anthropic: { model: 'claude-x', api_key: 'k', base_url: '' } },
  watchlist: ['AAPL'],
  indicator_params: { sma_windows: [50, 200], rsi_length: 14 },
  alerts: { enabled: false, channel: 'log', telegram_bot_token: '', telegram_chat_id: '', rsi_low: 30, rsi_high: 70 },
  truth_signal: { enabled: false, source_url: '', lookback_hours: 48 },
  screener: { enabled: true, top_n: 25, default_sector: null, rsi_low: 30, rsi_high: 70, weights: {} },
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4 },
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
};

const PROVIDERS: ProviderInfo[] = [
  { id: 'anthropic', label: 'Anthropic (Claude)', configured: true, default_model: 'claude-x' },
];

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.saveSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.listProviders).mockResolvedValue(PROVIDERS);
  vi.mocked(api.listModels).mockResolvedValue({ models: ['claude-a', 'claude-b'], error: '' });
});

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Settings />
    </QueryClientProvider>,
  );
}

describe('Settings fetch models', () => {
  it('fetches and renders the model dropdown', async () => {
    renderSettings();
    const btn = await screen.findByRole('button', { name: /fetch models/i });
    fireEvent.click(btn);
    await waitFor(() => expect(api.listModels).toHaveBeenCalledWith('anthropic'));
    expect(await screen.findByRole('option', { name: 'claude-a' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'claude-b' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend; npx vitest run src/pages/Settings.test.tsx`
Expected: FAIL — no "Fetch models" button exists yet (and `api.listModels` is undefined).

- [ ] **Step 3a: Add the API client method**

In `frontend/src/api/client.ts`, add inside the `api` object (e.g. after `testProvider`):

```typescript
  listModels: (id: string) =>
    http<{ models: string[]; error: string }>(`/providers/${encodeURIComponent(id)}/models`),
```

- [ ] **Step 3b: Add the hook**

In `frontend/src/hooks/queries.ts`, append:

```typescript
export function useListModels() {
  return useMutation({ mutationFn: (id: string) => api.listModels(id) });
}
```

- [ ] **Step 3c: Rework the Settings Model field**

In `frontend/src/pages/Settings.tsx`:

Update the queries import (line 3) to include the new hook:

```typescript
import { useListModels, useProviders, useSaveSettings, useSettings } from '../hooks/queries';
```

Add state + the hook after `const [saved, setSaved] = useState(false);` (line 13):

```typescript
  const listModels = useListModels();
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [modelsMsg, setModelsMsg] = useState<TestResult | null>(null);
```

Add `fetched` right after `const cfg = form.providers[active];` (line 22):

```typescript
  const fetched = models[active] ?? [];
```

Add the handler near `onTest` (after the `onTest` function, ~line 34):

```typescript
  const onFetchModels = async () => {
    setModelsMsg(null);
    await save.mutateAsync(form);
    listModels.mutate(active, {
      onSuccess: (res) => {
        if (res.error) setModelsMsg({ ok: false, message: res.error });
        else {
          setModels((m) => ({ ...m, [active]: res.models }));
          setModelsMsg({ ok: true, message: `${res.models.length} models` });
        }
      },
      onError: (e) => setModelsMsg({ ok: false, message: (e as Error).message }),
    });
  };
```

Replace the existing Model field block (lines 54-57):

```tsx
      <div className="field">
        <label>Model</label>
        <input value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
      </div>
```

with:

```tsx
      <div className="field">
        <label>Model</label>
        <div className="row">
          <input value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
          <button className="secondary" onClick={onFetchModels} disabled={save.isPending || listModels.isPending}>
            {listModels.isPending ? 'Fetching…' : 'Fetch models'}
          </button>
          {modelsMsg && (
            <span className={`note ${modelsMsg.ok ? 'muted' : 'error'}`}>
              {modelsMsg.ok ? `✓ ${modelsMsg.message}` : `✗ ${modelsMsg.message}`}
            </span>
          )}
        </div>
        {fetched.length > 0 && (
          <select value={fetched.includes(cfg.model) ? cfg.model : ''} onChange={(e) => e.target.value && updateCfg({ model: e.target.value })}>
            <option value="">Choose a fetched model…</option>
            {fetched.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        )}
      </div>
```

- [ ] **Step 4: Run the test + type check**

Run: `cd frontend; npx vitest run src/pages/Settings.test.tsx`
Expected: PASS (1 test).

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/hooks/queries.ts frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(models): Fetch models button + dropdown in Settings"
```

---

## Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run: `cd backend; .venv\Scripts\python.exe -m pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 2: Frontend type + tests + build**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

Run: `cd frontend; npx vitest run`
Expected: PASS (all suites, including the new `Settings.test.tsx`).

Run: `cd frontend; npm run build`
Expected: build succeeds.

- [ ] **Step 3: Finish the branch**

Use superpowers:finishing-a-development-branch to present completion options.

---

## Notes for the implementer

- **DeepSeek gets `list_models` for free** by inheriting `OpenAIProvider` — do NOT add a method to `deepseek_provider.py`. The `test_deepseek_list_models_inherits` test monkeypatches `app.llm.deepseek_provider.OpenAI` (the subclass constructs the client there with `**kwargs`).
- **Monkeypatch targets** mirror the existing tests: OpenAI uses `OpenAI(api_key=...)` (patch `lambda api_key:`), DeepSeek uses `OpenAI(**kwargs)` (patch `lambda **kwargs:`), Anthropic `Anthropic(api_key=...)`, Gemini `genai.Client(api_key=...)`, Ollama `httpx.get`.
- **Endpoint resilience:** the route returns HTTP 200 with `{models: [], error}` on provider failure (so the UI shows the message inline) and only 404s for an unknown provider id — matching the spec and the resilient `/test` endpoint.
- **Save-first workflow:** `onFetchModels` calls `await save.mutateAsync(form)` before listing, so a freshly-typed key / base URL is persisted and used by the backend (identical to `onTest`).
- **Dropdown value:** bound to `cfg.model` only when that model is in the fetched list, else empty (placeholder) — so picking an option updates the free-text Model field, which stays the source of truth.
- `TestResult` is already imported in `Settings.tsx`; `useState` is already imported. No other new imports beyond `useListModels`.
