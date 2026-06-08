from app.analysis.agent import AgentStep, AgentTrace, Tool, ToolContext
from app.config.cache import Cache
from app.models.schemas import Settings
from tests.test_analyzer import _stock  # reuse the existing minimal StockData factory


def test_tool_context_holds_dependencies():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    assert ctx.stock.ticker == "AAPL"
    assert ctx.settings.active_provider == "anthropic"


def test_tool_dataclass_fields():
    t = Tool("echo", "echoes", '{"q": str}', lambda args, ctx: "ok")
    assert t.name == "echo"
    assert t.run({}, None) == "ok"


def test_agent_trace_serializes_with_steps():
    trace = AgentTrace(ticker="AAPL", provider="fake", model="m", started_at="2026-06-08T00:00:00Z")
    trace.steps.append(AgentStep(index=0, thought="hi", action="echo", action_args={"q": "x"},
                                 observation="ok"))
    dumped = trace.model_dump()
    assert dumped["ticker"] == "AAPL"
    assert dumped["stopped_reason"] == "final"
    assert dumped["fell_back"] is False
    assert dumped["steps"][0]["action"] == "echo"
    assert dumped["steps"][0]["is_final"] is False


from app.analysis.agent import parse_step


def test_parse_action_with_json_args():
    p = parse_step('Thought: check the news\nAction: fetch_news({"query": "NVDA earnings", "limit": 3})')
    assert p.thought == "check the news"
    assert p.action == "fetch_news"
    assert p.action_args == {"query": "NVDA earnings", "limit": 3}
    assert p.final_json is None


def test_parse_final_answer_json():
    p = parse_step('Thought: done\nFinal Answer: {"current_recommendation": "buy"}')
    assert p.action is None
    assert p.final_json == {"current_recommendation": "buy"}


def test_parse_final_answer_in_code_fence():
    p = parse_step('Thought: x\nFinal Answer:\n```json\n{"a": 1}\n```')
    assert p.final_json == {"a": 1}


def test_parse_garbage_yields_no_action_no_final():
    p = parse_step("I am not following the format at all.")
    assert p.action is None
    assert p.final_json is None


def test_parse_action_with_malformed_args_defaults_to_empty():
    p = parse_step("Thought: t\nAction: price_window(not json)")
    assert p.action == "price_window"
    assert p.action_args == {}


from app.analysis.agent import build_react_system, render_tool_catalog

_DUMMY_TOOLS = [Tool("fetch_news", "Search recent headlines.", '{"query": str}', lambda a, c: "")]


def test_render_tool_catalog_lists_name_args_and_description():
    cat = render_tool_catalog(_DUMMY_TOOLS)
    assert "fetch_news" in cat
    assert '{"query": str}' in cat
    assert "Search recent headlines." in cat


def test_build_react_system_includes_protocol_catalog_and_schema():
    sysprompt = build_react_system(_DUMMY_TOOLS)
    assert "Action:" in sysprompt
    assert "Final Answer:" in sysprompt
    assert "fetch_news" in sysprompt          # the catalog
    assert "current_recommendation" in sysprompt  # the AnalysisResult schema hint
