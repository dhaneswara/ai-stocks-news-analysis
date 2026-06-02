from __future__ import annotations

import httpx

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class OllamaProvider:
    name = "ollama"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.base_url = (cfg.base_url or "http://localhost:11434").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.cfg.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": "json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama request failed: {exc}") from exc
