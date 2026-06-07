from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config.cache import Cache
from app.data.market import fetch_close_series
from app.evaluation.scoring import grade_for, is_hit, is_overconfident, score_call
from app.evaluation.store import PredictionStore
from app.llm.factory import build_provider
from app.models.schemas import (
    AnalysisResult,
    CompanyEvaluation,
    CompanyRollup,
    EvaluationBoard,
    HorizonResult,
    PredictionRecord,
    Settings,
    StockData,
)
from app.services.stock_service import get_stock_data

logger = logging.getLogger("evaluation")

EVAL_PERIOD = "2y"
EXPLAIN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


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


def build_board(store: PredictionStore, settings: Settings) -> EvaluationBoard:
    horizons = settings.evaluation.horizons
    eval_index = {(e.ticker, e.call_date, e.horizon): e for e in store.all_evals()}

    by_ticker: dict[str, list] = {}
    for p in store.all_predictions():
        by_ticker.setdefault(p.ticker, []).append(p)

    companies: list[CompanyEvaluation] = []
    for ticker, preds in by_ticker.items():
        preds.sort(key=lambda p: p.call_date, reverse=True)  # newest call first
        records: list[PredictionRecord] = []
        scores: list[float] = []
        hit_confs: list[float] = []
        miss_confs: list[float] = []

        for p in preds:
            results: list[HorizonResult] = []
            for h in horizons:
                e = eval_index.get((p.ticker, p.call_date, h))
                if e is None:
                    results.append(HorizonResult(horizon=h, status="pending"))
                    continue
                results.append(HorizonResult(
                    horizon=h, status="final", eval_date=e.eval_date,
                    return_pct=e.return_pct, hit=bool(e.hit), score=e.score,
                ))
                scores.append(e.score)
                (hit_confs if e.hit else miss_confs).append(p.confidence)
            records.append(PredictionRecord(
                ticker=p.ticker, call_date=p.call_date, provider=p.provider, model=p.model,
                recommendation=p.recommendation, confidence=p.confidence, sentiment=p.sentiment,
                entry_price=p.entry_price, results=results,
            ))

        n_matured = len(scores)
        n_hits = len(hit_confs)
        if n_matured:
            hit_rate: float | None = round(n_hits / n_matured * 100.0, 1)
            avg_score: float | None = round(sum(scores) / n_matured, 1)
            grade = grade_for(avg_score)
        else:
            hit_rate = avg_score = grade = None

        rollup = CompanyRollup(
            ticker=ticker, n_calls=len(preds), n_matured=n_matured,
            hit_rate=hit_rate, avg_score=avg_score, grade=grade,
            overconfident=is_overconfident(hit_confs, miss_confs),
            latest_recommendation=preds[0].recommendation, latest_call_date=preds[0].call_date,
        )
        companies.append(CompanyEvaluation(rollup=rollup, calls=records))

    companies.sort(key=lambda c: c.rollup.latest_call_date or "", reverse=True)
    return EvaluationBoard(as_of=datetime.now(timezone.utc).isoformat(), companies=companies)


def explain_prediction(ticker: str, call_date: str, settings: Settings, cache: Cache,
                       store: PredictionStore) -> str:
    """One short LLM post-mortem on why a call was off. Cached so it runs once per call."""
    ticker = ticker.upper().strip()
    pred = store.get_prediction(ticker, call_date)
    if pred is None:
        raise ValueError(f"No tracked prediction for {ticker} on {call_date}")

    key = f"prediction_explain:{ticker}:{call_date}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    evals = sorted(store.evals_for(ticker, call_date), key=lambda e: e.horizon)
    outcome_lines = [
        f"- {e.horizon} trading days later: {e.return_pct:+.2f}% "
        f"({'correct' if e.hit else 'wrong'})"
        for e in evals
    ] or ["- no matured horizons yet"]

    headlines: list[str] = []
    try:
        stock = get_stock_data(ticker, "1y", settings.indicator_params, cache)
        headlines = [n.title for n in stock.news[:8]]
    except Exception:  # noqa: BLE001
        logger.info("explain: news unavailable for %s", ticker)
    news_block = "\n".join(f"- {h}" for h in headlines) or "- (no recent headlines available)"

    system = (
        "You are a trading-analysis reviewer. In 3-4 sentences, explain why a past stock "
        "recommendation turned out to be inaccurate. Be concrete and concise. "
        "Not financial advice."
    )
    user = (
        f"Ticker: {ticker}\n"
        f"Call date: {call_date}\n"
        f"Recommendation: {pred.recommendation.upper()} (confidence {pred.confidence:.0%})\n"
        f"Entry price: {pred.entry_price:.2f}\n"
        "What actually happened:\n" + "\n".join(outcome_lines) + "\n\n"
        "Recent headlines:\n" + news_block + "\n\n"
        "Explain the most likely reasons the call was off, and what signal may have been missed."
    )
    provider = build_provider(settings)
    text = provider.complete(system, user).strip()
    cache.set(key, text, EXPLAIN_TTL_SECONDS)
    return text
