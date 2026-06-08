import json

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from tests.test_analyzer import VALID_PAYLOAD, FakeProvider, _stock

client = TestClient(app)


def test_deep_stream_emits_steps_and_final(monkeypatch):
    monkeypatch.setattr(routes, "gather_stock_context", lambda t, p, s, c, prov: _stock())
    monkeypatch.setattr(
        routes, "build_provider",
        lambda settings: FakeProvider([f'Thought: done\nFinal Answer: {json.dumps(VALID_PAYLOAD)}']),
    )
    resp = client.get("/api/analyze/AAPL/deep/stream?period=1y")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: final" in resp.text
    assert '"current_recommendation":"buy"' in resp.text


def test_deep_stream_404_when_no_price_data(monkeypatch):
    def boom(*a, **k):
        raise ValueError("No price history for ticker 'ZZZZ'")
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "gather_stock_context", boom)
    resp = client.get("/api/analyze/ZZZZ/deep/stream")
    assert resp.status_code == 404
