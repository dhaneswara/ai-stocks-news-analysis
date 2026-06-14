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


def _render_history(messages: list[ChatMessage]) -> str:
    return "\n".join(
        f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in messages)


def _initial_transcript(messages: list[ChatMessage]) -> str:
    return (
        "Conversation so far (the last User message is the question to answer now):\n"
        f"{_render_history(messages)}\n\n"
        "Work step by step. Begin with your first Thought."
    )


class ChatAgent:
    def __init__(self, tools: Optional[list[ChatTool]] = None,
                 max_steps: int = DEFAULT_MAX_STEPS) -> None:
        self.tools = tools if tools is not None else TOOLS
        self.tool_by_name = {t.name: t for t in self.tools}
        self.max_steps = max_steps

    def stream(self, provider: LLMProvider, model: str, provider_name: str,
               messages: list[ChatMessage], ctx: ChatContext) -> Iterator[ChatEvent]:
        """Yields a `step` ChatEvent per completed step, then a terminal `final` carrying the
        markdown answer. An LLMError from the provider propagates to the caller (the endpoint
        turns it into an `error` event) — chat has no structured single-shot fallback."""
        system = build_chat_system(self.tools)
        transcript = _initial_transcript(messages)
        tool_calls = 0
        nudged = False
        for i in range(self.max_steps):
            t0 = time.monotonic()
            raw = provider.complete(system, transcript, json_mode=False, stop=_REACT_STOP)
            parsed = parse_chat_step(raw)
            step = AgentStep(index=i, thought=parsed.thought, raw=raw,
                             elapsed_ms=int((time.monotonic() - t0) * 1000))
            if parsed.final_text is not None:
                step.is_final = True
                yield ChatEvent(type="step", step=step)
                yield ChatEvent(type="final", answer=parsed.final_text)
                return
            if parsed.action in self.tool_by_name and tool_calls < MAX_TOOL_CALLS:
                tool_calls += 1
                obs = self._run_tool(parsed.action, parsed.action_args, ctx)
                step.action = parsed.action
                step.action_args = parsed.action_args
                step.observation = obs
                yield ChatEvent(type="step", step=step)
                transcript += (
                    f"\n\nThought: {parsed.thought}\nAction: {parsed.action}"
                    f"({json.dumps(parsed.action_args)})\nObservation: {obs}\n"
                )
                continue
            yield ChatEvent(type="step", step=step)
            if not nudged:
                nudged = True
                transcript += (
                    "\n\nYour reply had no valid Action or Final Answer. Reply with exactly one "
                    "'Action: <tool>({json})' or 'Final Answer: <markdown>'."
                )
                continue
            yield ChatEvent(type="final",
                            answer="I couldn't complete that — try narrowing the question or "
                                   "asking about a specific ticker.")
            return
        yield ChatEvent(type="final",
                        answer="I reached my step limit before finishing. Try a more specific "
                               "question (e.g. about one ticker or one factor).")

    def run(self, provider: LLMProvider, model: str, provider_name: str,
            messages: list[ChatMessage], ctx: ChatContext) -> str:
        """Drain stream() to the final answer (CLI / non-streaming / tests)."""
        answer = ""
        for ev in self.stream(provider, model, provider_name, messages, ctx):
            if ev.type in ("final", "error"):
                answer = ev.answer or ev.message
        return answer

    def _run_tool(self, name: str, args: dict, ctx: ChatContext) -> str:
        try:
            obs = self.tool_by_name[name].run(args, ctx)
        except Exception as exc:  # noqa: BLE001 — tool errors must never break the loop
            return f"ERROR: {name} failed: {exc}"
        return obs if len(obs) <= _MAX_OBS_CHARS else obs[:_MAX_OBS_CHARS] + " …(truncated)"
