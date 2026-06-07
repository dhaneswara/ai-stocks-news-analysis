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
