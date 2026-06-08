from __future__ import annotations

import httpx

from app.llm.base import LLMError
from app.models.schemas import ProviderConfig


class OllamaProvider:
    name = "ollama"

    def __init__(self, cfg: ProviderConfig) -> None:
        self.cfg = cfg
        self.base_url = (cfg.base_url or "http://localhost:11434").rstrip("/")

    def complete(self, system: str, user: str, json_mode: bool = True,
                 stop: list[str] | None = None) -> str:
        try:
            body: dict = {
                "model": self.cfg.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
            }
            if json_mode:  # the ReAct agent (free-text turns) passes json_mode=False
                body["format"] = "json"
            if stop:       # halt before the model fabricates an Observation
                body["options"] = {"stop": stop}
            resp = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=120)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama request failed: {exc}") from exc

    def list_models(self) -> list[str]:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=30)
            resp.raise_for_status()
            return sorted({m["name"] for m in resp.json().get("models", [])})
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama model list failed: {exc}") from exc
