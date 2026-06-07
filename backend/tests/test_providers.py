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


def test_factory_applies_env_api_key_fallback(monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-secret")
    monkeypatch.setattr(
        "app.llm.anthropic_provider.Anthropic", lambda api_key: object()
    )
    s = Settings()
    s.active_provider = "anthropic"
    s.providers["anthropic"].api_key = ""  # not set in stored settings
    provider = build_provider(s)
    assert isinstance(provider, AnthropicProvider)
    assert provider.cfg.api_key == "env-secret"  # filled from environment


def test_openai_complete_returns_content(monkeypatch):
    from app.llm.openai_provider import OpenAIProvider

    class Msg:
        content = '{"ok": true}'

    class Choice:
        message = Msg()

    class Resp:
        choices = [Choice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["model"] == "gpt-x"
            assert kwargs["response_format"] == {"type": "json_object"}
            return Resp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("app.llm.openai_provider.OpenAI", lambda api_key: FakeClient())
    provider = OpenAIProvider(ProviderConfig(model="gpt-x", api_key="k"))
    assert provider.complete("sys", "user") == '{"ok": true}'


def test_gemini_complete_returns_text(monkeypatch):
    from app.llm.gemini_provider import GeminiProvider

    class Resp:
        text = '{"ok": true}'

    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == "gem-x"
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.gemini_provider.genai.Client", lambda api_key: FakeClient())
    provider = GeminiProvider(ProviderConfig(model="gem-x", api_key="k"))
    assert provider.complete("sys", "user") == '{"ok": true}'


def test_deepseek_defaults_present():
    from app.models.schemas import DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_MODELS

    assert DEFAULT_MODELS["deepseek"] == "deepseek-chat"
    assert DEFAULT_DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    s = Settings()  # default settings include a deepseek entry
    assert s.providers["deepseek"].model == "deepseek-chat"
    assert s.providers["deepseek"].base_url == "https://api.deepseek.com"


def test_settings_backfills_missing_providers():
    # Legacy settings that predate deepseek (only anthropic stored).
    s = Settings.model_validate({"providers": {"anthropic": {"model": "claude-x"}}})
    assert s.providers["anthropic"].model == "claude-x"   # existing entry preserved
    assert "deepseek" in s.providers                       # backfilled
    assert s.providers["deepseek"].model == "deepseek-chat"
    assert s.providers["deepseek"].base_url == "https://api.deepseek.com"
    # other known providers are also backfilled
    assert {"openai", "gemini", "ollama"} <= set(s.providers)
