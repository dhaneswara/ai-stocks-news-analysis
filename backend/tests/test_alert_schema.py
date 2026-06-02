from app.config.settings_store import mask_settings, merge_settings
from app.models.schemas import AlertConfig, RuleHit, Settings


def test_settings_has_alert_defaults():
    s = Settings()
    assert s.alerts.enabled is False
    assert s.alerts.channel == "telegram"
    assert s.alerts.rsi_low == 30
    assert s.alerts.rsi_high == 70


def test_rule_hit_model():
    h = RuleHit(ticker="AAPL", rule_id="golden_cross", action="buy", candle_date="2026-06-01", message="x")
    assert h.action == "buy"


def test_mask_hides_telegram_token():
    s = Settings()
    s.alerts.telegram_bot_token = "secret-token"
    masked = mask_settings(s)
    assert masked.alerts.telegram_bot_token == "****"
    assert s.alerts.telegram_bot_token == "secret-token"  # original untouched


def test_merge_preserves_telegram_token_when_masked():
    existing = Settings()
    existing.alerts.telegram_bot_token = "real-token"
    incoming = Settings()
    incoming.alerts.telegram_bot_token = "****"
    merged = merge_settings(existing, incoming)
    assert merged.alerts.telegram_bot_token == "real-token"
