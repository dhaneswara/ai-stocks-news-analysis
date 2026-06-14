from app.chat.agent import (
    ChatEvent, ChatMessage, build_chat_system, parse_chat_step,
)
from app.chat.tools import TOOLS


def test_parse_action_with_json_args():
    p = parse_chat_step('Thought: look it up\nAction: get_stock({"ticker": "NVDA"})')
    assert p.thought == "look it up"
    assert p.action == "get_stock"
    assert p.action_args == {"ticker": "NVDA"}
    assert p.final_text is None


def test_parse_final_answer_is_markdown_text():
    p = parse_chat_step("Thought: done\nFinal Answer: ## NVDA\n\n**Buy** — strong trend.")
    assert p.action is None
    assert p.final_text.startswith("## NVDA")
    assert "**Buy**" in p.final_text


def test_parse_garbage_yields_no_action_no_final():
    p = parse_chat_step("I am not following the format.")
    assert p.action is None
    assert p.final_text is None


def test_parse_empty_final_is_not_final():
    p = parse_chat_step("Thought: x\nFinal Answer:   ")
    assert p.final_text is None


def test_build_chat_system_includes_protocol_and_catalog():
    sysprompt = build_chat_system(TOOLS)
    assert "Action:" in sysprompt
    assert "Final Answer:" in sysprompt
    assert "get_stock" in sysprompt        # the catalog
    assert "Markdown" in sysprompt         # final-answer format instruction


def test_chat_event_serializes():
    ev = ChatEvent(type="final", answer="hi")
    assert ev.model_dump()["type"] == "final"
    assert ev.model_dump()["answer"] == "hi"


def test_chat_message_roles():
    m = ChatMessage(role="user", content="hello")
    assert m.role == "user"


import json

from app.chat.agent import ChatAgent
from app.chat.tools import ChatContext, ChatTool
from app.config.cache import Cache
from app.models.schemas import Settings


class _CapturingProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []
        self.json_modes = []
        self.stops = []

    def complete(self, system, user, json_mode=True, stop=None):
        self.prompts.append(user)
        self.json_modes.append(json_mode)
        self.stops.append(stop)
        return self.outputs.pop(0)

    def list_models(self):
        return []


_ECHO = ChatTool("echo", "echo a value", '{"q": str}',
                 lambda args, ctx: f"observed:{args.get('q', '')}")


def _ctx(provider):
    return ChatContext(settings=Settings(), cache=Cache(":memory:"), provider=provider)


def _msgs(text="What about NVDA?"):
    return [ChatMessage(role="user", content=text)]


def test_agent_answers_in_one_turn():
    provider = _CapturingProvider(["Thought: easy\nFinal Answer: **NVDA** looks strong."])
    events = list(ChatAgent(tools=[_ECHO]).stream(provider, "m", "fake", _msgs(), _ctx(provider)))
    assert [e.type for e in events] == ["step", "final"]
    assert events[-1].answer == "**NVDA** looks strong."
    assert provider.json_modes == [False]      # free-text ReAct turn
    assert provider.stops == [["\nObservation:"]]


def test_agent_runs_a_tool_then_answers():
    provider = _CapturingProvider([
        'Thought: check echo\nAction: echo({"q": "hi"})',
        "Thought: done\nFinal Answer: Result was hi.",
    ])
    events = list(ChatAgent(tools=[_ECHO]).stream(provider, "m", "fake", _msgs(), _ctx(provider)))
    assert [e.type for e in events] == ["step", "step", "final"]
    assert events[0].step.action == "echo"
    assert events[0].step.observation == "observed:hi"
    assert events[-1].answer == "Result was hi."


def test_agent_seeds_conversation_history_into_the_prompt():
    provider = _CapturingProvider(["Thought: ok\nFinal Answer: yes"])
    messages = [
        ChatMessage(role="user", content="Tell me about NVDA"),
        ChatMessage(role="assistant", content="NVDA is a chipmaker."),
        ChatMessage(role="user", content="Is it a buy?"),
    ]
    list(ChatAgent(tools=[_ECHO]).stream(provider, "m", "fake", messages, _ctx(provider)))
    seed = provider.prompts[0]
    assert "Tell me about NVDA" in seed
    assert "NVDA is a chipmaker." in seed
    assert "Is it a buy?" in seed


def test_agent_tool_error_becomes_observation():
    boom = ChatTool("boom", "raises", "{}",
                    lambda args, ctx: (_ for _ in ()).throw(RuntimeError("nope")))
    provider = _CapturingProvider([
        "Thought: try\nAction: boom({})",
        "Thought: recover\nFinal Answer: handled it.",
    ])
    events = list(ChatAgent(tools=[boom]).stream(provider, "m", "fake", _msgs(), _ctx(provider)))
    assert "ERROR: boom failed: nope" in events[0].step.observation
    assert events[-1].answer == "handled it."


def test_agent_nudges_once_then_gives_graceful_final():
    provider = _CapturingProvider(["garbage one", "garbage two"])
    events = list(ChatAgent(tools=[_ECHO], max_steps=5).stream(
        provider, "m", "fake", _msgs(), _ctx(provider)))
    assert events[-1].type == "final"
    assert "couldn't complete" in events[-1].answer.lower()


def test_agent_hits_max_steps_with_graceful_final():
    actions = ['Thought: loop\nAction: echo({"q": "x"})'] * 3
    provider = _CapturingProvider(actions)
    events = list(ChatAgent(tools=[_ECHO], max_steps=3).stream(
        provider, "m", "fake", _msgs(), _ctx(provider)))
    assert events[-1].type == "final"
    assert "step limit" in events[-1].answer.lower()


def test_run_drains_to_the_answer():
    provider = _CapturingProvider(["Thought: ok\nFinal Answer: the answer"])
    answer = ChatAgent(tools=[_ECHO]).run(provider, "m", "fake", _msgs(), _ctx(provider))
    assert answer == "the answer"
