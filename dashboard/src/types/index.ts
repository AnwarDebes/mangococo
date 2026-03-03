export interface Position {
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  current_price: number;
  amount: number;
  unrealized_pnl: number;
  stop_loss_price: number;
  take_profit_price: number;
  opened_at: string;
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
  tcn_prediction: { direction: string; confidence: number; weight: number };
  xgb_prediction: { direction: string; confidence: number; weight: number };
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
    rsi: number;
    macd_signal: "bullish" | "bearish" | "neutral";
    volume_vs_avg: number;
    trend: "uptrend" | "downtrend" | "sideways";
    volatility: "low" | "medium" | "high";
    support_level: number;
    resistance_level: number;
  };
  risk_assessment: {
    risk_score: number;
    position_size_pct: number;
    stop_loss: number;
    take_profit: number;
    risk_reward_ratio: number;
  };
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
