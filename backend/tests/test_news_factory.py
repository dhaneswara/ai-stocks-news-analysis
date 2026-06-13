from app.models.schemas import NewsConfig, NewsProviderConfig, Settings
from app.news.exa import ExaNewsProvider
from app.news.google import GoogleNewsProvider
from app.news.factory import build_news_provider, resolve_news_config


def test_build_returns_active_provider_class():
    s = Settings(news=NewsConfig(active_provider="google"))
    assert isinstance(build_news_provider(s), GoogleNewsProvider)


def test_build_by_explicit_id():
    s = Settings(news=NewsConfig(providers={"exa": NewsProviderConfig(api_key="k")}))
    assert isinstance(build_news_provider(s, "exa"), ExaNewsProvider)


def test_resolve_fills_key_from_env_and_default_url(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "env-key")
    resolved = resolve_news_config("exa", NewsProviderConfig())
    assert resolved.api_key == "env-key"
    assert resolved.mcp_url == "https://mcp.exa.ai/mcp"
