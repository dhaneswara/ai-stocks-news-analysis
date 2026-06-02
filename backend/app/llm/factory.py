from __future__ import annotations

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMError, LLMProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_provider import OpenAIProvider
from app.models.schemas import Settings

_REGISTRY = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def build_provider(settings: Settings) -> LLMProvider:
    provider_id = settings.active_provider
    cfg = settings.providers.get(provider_id)
    if cfg is None:
        raise LLMError(f"No configuration for provider '{provider_id}'")
    cls = _REGISTRY.get(provider_id)
    if cls is None:
        raise LLMError(f"Unknown provider '{provider_id}'")
    return cls(cfg)
