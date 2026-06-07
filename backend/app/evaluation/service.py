from __future__ import annotations

import logging

from app.data.market import fetch_close_series
from app.evaluation.scoring import is_hit, score_call
from app.evaluation.store import PredictionStore
from app.models.schemas import AnalysisResult, Settings, StockData

logger = logging.getLogger("evaluation")

EVAL_PERIOD = "2y"


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


def evaluate_pending(store: PredictionStore, settings: Settings, *, persist: bool = True) -> dict:
    """Score every matured-but-unscored horizon. Fetches price history once per ticker,
    only for tickers that still have an unresolved horizon. Idempotent: already-final
    horizons are skipped. A per-ticker fetch failure is logged and retried next run."""
    horizons = settings.evaluation.horizons
    by_ticker: dict[str, list] = {}
    for p in store.all_predictions():
        by_ticker.setdefault(p.ticker, []).append(p)

    summary = {"tickers": 0, "evaluated": 0, "pending": 0}
    for ticker, preds in by_ticker.items():
        missing = [
            (p, h) for p in preds for h in horizons
            if not store.has_eval(p.ticker, p.call_date, h)
        ]
        if not missing:
            continue
        summary["tickers"] += 1
        try:
            series = fetch_close_series(ticker, EVAL_PERIOD)
        except Exception:  # noqa: BLE001
            logger.warning("evaluation: could not fetch history for %s", ticker)
            summary["pending"] += len(missing)
            continue

        dates = [d for d, _ in series]
        close_by_date = dict(series)
        index_of = {d: i for i, d in enumerate(dates)}

        for p, h in missing:
            i = index_of.get(p.call_date)
            if i is None or i + h >= len(dates):
                summary["pending"] += 1
                continue
            exit_date = dates[i + h]
            exit_price = close_by_date[exit_date]
            return_pct = ((exit_price - p.entry_price) / p.entry_price * 100.0
                          if p.entry_price else 0.0)
            hit = is_hit(p.recommendation, return_pct, settings.evaluation.hold_band_pct)
            sc = score_call(p.recommendation, return_pct,
                            settings.evaluation.hold_band_pct, settings.evaluation.score_scale_pct)
            if persist:
                store.record_eval(p.ticker, p.call_date, h, exit_date, exit_price,
                                  return_pct, int(hit), sc)
            summary["evaluated"] += 1
    return summary
