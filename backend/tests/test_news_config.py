from app.models.schemas import NewsConfig, NewsProviderConfig, Settings


def test_news_defaults():
    n = NewsConfig()
    assert n.active_provider == "google"
    assert n.news_recency_days == 90
    assert set(n.providers) == {"google", "tavily", "exa", "you"}


def test_settings_has_news_and_validator_backfills_missing_providers():
    s = Settings(news=NewsConfig(providers={"tavily": NewsProviderConfig(api_key="k")}))
    assert set(s.news.providers) == {"google", "tavily", "exa", "you"}
    assert s.news.providers["tavily"].api_key == "k"


def test_settings_default_news_is_google():
    assert Settings().news.active_provider == "google"
