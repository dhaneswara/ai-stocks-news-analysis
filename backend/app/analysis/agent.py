from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from app.analysis.analyzer import extract_json
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


_THOUGHT_RE = re.compile(r"Thought:\s*(.*?)(?=\n(?:Action:|Final Answer:)|\Z)", re.S)
_ACTION_RE = re.compile(r"Action:\s*([A-Za-z_]\w*)\s*\((.*)\)\s*\Z", re.S)
_FINAL_RE = re.compile(r"Final Answer:\s*(.*)\Z", re.S)


@dataclass
class ParsedStep:
    thought: str
    action: Optional[str]          # tool name, or None
    action_args: dict
    final_json: Optional[dict]     # parsed Final Answer JSON, or None


def parse_step(text: str) -> ParsedStep:
    thought_m = _THOUGHT_RE.search(text)
    thought = thought_m.group(1).strip() if thought_m else ""

    final_m = _FINAL_RE.search(text)
    if final_m:
        try:
            return ParsedStep(thought, None, {}, extract_json(final_m.group(1)))
        except (json.JSONDecodeError, ValueError):
            return ParsedStep(thought, None, {}, None)

    action_m = _ACTION_RE.search(text)
    if action_m:
        raw_args = action_m.group(2).strip()
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return ParsedStep(thought, action_m.group(1), args, None)

    return ParsedStep(thought, None, {}, None)
