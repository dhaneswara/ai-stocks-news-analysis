from app.analysis.trace_store import AgentTraceStore


def test_upsert_and_recent_ordering(tmp_path):
    s = AgentTraceStore(str(tmp_path / "t.db"))
    s.upsert(ticker="aapl", call_date="2026-06-04", provider="a", model="m", trace_json='{"d":4}')
    s.upsert(ticker="AAPL", call_date="2026-06-05", provider="a", model="m", trace_json='{"d":5}')
    assert s.recent("AAPL") == ['{"d":5}', '{"d":4}']
    assert s.recent("AAPL", limit=1) == ['{"d":5}']


def test_upsert_replaces_same_day(tmp_path):
    s = AgentTraceStore(str(tmp_path / "t.db"))
    s.upsert(ticker="AAPL", call_date="2026-06-05", provider="a", model="m", trace_json='{"v":1}')
    s.upsert(ticker="AAPL", call_date="2026-06-05", provider="a", model="m", trace_json='{"v":2}')
    assert s.recent("AAPL") == ['{"v":2}']
