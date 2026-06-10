"""Multi-source signal recording + per-ticker signal summaries.

The deterministic scorer's calls (technical / network) are recorded through the SAME
PredictionStore the LLM paths use, so the evaluation engine judges every source by
identical rules."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from typing import Optional

from app.analysis.scoring import direction_for
from app.config.cache import Cache
from app.evaluation.scoring import grade_for, is_overconfident
from app.evaluation.store import (
    LLM_SOURCES,
    SOURCE_LLM_DEEP,
    SOURCE_LLM_FAST,
    SOURCE_NETWORK,
    SOURCE_TECHNICAL,
    SOURCES,
    PredictionStore,
)
from app.models.schemas import (
    LatestCall,
    Settings,
    SignalsAgreement,
    SignalsSummary,
    SourceSignal,
    SourceTrack,
    StockData,
)
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


_MIN_MATURED_FOR_WINNER = 3
_AGREEMENT_WINDOW_DAYS = 7   # ~5 trading days, calendar-approximated


def build_signals(ticker: str, store: PredictionStore, *,
                  today: Optional[date] = None) -> SignalsSummary:
    """Latest call + track record per source for one ticker, plus the agreement summary and
    the historically best source (>=3 matured evals; full ties get no crown). Reads only
    already-scored evals — maturing happens on the Evaluation page / CLI runs."""
    ticker = ticker.upper().strip()
    preds = [p for p in store.all_predictions() if p.ticker == ticker]
    eval_rows = [e for e in store.all_evals() if e.ticker == ticker]

    sources: dict[str, Optional[SourceSignal]] = {}
    for src in SOURCES:
        sp = sorted((p for p in preds if p.source == src), key=lambda p: p.call_date)
        if not sp:
            sources[src] = None
            continue
        es = [e for e in eval_rows if e.source == src]
        hit_rate = avg = grade = None
        if es:
            avg = round(sum(e.score for e in es) / len(es), 1)
            hit_rate = round(100.0 * sum(1 for e in es if e.hit) / len(es), 1)
            grade = grade_for(avg)
        latest = sp[-1]
        sources[src] = SourceSignal(
            latest=LatestCall(call_date=latest.call_date,
                              recommendation=latest.recommendation,
                              confidence=latest.confidence),
            track=SourceTrack(n_calls=len(sp), n_matured=len(es), hit_rate=hit_rate,
                              avg_score=avg, grade=grade),
        )

    qualified = sorted(
        ((src, s.track) for src, s in sources.items()
         if s is not None and s.track.n_matured >= _MIN_MATURED_FOR_WINNER),
        key=lambda kv: (kv[1].avg_score, kv[1].n_matured), reverse=True,
    )
    winner = None
    if qualified and (len(qualified) == 1 or
                      (qualified[0][1].avg_score, qualified[0][1].n_matured)
                      != (qualified[1][1].avg_score, qualified[1][1].n_matured)):
        winner = qualified[0][0]

    cutoff = ((today or date.today()) - timedelta(days=_AGREEMENT_WINDOW_DAYS)).isoformat()
    votes = [s.latest.recommendation for s in sources.values()
             if s is not None and s.latest.call_date >= cutoff]
    agreement = SignalsAgreement()
    if votes:
        counts = Counter(votes)
        on, agreeing = counts.most_common(1)[0]
        agreement = SignalsAgreement(counted=len(votes), agreeing=agreeing, on=on,
                                     conflict=len(counts) > 1)
    return SignalsSummary(ticker=ticker, sources=sources, agreement=agreement, winner=winner)
