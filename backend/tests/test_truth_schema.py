from app.models.schemas import (
    AnalysisResult,
    MarketMood,
    Mention,
    Settings,
    StockData,
    TruthPost,
    TruthSignalConfig,
)


def test_truth_signal_config_defaults():
    cfg = TruthSignalConfig()
    assert cfg.enabled is True
    assert cfg.lookback_hours == 48
    assert cfg.source_url.startswith("https://ix.cnn.io/")


def test_settings_includes_truth_signal_default():
    assert Settings().truth_signal.enabled is True


def test_market_mood_defaults_to_neutral():
    mood = MarketMood()
    assert mood.lean == "neutral"
    assert mood.themes == []
    assert mood.post_count == 0


def test_stockdata_truth_fields_default_to_none_and_empty_list():
    assert StockData.model_fields["market_mood"].default is None
    assert StockData.model_fields["trump_mentions"].default_factory is list


def test_truth_post_url_defaults_empty():
    assert TruthPost(id="1", created_at="t", content="c").url == ""


def test_analysis_result_has_market_mood_field():
    assert "market_mood" in AnalysisResult.model_fields
    assert Mention.model_fields["url"].default == ""
