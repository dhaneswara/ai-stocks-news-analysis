from app.alerts.notifier import LogNotifier, TelegramNotifier, build_notifier
from app.models.schemas import AlertConfig


def test_telegram_send_posts_expected_payload(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr("app.alerts.notifier.httpx.post", fake_post)
    TelegramNotifier("TOKEN", "CHAT").send("Title", "Body")
    assert captured["url"] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert captured["json"]["chat_id"] == "CHAT"
    assert "Title" in captured["json"]["text"] and "Body" in captured["json"]["text"]


def test_build_notifier_telegram_when_configured():
    cfg = AlertConfig(channel="telegram", telegram_bot_token="t", telegram_chat_id="c")
    assert isinstance(build_notifier(cfg), TelegramNotifier)


def test_build_notifier_log_when_dry_run():
    cfg = AlertConfig(channel="telegram", telegram_bot_token="t", telegram_chat_id="c")
    assert isinstance(build_notifier(cfg, dry_run=True), LogNotifier)


def test_build_notifier_log_when_unconfigured():
    cfg = AlertConfig(channel="telegram")  # no token/chat
    assert isinstance(build_notifier(cfg), LogNotifier)


def test_build_notifier_env_fallback(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
    cfg = AlertConfig(channel="telegram")  # empty in settings
    notifier = build_notifier(cfg)
    assert isinstance(notifier, TelegramNotifier)
    assert notifier.token == "env-tok"
    assert notifier.chat_id == "env-chat"


def test_log_notifier_does_not_raise():
    LogNotifier().send("t", "b")
