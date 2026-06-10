"""Multi-source signal recording + per-ticker signal summaries.

The deterministic scorer's calls (technical / network) are recorded through the SAME
PredictionStore the LLM paths use, so the evaluation engine judges every source by
identical rules."""
from __future__ import annotations

import logging

from app.analysis.scoring import direction_for
from app.config.cache import Cache
from app.evaluation.store import (
    SOURCE_NETWORK,
    SOURCE_TECHNICAL,
    PredictionStore,
)
from app.models.schemas import Settings, StockData
from app.screener.service import score_one

logger = logging.getLogger("evaluation")

_SENTIMENT_FOR = {"buy": "bullish", "sell": "bearish", "hold": "neutral"}


def record_deterministic_pair(stock: StockData, settings: Settings, cache: Cache,
                              store: PredictionStore) -> None:
    """Record the technical call (pre-network base vote) and — when a network signal actually
    influenced the score — the network-blended call, keyed to the same last-candle
    call_date/entry convention record_prediction uses."""
    if not stock.candles:
        return
    score = score_one(stock.ticker, settings, cache)
    last = stock.candles[-1]
    tech = direction_for(score.base_net)  # pre-network vote; score.direction is the blended call
    store.upsert_prediction(
        ticker=stock.ticker, call_date=last.time, provider="rules", model="",
        recommendation=tech, confidence=min(1.0, abs(score.base_net)),
        sentiment=_SENTIMENT_FOR[tech], entry_price=last.close, source=SOURCE_TECHNICAL,
    )
    if score.network is not None:
        store.upsert_prediction(
            ticker=stock.ticker, call_date=last.time, provider="rules", model="",
            recommendation=score.direction, confidence=min(1.0, abs(score.net)),
            sentiment=_SENTIMENT_FOR[score.direction], entry_price=last.close,
            source=SOURCE_NETWORK,
        )
