from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterator, Literal, Optional

from pydantic import BaseModel

from app.analysis.agent import (
    AgentStep, _ACTION_RE, _FINAL_RE, _THOUGHT_RE, _extract_args, render_tool_catalog,
)
from app.chat.tools import TOOLS, ChatContext, ChatTool
from app.llm.base import LLMProvider

DEFAULT_MAX_STEPS = 10
MAX_TOOL_CALLS = 12
_MAX_OBS_CHARS = 1500
_REACT_STOP = ["\nObservation:"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatEvent(BaseModel):
    type: Literal["step", "final", "error"]
    step: Optional[AgentStep] = None
    answer: str = ""       # markdown, on `final`
    message: str = ""      # on `error`


_CHAT_SYSTEM = (
    "You are MarketCortex's stock-analysis assistant. You help the user analyze stocks using the "
    "app's own data — prices, fundamentals, technicals, news, the geopolitics (Truth-Social) "
    "signal, the company ontology graph and network signal, the deterministic opportunity score, "
    "the portfolio board, and the model's own evaluation track record. Be concrete and cite the "
    "evidence you gathered. A question may span multiple companies. You are not a financial "
    "adviser; add a one-line caveat when you give a buy/sell view."
)


def build_chat_system(tools: list[ChatTool]) -> str:
    return (
        _CHAT_SYSTEM
        + "\n\nYou work step by step using TOOLS to gather evidence. On each turn reply with "
        "EXACTLY one of:\n"
        "  Thought: <your reasoning>\n  Action: <tool_name>({<json args>})\n"
        "OR, once you have enough evidence:\n"
        "  Thought: <final reasoning>\n  Final Answer: <your answer to the user, in Markdown>\n\n"
        "Rules: at most one Action per turn; after each Action you receive an Observation; never "
        "invent Observations; only call a tool if it could change your answer; answer as soon as "
        "you have enough.\n\n"
        "TOOLS:\n" + render_tool_catalog(tools)
    )


@dataclass
class ParsedChatStep:
    thought: str
    action: Optional[str]
    action_args: dict
    final_text: Optional[str]   # the markdown Final Answer, or None


def parse_chat_step(text: str) -> ParsedChatStep:
    """Tolerant ReAct parser whose Final Answer is free markdown text (not JSON). Reuses the
    single-ticker agent's Thought/Action regexes and JSON-arg extractor for consistency."""
    thought_m = _THOUGHT_RE.search(text)
    thought = thought_m.group(1).strip() if thought_m else ""

    final_m = _FINAL_RE.search(text)
    if final_m and final_m.group(1).strip():
        return ParsedChatStep(thought, None, {}, final_m.group(1).strip())

    action_m = _ACTION_RE.search(text)
    if action_m:
        if not thought:
            thought = text[: action_m.start()].strip()[:600]
        return ParsedChatStep(thought, action_m.group(1),
                              _extract_args(text[action_m.end():]), None)

    return ParsedChatStep(thought, None, {}, None)
