import json

import app.analysis.agent as agent_mod
from app.analysis.agent import (
    TOOL_BY_NAME,
    TOOLS,
    AgentEvent,
    AgentStep,
    AgentTrace,
    ReActAgent,
    Tool,
    ToolContext,
    build_react_system,
    parse_step,
    render_tool_catalog,
)
from app.config.cache import Cache
from app.models.schemas import Candle, NewsItem, Settings, StockScore
from tests.test_analyzer import VALID_PAYLOAD, FakeProvider, _stock


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


def test_parse_action_tolerates_trailing_text():
    # A chatty model appends an Observation/commentary after the Action line — the old
    # \Z-anchored regex failed here, producing an empty (no-action) step.
    p = parse_step(
        'Thought: check news\nAction: fetch_news({"query": "GLW Amazon"})\n'
        'Observation: I will wait for the result.'
    )
    assert p.action == "fetch_news"
    assert p.action_args == {"query": "GLW Amazon"}


def test_parse_action_inside_code_fence():
    p = parse_step('Thought: t\n```\nAction: fetch_news({"query": "x"})\n```')
    assert p.action == "fetch_news"
    assert p.action_args == {"query": "x"}


def test_parse_action_with_nested_json_and_trailing_text():
    p = parse_step('Action: app_signals({"kind": "score", "opts": {"deep": true}}) then I observe.')
    assert p.action == "app_signals"
    assert p.action_args == {"kind": "score", "opts": {"deep": True}}


def test_parse_uses_leading_prose_as_thought_when_no_label():
    # Model omits the literal "Thought:" label but reasons before acting.
    p = parse_step('I should look at recent headlines first.\nAction: fetch_news({"query": "x"})')
    assert p.action == "fetch_news"
    assert "look at recent headlines" in p.thought


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


def test_fetch_news_tool_formats_headlines(monkeypatch):
    monkeypatch.setattr(agent_mod, "search_news", lambda q, limit=5: [
        NewsItem(title="NVDA beats", source="Reuters", published_at="2026-06-01"),
        NewsItem(title="Guidance raised", source="CNBC", published_at="2026-06-02"),
    ])
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_fetch_news({"query": "NVDA earnings", "limit": 2}, ctx)
    assert "NVDA beats (Reuters)" in out
    assert "Guidance raised (CNBC)" in out


def test_fetch_news_tool_requires_query():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_fetch_news({}, ctx)
    assert out.startswith("ERROR")


def test_fetch_news_tool_tolerates_non_numeric_limit(monkeypatch):
    monkeypatch.setattr(agent_mod, "search_news", lambda q, limit=5: [
        NewsItem(title="NVDA beats", source="Reuters", published_at="2026-06-01"),
    ])
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_fetch_news({"query": "x", "limit": "abc"}, ctx)  # must not raise
    assert "NVDA beats (Reuters)" in out


def test_get_fundamentals_tool_returns_requested_fields(monkeypatch):
    monkeypatch.setattr(agent_mod, "fetch_info", lambda ticker: {
        "trailingEps": 5.2, "forwardEps": 6.1, "earningsGrowth": 0.18, "marketCap": 1e12})
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_get_fundamentals({"detail": "earnings"}, ctx)
    assert "trailingEps: 5.2" in out
    assert "forwardEps: 6.1" in out
    assert "marketCap" not in out  # not part of the 'earnings' field set


def test_get_fundamentals_tool_unknown_detail():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_get_fundamentals({"detail": "nonsense"}, ctx)
    assert out.startswith("ERROR")


def _stock_with_prices():
    s = _stock()
    s.candles = [Candle(time=f"2026-05-{d:02d}", open=p, high=p, low=p, close=p, volume=1)
                 for d, p in [(1, 100.0), (4, 102.0), (5, 98.0), (6, 105.0), (7, 110.0)]]
    return s


def test_price_window_tool_summarizes_window():
    ctx = ToolContext(stock=_stock_with_prices(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_price_window({"lookback_days": 5}, ctx)
    assert "last 5 trading days" in out
    assert "100.00 -> 110.00" in out        # start -> end
    assert "98.00 / 110.00" in out          # low / high


def test_price_window_tool_no_candles():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))  # _stock() has []
    out = agent_mod._tool_price_window({"lookback_days": 5}, ctx)
    assert out == "(no price history)"


def test_price_window_tool_appends_indicator_when_history_suffices():
    ctx = ToolContext(stock=_stock_with_prices(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_price_window({"lookback_days": 5, "indicator": "sma", "period": 3}, ctx)
    assert "SMA(3) latest: 104.33" in out  # (98 + 105 + 110) / 3


def test_price_window_tool_suppresses_indicator_when_history_short():
    ctx = ToolContext(stock=_stock_with_prices(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_price_window({"lookback_days": 5, "indicator": "sma", "period": 50}, ctx)
    assert "SMA" not in out  # only 5 candles -> SMA(50) is NaN -> line suppressed


def test_app_signals_score(monkeypatch):
    monkeypatch.setattr(agent_mod, "score_one", lambda t, s, c: StockScore(
        ticker=t, name="Apple Inc.", price=150.0, change_pct=0.7, score=63.0,
        direction="buy", reasons=["RSI 33 (oversold)", "above SMA50"]))
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_app_signals({"kind": "score"}, ctx)
    assert "63/100" in out
    assert "lean buy" in out
    assert "RSI 33 (oversold)" in out


def test_app_signals_invalid_kind():
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_app_signals({"kind": "bogus"}, ctx)
    assert out.startswith("ERROR")


def test_app_signals_network_none_when_no_edges(monkeypatch):
    monkeypatch.setattr(agent_mod, "_network_signal_for", lambda ticker, ctx: None)
    ctx = ToolContext(stock=_stock(), settings=Settings(), cache=Cache(":memory:"))
    out = agent_mod._tool_app_signals({"kind": "network"}, ctx)
    assert "no company-network signal" in out


def test_registry_has_the_four_tools():
    assert {t.name for t in TOOLS} == {"fetch_news", "get_fundamentals", "price_window", "app_signals"}
    assert TOOL_BY_NAME["fetch_news"].run is agent_mod._tool_fetch_news


_ECHO = Tool("echo", "echo a value", '{"q": str}', lambda args, ctx: f"observed:{args.get('q', '')}")


def _ctx(stock=None):
    return ToolContext(stock=stock or _stock(), settings=Settings(), cache=Cache(":memory:"))


def test_agent_returns_final_answer_in_one_turn():
    provider = FakeProvider([f'Thought: enough info\nFinal Answer: {json.dumps(VALID_PAYLOAD)}'])
    agent = ReActAgent(tools=[_ECHO])
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.current_recommendation == "buy"
    assert trace.stopped_reason == "final"
    assert trace.fell_back is False
    assert trace.steps[-1].is_final is True
    assert provider.calls == 1


def test_agent_runs_a_tool_then_finalizes():
    provider = FakeProvider([
        'Thought: check echo\nAction: echo({"q": "hi"})',
        f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}',
    ])
    agent = ReActAgent(tools=[_ECHO])
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.sentiment == "bullish"
    assert trace.steps[0].action == "echo"
    assert trace.steps[0].observation == "observed:hi"
    assert provider.calls == 2


def test_agent_falls_back_to_single_shot_on_max_steps():
    # Always emits a tool action, never a final answer -> hits max_steps -> single-shot fallback.
    # The fallback analyze() consumes one more provider output (valid JSON).
    actions = ['Thought: loop\nAction: echo({"q": "x"})'] * 3
    provider = FakeProvider([*actions, json.dumps(VALID_PAYLOAD)])
    agent = ReActAgent(tools=[_ECHO], max_steps=3)
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.current_recommendation == "buy"   # came from the fallback
    assert trace.stopped_reason == "max_steps"
    assert trace.fell_back is True


def test_agent_nudges_once_then_falls_back_on_garbage():
    # Two garbage turns (one nudge, then still garbage) -> fallback consumes the final valid JSON.
    provider = FakeProvider(["garbage one", "garbage two", json.dumps(VALID_PAYLOAD)])
    agent = ReActAgent(tools=[_ECHO], max_steps=5)
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert result.current_recommendation == "buy"
    assert trace.stopped_reason == "no_action"
    assert trace.fell_back is True


def test_agent_tool_error_becomes_observation_not_crash():
    boom = Tool("boom", "always raises", "{}", lambda args, ctx: (_ for _ in ()).throw(RuntimeError("nope")))
    provider = FakeProvider([
        'Thought: try boom\nAction: boom({})',
        f'Thought: recover\nFinal Answer: {json.dumps(VALID_PAYLOAD)}',
    ])
    agent = ReActAgent(tools=[boom])
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert "ERROR: boom failed: nope" in trace.steps[0].observation
    assert result.current_recommendation == "buy"


def test_agent_falls_back_when_final_answer_fails_validation():
    # Final Answer is valid JSON but not a valid AnalysisResult -> parse_error -> single-shot fallback.
    provider = FakeProvider([
        'Thought: done\nFinal Answer: {"sentiment": "not-an-enum"}',
        json.dumps(VALID_PAYLOAD),  # consumed by the fallback analyze()
    ])
    agent = ReActAgent(tools=[_ECHO])
    result, trace = agent.run(provider, "m", "fake", _ctx())
    assert trace.stopped_reason == "parse_error"
    assert trace.fell_back is True
    assert result.current_recommendation == "buy"  # from the fallback


def test_stream_yields_steps_then_final():
    provider = FakeProvider([
        'Thought: check\nAction: echo({"q": "hi"})',
        f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}',
    ])
    events = list(ReActAgent(tools=[_ECHO]).stream(provider, "m", "fake", _ctx()))
    assert [e.type for e in events] == ["step", "step", "final"]
    assert events[0].step.action == "echo"
    assert events[-1].result.current_recommendation == "buy"
    assert events[-1].trace.stopped_reason == "final"
    assert events[-1].trace.fell_back is False


def test_stream_emits_final_on_fallback():
    provider = FakeProvider(["garbage", "garbage", json.dumps(VALID_PAYLOAD)])
    events = list(ReActAgent(tools=[_ECHO], max_steps=5).stream(provider, "m", "fake", _ctx()))
    assert events[-1].type == "final"
    assert events[-1].trace.fell_back is True
    assert events[-1].result.current_recommendation == "buy"


def test_steps_capture_raw_model_output():
    # Each step carries the model's raw output, so the trace is never a blank box even when
    # the model strays from the format (the symptom that motivated this).
    raw = "I am rambling and not following the format."
    provider = FakeProvider([raw, raw, json.dumps(VALID_PAYLOAD)])
    _result, trace = ReActAgent(tools=[_ECHO], max_steps=2).run(provider, "m", "fake", _ctx())
    assert trace.steps[0].raw == raw
    assert trace.fell_back is True  # no parseable action -> fell back to single-shot
