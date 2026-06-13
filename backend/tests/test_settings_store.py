from app.config.settings_store import MASK, SettingsStore, mask_settings, merge_settings
from app.models.schemas import NewsConfig, NewsProviderConfig, ProviderConfig, Settings


def test_load_returns_defaults_when_empty(tmp_path):
    store = SettingsStore(str(tmp_path / "app.db"))
    s = store.load()
    assert s.active_provider == "anthropic"
    assert "ollama" in s.providers


def test_save_then_load_round_trip(tmp_path):
    store = SettingsStore(str(tmp_path / "app.db"))
    s = store.load()
    s.active_provider = "openai"
    s.providers["openai"].api_key = "sk-secret"
    store.save(s)
    reloaded = store.load()
    assert reloaded.active_provider == "openai"
    assert reloaded.providers["openai"].api_key == "sk-secret"


def test_mask_hides_keys():
    s = Settings()
    s.providers["anthropic"].api_key = "sk-secret"
    masked = mask_settings(s)
    assert masked.providers["anthropic"].api_key == "****"
    # original untouched
    assert s.providers["anthropic"].api_key == "sk-secret"


def test_merge_keeps_existing_key_when_masked():
    existing = Settings()
    existing.providers["anthropic"].api_key = "sk-real"
    incoming = Settings()
    incoming.providers["anthropic"].api_key = "****"  # sentinel: unchanged
    incoming.providers["openai"].api_key = "sk-new"
    merged = merge_settings(existing, incoming)
    assert merged.providers["anthropic"].api_key == "sk-real"
    assert merged.providers["openai"].api_key == "sk-new"


def test_mask_hides_news_keys():
    s = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key="secret")}))
    assert mask_settings(s).news.providers["tavily"].api_key == MASK


def test_merge_restores_masked_news_key():
    existing = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key="secret")}))
    incoming = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key=MASK)}))
    assert merge_settings(existing, incoming).news.providers["tavily"].api_key == "secret"
