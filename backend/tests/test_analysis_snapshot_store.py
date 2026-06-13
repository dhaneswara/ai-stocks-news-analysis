from app.services.analysis_snapshot_store import AnalysisSnapshotStore


def test_upsert_and_latest_roundtrip(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    store.upsert(ticker="aapl", source="llm_fast", call_date="2026-06-12", period="1y",
                 provider="anthropic", model="m", result_json='{"x": 1}')
    row = store.latest("AAPL")
    assert row is not None
    assert row.source == "llm_fast" and row.call_date == "2026-06-12"
    assert row.result_json == '{"x": 1}'


def test_latest_returns_most_recent_across_sources(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    store.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                 provider="p", model="m", result_json='{"who": "fast"}')
    store.upsert(ticker="AAPL", source="llm_deep", call_date="2026-06-12", period="1y",
                 provider="p", model="m", result_json='{"who": "deep"}')
    assert store.latest("AAPL").result_json == '{"who": "deep"}'  # newer created_at wins


def test_latest_none_for_unknown_ticker(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    assert store.latest("ZZZZ") is None


def test_upsert_replaces_same_ticker_source(tmp_path):
    store = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    store.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-11", period="1y",
                 provider="p", model="m", result_json='{"v": 1}')
    store.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                 provider="p", model="m", result_json='{"v": 2}')
    row = store.latest("AAPL")
    assert row.call_date == "2026-06-12" and row.result_json == '{"v": 2}'
