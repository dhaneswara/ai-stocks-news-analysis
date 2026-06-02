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

    def complete(self, system: str, user: str) -> str:
        try:
            resp = self.client.models.generate_content(
                model=self.cfg.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                ),
            )
            return resp.text or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini request failed: {exc}") from exc
