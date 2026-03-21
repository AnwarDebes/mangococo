export interface Position {
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  current_price: number;
  amount: number;
  unrealized_pnl: number;
  stop_loss_price?: number;
  take_profit_price?: number;
  opened_at: string;
  peak_pnl_pct?: number;
  trailing_active?: boolean;
}

export interface Trade {
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  exit_price: number;
  amount: number;
  realized_pnl: number;
  pnl_pct: number;
  exit_reason: string;
  strategy: string;
  hold_time_seconds: number;
  created_at: string;
  closed_at: string;
}

export interface PaginatedTrades {
  trades: Trade[];
  total: number;
}

export interface Signal {
  signal_id: string;
  symbol: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  price: number;
  timestamp: string;
}

export interface PortfolioState {
  total_value: number;
  cash_balance: number;
  positions_value: number;
  daily_pnl: number;
  open_positions: number;
}

export interface SystemHealth {
  service_name: string;
  status: "healthy" | "degraded" | "down";
  uptime: number;
  last_heartbeat: string;
}

export interface SentimentData {
  symbol: string;
  score: number;
  momentum_1h: number;
  momentum_24h: number;
  volume: number;
  fear_greed_index: number;
}

export interface ModelStatus {
  model_name: string;
  version: string;
  accuracy: number;
  last_retrain: string;
  status: "active" | "training" | "inactive";
}

export interface SignalExplanation {
  signal_id: string;
  symbol: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  timestamp: string;
  tcn_prediction: { direction: string; confidence: number; weight: number } | null;
  xgb_prediction: { direction: string; confidence: number; weight: number } | null;
  models_agree: boolean;
  top_factors: Array<{
    feature: string;
    value: number;
    impact: number;
    direction: "bullish" | "bearish" | "neutral";
    description: string;
  }>;
  market_snapshot: {
    price: number;
    rsi: number | null;
    macd_signal: string | null;
    volume_vs_avg: number | null;
    trend: string | null;
    volatility: string | null;
    support_level: number | null;
    resistance_level: number | null;
  };
  risk_assessment: {
    risk_score: number | null;
    position_size_pct: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    risk_reward_ratio: number | null;
  };
  data_quality?: "real" | "partial" | "unavailable";
}

/* ── Phase 4: War Room ───────────────────────────────────────────── */

export interface PredictionCone {
  symbol: string;
  current_price: number;
  prediction: { direction: "up" | "down"; confidence: number };
  cone: {
    "1h": { upper: number; mid: number; lower: number };
    "4h": { upper: number; mid: number; lower: number };
    "24h": { upper: number; mid: number; lower: number };
  };
  historical: number[];
}

export interface FactorCell {
  value: number;
  direction: "bullish" | "bearish" | "neutral";
  description: string;
}

export interface FactorRow {
  symbol: string;
  factors: Record<string, FactorCell>;
}

/* ── Phase 4: Whale Activity ─────────────────────────────────────── */

export interface WhaleTransaction {
  symbol: string;
  amount_usd: number;
  direction: "exchange_inflow" | "exchange_outflow" | "transfer";
  from_label: string;
  to_label: string;
  timestamp: string;
  significance: "bullish" | "bearish" | "neutral";
}

export interface WhaleData {
  transactions: WhaleTransaction[];
  summary: {
    net_exchange_flow_btc: number;
    net_exchange_flow_eth: number;
    whale_sentiment: "accumulation" | "distribution" | "neutral";
  };
}

/* ── Phase 4: Market Replay ──────────────────────────────────────── */

export interface ReplayEvent {
  type: "candle" | "signal" | "trade";
  time: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  symbol?: string;
  action?: "BUY" | "SELL" | "HOLD";
  confidence?: number;
  side?: string;
  price?: number;
  amount?: number;
  pnl?: number;
}

export interface ReplayData {
  events: ReplayEvent[];
  total_events: number;
}

/* ── Phase 4: Stress Test ────────────────────────────────────────── */

export interface StressScenario {
  name: string;
  crash_pct: number;
  duration_days: number;
}

export interface StressResult {
  scenario: string;
  original_value: number;
  stressed_value: number;
  total_loss: number;
  total_loss_pct: number;
  positions_liquidated: number;
  positions_survived: number;
  stop_loss_savings: number;
  cash_remaining: number;
  recovery_days: number;
  per_position: Array<{
    symbol: string;
    original_value: number;
    stressed_value: number;
    loss: number;
    stop_loss_triggered: boolean;
  }>;
}

/* ── Phase 4: Strategy Builder ───────────────────────────────────── */

export interface StrategyNode {
  id: string;
  type: "trigger" | "condition" | "action";
  name: string;
  category: string;
  params: Record<string, number | string | boolean>;
  x: number;
  y: number;
}

export interface StrategyConnection {
  id: string;
  from: string;
  to: string;
}

export interface StrategyGraph {
  nodes: StrategyNode[];
  connections: StrategyConnection[];
}

/* ── Phase 4: Chat ───────────────────────────────────────────────── */

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

/* ── Phase 5: Market Intelligence ───────────────────────────────── */

export interface FearGreedData {
  data: Array<{
    value: string;
    value_classification: string;
    timestamp: string;
  }>;
}

export interface GlobalMarketData {
  data: {
    total_market_cap: Record<string, number>;
    total_volume: Record<string, number>;
    market_cap_percentage: Record<string, number>;
    active_cryptocurrencies: number;
    market_cap_change_percentage_24h_usd: number;
  };
}

export interface TopCoin {
  id: string;
  symbol: string;
  name: string;
  image: string;
  current_price: number;
  market_cap: number;
  market_cap_rank: number;
  price_change_percentage_1h_in_currency: number;
  price_change_percentage_24h_in_currency: number;
  price_change_percentage_7d_in_currency: number;
  sparkline_in_7d: { price: number[] };
}

export interface TrendingCoin {
  item: {
    id: string;
    name: string;
    symbol: string;
    market_cap_rank: number;
    thumb: string;
    score: number;
    data?: {
      price_change_percentage_24h?: Record<string, number>;
    };
  };
}

export interface DefiOverview {
  total_tvl: number;
  top_protocols: Array<{
    name: string;
    tvl: number;
    change_1d: number;
    change_7d: number;
    category: string;
    logo: string;
  }>;
  top_chains: Array<{ name: string; tvl: number }>;
}

export interface StablecoinData {
  total_supply: number;
  top_stablecoins: Array<{
    name: string;
    symbol: string;
    supply: number;
    price: number;
  }>;
}

export interface BitcoinNetworkData {
  fees: {
    fastestFee: number;
    halfHourFee: number;
    hourFee: number;
    economyFee: number;
    minimumFee: number;
  };
  mempool: {
    count: number;
    vsize: number;
    total_fee: number;
  };
  mining: {
    currentHashrate: number;
    currentDifficulty: number;
    hashrates: Array<{ timestamp: number; avgHashrate: number }>;
  };
  difficulty: {
    progressPercent: number;
    difficultyChange: number;
    estimatedRetargetDate: number;
    remainingBlocks: number;
    previousRetarget: number;
  };
}

export interface DexVolumeData {
  chart: Array<[number, number]>;
  total_24h: number;
  top_dexs: Array<{
    name: string;
    volume_24h: number;
    change_1d: number;
  }>;
}

/* ── Phase 5: Derivatives Intelligence ──────────────────────────── */

export interface FundingSymbol {
  symbol: string;
  mark_price: number;
  current_rate: number;
  next_funding_time: number;
  history: Array<{ rate: number; time: number }>;
}

export interface FundingData {
  symbols: FundingSymbol[];
}

export interface OpenInterestData {
  current: { symbol: string; openInterest: string; time: number };
  history: Array<{
    symbol: string;
    sumOpenInterest: string;
    sumOpenInterestValue: string;
    timestamp: number;
  }>;
}

export interface LongShortData {
  long_short_ratio: Array<{
    symbol: string;
    longShortRatio: string;
    longAccount: string;
    shortAccount: string;
    timestamp: number;
  }>;
  taker_volume: Array<{
    buySellRatio: string;
    buyVol: string;
    sellVol: string;
    timestamp: number;
  }>;
}

/* ── Phase 5: Correlation Matrix ────────────────────────────────── */

export interface CorrelationData {
  symbols: string[];
  matrix: Record<string, Record<string, number>>;
  period: string;
  data_points: number;
}

/* ── Phase 5: Multi-Timeframe ───────────────────────────────────── */

export interface MultiTimeframeCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MultiTimeframeData {
  "5m": MultiTimeframeCandle[];
  "15m": MultiTimeframeCandle[];
  "1h": MultiTimeframeCandle[];
  "4h": MultiTimeframeCandle[];
}

/* ── Phase 5: Benchmark ─────────────────────────────────────────── */

export interface BenchmarkData {
  dates: string[];
  btc: number[];
  eth: number[];
  data_points: number;
}

/* ── Phase 6: AI Activity Logs ─────────────────────────────────── */

export type AILogCategory =
  | "prediction" | "signal" | "trade" | "sentiment"
  | "risk" | "model" | "market" | "portfolio"
  | "whale" | "system" | "chat" | "strategy";

export type AILogLevel = "debug" | "info" | "warning" | "error" | "critical";

export interface AILogEntry {
  id: string;
  timestamp: string;
  category: AILogCategory;
  level: AILogLevel;
  service: string;
  message: string;
  symbol?: string;
  confidence?: number;
  decision_impact?: string;
  chain_id?: string;
  details: Record<string, unknown>;
}

export interface AIStats {
  total_events_today: number;
  events_by_category: Record<string, number>;
  events_by_level: Record<string, number>;
  top_symbols: Array<{ symbol: string; count: number }>;
  avg_confidence_by_category: Record<string, number>;
}

export interface AIDecisionChain {
  chain_id: string;
  events: AILogEntry[];
  outcome?: "profitable" | "loss" | "pending" | "rejected";
  started_at: string;
  completed_at?: string;
  symbol: string;
}
