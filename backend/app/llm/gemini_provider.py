from __future__ import annotations

from google import genai
from google.genai import types

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class GeminiProvider:
    name = "gemini"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.client = genai.Client(api_key=cfg.api_key)

    def complete(self, system: str, user: str, json_mode: bool = True,
                 stop: list[str] | None = None) -> str:
        try:
            cfg_kwargs: dict = {"system_instruction": system}
            if json_mode:  # the ReAct agent (free-text turns) passes json_mode=False
                cfg_kwargs["response_mime_type"] = "application/json"
            if stop:       # halt before the model fabricates an Observation
                cfg_kwargs["stop_sequences"] = stop
            resp = self.client.models.generate_content(
                model=self.cfg.model,
                contents=user,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
            return resp.text or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini request failed: {exc}") from exc

    def list_models(self) -> list[str]:
        try:
            return sorted({m.name.split("/")[-1] for m in self.client.models.list()})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini model list failed: {exc}") from exc
