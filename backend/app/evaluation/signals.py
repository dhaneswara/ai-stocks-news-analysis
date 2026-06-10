"""Multi-source signal recording + per-ticker signal summaries.

The deterministic scorer's calls (technical / network) are recorded through the SAME
PredictionStore the LLM paths use, so the evaluation engine judges every source by
identical rules."""
from __future__ import annotations

import logging
from typing import Optional

from app.analysis.scoring import direction_for
from app.config.cache import Cache
from app.evaluation.scoring import is_overconfident
from app.evaluation.store import (
    LLM_SOURCES,
    SOURCE_LLM_DEEP,
    SOURCE_LLM_FAST,
    SOURCE_NETWORK,
    SOURCE_TECHNICAL,
    PredictionStore,
)
from app.models.schemas import Settings, StockData
from app.screener.service import SCAN_PERIOD, score_one
from app.services.stock_service import get_stock_data

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


def snapshot_watchlist(settings: Settings, cache: Cache, store: PredictionStore) -> dict:
    """Record today's technical/network calls for every watchlist ticker (the Discover page
    fires this after Rescan All). Per-ticker isolation: one bad ticker is skipped and
    reported, the rest record. Stock data is read via the same
    cache the rescan just populated (cold calls fall back to a live fetch; score_one's
    internal fetch hits the same cache entry)."""
    recorded, skipped = 0, []
    for raw in settings.watchlist:
        ticker = raw.upper().strip()
        try:
            stock = get_stock_data(ticker, SCAN_PERIOD, settings.indicator_params, cache)
            if not stock.candles:
                skipped.append({"ticker": ticker, "reason": "no candles"})
                continue
            record_deterministic_pair(stock, settings, cache, store)
            recorded += 1
        except Exception as exc:  # noqa: BLE001 — isolate per-ticker failures
            logger.warning("signal snapshot failed for %s", ticker)
            skipped.append({"ticker": ticker, "reason": str(exc)})
    return {"recorded": recorded, "skipped": skipped}


def build_track_record_block(ticker: str, store: PredictionStore,
                             settings: Settings) -> Optional[str]:
    """Compact 'your own history on this name' block for the LLM prompt, or None when there
    is nothing scored yet — the prompt must stay byte-identical for fresh tickers."""
    if not settings.evaluation.enabled:
        return None
    ticker = ticker.upper().strip()
    preds = sorted(
        (p for p in store.all_predictions()
         if p.ticker == ticker and p.source in LLM_SOURCES),
        key=lambda p: p.call_date, reverse=True,
    )
    if not preds:
        return None
    evals = [e for e in store.all_evals() if e.ticker == ticker and e.source in LLM_SOURCES]
    by_call: dict[tuple[str, str], list] = {}
    for e in evals:
        by_call.setdefault((e.call_date, e.source), []).append(e)
    matured = [(p, sorted(by_call[(p.call_date, p.source)], key=lambda e: e.horizon))
               for p in preds if (p.call_date, p.source) in by_call]
    if not matured:
        return None

    lines = []
    for p, es in matured[:5]:
        mode = "deep" if p.source == SOURCE_LLM_DEEP else "fast"
        outcomes = ", ".join(
            f"{e.return_pct:+.1f}% @{e.horizon}d {'✓' if e.hit else '✗'}" for e in es)
        lines.append(f"- {p.call_date} [{mode}] {p.recommendation.upper()} "
                     f"(conf {p.confidence:.0%}): {outcomes}")

    horizons = settings.evaluation.horizons
    mid = horizons[len(horizons) // 2] if horizons else 5
    conf_by_call = {(p.call_date, p.source): p.confidence for p, _ in matured}
    mid_evals = [e for e in evals
                 if e.horizon == mid and (e.call_date, e.source) in conf_by_call]
    summary = ""
    if mid_evals:
        rate = 100.0 * sum(1 for e in mid_evals if e.hit) / len(mid_evals)
        summary = f"\nAcross your scored calls you hit {rate:.0f}% at {mid} trading days."
        hit_confs = [conf_by_call[(e.call_date, e.source)] for e in mid_evals if e.hit]
        miss_confs = [conf_by_call[(e.call_date, e.source)] for e in mid_evals if not e.hit]
        if is_overconfident(hit_confs, miss_confs):
            summary += (
                f" Your average confidence on misses "
                f"({sum(miss_confs) / len(miss_confs):.2f}) is at least your confidence on "
                f"hits ({sum(hit_confs) / len(hit_confs):.2f}) — you skew overconfident.")
    return ("\n".join(lines) + summary +
            "\nCalibrate this call's confidence accordingly.")
