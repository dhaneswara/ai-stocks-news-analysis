export interface Candle { time: string; open: number; high: number; low: number; close: number; volume: number; }
export interface IndicatorPoint { time: string; value: number; }
export interface Indicators {
  sma50: IndicatorPoint[];
  sma200: IndicatorPoint[];
  rsi14: IndicatorPoint[];
  dist_from_52wk_high_pct: number | null;
}
export interface Fundamentals {
  market_cap: number | null;
  pe_ratio: number | null;
  eps: number | null;
  dividend_yield: number | null;
  week52_high: number | null;
  week52_low: number | null;
}
export interface PriceSummary { current: number; change: number; change_pct: number; currency: string; }
export interface NewsItem { title: string; source: string; published_at: string; url: string; summary: string; }
export interface MoodTheme { label: string; lean: 'bullish' | 'bearish' | 'neutral'; quote: string; post_url: string; created_at: string; }
export interface MarketMood { lean: 'risk_on' | 'neutral' | 'risk_off'; confidence: number; summary: string; themes: MoodTheme[]; as_of: string; post_count: number; }
export interface Mention { post_id: string; created_at: string; matched: string; excerpt: string; url: string; }
export type RelationType = 'supplier' | 'customer' | 'partner' | 'competitor' | 'owner' | 'subsidiary' | 'other';
export type EdgeSentiment = 'positive' | 'negative' | 'neutral';
export interface NetworkInfluence {
  neighbour: string;
  name: string;
  type: RelationType;
  edge_sentiment: EdgeSentiment;
  neighbour_direction: string;
  signed: number;
  reason: string;
}
export interface NetworkSignal {
  ticker: string;
  intensity: number;
  signed: number;
  influences: NetworkInfluence[];
  reasons: string[];
}
export interface NodeMeta { label: string; kind: string; source: 'native' | 'imported' | 'manual'; }
export interface GraphEdge {
  source: string; target: string; type: RelationType; sentiment: EdgeSentiment;
  weight: number; confidence: number; evidence: string; url: string; as_of: string;
  origin?: 'extracted' | 'imported' | 'manual';
}
export interface KnowledgeGraph {
  as_of: string; scope: string; nodes: string[]; edges: GraphEdge[]; built: number; skipped: number;
  node_meta?: Record<string, NodeMeta>;
}
export interface NetworkConfig {
  enabled: boolean; focus_top_n: number; max_edges_per_company: number;
  min_confidence: number; weight: number; alpha_event: number; beta_state: number;
  symmetric_types: RelationType[];
}
export interface TruthSignalConfig { enabled: boolean; source_url: string; lookback_hours: number; }
export interface StockScore {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  change_pct: number;
  score: number;
  net: number;
  direction: Recommendation;
  reasons: string[];
  components: Record<string, number>;
  as_of: string;
  network?: NetworkSignal | null;
}
export interface ScreenBoard {
  as_of: string;
  scope: string;
  scanned: number;
  skipped: number;
  items: StockScore[];
}
export interface StockData {
  ticker: string;
  company_name: string;
  as_of: string;
  price: PriceSummary;
  candles: Candle[];
  fundamentals: Fundamentals;
  indicators: Indicators;
  news: NewsItem[];
  market_mood?: MarketMood | null;
  trump_mentions?: Mention[];
  network?: NetworkSignal | null;
}
export type Action = 'buy' | 'sell';
export interface Signal { date: string; action: Action; price: number; confidence: number; reasoning: string; }
export type Sentiment = 'bullish' | 'neutral' | 'bearish';
export type Recommendation = 'buy' | 'sell' | 'hold';
export interface AnalysisResult {
  ticker: string;
  provider: string;
  model: string;
  generated_at: string;
  overall_summary: string;
  news_analysis: string;
  sentiment: Sentiment;
  current_recommendation: Recommendation;
  confidence: number;
  key_factors: string[];
  signals: Signal[];
  risks: string[];
  disclaimer: string;
  market_mood?: MarketMood | null;
  network?: NetworkSignal | null;
}
export type Grade = 'Strong' | 'Mixed' | 'Weak';

export type Source = 'llm_fast' | 'llm_deep' | 'technical' | 'network';

export interface SourceTrack {
  n_calls: number;
  n_matured: number;
  hit_rate: number | null;
  avg_score: number | null;
  grade: Grade | null;
}

export interface LatestCall {
  call_date: string;
  recommendation: Recommendation;
  confidence: number;
}

export interface SourceSignal {
  latest: LatestCall;
  track: SourceTrack;
}

export interface SignalsAgreement {
  counted: number;
  agreeing: number;
  on: Recommendation | null;
  conflict: boolean;
}

export interface SignalsSummary {
  ticker: string;
  sources: Partial<Record<Source, SourceSignal | null>>;
  agreement: SignalsAgreement;
  winner: Source | null;
}

export interface SnapshotResult {
  recorded: number;
  skipped: { ticker: string; reason: string }[];
}

export type TickerRunStatus = 'running' | 'done' | 'skipped' | 'failed';

/** One SSE frame of a watchlist-wide LLM batch run (mode=fast|deep). */
export interface WatchlistRunEvent {
  type: 'start' | 'ticker' | 'done' | 'error';
  ticker?: string;
  index?: number;
  total?: number;
  status?: TickerRunStatus;
  recommendation?: Recommendation | '';
  confidence?: number;
  fell_back?: boolean;
  error?: string;
  analyzed?: number;
  skipped?: number;
  failed?: number;
  message?: string;
  tickers?: string[];
}

export interface HorizonResult {
  horizon: number;
  status: 'pending' | 'final';
  eval_date?: string | null;
  return_pct?: number | null;
  hit?: boolean | null;
  score?: number | null;
}
export interface PredictionRecord {
  ticker: string;
  call_date: string;
  provider: string;
  model: string;
  recommendation: Recommendation;
  confidence: number;
  sentiment: Sentiment;
  entry_price: number;
  source: Source;
  results: HorizonResult[];
}
export interface CompanyRollup {
  ticker: string;
  n_calls: number;
  n_matured: number;
  hit_rate: number | null;
  avg_score: number | null;
  grade: Grade | null;
  overconfident: boolean;
  latest_recommendation: Recommendation | null;
  latest_call_date: string | null;
}
export interface CompanyEvaluation {
  rollup: CompanyRollup;
  calls: PredictionRecord[];
  by_source: Partial<Record<Source, SourceTrack>>;
}
export interface EvaluationBoard {
  as_of: string;
  companies: CompanyEvaluation[];
  sources: Partial<Record<Source, SourceTrack>>;
}
export interface EvaluationConfig {
  enabled: boolean;
  horizons: number[];
  hold_band_pct: number;
  score_scale_pct: number;
}
export interface ProviderConfig { model: string; api_key: string; base_url: string; }
export interface IndicatorParams { sma_windows: number[]; rsi_length: number; }
export interface AlertConfig {
  enabled: boolean;
  channel: 'telegram' | 'log';
  telegram_bot_token: string;
  telegram_chat_id: string;
  rsi_low: number;
  rsi_high: number;
}
export interface ScreenerConfig {
  enabled: boolean;
  top_n: number;
  default_sector: string | null;
  rsi_low: number;
  rsi_high: number;
  weights: Record<string, number>;
}
export type ProviderId = 'anthropic' | 'openai' | 'gemini' | 'ollama' | 'deepseek';
export interface Settings {
  active_provider: ProviderId;
  providers: Record<string, ProviderConfig>;
  watchlist: string[];
  indicator_params: IndicatorParams;
  alerts: AlertConfig;
  truth_signal: TruthSignalConfig;
  screener: ScreenerConfig;
  network: NetworkConfig;
  evaluation: EvaluationConfig;
}
export interface ProviderInfo { id: string; label: string; configured: boolean; default_model: string; }
export interface TestResult { ok: boolean; message: string; }
export interface SavedGraphVersion { root: string; saved_at: string; expanded: string[]; graph: KnowledgeGraph; }
export interface SavedGraphSummary { root: string; versions: string[]; }
export interface ImportSetSummary {
  id: string; name: string; as_of: string; created_at: string; node_count: number; edge_count: number;
}
export interface ImportReport {
  id: string; name: string; nodes_added: number; edges_added: number; dropped: number; warnings: string[];
}
export interface AgentStep {
  index: number;
  thought: string;
  action: string | null;
  action_args: Record<string, unknown>;
  observation: string | null;
  is_final: boolean;
  elapsed_ms: number;
  raw?: string;
}
export interface AgentTrace {
  ticker: string;
  provider: string;
  model: string;
  started_at: string;
  elapsed_ms: number;
  stopped_reason: 'final' | 'max_steps' | 'parse_error' | 'no_action';
  fell_back: boolean;
  steps: AgentStep[];
  final: AnalysisResult | null;
}
export interface AgentEvent {
  type: 'step' | 'final' | 'error';
  step?: AgentStep | null;
  result?: AnalysisResult | null;
  trace?: AgentTrace | null;
  message?: string;
}
