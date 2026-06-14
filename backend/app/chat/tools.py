from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from app.config.cache import Cache
from app.evaluation.store import PredictionStore
from app.llm.base import LLMProvider
from app.models.schemas import Settings


@dataclass
class ChatContext:
    """Dependencies the chat tools resolve data through, built once before the loop."""
    settings: Settings
    cache: Cache
    provider: LLMProvider
    prediction_store: Optional[PredictionStore] = None


@dataclass
class ChatTool:
    name: str
    description: str          # LLM-facing routing text, rendered into the system prompt
    args_spec: str            # short JSON-ish arg description for the catalog
    run: Callable[[dict, "ChatContext"], str]


def _int_arg(args: dict, key: str, default: int) -> int:
    """Parse an int tool-arg defensively — the LLM may emit a string or a non-number."""
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError):
        return default


def _model(ctx: ChatContext) -> str:
    return ctx.settings.providers[ctx.settings.active_provider].model


TOOLS: list[ChatTool] = []
TOOL_BY_NAME: dict[str, ChatTool] = {}
