from __future__ import annotations

import os

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMError, LLMProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_provider import OpenAIProvider
from app.models.schemas import ProviderConfig, Settings

_REGISTRY = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}

_ENV_API_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def resolve_config(provider_id: str, cfg: ProviderConfig) -> ProviderConfig:
    """Return a copy of cfg with the API key / base URL filled from environment
    variables when not set in stored settings (fallback for headless use)."""
    resolved = cfg.model_copy()
    if not resolved.api_key and provider_id in _ENV_API_KEYS:
        resolved.api_key = os.environ.get(_ENV_API_KEYS[provider_id], "")
    if provider_id == "ollama" and not resolved.base_url:
        resolved.base_url = os.environ.get("OLLAMA_BASE_URL", "")
    return resolved


def build_provider(settings: Settings) -> LLMProvider:
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise LLMError(f"No configuration for provider '{provider_id}'")
    cls = _REGISTRY.get(provider_id)
    if cls is None:
        raise LLMError(f"Unknown provider '{provider_id}'")
    return cls(resolve_config(provider_id, cfg))
