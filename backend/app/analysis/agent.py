from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from app.config.cache import Cache
from app.models.schemas import AnalysisResult, Settings, StockData


@dataclass
class ToolContext:
    """Everything the tools need, gathered once before the loop starts."""
    stock: StockData
    settings: Settings
    cache: Cache


@dataclass
class Tool:
    name: str
    description: str
    args_spec: str  # short JSON-ish description of args, shown in the prompt catalog
    run: Callable[[dict, "ToolContext"], str]


class AgentStep(BaseModel):
    index: int
    thought: str = ""
    action: Optional[str] = None          # tool name, or None for a final/empty step
    action_args: dict = Field(default_factory=dict)
    observation: Optional[str] = None
    is_final: bool = False
    elapsed_ms: int = 0


class AgentTrace(BaseModel):
    ticker: str
    provider: str
    model: str
    started_at: str
    elapsed_ms: int = 0
    stopped_reason: Literal["final", "max_steps", "parse_error", "no_action"] = "final"
    fell_back: bool = False                # True when the single-shot fallback produced `final`
    steps: list[AgentStep] = Field(default_factory=list)
    final: Optional[AnalysisResult] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
