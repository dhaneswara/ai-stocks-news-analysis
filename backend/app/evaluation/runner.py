from __future__ import annotations

import logging

from app.evaluation.service import evaluate_pending
from app.evaluation.store import PredictionStore
from app.models.schemas import Settings

logger = logging.getLogger("evaluation")


def run_evaluation(store: PredictionStore, settings: Settings, dry_run: bool = False) -> dict:
    if not settings.evaluation.enabled:
        logger.info("Evaluation is disabled; nothing to do.")
        return {"enabled": False, "tickers": 0, "evaluated": 0, "pending": 0}
    summary = evaluate_pending(store, settings, persist=not dry_run)
    summary["enabled"] = True
    return summary
