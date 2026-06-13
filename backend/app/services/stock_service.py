from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from app.analysis.indicators import compute_indicators
from app.config.cache import Cache
from app.data.market import (
    build_candles,
    build_fundamentals,
    build_price,
    company_name,
    fetch_history,
    fetch_info,
    friendly_exchange,
)
from app.data.news import get_news
from app.models.schemas import IndicatorParams, StockData

STOCK_TTL_SECONDS = 30 * 60  # 30 minutes


def get_stock_data(
    ticker: str,
    period: str,
    params: IndicatorParams,
    cache: Cache,
) -> StockData:
    ticker = ticker.upper().strip()
    cache_key = f"stock:{ticker}:{period}"
    cached = cache.get(cache_key)
    if cached is not None:
        try:
            return StockData.model_validate_json(cached)
        except ValidationError:
            # Corrupt/poisoned entry (e.g. a NaN price serialized to JSON null) —
            # discard and re-fetch fresh rather than failing the request.
            pass

    df = fetch_history(ticker, period)
    if df is None or df.empty:
        raise ValueError(f"No price history for ticker '{ticker}'")

    info = fetch_info(ticker)
    name = company_name(info, ticker)
    data = StockData(
        ticker=ticker,
        company_name=name,
        as_of=datetime.now(timezone.utc).isoformat(),
        exchange=friendly_exchange(info),
        sector=str(info.get("sector") or ""),
        price=build_price(df),
        candles=build_candles(df),
        fundamentals=build_fundamentals(info),
        indicators=compute_indicators(df, params),
        news=get_news(ticker, name, limit=10),
    )
    cache.set(cache_key, data.model_dump_json(), STOCK_TTL_SECONDS)
    return data
