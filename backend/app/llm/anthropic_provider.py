from __future__ import annotations

from anthropic import Anthropic

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = Anthropic(api_key=cfg.api_key)

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self.client.messages.create(
                model=self.cfg.model,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Anthropic request failed: {exc}") from exc
