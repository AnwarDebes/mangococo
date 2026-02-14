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
