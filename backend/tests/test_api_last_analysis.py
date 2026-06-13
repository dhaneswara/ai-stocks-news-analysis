from fastapi.testclient import TestClient

from app.deps import get_analysis_snapshot_store
from app.main import app
from app.services.analysis_snapshot_store import AnalysisSnapshotStore


def _client(tmp_path):
    snap = AnalysisSnapshotStore(str(tmp_path / "snap.db"))
    app.dependency_overrides[get_analysis_snapshot_store] = lambda: snap
    return TestClient(app), snap


def teardown_function():
    app.dependency_overrides.clear()


_RESULT_JSON = (
    '{"ticker":"AAPL","provider":"anthropic","model":"m","generated_at":"2026-06-12",'
    '"overall_summary":"hello","news_analysis":"n","sentiment":"bullish",'
    '"current_recommendation":"buy","confidence":0.8,"key_factors":[],"signals":[],'
    '"risks":[],"disclaimer":"Not financial advice"}'
)


def test_returns_null_when_no_snapshot(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/api/analysis/AAPL").json() is None


def test_returns_latest_snapshot(tmp_path):
    client, snap = _client(tmp_path)
    snap.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                provider="anthropic", model="m", result_json=_RESULT_JSON)
    body = client.get("/api/analysis/aapl").json()
    assert body["source"] == "llm_fast"
    assert body["call_date"] == "2026-06-12"
    assert body["result"]["overall_summary"] == "hello"


def test_corrupt_snapshot_returns_null(tmp_path):
    client, snap = _client(tmp_path)
    snap.upsert(ticker="AAPL", source="llm_fast", call_date="2026-06-12", period="1y",
                provider="anthropic", model="m", result_json="{not valid json")
    assert client.get("/api/analysis/AAPL").json() is None
