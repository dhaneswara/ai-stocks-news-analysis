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
