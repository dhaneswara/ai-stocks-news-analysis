from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Raised when a provider cannot be built or a completion fails."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    # json_mode=True constrains providers that support it to emit a JSON object (the single-shot
    # analyzer path). The ReAct agent passes json_mode=False because it needs free-text
    # Thought/Action turns — a JSON-only constraint makes the text protocol impossible.
    def complete(self, system: str, user: str, json_mode: bool = True) -> str: ...

    def list_models(self) -> list[str]: ...
