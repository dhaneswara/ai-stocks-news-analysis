from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Raised when a provider cannot be built or a completion fails."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...

    def list_models(self) -> list[str]: ...
