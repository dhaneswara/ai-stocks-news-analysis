from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from app.models.schemas import AlertConfig

logger = logging.getLogger("alerts")


class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class LogNotifier:
    def send(self, title: str, body: str) -> None:
        logger.info("ALERT %s | %s", title, body)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def send(self, title: str, body: str) -> None:
        resp = httpx.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": f"<b>{title}</b>\n{body}", "parse_mode": "HTML"},
            timeout=30,
        )
        resp.raise_for_status()


def build_notifier(cfg: AlertConfig, dry_run: bool = False) -> Notifier:
    if dry_run or cfg.channel == "log":
        return LogNotifier()
    token = cfg.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if cfg.channel == "telegram" and token and chat_id:
        return TelegramNotifier(token, chat_id)
    logger.warning("Alerts enabled but Telegram is not fully configured; using log notifier.")
    return LogNotifier()
