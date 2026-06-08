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
    assert "event: step" in resp.text   # streamed step-by-step, not just the final
    assert "event: final" in resp.text
    assert '"current_recommendation":"buy"' in resp.text


def test_deep_stream_404_when_no_price_data(monkeypatch):
    def boom(*a, **k):
        raise ValueError("No price history for ticker 'ZZZZ'")
    monkeypatch.setattr(routes, "build_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr(routes, "gather_stock_context", boom)
    resp = client.get("/api/analyze/ZZZZ/deep/stream")
    assert resp.status_code == 404


def test_deep_stream_emits_error_event_when_provider_fails(monkeypatch):
    """Provider/LLM failures (e.g. a missing key) reach the client as a usable in-stream
    `event: error` — not a generic EventSource connection error."""
    from app.llm.base import LLMError

    class _Raising:
        name = "raise"

        def complete(self, system, user, json_mode=True):
            raise LLMError("provider down")

    monkeypatch.setattr(routes, "gather_stock_context", lambda t, p, s, c, prov: _stock())
    monkeypatch.setattr(routes, "build_provider", lambda settings: _Raising())
    resp = client.get("/api/analyze/AAPL/deep/stream")
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "provider down" in resp.text
