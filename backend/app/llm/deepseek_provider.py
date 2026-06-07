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
