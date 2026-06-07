from __future__ import annotations

import logging

from app.evaluation.store import PredictionStore
from app.models.schemas import AnalysisResult, StockData

logger = logging.getLogger("evaluation")


def record_prediction(stock: StockData, result: AnalysisResult, store: PredictionStore) -> None:
    """Persist one call, keyed by the last trading day in the stock data."""
    if not stock.candles:
        return
    last = stock.candles[-1]
    store.upsert_prediction(
        ticker=result.ticker,
        call_date=last.time,
        provider=result.provider,
        model=result.model,
        recommendation=result.current_recommendation,
        confidence=result.confidence,
        sentiment=result.sentiment,
        entry_price=last.close,
    )
