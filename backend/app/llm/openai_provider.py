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

    def complete(self, system: str, user: str, json_mode: bool = True) -> str:
        try:
            kwargs: dict = {
                "model": self.cfg.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if json_mode:  # the ReAct agent (free-text turns) passes json_mode=False
                kwargs["response_format"] = {"type": "json_object"}
            resp = self.client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{self.label} request failed: {exc}") from exc

    def list_models(self) -> list[str]:
        try:
            return sorted({m.id for m in self.client.models.list().data})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{self.label} model list failed: {exc}") from exc
