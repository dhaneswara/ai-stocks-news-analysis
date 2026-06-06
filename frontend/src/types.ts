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
export type RelationType = 'supplier' | 'customer' | 'partner' | 'competitor' | 'owner' | 'subsidiary';
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
export interface GraphEdge {
  source: string; target: string; type: RelationType; sentiment: EdgeSentiment;
  weight: number; confidence: number; evidence: string; url: string; as_of: string;
}
export interface KnowledgeGraph {
  as_of: string; scope: string; nodes: string[]; edges: GraphEdge[]; built: number; skipped: number;
}
export interface NetworkConfig {
  enabled: boolean; focus_top_n: number; max_edges_per_company: number;
  min_confidence: number; weight: number; alpha_event: number; beta_state: number;
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
export type ProviderId = 'anthropic' | 'openai' | 'gemini' | 'ollama';
export interface Settings {
  active_provider: ProviderId;
  providers: Record<string, ProviderConfig>;
  watchlist: string[];
  indicator_params: IndicatorParams;
  alerts: AlertConfig;
  truth_signal: TruthSignalConfig;
  screener: ScreenerConfig;
  network: NetworkConfig;
}
export interface ProviderInfo { id: string; label: string; configured: boolean; default_model: string; }
export interface TestResult { ok: boolean; message: string; }
