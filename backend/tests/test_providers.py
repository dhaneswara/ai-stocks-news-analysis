import pytest

from app.llm.factory import build_provider
from app.llm.ollama_provider import OllamaProvider
from app.models.schemas import ProviderConfig, Settings


def test_factory_builds_active_provider():
    s = Settings()
    s.active_provider = "ollama"
    provider = build_provider(s)
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"


def test_factory_unknown_provider_raises():
    from app.llm.base import LLMError

    s = Settings()
    s.active_provider = "anthropic"
    s.providers.pop("anthropic")  # simulate missing config
    with pytest.raises(LLMError):
        build_provider(s)


def test_ollama_complete_parses_message(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"ok": true}'}}

    def fake_post(url, json, timeout):
        assert url.endswith("/api/chat")
        assert json["model"] == "llama3.1"
        return FakeResp()

    monkeypatch.setattr("app.llm.ollama_provider.httpx.post", fake_post)
    provider = OllamaProvider(ProviderConfig(model="llama3.1", base_url="http://localhost:11434"))
    assert provider.complete("sys", "user") == '{"ok": true}'


def test_anthropic_complete_joins_text_blocks(monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    class Block:
        type = "text"
        text = "hello"

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["model"] == "claude-x"
            class R:
                content = [Block()]
            return R()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(
        "app.llm.anthropic_provider.Anthropic", lambda api_key: FakeClient()
    )
    provider = AnthropicProvider(ProviderConfig(model="claude-x", api_key="k"))
    assert provider.complete("sys", "user") == "hello"
