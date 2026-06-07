# DeepSeek LLM Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add **DeepSeek** as a 5th selectable LLM provider (default selection stays Anthropic), reusing the OpenAI-compatible client path.

**Architecture:** DeepSeek's API is OpenAI-compatible, so a small `DeepSeekProvider(OpenAIProvider)` points the OpenAI SDK at `https://api.deepseek.com` and inherits the JSON `complete()`. It is registered in the provider factory, added to the schema's `ProviderId`/defaults, and a `Settings` validator backfills the new provider into already-saved settings. The frontend needs only a one-word type addition (the dropdown is data-driven from `/api/providers`).

**Tech Stack:** FastAPI + Pydantic v2 (raw sqlite settings), `openai` Python SDK, pytest; React + TS frontend (vitest, tsc).

**Conventions (Windows / PowerShell):**
- Backend tests: `cd backend; .venv\Scripts\python.exe -m pytest -q` (use the PowerShell tool, not Bash — Bash mangles the `.venv\Scripts\python.exe` path).
- Frontend: `cd frontend; npx tsc --noEmit`, `npx vitest run`, `npm run build`.
- Conventional Commits, one per task. **Never** add a `Co-Authored-By: Claude` trailer.
- Work on branch `feat/deepseek-provider` (already created; the spec is committed there).

---

## File Structure

- **Modify** `backend/app/models/schemas.py` — `ProviderId`, `DEFAULT_MODELS`, new `DEFAULT_DEEPSEEK_BASE_URL`, `_default_providers()`, and a `Settings` backfill validator.
- **Modify** `backend/app/llm/openai_provider.py` — add a `label` class attribute used in the error message.
- **Create** `backend/app/llm/deepseek_provider.py` — `DeepSeekProvider(OpenAIProvider)`.
- **Modify** `backend/app/llm/factory.py` — register the class + `DEEPSEEK_API_KEY` env fallback.
- **Modify** `backend/app/api/routes.py` — add the `deepseek` label to `_PROVIDER_LABELS`.
- **Modify** `frontend/src/types.ts` — add `'deepseek'` to the `ProviderId` union.
- **Tests** — extend `backend/tests/test_providers.py` and `backend/tests/test_api_provider_test.py`.

---

## Task 1: Schemas + Settings provider backfill

**Files:**
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/test_providers.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_providers.py`:

```python
def test_deepseek_defaults_present():
    from app.models.schemas import DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_MODELS

    assert DEFAULT_MODELS["deepseek"] == "deepseek-chat"
    assert DEFAULT_DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    s = Settings()  # default settings include a deepseek entry
    assert s.providers["deepseek"].model == "deepseek-chat"
    assert s.providers["deepseek"].base_url == "https://api.deepseek.com"


def test_settings_backfills_missing_providers():
    # Legacy settings that predate deepseek (only anthropic stored).
    s = Settings.model_validate({"providers": {"anthropic": {"model": "claude-x"}}})
    assert s.providers["anthropic"].model == "claude-x"   # existing entry preserved
    assert "deepseek" in s.providers                       # backfilled
    assert s.providers["deepseek"].model == "deepseek-chat"
    assert s.providers["deepseek"].base_url == "https://api.deepseek.com"
    # other known providers are also backfilled
    assert {"openai", "gemini", "ollama"} <= set(s.providers)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_providers.py -k "deepseek_defaults or backfills" -q`
Expected: FAIL with `KeyError: 'deepseek'` / `AttributeError` (no `DEFAULT_DEEPSEEK_BASE_URL`).

- [ ] **Step 3: Edit `backend/app/models/schemas.py`**

Change the pydantic import (line 5) from:

```python
from pydantic import BaseModel, Field
```

to:

```python
from pydantic import BaseModel, Field, model_validator
```

Change `ProviderId` (line 7) from:

```python
ProviderId = Literal["anthropic", "openai", "gemini", "ollama"]
```

to:

```python
ProviderId = Literal["anthropic", "openai", "gemini", "ollama", "deepseek"]
```

In `DEFAULT_MODELS` (lines 9-14), add the deepseek entry:

```python
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "ollama": "llama3.1",
    "deepseek": "deepseek-chat",
}
```

Immediately after `DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"` (line 15), add:

```python
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
```

In `_default_providers()` (lines 278-286), add a deepseek entry to the returned dict (after the `ollama` entry, before the closing `}`):

```python
        "deepseek": ProviderConfig(
            model=DEFAULT_MODELS["deepseek"], base_url=DEFAULT_DEEPSEEK_BASE_URL
        ),
```

In the `Settings` class, add this validator as the **last** member of the class (after the `evaluation` field):

```python
    @model_validator(mode="after")
    def _ensure_all_providers(self) -> "Settings":
        for pid, cfg in _default_providers().items():
            self.providers.setdefault(pid, cfg)
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_providers.py -q`
Expected: PASS (the two new tests + all existing provider tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/tests/test_providers.py
git commit -m "feat(deepseek): add provider id, defaults, and settings backfill"
```

---

## Task 2: DeepSeekProvider + factory registration

**Files:**
- Modify: `backend/app/llm/openai_provider.py`
- Create: `backend/app/llm/deepseek_provider.py`
- Modify: `backend/app/llm/factory.py`
- Test: `backend/tests/test_providers.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_providers.py`:

```python
def test_deepseek_complete_uses_base_url_and_returns_content(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    captured = {}

    class Msg:
        content = '{"ok": true}'

    class Choice:
        message = Msg()

    class Resp:
        choices = [Choice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["model"] == "deepseek-chat"
            assert kwargs["response_format"] == {"type": "json_object"}
            return Resp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", fake_openai)
    provider = DeepSeekProvider(
        ProviderConfig(model="deepseek-chat", api_key="k", base_url="https://api.deepseek.com")
    )
    assert provider.complete("sys", "user") == '{"ok": true}'
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["api_key"] == "k"
    assert provider.name == "deepseek"


def test_factory_builds_deepseek(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", lambda **kwargs: object())
    s = Settings()
    s.active_provider = "deepseek"
    s.providers["deepseek"].api_key = "k"
    provider = build_provider(s)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.name == "deepseek"


def test_factory_deepseek_env_key_fallback(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")
    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", lambda **kwargs: object())
    s = Settings()
    s.active_provider = "deepseek"
    s.providers["deepseek"].api_key = ""  # not set in stored settings
    provider = build_provider(s)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.cfg.api_key == "env-secret"  # filled from environment
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_providers.py -k deepseek -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.llm.deepseek_provider'`.

- [ ] **Step 3a: Add a `label` to `OpenAIProvider`**

In `backend/app/llm/openai_provider.py`, add a `label` class attribute under `name` and use it in the error string. The class becomes:

```python
from __future__ import annotations

from openai import OpenAI

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class OpenAIProvider:
    name = "openai"
    label = "OpenAI"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = OpenAI(api_key=cfg.api_key)

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{self.label} request failed: {exc}") from exc
```

- [ ] **Step 3b: Create `backend/app/llm/deepseek_provider.py`**

```python
from __future__ import annotations

from openai import OpenAI

from app.llm.openai_provider import OpenAIProvider
from app.models.schemas import DEFAULT_DEEPSEEK_BASE_URL, ProviderConfig


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek is OpenAI-API-compatible — reuse OpenAIProvider.complete() with DeepSeek's base URL."""

    name = "deepseek"
    label = "DeepSeek"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url or DEFAULT_DEEPSEEK_BASE_URL,
        )
```

- [ ] **Step 3c: Register it in `backend/app/llm/factory.py`**

Add the import (after the other provider imports, e.g. after the `from app.llm.base import ...` / provider imports block):

```python
from app.llm.deepseek_provider import DeepSeekProvider
```

Add to `_REGISTRY` (after the `"ollama"` entry):

```python
    "deepseek": DeepSeekProvider,
```

Add to `_ENV_API_KEYS` (after the `"gemini"` entry):

```python
    "deepseek": "DEEPSEEK_API_KEY",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_providers.py -q`
Expected: PASS (all provider tests, including the three new deepseek ones and the unchanged OpenAI test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/openai_provider.py backend/app/llm/deepseek_provider.py backend/app/llm/factory.py backend/tests/test_providers.py
git commit -m "feat(deepseek): add DeepSeekProvider and register it in the factory"
```

---

## Task 3: Provider label + frontend type

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `frontend/src/types.ts`
- Test: `backend/tests/test_api_provider_test.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api_provider_test.py`:

```python
def test_providers_lists_deepseek(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    by_id = {p["id"]: p for p in resp.json()}
    assert "deepseek" in by_id
    assert by_id["deepseek"]["label"] == "DeepSeek"
    assert by_id["deepseek"]["default_model"] == "deepseek-chat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_provider_test.py::test_providers_lists_deepseek -q`
Expected: FAIL (`KeyError: 'deepseek'` — `_PROVIDER_LABELS` has no deepseek yet, so it isn't listed).

- [ ] **Step 3a: Add the label in `backend/app/api/routes.py`**

In the `_PROVIDER_LABELS` dict (currently anthropic / openai / gemini / ollama), add a deepseek entry after `"ollama"`:

```python
_PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "ollama": "Ollama (local)",
    "deepseek": "DeepSeek",
}
```

- [ ] **Step 3b: Add the frontend type in `frontend/src/types.ts`**

Change the `ProviderId` union from:

```typescript
export type ProviderId = 'anthropic' | 'openai' | 'gemini' | 'ollama';
```

to:

```typescript
export type ProviderId = 'anthropic' | 'openai' | 'gemini' | 'ollama' | 'deepseek';
```

- [ ] **Step 4: Run the test + frontend type check**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_api_provider_test.py -q`
Expected: PASS (the new listing test + the existing two).

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py frontend/src/types.ts backend/tests/test_api_provider_test.py
git commit -m "feat(deepseek): list DeepSeek in /providers and the frontend type"
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
Expected: PASS (all suites — no fixture changes were needed because `Settings.providers` is a `Record`).

Run: `cd frontend; npm run build`
Expected: build succeeds.

- [ ] **Step 3: Finish the branch**

Use superpowers:finishing-a-development-branch to present completion options.

---

## Notes for the implementer

- **Why the backfill validator matters:** existing settings in `data/app.db` were saved before
  DeepSeek existed, so their `providers` dict has no `deepseek` key. Without the
  `_ensure_all_providers` validator, `GET /settings` would return settings lacking `deepseek`,
  and the frontend Settings page (`form.providers[active]`) would read `undefined` and crash
  when the user selects DeepSeek. The validator runs on every `Settings` load
  (`SettingsStore.load` → `Settings.model_validate_json`), self-healing old rows.
- **No `resolve_config` change:** the DeepSeek base URL default lives in `_default_providers()`
  (and is backfilled into legacy settings), so the provider always has a base URL. The OpenAI
  env-key fallback path is reused by adding `deepseek` to `_ENV_API_KEYS`.
- **No frontend UI change:** the Settings dropdown is rendered from `GET /api/providers`, and
  DeepSeek uses the existing API-key field because `active !== 'ollama'`.
- **DeepSeek model:** default `deepseek-chat` (supports `response_format` JSON). The user can
  type `deepseek-reasoner` or any other model in the Settings Model field.
