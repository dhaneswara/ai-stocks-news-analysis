from __future__ import annotations

import logging

from app.alerts.notifier import Notifier
from app.alerts.rules import evaluate_rules
from app.alerts.state import AlertState
from app.config.cache import Cache
from app.models.schemas import DISCLAIMER, Settings
from app.services.analysis_service import run_analysis
from app.services.stock_service import get_stock_data

logger = logging.getLogger("alerts")
ALERT_PERIOD = "1y"


def _reasoning(ticker: str, period: str, settings: Settings, cache: Cache) -> str:
    try:
        result = run_analysis(ticker, period, settings, cache)
        return f"LLM ({result.current_recommendation.upper()}): {result.overall_summary}"
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM reasoning unavailable for %s: %s", ticker, exc)
        return ""


def run_alerts(
    settings: Settings,
    cache: Cache,
    state: AlertState,
    notifier: Notifier,
    with_llm: bool = True,
    period: str = ALERT_PERIOD,
) -> dict:
    if not settings.alerts.enabled:
        logger.info("Alerts are disabled; nothing to do.")
        return {"enabled": False, "checked": 0, "sent": 0}

    checked = 0
    sent = 0
    for ticker in settings.watchlist:
        checked += 1
        try:
            stock = get_stock_data(ticker, period, settings.indicator_params, cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: %s", ticker, exc)
            continue
        for hit in evaluate_rules(stock, settings.alerts.rsi_low, settings.alerts.rsi_high):
            if state.was_alerted(hit.ticker, hit.rule_id, hit.candle_date):
                continue
            reasoning = _reasoning(ticker, period, settings, cache) if with_llm else ""
            title = f"{hit.action.upper()} signal — {stock.company_name} ({ticker})"
            body = hit.message + (f"\n\n{reasoning}" if reasoning else "") + f"\n\n{DISCLAIMER}"
            try:
                notifier.send(title, body)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send alert for %s/%s: %s", ticker, hit.rule_id, exc)
                continue
            state.mark(hit.ticker, hit.rule_id, hit.candle_date)
            sent += 1
            logger.info("Sent %s alert for %s (%s)", hit.action, ticker, hit.rule_id)
    return {"enabled": True, "checked": checked, "sent": sent}
