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


def test_deepseek_complete_uses_base_url_and_returns_content(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    captured = {}

    class Msg:
        content = '{"ok": true}'

    class Choice:
        message = Msg()

    class Resp:
        choices = [Choice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["model"] == "deepseek-chat"
            assert kwargs["response_format"] == {"type": "json_object"}
            return Resp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", fake_openai)
    provider = DeepSeekProvider(
        ProviderConfig(model="deepseek-chat", api_key="k", base_url="https://api.deepseek.com")
    )
    assert provider.complete("sys", "user") == '{"ok": true}'
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["api_key"] == "k"
    assert provider.name == "deepseek"


def test_factory_builds_deepseek(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", lambda **kwargs: object())
    s = Settings()
    s.active_provider = "deepseek"
    s.providers["deepseek"].api_key = "k"
    provider = build_provider(s)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.name == "deepseek"


def test_factory_deepseek_env_key_fallback(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-secret")
    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", lambda **kwargs: object())
    s = Settings()
    s.active_provider = "deepseek"
    s.providers["deepseek"].api_key = ""  # not set in stored settings
    provider = build_provider(s)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.cfg.api_key == "env-secret"  # filled from environment


def test_openai_list_models_sorted_deduped(monkeypatch):
    from app.llm.openai_provider import OpenAIProvider

    class M:
        def __init__(self, id):
            self.id = id

    class Resp:
        data = [M("gpt-b"), M("gpt-a"), M("gpt-a")]

    class FakeModels:
        def list(self):
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.openai_provider.OpenAI", lambda api_key: FakeClient())
    provider = OpenAIProvider(ProviderConfig(model="x", api_key="k"))
    assert provider.list_models() == ["gpt-a", "gpt-b"]


def test_deepseek_list_models_inherits(monkeypatch):
    from app.llm.deepseek_provider import DeepSeekProvider

    class M:
        def __init__(self, id):
            self.id = id

    class Resp:
        data = [M("deepseek-reasoner"), M("deepseek-chat")]

    class FakeModels:
        def list(self):
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.deepseek_provider.OpenAI", lambda **kwargs: FakeClient())
    provider = DeepSeekProvider(ProviderConfig(model="deepseek-chat", api_key="k"))
    assert provider.list_models() == ["deepseek-chat", "deepseek-reasoner"]


def test_anthropic_list_models_sorted(monkeypatch):
    from app.llm.anthropic_provider import AnthropicProvider

    class M:
        def __init__(self, id):
            self.id = id

    class Resp:
        data = [M("claude-b"), M("claude-a")]

    class FakeModels:
        def list(self):
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.anthropic_provider.Anthropic", lambda api_key: FakeClient())
    provider = AnthropicProvider(ProviderConfig(model="x", api_key="k"))
    assert provider.list_models() == ["claude-a", "claude-b"]


def test_gemini_list_models_strips_prefix(monkeypatch):
    from app.llm.gemini_provider import GeminiProvider

    class M:
        def __init__(self, name):
            self.name = name

    class FakeModels:
        def list(self):
            return [M("models/gemini-2.0-flash"), M("models/gemini-1.5-pro")]

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.gemini_provider.genai.Client", lambda api_key: FakeClient())
    provider = GeminiProvider(ProviderConfig(model="x", api_key="k"))
    assert provider.list_models() == ["gemini-1.5-pro", "gemini-2.0-flash"]


def test_ollama_list_models(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "llama3.1:latest"}, {"name": "mistral:latest"}]}

    def fake_get(url, timeout):
        assert url.endswith("/api/tags")
        return FakeResp()

    monkeypatch.setattr("app.llm.ollama_provider.httpx.get", fake_get)
    provider = OllamaProvider(ProviderConfig(model="x", base_url="http://localhost:11434"))
    assert provider.list_models() == ["llama3.1:latest", "mistral:latest"]


def test_openai_complete_omits_json_format_when_json_mode_false(monkeypatch):
    # json_mode=False (the ReAct agent path) must NOT force a JSON object — the model needs to be
    # free to emit the Thought/Action text protocol.
    from app.llm.openai_provider import OpenAIProvider

    captured = {}

    class Msg:
        content = "Thought: x"

    class Choice:
        message = Msg()

    class Resp:
        choices = [Choice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Resp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("app.llm.openai_provider.OpenAI", lambda api_key: FakeClient())
    provider = OpenAIProvider(ProviderConfig(model="gpt-x", api_key="k"))
    assert provider.complete("sys", "user", json_mode=False) == "Thought: x"
    assert "response_format" not in captured  # JSON mode was opted out


def test_gemini_complete_omits_json_mime_when_json_mode_false(monkeypatch):
    from app.llm.gemini_provider import GeminiProvider

    captured = {}

    class Resp:
        text = "Thought: x"

    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return Resp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("app.llm.gemini_provider.genai.Client", lambda api_key: FakeClient())
    provider = GeminiProvider(ProviderConfig(model="gem-x", api_key="k"))
    assert provider.complete("sys", "user", json_mode=False) == "Thought: x"
    assert getattr(captured["config"], "response_mime_type", None) is None


def test_ollama_complete_omits_json_format_when_json_mode_false(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "Thought: x"}}

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResp()

    monkeypatch.setattr("app.llm.ollama_provider.httpx.post", fake_post)
    provider = OllamaProvider(ProviderConfig(model="llama3.1", base_url="http://localhost:11434"))
    assert provider.complete("sys", "user", json_mode=False) == "Thought: x"
    assert "format" not in captured  # JSON mode was opted out
