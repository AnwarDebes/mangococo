import type {
  ModelStatus,
  PortfolioState,
  Position,
  SentimentData,
  Signal,
  SignalExplanation,
  SystemHealth,
  Trade,
  PredictionCone,
  FactorRow,
  WhaleData,
  ReplayData,
  StressResult,
  StressScenario,
  ChatMessage,
} from "@/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

/* ── Helpers ──────────────────────────────────────────────────────── */

function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function toIso(value: unknown): string {
  if (typeof value === "string" && value.trim() !== "") return value;
  return new Date().toISOString();
}

function toSignalAction(value: unknown): Signal["action"] {
  const v = String(value || "").toLowerCase();
  if (v === "buy") return "BUY";
  if (v === "sell") return "SELL";
  return "HOLD";
}

function toPositionSide(value: unknown): Position["side"] {
  const v = String(value || "").toLowerCase();
  if (v === "short") return "short";
  return "long";
}

async function requestJson<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Request failed (${res.status}) for ${path}`);
  }
  return (await res.json()) as T;
}

/* ── Mappers ─────────────────────────────────────────────────────── */

function mapPortfolio(payload: unknown): PortfolioState {
  const root = asRecord(payload);
  const summary = asRecord(root.summary);

  const totalValue = asNumber(summary.total_value, asNumber(root.total_value));
  const cash = asNumber(
    summary.cash_balance,
    asNumber(root.cash_balance, asNumber(root.available_capital))
  );
  const posValue = asNumber(
    summary.positions_value,
    asNumber(root.positions_value, asNumber(root.total_unrealized_pnl))
  );
  const dailyPnl = asNumber(summary.daily_pnl, asNumber(root.daily_pnl));
  const openPositions = asNumber(
    summary.open_positions,
    asNumber(root.open_positions, asNumber(root.open_positions_count))
  );

  return {
    total_value: totalValue,
    cash_balance: cash,
    positions_value: posValue,
    daily_pnl: dailyPnl,
    open_positions: openPositions,
  };
}

function mapPosition(symbolKey: string, rawValue: unknown): Position {
  const row = asRecord(rawValue);
  return {
    symbol: String(row.symbol || symbolKey || "").toUpperCase(),
    side: toPositionSide(row.side),
    entry_price: asNumber(row.entry_price),
    current_price: asNumber(row.current_price, asNumber(row.price, asNumber(row.entry_price))),
    amount: asNumber(row.amount),
    unrealized_pnl: asNumber(row.unrealized_pnl),
    stop_loss_price: asNumber(row.stop_loss_price),
    take_profit_price: asNumber(row.take_profit_price),
    opened_at: toIso(row.opened_at || row.entry_time || row.created_at),
  };
}

function mapTrade(rawValue: unknown): Trade {
  const row = asRecord(rawValue);
  const sideValue = String(row.side || "").toLowerCase();
  const side: Trade["side"] = sideValue === "short" ? "short" : "long";

  const entryPrice = asNumber(row.entry_price);
  const exitPrice = asNumber(
    row.exit_price,
    asNumber(row.close_price, asNumber(row.price, entryPrice))
  );
  const realizedPnl = asNumber(
    row.realized_pnl,
    asNumber(row.pnl, asNumber(row.total_pnl))
  );

  let pnlPct = asNumber(row.pnl_pct);
  if (pnlPct === 0 && entryPrice > 0 && exitPrice > 0) {
    const rawPct = ((exitPrice - entryPrice) / entryPrice) * 100;
    pnlPct = side === "long" ? rawPct : -rawPct;
  }

  const createdAt = toIso(row.created_at || row.entry_time || row.opened_at);
  const closedAt = toIso(
    row.closed_at || row.exit_time || row.timestamp || createdAt
  );

  return {
    symbol: String(row.symbol || "").toUpperCase(),
    side,
    entry_price: entryPrice,
    exit_price: exitPrice,
    amount: asNumber(row.amount),
    realized_pnl: realizedPnl,
    pnl_pct: pnlPct,
    exit_reason: String(row.exit_reason || row.reason || "unknown"),
    strategy: String(row.strategy || row.model_name || "ml_ensemble"),
    hold_time_seconds: asNumber(
      row.hold_time_seconds,
      asNumber(row.hold_time_minutes) * 60
    ),
    created_at: createdAt,
    closed_at: closedAt,
  };
}

function normalizeSentimentScore(score: number): number {
  if (score >= -1 && score <= 1) return (score + 1) * 50;
  if (score >= 0 && score <= 1) return score * 100;
  return Math.max(0, Math.min(100, score));
}

function mapSentiment(symbol: string, rawValue: unknown, fearGreed: number): SentimentData {
  const row = asRecord(rawValue);
  const rawScore = asNumber(row.score);
  return {
    symbol: symbol.toUpperCase(),
    score: normalizeSentimentScore(rawScore),
    momentum_1h: asNumber(row.sentiment_momentum_1h, asNumber(row.momentum_1h)),
    momentum_24h: asNumber(
      row.sentiment_momentum_24h,
      asNumber(row.momentum_24h, asNumber(row.sentiment_momentum_4h))
    ),
    volume: asNumber(row.volume, asNumber(row.sample_count)),
    fear_greed_index: fearGreed,
  };
}

/* ── Core API Functions ──────────────────────────────────────────── */

export async function getPortfolio(): Promise<PortfolioState> {
  try {
    const data = await requestJson("/api/v2/portfolio");
    return mapPortfolio(data);
  } catch (err) {
    console.error("[api] getPortfolio failed:", err);
    return { total_value: 0, cash_balance: 0, positions_value: 0, daily_pnl: 0, open_positions: 0 };
  }
}

export async function getPositions(): Promise<Position[]> {
  try {
    let data: unknown;
    try {
      data = await requestJson("/api/v2/positions");
    } catch {
      data = await requestJson("/api/positions");
    }

    // Handle executor paper_portfolio format: { balances: {...}, summary: { positions: {...} } }
    const root = asRecord(data);
    const balSummary = asRecord(root.summary);
    const summaryPositions = asRecord(balSummary.positions);

    // If executor returns paper positions in summary.positions
    if (Object.keys(summaryPositions).length > 0) {
      return Object.entries(summaryPositions)
        .map(([symbol, value]) => {
          const pos = asRecord(value);
          return {
            symbol: symbol.toUpperCase(),
            side: "long" as const,
            entry_price: asNumber(pos.price),
            current_price: asNumber(pos.price),
            amount: asNumber(pos.amount),
            unrealized_pnl: 0,
            stop_loss_price: 0,
            take_profit_price: 0,
            opened_at: new Date().toISOString(),
          };
        })
        .filter((p) => p.amount > 0);
    }

    // Standard position service format: { "BTC/USDT": {...}, ... }
    const mapSource = Object.keys(root).length > 0 && !Array.isArray(data)
      ? root
      : asRecord((data as Record<string, unknown> | undefined)?.positions);

    return Object.entries(mapSource)
      .filter(([k]) => k !== "summary" && k !== "balances" && k !== "simulated")
      .map(([symbol, value]) => mapPosition(symbol, value))
      .filter((p) => p.symbol.length > 0 && p.amount > 0);
  } catch (err) {
    console.error("[api] getPositions failed:", err);
    return [];
  }
}

export async function getTrades(): Promise<Trade[]> {
  try {
    let data: unknown;
    try {
      data = await requestJson("/api/v2/trades");
    } catch {
      data = await requestJson("/api/trades");
    }

    const root = asRecord(data);
    const items = Array.isArray(data)
      ? data
      : Array.isArray(root.trades)
      ? root.trades
      : [];

    return items
      .map((item) => mapTrade(item))
      .sort((a, b) => new Date(b.closed_at).getTime() - new Date(a.closed_at).getTime());
  } catch (err) {
    console.error("[api] getTrades failed:", err);
    return [];
  }
}

export async function getSignals(): Promise<Signal[]> {
  try {
    let data: unknown;
    try {
      data = await requestJson("/api/v2/signals");
    } catch {
      data = await requestJson("/api/signals");
    }

    const items = Array.isArray(data) ? data : Object.values(asRecord(data));

    return items
      .map((raw) => {
        const row = asRecord(raw);
        return {
          signal_id: String(row.signal_id || `${String(row.symbol || "UNKNOWN")}_${toIso(row.timestamp)}`),
          symbol: String(row.symbol || "").toUpperCase(),
          action: toSignalAction(row.action),
          confidence: asNumber(row.confidence),
          price: asNumber(row.price),
          timestamp: toIso(row.timestamp),
        } as Signal;
      })
      .filter((s) => s.symbol.length > 0)
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  } catch (err) {
    console.error("[api] getSignals failed:", err);
    return [];
  }
}

export async function getSystemHealth(): Promise<SystemHealth[]> {
  try {
    const data = await requestJson("/api/v2/system");
    const services = Array.isArray(asRecord(data).services)
      ? (asRecord(data).services as unknown[])
      : [];

    return services.map((raw) => {
      const row = asRecord(raw);
      const status = String(row.status || "down").toLowerCase();
      return {
        service_name: String(row.name || row.service_name || "unknown"),
        status: status === "healthy" ? "healthy" : status === "degraded" ? "degraded" : "down",
        uptime: asNumber(row.uptime, 0),
        last_heartbeat: toIso(row.last_heartbeat || row.timestamp),
      } as SystemHealth;
    });
  } catch {
    try {
      const statusResp = await requestJson("/status");
      const servicesMap = asRecord(asRecord(statusResp).services);
      return Object.entries(servicesMap).map(([name, info]) => {
        const row = asRecord(info);
        return {
          service_name: name,
          status: row.healthy ? "healthy" : "down",
          uptime: 0,
          last_heartbeat: new Date().toISOString(),
        } as SystemHealth;
      });
    } catch (err) {
      console.error("[api] getSystemHealth failed:", err);
      return [];
    }
  }
}

export async function getSentiment(): Promise<SentimentData[]> {
  try {
    const data = await requestJson("/api/v2/sentiment");
    const root = asRecord(data);
    const fearGreed = asNumber(asRecord(root.fear_greed).value, 50);

    const symbolsFromNested = asRecord(root.symbols);
    if (Object.keys(symbolsFromNested).length > 0) {
      return Object.entries(symbolsFromNested)
        .map(([symbol, value]) => mapSentiment(symbol, value, fearGreed))
        .sort((a, b) => b.score - a.score);
    }

    const directEntries = Object.entries(root).filter(
      ([k, v]) => k !== "fear_greed" && k !== "symbols" && typeof v === "object"
    );
    if (directEntries.length > 0) {
      return directEntries
        .map(([symbol, value]) => mapSentiment(symbol, value, fearGreed))
        .sort((a, b) => b.score - a.score);
    }
    return [];
  } catch (err) {
    console.error("[api] getSentiment failed:", err);
    return [];
  }
}

export async function getModelStatus(): Promise<ModelStatus[]> {
  try {
    const data = await requestJson("/api/v2/models");
    const root = asRecord(data);

    const modelsArray = Array.isArray(root.models) ? (root.models as unknown[]) : [];
    if (modelsArray.length > 0) {
      return modelsArray.map((raw) => {
        const row = asRecord(raw);
        const statusRaw = String(row.status || "inactive").toLowerCase();
        return {
          model_name: String(row.model_name || row.name || "unknown"),
          version: String(row.version || "n/a"),
          accuracy: asNumber(row.accuracy, 0),
          last_retrain: toIso(row.last_retrain || row.updated_at),
          status: statusRaw === "active" || statusRaw === "training"
            ? (statusRaw as ModelStatus["status"])
            : "inactive",
        };
      });
    }

    const tcnLoaded = Boolean(root.tcn_loaded);
    const xgbLoaded = Boolean(root.xgb_loaded);
    const mode = String(root.mode || "legacy").toLowerCase();
    const now = new Date().toISOString();

    return [
      {
        model_name: "tcn",
        version: String(root.tcn_version || "unavailable"),
        accuracy: tcnLoaded ? (mode === "ml" ? 0.7 : 0.55) : 0,
        last_retrain: now,
        status: tcnLoaded ? "active" : "inactive",
      },
      {
        model_name: "xgboost",
        version: String(root.xgb_version || "unavailable"),
        accuracy: xgbLoaded ? (mode === "ml" ? 0.7 : 0.55) : 0,
        last_retrain: now,
        status: xgbLoaded ? "active" : "inactive",
      },
    ];
  } catch (err) {
    console.error("[api] getModelStatus failed:", err);
    return [];
  }
}

/* ── Container Logs ────────────────────────────────────────────────── */

export interface ContainerLog {
  container: string;
  timestamp: string;
  level: "info" | "warn" | "error" | "debug";
  message: string;
}

export async function getContainerLogs(
  container?: string,
  limit?: number,
  level?: string,
  since?: string
): Promise<ContainerLog[]> {
  try {
    const params = new URLSearchParams();
    if (container) params.set("container", container);
    if (limit) params.set("limit", limit.toString());
    if (level) params.set("level", level);
    if (since) params.set("since", since);
    const data = await requestJson<unknown>(`/api/v2/logs?${params.toString()}`);
    if (!Array.isArray(data)) return [];
    return data.map((raw) => {
      const row = asRecord(raw);
      const lvl = String(row.level || "info").toLowerCase();
      return {
        container: String(row.container || "unknown"),
        timestamp: toIso(row.timestamp),
        level: (["info", "warn", "error", "debug"].includes(lvl) ? lvl : "info") as ContainerLog["level"],
        message: String(row.message || ""),
      };
    });
  } catch (err) {
    console.error("[api] getContainerLogs failed:", err);
    return [];
  }
}

/* ── Resource Metrics ──────────────────────────────────────────────── */

export interface ResourceMetrics {
  container: string;
  cpu_percent: number;
  memory_used_mb: number;
  memory_limit_mb: number;
  memory_percent: number;
  network_rx_mb: number;
  network_tx_mb: number;
  disk_read_mb: number;
  disk_write_mb: number;
  uptime_seconds: number;
  restart_count: number;
  status: "running" | "stopped" | "restarting" | "paused";
}

export async function getResourceMetrics(): Promise<ResourceMetrics[]> {
  try {
    const data = await requestJson<unknown[]>("/api/v2/resources");
    if (!Array.isArray(data)) return [];
    return data.map((raw) => {
      const row = asRecord(raw);
      return {
        container: String(row.container || "unknown"),
        cpu_percent: asNumber(row.cpu_percent),
        memory_used_mb: asNumber(row.memory_used_mb),
        memory_limit_mb: asNumber(row.memory_limit_mb, 512),
        memory_percent: asNumber(row.memory_percent),
        network_rx_mb: asNumber(row.network_rx_mb),
        network_tx_mb: asNumber(row.network_tx_mb),
        disk_read_mb: asNumber(row.disk_read_mb),
        disk_write_mb: asNumber(row.disk_write_mb),
        uptime_seconds: asNumber(row.uptime_seconds),
        restart_count: asNumber(row.restart_count),
        status: (["running", "stopped", "restarting", "paused"].includes(String(row.status))
          ? String(row.status)
          : "stopped") as ResourceMetrics["status"],
      };
    });
  } catch (err) {
    console.error("[api] getResourceMetrics failed:", err);
    return [];
  }
}

/* ── Signal Explanation ────────────────────────────────────────────── */

export async function getSignalExplanation(signalId: string, symbol: string): Promise<SignalExplanation | null> {
  try {
    return await requestJson(`/api/v2/signals/${signalId}/explain`);
  } catch {
    // Build explanation from available ticker data
    try {
      const ticker = await getTicker(symbol);
      const t = asRecord(ticker);
      const price = asNumber(t.lastPrice, asNumber(t.price));
      return {
        signal_id: signalId,
        symbol,
        action: "HOLD",
        confidence: 0.5,
        timestamp: new Date().toISOString(),
        tcn_prediction: { direction: "HOLD", confidence: 0.5, weight: 0.6 },
        xgb_prediction: { direction: "HOLD", confidence: 0.5, weight: 0.4 },
        models_agree: true,
        top_factors: [],
        market_snapshot: {
          price,
          rsi: 50,
          macd_signal: "neutral",
          volume_vs_avg: 1,
          trend: "sideways",
          volatility: "medium",
          support_level: price * 0.95,
          resistance_level: price * 1.05,
        },
        risk_assessment: {
          risk_score: 50,
          position_size_pct: 10,
          stop_loss: price * 0.97,
          take_profit: price * 1.03,
          risk_reward_ratio: 1.5,
        },
      };
    } catch {
      return null;
    }
  }
}

/* ── MEXC Market Data Proxy ──────────────────────────────────────── */

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export async function getCandles(symbol: string, interval: string = "1h", limit: number = 200): Promise<Candle[]> {
  try {
    return await requestJson(`/api/v2/candles?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=${limit}`);
  } catch (err) {
    console.error("[api] getCandles failed:", err);
    return [];
  }
}

export interface DepthData {
  bids: [string, string][];
  asks: [string, string][];
}

export async function getDepth(symbol: string, limit: number = 20): Promise<DepthData> {
  try {
    return await requestJson(`/api/v2/depth?symbol=${encodeURIComponent(symbol)}&limit=${limit}`);
  } catch (err) {
    console.error("[api] getDepth failed:", err);
    return { bids: [], asks: [] };
  }
}

export async function getTicker(symbol?: string): Promise<unknown> {
  try {
    const params = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
    return await requestJson(`/api/v2/ticker${params}`);
  } catch (err) {
    console.error("[api] getTicker failed:", err);
    return {};
  }
}

export interface TickerPrice {
  symbol: string;
  price: string;
  lastPrice: string;
  priceChangePercent: string;
  volume: string;
}

export async function getAllTickers(): Promise<TickerPrice[]> {
  try {
    // Try batch prices endpoint first
    try {
      const prices = await requestJson<Array<{ symbol: string; price: string }>>("/api/v2/prices");
      if (Array.isArray(prices) && prices.length > 0) {
        // Also fetch 24hr change data in parallel for each tracked symbol
        const tracked = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT"];
        const priceMap = new Map(prices.map((p) => [p.symbol, p.price]));
        const tickerResults = await Promise.allSettled(
          tracked.map((sym) => requestJson<Record<string, string>>(`/api/v2/ticker?symbol=${sym}`))
        );
        return tracked.map((sym, i) => {
          const res = tickerResults[i];
          const data = res.status === "fulfilled" ? res.value : {};
          return {
            symbol: sym,
            price: data.lastPrice || priceMap.get(sym) || "0",
            lastPrice: data.lastPrice || priceMap.get(sym) || "0",
            priceChangePercent: data.priceChangePercent || "0",
            volume: data.volume || "0",
          };
        });
      }
    } catch {}

    // Fallback: fetch each ticker in parallel
    const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT"];
    const results = await Promise.allSettled(
      symbols.map((sym) => requestJson<Record<string, string>>(`/api/v2/ticker?symbol=${sym}`))
    );
    return symbols
      .map((sym, i) => {
        const res = results[i];
        if (res.status !== "fulfilled") return null;
        const data = res.value;
        return {
          symbol: sym,
          price: data.lastPrice || "0",
          lastPrice: data.lastPrice || "0",
          priceChangePercent: data.priceChangePercent || "0",
          volume: data.volume || "0",
        };
      })
      .filter((t): t is TickerPrice => t !== null);
  } catch (err) {
    console.error("[api] getAllTickers failed:", err);
    return [];
  }
}

/* ── Phase 4: Prediction Cone ────────────────────────────────────── */

export async function getPredictionCone(symbol: string = "BTCUSDT"): Promise<PredictionCone | null> {
  try {
    const data = await requestJson<unknown>(`/api/v2/prediction/cone?symbol=${encodeURIComponent(symbol)}`);
    const row = asRecord(data);
    const pred = asRecord(row.prediction);
    const cone = asRecord(row.cone);
    const h1 = asRecord(cone["1h"]);
    const h4 = asRecord(cone["4h"]);
    const h24 = asRecord(cone["24h"]);
    return {
      symbol: String(row.symbol || symbol),
      current_price: asNumber(row.current_price),
      prediction: {
        direction: String(pred.direction) === "up" ? "up" : "down",
        confidence: asNumber(pred.confidence, 0.5),
      },
      cone: {
        "1h": { upper: asNumber(h1.upper), mid: asNumber(h1.mid), lower: asNumber(h1.lower) },
        "4h": { upper: asNumber(h4.upper), mid: asNumber(h4.mid), lower: asNumber(h4.lower) },
        "24h": { upper: asNumber(h24.upper), mid: asNumber(h24.mid), lower: asNumber(h24.lower) },
      },
      historical: Array.isArray(row.historical)
        ? (row.historical as unknown[]).map((v) => asNumber(v))
        : [],
    };
  } catch (err) {
    console.error("[api] getPredictionCone failed:", err);
    return null;
  }
}

/* ── Phase 4: Factor Heatmap ─────────────────────────────────────── */

export async function getPredictionFactors(): Promise<FactorRow[]> {
  try {
    const data = await requestJson<unknown>("/api/v2/prediction/factors");
    if (!Array.isArray(data)) return [];
    return (data as unknown[]).map((raw) => {
      const row = asRecord(raw);
      const factors: Record<string, { value: number; direction: "bullish" | "bearish" | "neutral"; description: string }> = {};
      const rawFactors = asRecord(row.factors);
      for (const [key, val] of Object.entries(rawFactors)) {
        const f = asRecord(val);
        const dir = String(f.direction || "neutral");
        factors[key] = {
          value: asNumber(f.value),
          direction: dir === "bullish" ? "bullish" : dir === "bearish" ? "bearish" : "neutral",
          description: String(f.description || ""),
        };
      }
      return { symbol: String(row.symbol || ""), factors };
    });
  } catch (err) {
    console.error("[api] getPredictionFactors failed:", err);
    return [];
  }
}

/* ── Phase 4: Whale Activity ─────────────────────────────────────── */

export async function getWhaleActivity(limit: number = 20): Promise<WhaleData> {
  const empty: WhaleData = {
    transactions: [],
    summary: { net_exchange_flow_btc: 0, net_exchange_flow_eth: 0, whale_sentiment: "neutral" },
  };
  try {
    const data = await requestJson<unknown>(`/api/v2/whales?limit=${limit}`);
    const row = asRecord(data);
    const txs = Array.isArray(row.transactions) ? (row.transactions as unknown[]) : [];
    const summary = asRecord(row.summary);
    const ws = String(summary.whale_sentiment || "neutral");
    return {
      transactions: txs.map((raw) => {
        const t = asRecord(raw);
        const dir = String(t.direction || "transfer");
        const sig = String(t.significance || "neutral");
        return {
          symbol: String(t.symbol || "BTC/USDT"),
          amount_usd: asNumber(t.amount_usd),
          direction: dir === "exchange_inflow" ? "exchange_inflow" : dir === "exchange_outflow" ? "exchange_outflow" : "transfer",
          from_label: String(t.from_label || "Unknown"),
          to_label: String(t.to_label || "Unknown"),
          timestamp: toIso(t.timestamp),
          significance: sig === "bullish" ? "bullish" : sig === "bearish" ? "bearish" : "neutral",
        };
      }),
      summary: {
        net_exchange_flow_btc: asNumber(summary.net_exchange_flow_btc),
        net_exchange_flow_eth: asNumber(summary.net_exchange_flow_eth),
        whale_sentiment: ws === "accumulation" ? "accumulation" : ws === "distribution" ? "distribution" : "neutral",
      },
    };
  } catch (err) {
    console.error("[api] getWhaleActivity failed:", err);
    return empty;
  }
}

/* ── Phase 4: Market Replay ──────────────────────────────────────── */

export async function getReplayData(
  symbol: string,
  start: string,
  end: string,
): Promise<ReplayData> {
  try {
    const params = new URLSearchParams({ symbol, start, end });
    const data = await requestJson<unknown>(`/api/v2/replay?${params.toString()}`);
    const row = asRecord(data);
    const events = Array.isArray(row.events) ? (row.events as unknown[]) : [];
    return {
      events: events.map((raw) => {
        const e = asRecord(raw);
        return {
          type: (["candle", "signal", "trade"].includes(String(e.type)) ? String(e.type) : "candle") as "candle" | "signal" | "trade",
          time: toIso(e.time),
          open: asNumber(e.open),
          high: asNumber(e.high),
          low: asNumber(e.low),
          close: asNumber(e.close),
          volume: asNumber(e.volume),
          symbol: String(e.symbol || ""),
          action: toSignalAction(e.action),
          confidence: asNumber(e.confidence),
          side: String(e.side || ""),
          price: asNumber(e.price),
          amount: asNumber(e.amount),
          pnl: asNumber(e.pnl),
        };
      }),
      total_events: asNumber(row.total_events, events.length),
    };
  } catch (err) {
    console.error("[api] getReplayData failed:", err);
    return { events: [], total_events: 0 };
  }
}

/* ── Phase 4: Stress Test ────────────────────────────────────────── */

export async function runStressTest(scenario: StressScenario): Promise<StressResult | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v2/stress-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenario),
    });
    if (!res.ok) throw new Error(`Stress test failed (${res.status})`);
    const data = asRecord(await res.json());
    return {
      scenario: String(data.scenario || scenario.name),
      original_value: asNumber(data.original_value),
      stressed_value: asNumber(data.stressed_value),
      total_loss: asNumber(data.total_loss),
      total_loss_pct: asNumber(data.total_loss_pct),
      positions_liquidated: asNumber(data.positions_liquidated),
      positions_survived: asNumber(data.positions_survived),
      stop_loss_savings: asNumber(data.stop_loss_savings),
      cash_remaining: asNumber(data.cash_remaining),
      recovery_days: asNumber(data.recovery_days),
      per_position: Array.isArray(data.per_position)
        ? (data.per_position as unknown[]).map((raw) => {
            const p = asRecord(raw);
            return {
              symbol: String(p.symbol || ""),
              original_value: asNumber(p.original_value),
              stressed_value: asNumber(p.stressed_value),
              loss: asNumber(p.loss),
              stop_loss_triggered: Boolean(p.stop_loss_triggered),
            };
          })
        : [],
    };
  } catch (err) {
    console.error("[api] runStressTest failed:", err);
    return null;
  }
}

/* ── Phase 4: Chat ───────────────────────────────────────────────── */

export async function sendChatMessage(message: string): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/api/v2/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!res.ok) throw new Error(`Chat failed (${res.status})`);
    const data = asRecord(await res.json());
    return String(data.response || "I couldn't process that request. Try asking about your portfolio or recent trades.");
  } catch (err) {
    console.error("[api] sendChatMessage failed:", err);
    return "Sorry, I'm having trouble connecting to the server. Please try again.";
  }
}
