# DeepSeek LLM Provider — Design

- **Date:** 2026-06-07
- **Status:** Approved
- **Scope:** Add **DeepSeek** as a 5th selectable LLM provider. Backend (provider class +
  registry + schemas + a settings backfill + an error label) plus a one-line frontend type
  addition. The default active provider is unchanged (`anthropic`).

## Overview

Add **DeepSeek** alongside Anthropic / OpenAI / Gemini / Ollama as a provider the user can
select in **Settings → Active provider**. DeepSeek's API is OpenAI-compatible (Chat
Completions with a `response_format` JSON object), so it reuses the existing OpenAI client
pointed at DeepSeek's base URL. The default selected provider stays Anthropic; the user
switches to DeepSeek and supplies a key (in Settings, masked, or via `DEEPSEEK_API_KEY`).

## Locked decisions

| Decision | Choice |
|---|---|
| Roster vs default | **Selectable**; default `active_provider` stays `anthropic`. |
| Client | Reuse the OpenAI SDK via `DeepSeekProvider(OpenAIProvider)` with `base_url=https://api.deepseek.com`. |
| Default model | `deepseek-chat` (supports JSON output). `deepseek-reasoner` (R1) out of scope; the model field is user-editable. |
| Key handling | API key in Settings (masked) **or** `DEEPSEEK_API_KEY` env fallback — same pattern as the other key-based providers. |
| Legacy settings | A `Settings` model validator backfills any missing provider entry on load, so existing `data/app.db` settings gain a `deepseek` entry automatically. |
| Error label | `OpenAIProvider` gains a `label` class attribute; the subclass sets `"DeepSeek"` so failures read "DeepSeek request failed: …". |

## Current state (verified by reading the code)

- Each provider is a class in `backend/app/llm/<id>_provider.py`, registered in
  `factory.py` `_REGISTRY`; env-key fallback in `_ENV_API_KEYS`; `resolve_config` fills
  key/base_url from environment when blank.
- `OpenAIProvider.complete` calls Chat Completions with
  `response_format={"type": "json_object"}` and returns `choices[0].message.content`. Its
  constructor is `OpenAI(api_key=cfg.api_key)` — it does **not** currently pass a base URL.
- `schemas.py` holds `ProviderId` (a `Literal`), `DEFAULT_MODELS`, `DEFAULT_OLLAMA_BASE_URL`,
  `_default_providers()`, and `Settings` (with `providers: dict[str, ProviderConfig]`,
  `active_provider: ProviderId = "anthropic"`). Settings persist as a single JSON row;
  existing rows contain only the 4 current providers.
- `routes._PROVIDER_LABELS` (anthropic / openai / gemini / ollama) drives `GET /api/providers`,
  which the frontend Settings dropdown renders. `run_analysis` already raises
  `Missing API key for provider '<id>'` when a non-Ollama provider has no key.
- Frontend: `ProviderId` union in `types.ts`; `Settings.tsx` reads `form.providers[active]`
  and shows the **API-key** field unless `active === 'ollama'` (DeepSeek therefore gets the
  key field with no UI change). Dropdown options come from `/providers`.

## Design — changes per file

### Backend

1. **`backend/app/models/schemas.py`**
   - `ProviderId = Literal["anthropic", "openai", "gemini", "ollama", "deepseek"]`.
   - `DEFAULT_MODELS["deepseek"] = "deepseek-chat"`.
   - Add `DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"`.
   - `_default_providers()` adds:
     `"deepseek": ProviderConfig(model=DEFAULT_MODELS["deepseek"], base_url=DEFAULT_DEEPSEEK_BASE_URL)`.
   - Import `model_validator` and add an after-validator on `Settings` that backfills missing
     providers:
     ```python
     @model_validator(mode="after")
     def _ensure_all_providers(self) -> "Settings":
         for pid, cfg in _default_providers().items():
             self.providers.setdefault(pid, cfg)
         return self
     ```
     This self-heals legacy settings and is future-proof for any later provider.

2. **`backend/app/llm/openai_provider.py`** — add a `label = "OpenAI"` class attribute and
   use it in the error string (`f"{self.label} request failed: {exc}"`). Behaviour
   unchanged for OpenAI.

3. **`backend/app/llm/deepseek_provider.py`** (new):
   ```python
   from __future__ import annotations
   from openai import OpenAI
   from app.llm.openai_provider import OpenAIProvider
   from app.models.schemas import DEFAULT_DEEPSEEK_BASE_URL, ProviderConfig

   class DeepSeekProvider(OpenAIProvider):
       name = "deepseek"
       label = "DeepSeek"

       def __init__(self, cfg: ProviderConfig) -> None:
           self.cfg = cfg
           self.client = OpenAI(
               api_key=cfg.api_key,
               base_url=cfg.base_url or DEFAULT_DEEPSEEK_BASE_URL,
           )
   ```
   It inherits `complete()` (JSON Chat Completions) from `OpenAIProvider`.

4. **`backend/app/llm/factory.py`** — `_REGISTRY["deepseek"] = DeepSeekProvider`;
   `_ENV_API_KEYS["deepseek"] = "DEEPSEEK_API_KEY"`. (No `resolve_config` change needed: the
   base URL default lives in `_default_providers()` / the backfill.)

5. **`backend/app/api/routes.py`** — `_PROVIDER_LABELS["deepseek"] = "DeepSeek"` (after
   `ollama`) so DeepSeek appears in `GET /api/providers` and thus the dropdown.

### Frontend

6. **`frontend/src/types.ts`** — `ProviderId` add `'deepseek'`. No other change: the dropdown
   auto-populates from `/providers`, DeepSeek uses the existing API-key field, and existing
   `Settings` fixtures keep compiling (`providers` is a `Record<string, ProviderConfig>`, not
   a per-id map).

## Edge cases

- **Legacy settings** (no `deepseek`): the validator backfills on load → `GET /settings`
  returns a `deepseek` entry (empty key, `configured=false`) → dropdown shows it; selecting it
  shows the API-key field.
- **No key when selected:** the existing `run_analysis` check (`provider_id != "ollama" and
  not effective.api_key`) raises `Missing API key for provider 'deepseek'`.
- **base_url:** defaulted in config (and via env `OLLAMA_BASE_URL` logic is unrelated); the
  user isn't asked to enter it. A custom `cfg.base_url` still overrides if present.
- **Connection test:** `POST /api/providers/deepseek/test` works through `build_provider` +
  `complete` like the others.

## Error handling

- DeepSeek request failures surface as `LLMError("DeepSeek request failed: …")` (inherited
  `complete()` using the `label`), mapped to HTTP 502 by the analyze route as today.
- A blank key surfaces as the existing 502 `Missing API key…` message.

## Out of scope

- Changing the default provider (stays Anthropic, per the chosen scope).
- `deepseek-reasoner` (R1) tuning — default is `deepseek-chat`; any model name can be typed in
  Settings.
- A dedicated base-URL field in the UI for DeepSeek (the default endpoint is sufficient).

## Testing

**Backend (pytest), mostly in `backend/tests/test_providers.py`:**
- `test_deepseek_complete_returns_content` — monkeypatch `app.llm.deepseek_provider.OpenAI`
  with a fake client that records the `base_url` kwarg and returns a JSON message; assert the
  content is returned and the DeepSeek base URL was used.
- `test_factory_builds_deepseek` — `Settings(active_provider="deepseek")` →
  `isinstance(build_provider(s), DeepSeekProvider)` and `name == "deepseek"`.
- `test_factory_deepseek_env_key_fallback` — set `DEEPSEEK_API_KEY`, blank stored key,
  monkeypatch the client; `build_provider` fills the key from env.
- `test_settings_backfills_missing_providers` — construct a `Settings` whose `providers` lacks
  `deepseek` (e.g. via `model_validate` of a dict) → after validation, `deepseek` is present
  with the default model and base URL.
- `test_providers_endpoint_lists_deepseek` — `GET /api/providers` includes
  `{"id": "deepseek", "label": "DeepSeek", …}` (use `dependency_overrides` + tmp settings
  store, mirroring `test_api_provider_test.py`).

**Frontend:** type-only change — `npx tsc --noEmit`, `npx vitest run`, and `npm run build`
stay green (no fixture changes required).

**Gates:** `pytest -q`, `tsc --noEmit`, `vitest run`, `vite build` — all green.

## Files

- Modify: `backend/app/models/schemas.py`, `backend/app/llm/openai_provider.py`,
  `backend/app/llm/factory.py`, `backend/app/api/routes.py`, `frontend/src/types.ts`
- Add: `backend/app/llm/deepseek_provider.py`
- Tests: extend `backend/tests/test_providers.py` (+ a `/providers` listing test using a
  TestClient with `dependency_overrides`).
