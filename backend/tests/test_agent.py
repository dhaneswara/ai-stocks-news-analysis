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
