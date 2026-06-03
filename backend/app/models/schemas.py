from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ProviderId = Literal["anthropic", "openai", "gemini", "ollama"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "ollama": "llama3.1",
}
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DISCLAIMER = "Not financial advice. For educational use only."


class Candle(BaseModel):
    time: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorPoint(BaseModel):
    time: str
    value: float


class Indicators(BaseModel):
    sma50: list[IndicatorPoint] = Field(default_factory=list)
    sma200: list[IndicatorPoint] = Field(default_factory=list)
    rsi14: list[IndicatorPoint] = Field(default_factory=list)
    dist_from_52wk_high_pct: Optional[float] = None


class Fundamentals(BaseModel):
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None


class PriceSummary(BaseModel):
    current: float
    change: float
    change_pct: float
    currency: str = "USD"


class NewsItem(BaseModel):
    title: str
    source: str = ""
    published_at: str = ""
    url: str = ""
    summary: str = ""


class StockData(BaseModel):
    ticker: str
    company_name: str
    as_of: str
    price: PriceSummary
    candles: list[Candle]
    fundamentals: Fundamentals
    indicators: Indicators
    news: list[NewsItem] = Field(default_factory=list)


class Signal(BaseModel):
    date: str
    action: Literal["buy", "sell"]
    price: float
    confidence: float
    reasoning: str


class AnalysisResult(BaseModel):
    ticker: str
    provider: str
    model: str
    generated_at: str
    overall_summary: str
    news_analysis: str
    sentiment: Literal["bullish", "neutral", "bearish"]
    current_recommendation: Literal["buy", "sell", "hold"]
    confidence: float
    key_factors: list[str] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class ProviderConfig(BaseModel):
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class IndicatorParams(BaseModel):
    sma_windows: list[int] = Field(default_factory=lambda: [50, 200])
    rsi_length: int = 14


class AlertConfig(BaseModel):
    enabled: bool = False
    channel: Literal["telegram", "log"] = "telegram"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    rsi_low: float = 30.0
    rsi_high: float = 70.0


class RuleHit(BaseModel):
    ticker: str
    rule_id: str
    action: Literal["buy", "sell"]
    candle_date: str
    message: str


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "anthropic": ProviderConfig(model=DEFAULT_MODELS["anthropic"]),
        "openai": ProviderConfig(model=DEFAULT_MODELS["openai"]),
        "gemini": ProviderConfig(model=DEFAULT_MODELS["gemini"]),
        "ollama": ProviderConfig(
            model=DEFAULT_MODELS["ollama"], base_url=DEFAULT_OLLAMA_BASE_URL
        ),
    }


class Settings(BaseModel):
    active_provider: ProviderId = "anthropic"
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)
    watchlist: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT"])
    indicator_params: IndicatorParams = Field(default_factory=IndicatorParams)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
