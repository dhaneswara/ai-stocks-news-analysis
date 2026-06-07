from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ProviderId = Literal["anthropic", "openai", "gemini", "ollama", "deepseek"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "ollama": "llama3.1",
    "deepseek": "deepseek-chat",
}
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
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


class UniverseEntry(BaseModel):
    ticker: str
    name: str
    sector: str


class TruthPost(BaseModel):
    id: str
    created_at: str
    content: str
    url: str = ""


class MoodTheme(BaseModel):
    label: str
    lean: Literal["bullish", "bearish", "neutral"] = "neutral"
    quote: str = ""
    post_url: str = ""
    created_at: str = ""


class MarketMood(BaseModel):
    lean: Literal["risk_on", "neutral", "risk_off"] = "neutral"
    confidence: float = 0.0
    summary: str = ""
    themes: list[MoodTheme] = Field(default_factory=list)
    as_of: str = ""
    post_count: int = 0


class Mention(BaseModel):
    post_id: str
    created_at: str
    matched: str
    excerpt: str
    url: str = ""


RelationType = Literal["supplier", "customer", "partner", "competitor", "owner", "subsidiary", "other"]


class NodeMeta(BaseModel):
    label: str = ""
    kind: str = ""
    source: Literal["native", "imported"] = "native"


class GraphEdge(BaseModel):
    source: str
    target: str
    type: RelationType
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"  # effect ON THE SOURCE
    weight: float = 0.5        # 0..1 materiality
    confidence: float = 0.5    # 0..1 extraction confidence
    evidence: str = ""
    url: str = ""
    as_of: str = ""
    origin: Literal["extracted", "imported"] = "extracted"


class KnowledgeGraph(BaseModel):
    as_of: str = ""
    scope: str = "focus"
    nodes: list[str] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    node_meta: dict[str, NodeMeta] = Field(default_factory=dict)
    built: int = 0
    skipped: int = 0


class SavedGraphVersion(BaseModel):
    root: str
    saved_at: str = ""
    expanded: list[str] = Field(default_factory=list)
    graph: KnowledgeGraph = Field(default_factory=KnowledgeGraph)


class SavedGraphSummary(BaseModel):
    root: str
    versions: list[str] = Field(default_factory=list)


class ImportSetSummary(BaseModel):
    id: str = ""
    name: str = ""
    as_of: str = ""
    created_at: str = ""
    node_count: int = 0
    edge_count: int = 0


class ImportReport(BaseModel):
    id: str = ""
    name: str = ""
    nodes_added: int = 0
    edges_added: int = 0
    dropped: int = 0
    warnings: list[str] = Field(default_factory=list)


class NetworkInfluence(BaseModel):
    neighbour: str
    name: str = ""
    type: RelationType
    edge_sentiment: Literal["positive", "negative", "neutral"] = "neutral"
    neighbour_direction: Literal["buy", "sell", "hold", "unknown"] = "unknown"
    signed: float = 0.0
    reason: str = ""


class NetworkSignal(BaseModel):
    ticker: str
    intensity: float = 0.0
    signed: float = 0.0
    influences: list[NetworkInfluence] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class NetworkConfig(BaseModel):
    enabled: bool = True
    focus_top_n: int = 30
    max_edges_per_company: int = 8
    min_confidence: float = 0.4
    weight: float = 0.5        # the tilt cap (network family weight)
    alpha_event: float = 0.6   # blend weight on the edge news-event term
    beta_state: float = 0.4    # blend weight on the neighbour-state term


class EvaluationConfig(BaseModel):
    enabled: bool = True
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 20])
    hold_band_pct: float = 2.0     # |return %| <= this counts as "flat" (the hold target)
    score_scale_pct: float = 5.0   # the move size (in %) that maps to a full 0 or 100 score


class StockData(BaseModel):
    ticker: str
    company_name: str
    as_of: str
    price: PriceSummary
    candles: list[Candle]
    fundamentals: Fundamentals
    indicators: Indicators
    news: list[NewsItem] = Field(default_factory=list)
    market_mood: Optional[MarketMood] = None
    trump_mentions: list[Mention] = Field(default_factory=list)
    network: Optional[NetworkSignal] = None


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
    market_mood: Optional[MarketMood] = None
    network: Optional[NetworkSignal] = None


class HorizonResult(BaseModel):
    horizon: int
    status: Literal["pending", "final"] = "pending"
    eval_date: Optional[str] = None
    return_pct: Optional[float] = None
    hit: Optional[bool] = None
    score: Optional[float] = None


class PredictionRecord(BaseModel):
    ticker: str
    call_date: str
    provider: str = ""
    model: str = ""
    recommendation: Literal["buy", "sell", "hold"]
    confidence: float = 0.0
    sentiment: Literal["bullish", "neutral", "bearish"] = "neutral"
    entry_price: float
    results: list[HorizonResult] = Field(default_factory=list)


class CompanyRollup(BaseModel):
    ticker: str
    n_calls: int = 0
    n_matured: int = 0
    hit_rate: Optional[float] = None
    avg_score: Optional[float] = None
    grade: Optional[Literal["Strong", "Mixed", "Weak"]] = None
    overconfident: bool = False
    latest_recommendation: Optional[Literal["buy", "sell", "hold"]] = None
    latest_call_date: Optional[str] = None


class CompanyEvaluation(BaseModel):
    rollup: CompanyRollup
    calls: list[PredictionRecord] = Field(default_factory=list)


class EvaluationBoard(BaseModel):
    as_of: str = ""
    companies: list[CompanyEvaluation] = Field(default_factory=list)


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


class TruthSignalConfig(BaseModel):
    enabled: bool = True
    source_url: str = "https://ix.cnn.io/data/truth-social/truth_archive.json"
    lookback_hours: int = 48


class RuleHit(BaseModel):
    ticker: str
    rule_id: str
    action: Literal["buy", "sell"]
    candle_date: str
    message: str


class StockScore(BaseModel):
    ticker: str
    name: str
    sector: str = ""
    price: float
    change_pct: float
    score: float                       # 0–100 opportunity
    direction: Literal["buy", "sell", "hold"]
    reasons: list[str] = Field(default_factory=list)
    components: dict[str, float] = Field(default_factory=dict)
    as_of: str = ""
    net: float = 0.0
    base_net: float = 0.0              # pre-network directional vote (lets re-blend stay idempotent)
    base_score: float = 0.0           # pre-network 0–100 score (lets re-blend stay idempotent)
    network: Optional[NetworkSignal] = None


class ScreenBoard(BaseModel):
    as_of: str = ""
    scope: str = "all"
    scanned: int = 0
    skipped: int = 0
    items: list[StockScore] = Field(default_factory=list)


def _default_screener_weights() -> dict[str, float]:
    return {"extremes": 1.0, "trend": 1.0, "momentum": 0.8, "volume": 0.4, "catalyst": 0.5}


class ScreenerConfig(BaseModel):
    enabled: bool = True
    top_n: int = 25
    default_sector: Optional[str] = None
    rsi_low: float = 30.0
    rsi_high: float = 70.0
    weights: dict[str, float] = Field(default_factory=_default_screener_weights)


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "anthropic": ProviderConfig(model=DEFAULT_MODELS["anthropic"]),
        "openai": ProviderConfig(model=DEFAULT_MODELS["openai"]),
        "gemini": ProviderConfig(model=DEFAULT_MODELS["gemini"]),
        "ollama": ProviderConfig(
            model=DEFAULT_MODELS["ollama"], base_url=DEFAULT_OLLAMA_BASE_URL
        ),
        "deepseek": ProviderConfig(
            model=DEFAULT_MODELS["deepseek"], base_url=DEFAULT_DEEPSEEK_BASE_URL
        ),
    }


class Settings(BaseModel):
    active_provider: ProviderId = "anthropic"
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)
    watchlist: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT"])
    indicator_params: IndicatorParams = Field(default_factory=IndicatorParams)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    truth_signal: TruthSignalConfig = Field(default_factory=TruthSignalConfig)
    screener: ScreenerConfig = Field(default_factory=ScreenerConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    @model_validator(mode="after")
    def _ensure_all_providers(self) -> "Settings":
        for pid, cfg in _default_providers().items():
            self.providers.setdefault(pid, cfg)
        return self
