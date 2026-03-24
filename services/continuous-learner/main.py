"""
Goblin Continuous Learner — Reinforcement Learning & Online Training Service (v5.0).

v5.0 improvements (MAX GPU utilization + aggressive PnL-based learning):
- Training every 1 minute — V100 should NEVER sit idle
- TCN epochs: 100 per cycle (was 50) — deeper learning
- XGBoost rounds: 500 (was 300) — stronger trees
- Batch size: 2048 (was 1024) with gradient accumulation fallback
- Aggressive PnL reward system with asymmetric weighting:
  - Big wins (>2%): 3.0x multiplier — learn a LOT from big wins
  - Small wins (0-2%): 1.5x multiplier
  - Small losses (-2%-0%): 2.0x penalty — penalize losses harder
  - Big losses (<-2%): 4.0x penalty — heavily penalize big losses
- Online micro-training: quick model update after each trade closes
- All TCN variants (micro/short/medium/long) trained every cycle with FULL epochs
- Higher initial LR (0.001) with cosine annealing for fast adaptation
- Trade feature buffer: last N trade vectors kept in memory for micro-training

v3.0 improvements (GPU maximization + faster convergence):
- Mixed Precision (AMP): ~2x faster GPU training, lower VRAM usage
- AdamW optimizer with weight decay for better generalization
- Cosine annealing LR scheduler with warm restarts for smoother convergence

v2.0 improvements over v1.0:
- Exponential recency weighting: recent data weighted up to 3x more than old data
- Performance gating: new model only deployed if it beats current accuracy
- Faster reward evaluation: 10-minute outcome window (was 25 minutes)
- Per-sample recency + reward combined weighting
- Data freshness validation: warns if data is stale
- Warm start: RL weighting active from first cycle if rewards exist

Runs as a persistent background service that:
1. Continuously collects new market data from TimescaleDB
2. Tracks prediction outcomes (reward signals)
3. Performs incremental RL-weighted training on both TCN and XGBoost
4. Hot-swaps model files so the prediction service picks up improvements
5. Logs training metrics to Redis for the AI Nerve Monitor
6. Micro-trains on individual closed trades for rapid online adaptation
"""

import asyncio
import collections
import json
import os
import sys
import time
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import asyncpg
import numpy as np
import pandas as pd
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

# ── Configuration ──────────────────────────────────────────────────────

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "goblin")
POSTGRES_USER = os.getenv("POSTGRES_USER", "goblin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

MODELS_DIR = Path(os.environ.get("MODEL_DIR", "/home/coder/Goblin/shared/models"))
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Training schedule
TRAIN_INTERVAL_MINUTES = int(os.getenv("TRAIN_INTERVAL_MINUTES", "1"))  # v5: 1min — V100 should NEVER idle
REWARD_LOOKBACK_CANDLES = 2  # v2: 2 candles = 10 minutes (was 5 candles = 25min)
MIN_SAMPLES_FOR_TRAINING = 500
LEARNING_RATE_TCN = 0.001   # v5: higher initial LR for fast adaptation (was 0.0003)
LEARNING_RATE_XGB = 0.03
TCN_EPOCHS_PER_CYCLE = int(os.getenv("TCN_EPOCHS_PER_CYCLE", "20"))   # v6: 20 — fast cycles, deploy models quickly
XGB_BOOST_ROUNDS_PER_CYCLE = int(os.getenv("XGB_BOOST_ROUNDS_PER_CYCLE", "500"))  # v5: 500 (was 300)
TCN_HIDDEN_CHANNELS = int(os.getenv("TCN_HIDDEN_CHANNELS", "512"))  # v6: wider model for V100
TCN_BATCH_SIZE = int(os.getenv("TCN_BATCH_SIZE", "8192"))  # v6: 8192 — larger batches = higher GPU utilization on V100 32GB
GRADIENT_ACCUMULATION_STEPS = int(os.getenv("GRADIENT_ACCUMULATION_STEPS", "1"))  # v6: no accumulation — full GPU batches
XGB_MAX_DEPTH = int(os.getenv("XGB_MAX_DEPTH", "10"))
USE_AMP = os.getenv("USE_AMP", "true").lower() == "true"  # v3: Mixed precision for 2x GPU speedup
TRAINING_DAYS = int(os.getenv("TRAINING_DAYS", "90"))
MAX_TRAINING_SYMBOLS = int(os.getenv("MAX_TRAINING_SYMBOLS", "100"))

# v5: Online micro-training buffer — last N trade feature vectors for quick updates
MICRO_TRAIN_BUFFER_SIZE = int(os.getenv("MICRO_TRAIN_BUFFER_SIZE", "200"))
MICRO_TRAIN_EPOCHS = int(os.getenv("MICRO_TRAIN_EPOCHS", "5"))
MICRO_TRAIN_LR = 0.0005  # Lower LR for micro-updates to avoid catastrophic forgetting

# v5: PnL reward multipliers — asymmetric (losses penalized harder for conservative trading)
PNL_BIG_WIN_THRESHOLD = 0.02      # > 2% PnL
PNL_BIG_WIN_MULTIPLIER = 3.0      # Learn a LOT from big wins
PNL_SMALL_WIN_MULTIPLIER = 1.5    # Moderate boost for small wins
PNL_SMALL_LOSS_MULTIPLIER = 2.0   # Penalize small losses more than reward equivalent wins
PNL_BIG_LOSS_THRESHOLD = -0.02    # <= -2% PnL
PNL_BIG_LOSS_MULTIPLIER = 4.0     # Heavily penalize big losses

# v2: Recency weighting — recent data is more valuable
RECENCY_HALF_LIFE_DAYS = 7  # Data from 7 days ago gets 50% weight
RECENCY_MAX_BOOST = 3.0     # Most recent data weighted up to 3x

# v6: Feature cache — avoid recomputing 5M candles of features every cycle
_feature_cache: dict = {}  # {symbol: (candle_count, features, targets_3, targets_5)}
_feature_cache_hits = 0
_feature_cache_misses = 0

# v2: Performance gating — only deploy if new model is better
MIN_ACCURACY_IMPROVEMENT = 0.001  # Require marginal improvement to avoid deploying noise
GATE_MODELS = os.getenv("GATE_MODELS", "true").lower() == "true"

# Feature names matching prediction service's features/technical.py
TECHNICAL_FEATURES = [
    "rsi_14", "rsi_7", "macd_histogram", "macd_signal",
    "bb_percent_b", "bb_bandwidth", "atr_pct", "obv_trend",
    "stoch_rsi_k", "stoch_rsi_d", "williams_r",
    "ema_9_21_cross", "ema_25_50_cross", "volume_ratio",
    "momentum_5m", "momentum_15m", "momentum_30m", "momentum_60m",
    "spread_pct", "vwap_deviation",
]

_FALLBACK_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
]

async def _load_symbols_from_db(pool: asyncpg.Pool) -> list:
    """Load top symbols by candle/tick count from DB. Falls back to hardcoded list."""
    try:
        async with pool.acquire() as conn:
            # Prefer symbols with candle data, sorted by count
            rows = await conn.fetch(
                """SELECT symbol, COUNT(*) as cnt FROM candles
                   GROUP BY symbol ORDER BY cnt DESC LIMIT $1""",
                MAX_TRAINING_SYMBOLS,
            )
            if rows and len(rows) >= 5:
                return [r["symbol"] for r in rows]
            # Fallback: derive from ticks (symbols with most data)
            rows = await conn.fetch(
                """SELECT symbol, COUNT(*) as cnt FROM ticks
                   GROUP BY symbol ORDER BY cnt DESC LIMIT $1""",
                MAX_TRAINING_SYMBOLS,
            )
            if rows:
                return [r["symbol"] for r in rows]
    except Exception:
        pass
    return _FALLBACK_SYMBOLS

DEFAULT_SYMBOLS = _FALLBACK_SYMBOLS  # Updated at runtime in main()

# 5-class labels matching prediction service's xgboost_model.py
CLASS_5 = ["strong_sell", "sell", "hold", "buy", "strong_buy"]
# 3-class labels matching prediction service's tcn_model.py
CLASS_3 = ["up", "down", "neutral"]

running = True


def handle_signal(signum, frame):
    global running
    running = False


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


# ── Technical Feature Computation ─────────────────────────────────────
# Mirrors features/technical.py from the prediction service exactly

def _ema(data: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.zeros_like(data, dtype=np.float64)
    out[0] = data[0]
    for i in range(1, len(data)):
        out[i] = alpha * data[i] + (1 - alpha) * out[i - 1]
    return out


def _sma(data: np.ndarray, period: int) -> np.ndarray:
    return pd.Series(data).rolling(period, min_periods=1).mean().values


def _rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(data, prepend=data[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain).rolling(period, min_periods=1).mean().values
    avg_loss = pd.Series(loss).rolling(period, min_periods=1).mean().values
    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain), where=avg_loss > 0)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_features_for_df(df: pd.DataFrame) -> np.ndarray:
    """Compute the 20 technical features matching the prediction service.
    Returns array of shape (len(df), 20).
    """
    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)
    opn = df["open"].values.astype(np.float64)
    volume = df["volume"].values.astype(np.float64)
    n = len(close)

    if n < 2:
        return np.zeros((n, 20))

    # RSI
    rsi_14 = _rsi(close, 14)
    rsi_7 = _rsi(close, 7)

    # MACD (8/17 EMA, matching technical.py)
    ema8 = _ema(close, 8)
    ema17 = _ema(close, 17)
    macd_line = ema8 - ema17
    macd_sig = _ema(macd_line, 9)
    macd_hist = macd_line - macd_sig

    # Bollinger Bands (20-period)
    sma20 = _sma(close, 20)
    std20 = pd.Series(close).rolling(20, min_periods=1).std().values
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_range = bb_upper - bb_lower
    bb_percent_b = np.divide(close - bb_lower, bb_range, out=np.full(n, 0.5), where=bb_range > 0)
    bb_bandwidth = np.divide(bb_range, sma20, out=np.zeros(n), where=sma20 > 0)

    # ATR %
    tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)),
                                            np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr14 = pd.Series(tr).rolling(14, min_periods=1).mean().values
    atr_pct = np.divide(atr14, close, out=np.zeros(n), where=close > 0) * 100

    # OBV trend (vectorized)
    price_diff = np.diff(close, prepend=close[0])
    obv_direction = np.sign(price_diff)
    obv = np.cumsum(obv_direction * volume)
    obv_ema = _ema(obv, 20)
    obv_trend = np.where(obv > obv_ema, 1.0, -1.0)

    # Stochastic RSI (vectorized using pandas rolling)
    rsi_series = pd.Series(rsi_14)
    rsi_min = rsi_series.rolling(14, min_periods=1).min().values
    rsi_max = rsi_series.rolling(14, min_periods=1).max().values
    rsi_range = rsi_max - rsi_min
    stoch_k = np.where(rsi_range > 0, (rsi_14 - rsi_min) / rsi_range, 0.5)
    stoch_d = _sma(stoch_k, 3)

    # Williams %R (vectorized using pandas rolling)
    high_series = pd.Series(high)
    low_series = pd.Series(low)
    hh = high_series.rolling(14, min_periods=1).max().values
    ll = low_series.rolling(14, min_periods=1).min().values
    hl_range = hh - ll
    williams = np.where(hl_range > 0, (hh - close) / hl_range * -100, -50.0)

    # EMA crosses
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema25 = _ema(close, 25)
    ema50 = _ema(close, 50)
    ema_9_21_cross = np.where(ema9 > ema21, 1.0, -1.0)
    ema_25_50_cross = np.where(ema25 > ema50, 1.0, -1.0)

    # Volume ratio
    vol_sma20 = _sma(volume, 20)
    volume_ratio = np.divide(volume, vol_sma20, out=np.ones(n), where=vol_sma20 > 0)

    # Momentum at various lookbacks
    def pct_change(arr, periods):
        shifted = np.roll(arr, periods)
        shifted[:periods] = arr[0]
        return np.divide(arr - shifted, shifted, out=np.zeros(n), where=shifted > 0) * 100

    mom_5 = pct_change(close, 5)
    mom_15 = pct_change(close, 15)
    mom_30 = pct_change(close, 30)
    mom_60 = pct_change(close, 60)

    # Spread %
    spread_pct = np.divide(high - low, close, out=np.zeros(n), where=close > 0) * 100

    # VWAP deviation
    cum_vol = np.cumsum(volume)
    cum_vwap = np.cumsum(close * volume)
    vwap = np.divide(cum_vwap, cum_vol, out=close.copy(), where=cum_vol > 0)
    vwap_dev = np.divide(close - vwap, vwap, out=np.zeros(n), where=vwap > 0) * 100

    # Stack all 20 features
    features = np.column_stack([
        rsi_14, rsi_7, macd_hist, macd_sig,
        bb_percent_b, bb_bandwidth, atr_pct, obv_trend,
        stoch_k, stoch_d, williams,
        ema_9_21_cross, ema_25_50_cross, volume_ratio,
        mom_5, mom_15, mom_30, mom_60,
        spread_pct, vwap_dev,
    ])

    # Replace NaN/Inf
    features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    return features


def compute_targets_5class(close: np.ndarray, horizon: int = REWARD_LOOKBACK_CANDLES) -> np.ndarray:
    """5-class targets for XGBoost matching prediction service labels.

    Thresholds lowered from 0.003/0.015 to 0.0005/0.002 to avoid class imbalance.
    Old thresholds gave 95% hold class → model always predicts hold.
    New thresholds give ~47% hold, ~22% buy/sell, ~5% strong_buy/sell.
    """
    future_close = np.roll(close, -horizon)
    future_ret = np.divide(future_close - close, np.maximum(close, 1e-10))
    future_ret[-horizon:] = 0  # no future data for last `horizon` candles

    targets = np.full(len(close), 2)  # default: hold
    targets[future_ret > 0.0005] = 3   # buy
    targets[future_ret > 0.002] = 4    # strong_buy
    targets[future_ret < -0.0005] = 1  # sell
    targets[future_ret < -0.002] = 0   # strong_sell
    return targets


def compute_targets_3class(close: np.ndarray, horizon: int = REWARD_LOOKBACK_CANDLES) -> np.ndarray:
    """3-class targets for TCN: 0=up, 1=down, 2=neutral.

    Threshold lowered from 0.001 to 0.0003 to avoid class imbalance
    (0.001 gave ~72% neutral, causing model to collapse to always-neutral).
    0.0003 gives ~34/35/31 distribution across up/down/neutral.
    """
    future_close = np.roll(close, -horizon)
    future_ret = np.divide(future_close - close, np.maximum(close, 1e-10))
    future_ret[-horizon:] = 0  # no future data for last `horizon` candles

    targets = np.full(len(close), 2)  # neutral
    targets[future_ret > 0.0003] = 0   # up
    targets[future_ret < -0.0003] = 1  # down
    return targets


# ── Reward Tracker ────────────────────────────────────────────────────

class RewardTracker:
    """Tracks prediction outcomes and computes RL reward signals."""

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self.reward_key = "rl:rewards"
        self.prediction_key = "rl:predictions"

    async def record_prediction(self, symbol: str, direction: str,
                                 confidence: float, price: float):
        """Record a prediction for later reward evaluation."""
        entry = {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.redis.lpush(self.prediction_key, json.dumps(entry))
        await self.redis.ltrim(self.prediction_key, 0, 9999)

    async def evaluate_rewards(self, pool: asyncpg.Pool) -> Dict[str, float]:
        """Check past predictions against actual outcomes, return reward weights per symbol.

        v2.0: Faster evaluation — checks outcome after 10 minutes (2 candles) instead of 25.
        Also checks tick data as fallback when candles aren't available yet.
        """
        rewards = {}
        pending = await self.redis.lrange(self.prediction_key, 0, 999)
        resolved = []
        unresolved = []

        outcome_minutes = REWARD_LOOKBACK_CANDLES * 5  # 2 candles × 5min = 10 min

        for raw in pending:
            try:
                pred = json.loads(raw)
                pred_time = datetime.fromisoformat(pred["timestamp"])
                age_minutes = (datetime.now(timezone.utc) - pred_time).total_seconds() / 60

                # v2: 10 minutes for 2-candle outcome (was 25 min)
                if age_minutes < outcome_minutes:
                    unresolved.append(raw)
                    continue

                # Check actual price movement — try candles first, then ticks
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """SELECT close FROM candles
                           WHERE symbol = $1 AND time > $2
                           ORDER BY time ASC LIMIT 1""",
                        pred["symbol"],
                        pred_time + timedelta(minutes=outcome_minutes),
                    )
                    # Fallback: use tick data if candles not yet aggregated
                    if row is None:
                        row = await conn.fetchrow(
                            """SELECT price AS close FROM ticks
                               WHERE symbol = $1 AND time > $2
                               ORDER BY time ASC LIMIT 1""",
                            pred["symbol"],
                            pred_time + timedelta(minutes=outcome_minutes),
                        )

                if row is None:
                    if age_minutes > 120:  # Too old, discard
                        resolved.append(raw)
                    else:
                        unresolved.append(raw)
                    continue

                actual_price = float(row["close"])
                pred_price = pred["price"]
                actual_return = (actual_price - pred_price) / max(pred_price, 1e-10)

                # Compute reward
                direction = pred["direction"].lower()
                if direction in ("buy", "strong_buy", "up"):
                    reward = 1.0 if actual_return > 0.001 else (-1.0 if actual_return < -0.001 else 0.0)
                elif direction in ("sell", "strong_sell", "down"):
                    reward = 1.0 if actual_return < -0.001 else (-1.0 if actual_return > 0.001 else 0.0)
                else:
                    reward = 0.5 if abs(actual_return) < 0.002 else -0.5

                sym = pred["symbol"]
                if sym not in rewards:
                    rewards[sym] = []
                rewards[sym].append(reward)

                resolved.append(raw)

            except Exception as e:
                logger.debug("Reward eval error", error=str(e))
                resolved.append(raw)

        # Update Redis: keep only unresolved
        if resolved:
            pipe = self.redis.pipeline()
            pipe.delete(self.prediction_key)
            for item in unresolved:
                pipe.rpush(self.prediction_key, item)
            await pipe.execute()

        # Store reward stats
        reward_summary = {}
        for sym, rews in rewards.items():
            avg = sum(rews) / len(rews) if rews else 0
            reward_summary[sym] = avg
            await self.redis.hset("rl:reward_avg", sym, str(round(avg, 4)))

        return reward_summary


# ── Live PnL Feedback ─────────────────────────────────────────────────

async def fetch_pnl_reward_signal(redis: aioredis.Redis, lookback_hours: int = 6) -> Dict[str, float]:
    """Read recent closed trades from Redis and compute per-symbol PnL reward signals.

    v5: Aggressive asymmetric PnL reward system:
      - Big win (PnL > 2%):     3.0x multiplier — learn heavily from big wins
      - Small win (0-2%):       1.5x multiplier — moderate reward
      - Small loss (-2% to 0%): 2.0x penalty   — penalize losses harder than equivalent wins
      - Big loss (< -2%):       4.0x penalty   — heavily penalize to avoid repeating

    Returns:
        Dict mapping symbol -> PnL reward multiplier.
        Values > 1.0 mean upweight (profitable patterns).
        Values < 1.0 mean downweight (losing patterns).
    """
    pnl_signals: Dict[str, float] = {}
    try:
        # Read last 500 trades (trade_history is an lpush list, newest first)
        raw_trades = await redis.lrange("trade_history", 0, 499)
        if not raw_trades:
            return pnl_signals

        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        symbol_pnls: Dict[str, List[Tuple[float, float, float]]] = {}  # symbol -> [(pnl_pct, recency_weight, pnl_multiplier)]

        for raw in raw_trades:
            try:
                trade = json.loads(raw)
                exit_time_str = trade.get("exit_time", "")
                if not exit_time_str:
                    continue

                exit_time = datetime.fromisoformat(exit_time_str)
                if exit_time.tzinfo is None:
                    exit_time = exit_time.replace(tzinfo=timezone.utc)

                if exit_time < cutoff:
                    continue  # Too old

                symbol = trade.get("symbol", "")
                realized_pnl = float(trade.get("realized_pnl", 0))
                # Compute PnL as percentage of entry
                entry_price = float(trade.get("entry_price", trade.get("price", 0)))
                if entry_price > 0:
                    pnl_pct = realized_pnl / entry_price
                else:
                    pnl_pct = realized_pnl  # fallback: treat as fraction directly
                if not symbol:
                    continue

                # v5: Asymmetric PnL multipliers — losses penalized harder
                if pnl_pct > PNL_BIG_WIN_THRESHOLD:
                    pnl_multiplier = PNL_BIG_WIN_MULTIPLIER      # 3.0x — learn a LOT
                elif pnl_pct > 0:
                    pnl_multiplier = PNL_SMALL_WIN_MULTIPLIER     # 1.5x
                elif pnl_pct > PNL_BIG_LOSS_THRESHOLD:
                    pnl_multiplier = PNL_SMALL_LOSS_MULTIPLIER    # 2.0x — penalize more
                else:
                    pnl_multiplier = PNL_BIG_LOSS_MULTIPLIER      # 4.0x — heavy penalty

                # Recency weight: trades from last hour weighted 3x, decaying
                age_hours = (datetime.now(timezone.utc) - exit_time).total_seconds() / 3600
                recency_w = max(0.3, 3.0 * (0.5 ** (age_hours / 2.0)))

                if symbol not in symbol_pnls:
                    symbol_pnls[symbol] = []
                symbol_pnls[symbol].append((pnl_pct, recency_w, pnl_multiplier))

            except Exception:
                continue

        # Compute weighted PnL signal per symbol using asymmetric multipliers
        for symbol, pnl_entries in symbol_pnls.items():
            if not pnl_entries:
                continue

            # Weighted average of PnL multipliers (recency-weighted)
            weighted_mult_sum = sum(mult * recency for _, recency, mult in pnl_entries)
            total_recency = sum(recency for _, recency, _ in pnl_entries)
            avg_multiplier = weighted_mult_sum / total_recency if total_recency > 0 else 1.0

            # Direction: are recent trades net profitable or losing?
            weighted_pnl = sum(pnl * recency for pnl, recency, _ in pnl_entries)
            net_direction = 1.0 if weighted_pnl >= 0 else -1.0

            # Final signal: multiplier applied in the direction of net PnL
            # Profitable symbols get upweighted, losing symbols get downweighted
            if net_direction > 0:
                signal = 1.0 + (avg_multiplier - 1.0) * 0.3  # Boost: scale into [1.0, ~1.9]
            else:
                signal = max(0.2, 1.0 - (avg_multiplier - 1.0) * 0.3)  # Penalize: scale into [~0.1, 1.0]

            pnl_signals[symbol] = round(signal, 4)

        if pnl_signals:
            logger.info("PnL reward signals computed (v5 asymmetric)",
                        symbols=len(pnl_signals),
                        profitable=sum(1 for v in pnl_signals.values() if v > 1.0),
                        losing=sum(1 for v in pnl_signals.values() if v < 1.0),
                        big_win_mult=PNL_BIG_WIN_MULTIPLIER,
                        big_loss_mult=PNL_BIG_LOSS_MULTIPLIER)

    except Exception as e:
        logger.warning("Failed to fetch PnL reward signal", error=str(e))

    return pnl_signals


async def fetch_trade_sample_weights(redis: aioredis.Redis, n_samples: int,
                                      sample_timestamps: np.ndarray) -> np.ndarray:
    """Compute per-sample PnL-based weights for training data.

    v5: Maps recent trade PnL outcomes back to training samples by timestamp proximity.
    Samples near winning trades get upweighted, samples near losing trades get penalized.
    This makes the model pay MORE attention to patterns that led to wins/losses.

    Returns:
        Array of shape (n_samples,) with per-sample PnL multipliers.
    """
    weights = np.ones(n_samples, dtype=np.float32)
    try:
        raw_trades = await redis.lrange("trade_history", 0, 999)
        if not raw_trades:
            return weights

        trade_events = []  # (timestamp_epoch, pnl_multiplier)
        for raw in raw_trades:
            try:
                trade = json.loads(raw)
                entry_time_str = trade.get("entry_time", trade.get("timestamp", ""))
                exit_time_str = trade.get("exit_time", "")
                if not entry_time_str:
                    continue

                entry_time = datetime.fromisoformat(entry_time_str)
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)

                realized_pnl = float(trade.get("realized_pnl", 0))
                entry_price = float(trade.get("entry_price", trade.get("price", 0)))
                pnl_pct = realized_pnl / entry_price if entry_price > 0 else realized_pnl

                # Asymmetric multiplier
                if pnl_pct > PNL_BIG_WIN_THRESHOLD:
                    mult = PNL_BIG_WIN_MULTIPLIER
                elif pnl_pct > 0:
                    mult = PNL_SMALL_WIN_MULTIPLIER
                elif pnl_pct > PNL_BIG_LOSS_THRESHOLD:
                    mult = PNL_SMALL_LOSS_MULTIPLIER
                else:
                    mult = PNL_BIG_LOSS_MULTIPLIER

                trade_events.append((entry_time.timestamp(), mult))
            except Exception:
                continue

        if not trade_events:
            return weights

        # Apply multipliers to nearby samples (within 30 minute window)
        trade_times = np.array([t for t, _ in trade_events])
        trade_mults = np.array([m for _, m in trade_events])
        window_sec = 1800  # 30 minutes

        for i in range(n_samples):
            if sample_timestamps[i] > 0:
                diffs = np.abs(trade_times - sample_timestamps[i])
                nearby = diffs < window_sec
                if nearby.any():
                    # Use the highest multiplier from nearby trades
                    weights[i] = float(trade_mults[nearby].max())

    except Exception as e:
        logger.debug("Failed to compute per-sample PnL weights", error=str(e))

    return weights


# ── Online Micro-Training Buffer ─────────────────────────────────────

class TradeFeatureBuffer:
    """In-memory ring buffer of recent trade feature vectors for micro-training.

    v5: After each trade closes, we store its feature vector and outcome
    for quick online updates without waiting for the full training cycle.
    """

    def __init__(self, max_size: int = MICRO_TRAIN_BUFFER_SIZE):
        self.max_size = max_size
        self.features = collections.deque(maxlen=max_size)   # feature vectors (20,)
        self.targets_3 = collections.deque(maxlen=max_size)  # 3-class target
        self.targets_5 = collections.deque(maxlen=max_size)  # 5-class target
        self.pnl_weights = collections.deque(maxlen=max_size)  # PnL-based sample weight
        self.timestamps = collections.deque(maxlen=max_size)

    def add(self, features: np.ndarray, target_3: int, target_5: int,
            pnl_weight: float, timestamp: float):
        self.features.append(features)
        self.targets_3.append(target_3)
        self.targets_5.append(target_5)
        self.pnl_weights.append(pnl_weight)
        self.timestamps.append(timestamp)

    def __len__(self):
        return len(self.features)

    def get_arrays(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return (features, targets_3, targets_5, weights) as numpy arrays."""
        if len(self.features) == 0:
            return (np.empty((0, 20)), np.empty(0, dtype=np.int64),
                    np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32))
        return (
            np.array(list(self.features), dtype=np.float32),
            np.array(list(self.targets_3), dtype=np.int64),
            np.array(list(self.targets_5), dtype=np.int64),
            np.array(list(self.pnl_weights), dtype=np.float32),
        )


# Global buffer instance
_trade_buffer = TradeFeatureBuffer()


def micro_train_tcn(trade_buffer: TradeFeatureBuffer, model_path: str) -> Optional[dict]:
    """Quick online TCN update using buffered trade features.

    v5: Runs a few epochs on recent trade data only — fast adaptation
    without waiting for the full training cycle. Uses lower LR to
    avoid catastrophic forgetting of general patterns.
    """
    if len(trade_buffer) < 30:
        return None

    import torch
    import torch.nn as nn

    sys.path.insert(0, "/home/coder/Goblin/services/prediction")
    from models.tcn_model import TCNNetwork

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    feats, targets_3, _, weights = trade_buffer.get_arrays()

    if len(feats) < 30:
        return None

    model = TCNNetwork(
        n_features=20,
        hidden_channels=TCN_HIDDEN_CHANNELS,
        n_classes=3,
        kernel_size=3,
        dropout=0.1,  # Lower dropout for micro-training
    ).to(device)

    # Load existing weights
    if os.path.isfile(model_path):
        try:
            state = torch.load(model_path, map_location=device, weights_only=True)
            if "model_state_dict" in state:
                model.load_state_dict(state["model_state_dict"])
            else:
                model.load_state_dict(state)
            model.float()  # Ensure float32 after loading (AMP may save half-precision)
        except Exception:
            return None

    # Build sequences from buffer
    seq_length = min(30, len(feats) - 1)
    X_seqs, y_seqs, w_seqs = [], [], []
    for i in range(seq_length, len(feats)):
        X_seqs.append(feats[i - seq_length:i])
        y_seqs.append(targets_3[i])
        w_seqs.append(max(weights[i], 0.1))

    if len(X_seqs) < 10:
        return None

    X = torch.tensor(np.array(X_seqs, dtype=np.float32)).to(device)
    y = torch.tensor(np.array(y_seqs, dtype=np.int64)).to(device)
    w = torch.tensor(np.array(w_seqs, dtype=np.float32)).to(device)

    # Inverse-frequency class weights for micro-training
    micro_counts = torch.bincount(y, minlength=3).float().clamp(min=1.0)
    micro_cw = (1.0 / micro_counts)
    micro_cw = micro_cw / micro_cw.sum() * 3.0
    micro_cw = micro_cw.to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=MICRO_TRAIN_LR, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss(weight=micro_cw, reduction='none')

    use_amp = USE_AMP and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    model.train()
    total_loss = 0.0
    for epoch in range(MICRO_TRAIN_EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda", enabled=use_amp):
            logits = model(X)
            loss_per_sample = criterion(logits, y)
            weighted_loss = (loss_per_sample * w).mean()
        scaler.scale(weighted_loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optimizer)
        scaler.update()
        total_loss += weighted_loss.item()

    # Ensure float32 before saving (AMP autocast may leave BatchNorm buffers in float16)
    model.float()

    # Save updated model
    torch.save({
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "n_features": 20,
        "hidden_channels": TCN_HIDDEN_CHANNELS,
        "n_classes": 3,
    }, model_path)

    avg_loss = total_loss / MICRO_TRAIN_EPOCHS
    logger.info("TCN micro-training complete", buffer_size=len(trade_buffer),
                sequences=len(X_seqs), avg_loss=round(avg_loss, 4))
    return {"micro_train": True, "loss": round(avg_loss, 4), "samples": len(X_seqs)}


# ── Model Training Functions ──────────────────────────────────────────

def train_tcn_rl(
    features: np.ndarray,
    targets: np.ndarray,
    reward_weights: Optional[np.ndarray],
    existing_model_path: Optional[str],
    output_path: Path,
    epochs: int = 5,
    lr: float = 0.0003,
    hidden_channels: int = 192,
    seq_length: int = 30,
    variant_name: str = "tcn",
) -> dict:
    """Train/update TCN model with RL reward weighting.

    Uses the same TCNNetwork architecture as the prediction service.
    If an existing model exists, loads it and fine-tunes (online learning).
    Reward weights bias the loss toward correctly predicting rewarded directions.
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    # Import the actual TCN architecture from the prediction service
    sys.path.insert(0, "/home/coder/Goblin/services/prediction")
    from models.tcn_model import TCNNetwork

    n_features = features.shape[2] if features.ndim == 3 else 20
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # v4: GPU optimizations — cudnn.benchmark auto-tunes convolution kernels
    # for the TCN's fixed input sizes, giving ~10-20% speedup after first epoch
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True

    model = TCNNetwork(
        n_features=n_features,
        hidden_channels=hidden_channels,
        n_classes=3,
        kernel_size=3,
        dropout=0.2,
    ).to(device)

    # Load existing weights if available (online learning)
    _loaded_state = None
    if existing_model_path and os.path.isfile(existing_model_path):
        try:
            state = torch.load(existing_model_path, map_location=device, weights_only=True)
            # If checkpoint has different hidden_channels, rebuild the network
            ckpt_hc = state.get("hidden_channels", hidden_channels)
            if ckpt_hc != hidden_channels:
                logger.info("TCN: checkpoint hidden_channels mismatch, training from scratch",
                            checkpoint=ckpt_hc, configured=hidden_channels)
            else:
                if "model_state_dict" in state:
                    model.load_state_dict(state["model_state_dict"])
                else:
                    model.load_state_dict(state)
                model.float()  # Ensure float32 after loading (AMP may save half-precision)
                _loaded_state = state
                logger.info("TCN: loaded existing model for fine-tuning")
        except Exception as e:
            logger.warning("TCN: could not load existing model, training from scratch", error=str(e))

    # Prepare data (seq_length comes from function parameter)
    X_seqs, y_seqs, w_seqs = [], [], []

    for i in range(seq_length, len(features)):
        X_seqs.append(features[i - seq_length:i])
        y_seqs.append(targets[i])
        if reward_weights is not None:
            w_seqs.append(max(reward_weights[i], 0.1))  # Floor at 0.1
        else:
            w_seqs.append(1.0)

    if len(X_seqs) < 100:
        return {"status": "skipped", "reason": "insufficient sequences"}

    # Keep data on CPU, use DataLoader to batch-transfer to GPU (avoids OOM)
    X = torch.tensor(np.array(X_seqs, dtype=np.float32))
    y = torch.tensor(np.array(y_seqs, dtype=np.int64))
    w = torch.tensor(np.array(w_seqs, dtype=np.float32))

    # Walk-forward split: 80/20
    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    w_train = w[:split]

    from torch.utils.data import TensorDataset, DataLoader
    batch_size = TCN_BATCH_SIZE
    accum_steps = GRADIENT_ACCUMULATION_STEPS

    train_dataset = TensorDataset(X_train, y_train, w_train)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True,
                              num_workers=8, pin_memory=True, drop_last=True, persistent_workers=True)
    test_dataset = TensorDataset(X_test, y_test)
    test_loader = DataLoader(test_dataset, batch_size=batch_size * 2, shuffle=False,
                             num_workers=4, pin_memory=True, persistent_workers=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    # Compute inverse-frequency class weights to combat class imbalance
    # Without this, the model collapses to always predicting the majority class
    class_counts = torch.bincount(y_train, minlength=3).float().clamp(min=1.0)
    class_weights = (1.0 / class_counts)
    class_weights = class_weights / class_weights.sum() * len(class_counts)  # normalize to mean=1
    class_weights = class_weights.to(device)
    logger.info("TCN class weights", weights=class_weights.tolist(),
                counts=class_counts.int().tolist())

    criterion = nn.CrossEntropyLoss(weight=class_weights, reduction='none')
    best_acc = 0.0

    # v5: Cosine annealing with higher initial LR for fast adaptation
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
        optimizer, T_0=max(epochs // 4, 5), T_mult=2, eta_min=lr * 0.01,
    )

    # Restore optimizer/scheduler state from checkpoint if available
    if _loaded_state is not None:
        if "optimizer_state_dict" in _loaded_state:
            try:
                optimizer.load_state_dict(_loaded_state["optimizer_state_dict"])
                logger.info("TCN: restored optimizer state from checkpoint")
            except Exception as e:
                logger.warning("TCN: could not restore optimizer state", error=str(e))
        if "scheduler_state_dict" in _loaded_state:
            try:
                scheduler.load_state_dict(_loaded_state["scheduler_state_dict"])
                logger.info("TCN: restored scheduler state from checkpoint")
            except Exception as e:
                logger.warning("TCN: could not restore scheduler state", error=str(e))

    # v3: Mixed Precision (AMP) — 2x faster training on GPU, less VRAM usage
    use_amp = USE_AMP and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        n_batches = 0

        optimizer.zero_grad(set_to_none=True)
        for xb, yb, wb in train_loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            wb = wb.to(device, non_blocking=True)

            with torch.amp.autocast("cuda", enabled=use_amp):
                logits = model(xb)
                loss_per_sample = criterion(logits, yb)
                weighted_loss = (loss_per_sample * wb).mean()
                weighted_loss = weighted_loss / accum_steps

            scaler.scale(weighted_loss).backward()

            n_batches += 1
            total_loss += weighted_loss.item() * accum_steps

            if n_batches % accum_steps == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)

        # Final optimizer step if leftover gradients
        if n_batches % accum_steps != 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)

        scheduler.step()

        # Evaluate using batched DataLoader (avoids GPU OOM on test set)
        model.eval()
        correct = 0
        total_test = 0
        with torch.no_grad():
            for xb_test, yb_test in test_loader:
                xb_test = xb_test.to(device, non_blocking=True)
                yb_test = yb_test.to(device, non_blocking=True)
                with torch.amp.autocast("cuda", enabled=use_amp):
                    test_logits = model(xb_test)
                preds = test_logits.argmax(dim=1)
                correct += (preds == yb_test).sum().item()
                total_test += len(yb_test)
        acc = correct / max(total_test, 1)

        if acc > best_acc:
            best_acc = acc
            # Ensure float32 before saving (AMP autocast may leave BatchNorm buffers in float16)
            model.float()
            save_dict = {
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "n_features": n_features,
                "hidden_channels": hidden_channels,
                "n_classes": 3,
                "epoch": epoch,
                "accuracy": best_acc,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            # Save as variant-specific latest file
            latest_filename = f"{variant_name}_latest.pt"
            torch.save(save_dict, output_path / latest_filename)

            # Model versioning: save timestamped copy
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            versioned_filename = f"{variant_name}_{ts}.pt"
            torch.save(save_dict, output_path / versioned_filename)

            # Keep only last 3 versioned copies per variant
            import glob as _glob
            version_pattern = str(output_path / f"{variant_name}_20*.pt")
            versioned_files = sorted(_glob.glob(version_pattern))
            while len(versioned_files) > 3:
                os.remove(versioned_files.pop(0))

            # Save best model copy when new best accuracy is achieved
            best_path = output_path / f"{variant_name}_best.pt"
            existing_best_acc = 0.0
            if best_path.exists():
                try:
                    old_best = torch.load(best_path, map_location="cpu", weights_only=True)
                    existing_best_acc = old_best.get("accuracy", 0.0)
                except Exception:
                    pass
            if best_acc > existing_best_acc:
                torch.save(save_dict, best_path)

    # Directional accuracy (ignore neutral class=2)
    model.float()  # Ensure float32 for final evaluation
    model.eval()
    with torch.no_grad():
        X_test_dev = X_test.to(device)
        y_test_dev = y_test.to(device)
        with torch.amp.autocast("cuda", enabled=use_amp):
            test_logits = model(X_test_dev)
        preds = test_logits.argmax(dim=1)
        dir_mask = y_test_dev != 2
        dir_acc = (preds[dir_mask] == y_test_dev[dir_mask]).float().mean().item() if dir_mask.sum() > 0 else 0.0

    metadata = {
        "model_type": "tcn",
        "variant": variant_name,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples_train": int(len(X_train)),
        "samples_test": int(len(X_test)),
        "accuracy": round(best_acc, 4),
        "directional_accuracy": round(dir_acc, 4),
        "rl_weighted": reward_weights is not None,
        "features": TECHNICAL_FEATURES,
        "seq_length": seq_length,
        "hidden_channels": hidden_channels,
        "device": str(device),
        "version": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "learning_type": "reinforcement_online",
        "mixed_precision": use_amp,
        "optimizer": "AdamW",
        "lr_scheduler": "CosineAnnealingWarmRestarts",
    }

    with open(output_path / f"{variant_name}_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("TCN RL training complete", variant=variant_name, accuracy=best_acc,
                dir_accuracy=dir_acc, rl_weighted=reward_weights is not None)
    return metadata


def train_xgboost_rl(
    features: np.ndarray,
    targets: np.ndarray,
    reward_weights: Optional[np.ndarray],
    existing_model_path: Optional[str],
    output_path: Path,
    n_rounds: int = 20,
    lr: float = 0.03,
) -> dict:
    """Train/update XGBoost with RL reward-weighted samples.

    Uses xgb.train() with xgb_model parameter for incremental learning.
    Reward weights increase importance of samples where the model was right/wrong.
    """
    import xgboost as xgb

    # Feature names matching prediction service
    feature_names = TECHNICAL_FEATURES + [
        "sentiment_score", "sentiment_momentum_1h", "sentiment_momentum_4h",
        "sentiment_momentum_24h", "sentiment_volume", "fear_greed_index",
        "whale_activity_score", "exchange_netflow", "funding_rate",
        "google_trends_score", "social_volume_zscore",
        "price_change_1m", "price_change_5m", "price_change_15m",
        "high_low_range", "close_open_ratio", "upper_shadow_pct",
        "lower_shadow_pct", "body_pct", "volume_change_pct",
    ]

    # Pad features to 40 columns if we only have 20 technical
    if features.shape[1] < len(feature_names):
        padding = np.zeros((features.shape[0], len(feature_names) - features.shape[1]))
        features = np.concatenate([features, padding], axis=1)
    elif features.shape[1] > len(feature_names):
        features = features[:, :len(feature_names)]

    # Walk-forward split
    split = int(len(features) * 0.8)
    X_train, X_test = features[:split], features[split:]
    y_train, y_test = targets[:split], targets[split:]

    # RL sample weights
    if reward_weights is not None:
        w_train = np.maximum(reward_weights[:split], 0.1)
    else:
        w_train = np.ones(len(X_train))

    dtrain = xgb.DMatrix(X_train, label=y_train, weight=w_train, feature_names=feature_names)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=feature_names)

    params = {
        "objective": "multi:softprob",
        "num_class": 5,
        "eval_metric": "mlogloss",
        "max_depth": XGB_MAX_DEPTH,
        "learning_rate": lr,
        "tree_method": "hist",
        "device": "cpu",  # Use CPU — GPU memory reserved by TCN variants
        "subsample": 0.8,
        "colsample_bytree": 0.8,
    }

    # Incremental learning: continue from existing model
    existing_booster = None
    if existing_model_path and os.path.isfile(existing_model_path):
        try:
            existing_booster = xgb.Booster()
            existing_booster.load_model(existing_model_path)
            logger.info("XGBoost: loaded existing model for incremental training")
        except Exception as e:
            logger.warning("XGBoost: could not load existing, training fresh", error=str(e))
            existing_booster = None

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=n_rounds,
        evals=[(dtest, "test")],
        verbose_eval=False,
        xgb_model=existing_booster,
    )

    # Evaluate
    preds_proba = model.predict(dtest)
    preds = np.argmax(preds_proba, axis=1)
    accuracy = float(np.mean(preds == y_test))

    # Directional accuracy (non-hold)
    # Directional: non-hold predictions that match non-hold targets
    dir_mask = (y_test != 2) | (preds != 2)  # either target or pred is non-hold
    if dir_mask.sum() > 0:
        # Check if predicted direction matches actual direction
        pred_dir = np.where(preds > 2, 1, np.where(preds < 2, -1, 0))
        true_dir = np.where(y_test > 2, 1, np.where(y_test < 2, -1, 0))
        nonzero = (pred_dir != 0) | (true_dir != 0)
        dir_acc = float(np.mean(pred_dir[nonzero] == true_dir[nonzero])) if nonzero.sum() > 0 else 0.0
    else:
        dir_acc = 0.0

    # Save
    model_path = output_path / "xgboost_latest.json"
    model.save_model(str(model_path))

    metadata = {
        "model_type": "xgboost",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples_train": int(len(X_train)),
        "samples_test": int(len(X_test)),
        "accuracy": round(accuracy, 4),
        "directional_accuracy": round(dir_acc, 4),
        "rl_weighted": reward_weights is not None,
        "features": feature_names,
        "n_boost_rounds": n_rounds,
        "incremental": existing_booster is not None,
        "version": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "learning_type": "reinforcement_online",
    }

    with open(output_path / "xgboost_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("XGBoost RL training complete", accuracy=accuracy, dir_accuracy=dir_acc,
                incremental=existing_booster is not None)
    return metadata


def update_registry(models_dir: Path, tcn_meta: dict, xgb_meta: dict):
    """Update registry.json so the prediction service discovers the models."""
    registry_path = models_dir / "registry.json"
    entries = []

    if os.path.isfile(registry_path):
        try:
            with open(registry_path) as f:
                entries = json.load(f)
        except Exception:
            entries = []

    now = datetime.now(timezone.utc).isoformat()

    if tcn_meta.get("accuracy"):
        entries.append({
            "model_name": "tcn",
            "version": tcn_meta.get("version", now),
            "creation_date": now,
            "metrics": {
                "accuracy": tcn_meta.get("accuracy", 0),
                "directional_accuracy": tcn_meta.get("directional_accuracy", 0),
            },
            "path": str(models_dir / "tcn_latest.pt"),
        })

    if xgb_meta.get("accuracy"):
        entries.append({
            "model_name": "xgboost",
            "version": xgb_meta.get("version", now),
            "creation_date": now,
            "metrics": {
                "accuracy": xgb_meta.get("accuracy", 0),
                "directional_accuracy": xgb_meta.get("directional_accuracy", 0),
            },
            "path": str(models_dir / "xgboost_latest.json"),
        })

    with open(registry_path, "w") as f:
        json.dump(entries, f, indent=2)

    logger.info("Registry updated", tcn_version=tcn_meta.get("version"),
                xgb_version=xgb_meta.get("version"))


async def log_to_nerve_monitor(redis: aioredis.Redis, message: str, details: dict,
                                level: str = "info", category: str = "model"):
    """Log training events to the AI Nerve Monitor."""
    import uuid
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "action": "rl_training",
        "level": level,
        "symbol": "",
        "confidence": details.get("accuracy", 0),
        "details": details,
        "service": "continuous-learner",
        "message": message,
    }
    try:
        await redis.lpush("ai:logs", json.dumps(entry))
        await redis.ltrim("ai:logs", 0, 9999)
        await redis.lpush(f"ai:logs:{category}", json.dumps(entry))
        await redis.ltrim(f"ai:logs:{category}", 0, 999)
        await redis.publish("ai:activity", json.dumps(entry))

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await redis.hincrby(f"ai:stats:{today}", category, 1)
        await redis.hincrby(f"ai:stats:{today}", f"{category}:{level}", 1)
    except Exception:
        pass


# ── Main Training Loop ────────────────────────────────────────────────

async def load_candle_data(pool: asyncpg.Pool, symbols: list, days: int) -> pd.DataFrame:
    """Load candle data from TimescaleDB. Falls back to deriving from ticks."""
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT time, symbol, open, high, low, close, volume
               FROM candles
               WHERE symbol = ANY($1::text[]) AND time >= $2
               ORDER BY symbol, time ASC""",
            symbols, start_time,
        )

        # If not enough candle data, derive from ticks
        candle_symbols = {r["symbol"] for r in rows}
        missing = [s for s in symbols if s not in candle_symbols]
        if missing:
            tick_rows = await conn.fetch(
                """WITH bucketed AS (
                    SELECT
                        time_bucket(INTERVAL '5 minutes', time) AS time,
                        symbol,
                        first(price, time) AS open,
                        max(price) AS high,
                        min(price) AS low,
                        last(price, time) AS close,
                        sum(COALESCE(volume, 0)) AS volume
                    FROM ticks
                    WHERE symbol = ANY($1::text[]) AND time >= $2
                    GROUP BY time_bucket(INTERVAL '5 minutes', time), symbol
                    HAVING COUNT(*) >= 2
                )
                SELECT time, symbol, open, high, low, close, volume
                FROM bucketed
                ORDER BY symbol, time ASC""",
                missing[:50], start_time,  # Limit to 50 to avoid huge queries
            )
            rows = list(rows) + list(tick_rows)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


async def training_cycle(pool: asyncpg.Pool, redis: aioredis.Redis,
                          reward_tracker: RewardTracker, cycle_num: int):
    """Run one training cycle: load data, compute rewards, train both models."""

    logger.info(f"=== Training cycle {cycle_num} starting ===")
    await log_to_nerve_monitor(redis, f"RL training cycle {cycle_num} starting",
                                {"cycle": cycle_num})

    # Load data
    candles_df = await load_candle_data(pool, DEFAULT_SYMBOLS, days=TRAINING_DAYS)
    if candles_df.empty or len(candles_df) < MIN_SAMPLES_FOR_TRAINING:
        logger.warning("Insufficient candle data for training", count=len(candles_df))
        return

    # v2: Data freshness validation
    if "time" in candles_df.columns and len(candles_df) > 0:
        latest_candle = pd.Timestamp(candles_df["time"].max())
        if latest_candle.tzinfo is None:
            latest_candle = latest_candle.tz_localize("UTC")
        data_age_min = (datetime.now(timezone.utc) - latest_candle.to_pydatetime()).total_seconds() / 60
        if data_age_min > 30:
            logger.warning("Training data may be STALE — newest candle is old",
                           age_minutes=round(data_age_min, 1),
                           latest_candle=str(latest_candle))
        else:
            logger.info("Training data fresh", age_minutes=round(data_age_min, 1))

    logger.info(f"Loaded {len(candles_df)} candles for {candles_df['symbol'].nunique()} symbols")

    # Evaluate pending prediction rewards
    reward_summary = await reward_tracker.evaluate_rewards(pool)
    if reward_summary:
        logger.info("Reward evaluation", rewards=reward_summary)

    # v4: Live PnL feedback — read recent trade outcomes from Redis
    pnl_signals = await fetch_pnl_reward_signal(redis, lookback_hours=6)

    # Compute features and targets per symbol — parallelized across CPU cores
    now_utc = datetime.now(timezone.utc)
    symbols_to_process = []
    symbol_dfs = {}

    for symbol in candles_df["symbol"].unique():
        sym_df = candles_df[candles_df["symbol"] == symbol].sort_values("time").reset_index(drop=True)
        if len(sym_df) < 100:
            continue
        symbols_to_process.append(symbol)
        symbol_dfs[symbol] = sym_df

    def _process_symbol_data(symbol: str) -> Optional[tuple]:
        """Compute features, targets, and weights for one symbol. Runs in parallel."""
        global _feature_cache, _feature_cache_hits, _feature_cache_misses
        sym_df = symbol_dfs[symbol]
        n_candles = len(sym_df)

        # v6: Check feature cache — reuse if candle count unchanged (same data)
        cached = _feature_cache.get(symbol)
        if cached and cached[0] == n_candles:
            feats, t3, t5 = cached[1], cached[2], cached[3]
            _feature_cache_hits += 1
        else:
            feats = compute_features_for_df(sym_df)  # (N, 20)
            t3 = compute_targets_3class(sym_df["close"].values)
            t5 = compute_targets_5class(sym_df["close"].values)
            _feature_cache[symbol] = (n_candles, feats, t3, t5)
            _feature_cache_misses += 1

        sym_reward = reward_summary.get(symbol, 0.0)
        # v5: Combine RL reward with live PnL feedback (asymmetric multipliers)
        pnl_multiplier = pnl_signals.get(symbol, 1.0)
        reward_weight = (1.0 + sym_reward * 0.5) * pnl_multiplier

        weights = np.ones(len(feats))
        timestamps_epoch = np.zeros(len(feats))
        if "time" in sym_df.columns:
            try:
                times_series = pd.to_datetime(sym_df["time"].values, utc=True)
                age_seconds = (now_utc - times_series).total_seconds()
                age_days = age_seconds.values.astype(float) / 86400
                recency = RECENCY_MAX_BOOST * np.power(0.5, age_days / RECENCY_HALF_LIFE_DAYS)
                recency = np.maximum(recency, 0.3)
                weights[:len(recency)] = recency * reward_weight
                timestamps_epoch[:len(times_series)] = times_series.astype(np.int64) / 1e9
            except Exception:
                weights[:] = reward_weight

        valid = len(feats) - REWARD_LOOKBACK_CANDLES
        return (feats[:valid], t3[:valid], t5[:valid], weights[:valid], timestamps_epoch[:valid])

    # Parallel feature computation across CPU cores
    from concurrent.futures import ThreadPoolExecutor
    import concurrent.futures

    all_features = []
    all_targets_3 = []
    all_targets_5 = []
    all_reward_weights = []
    all_timestamps = []

    n_workers = min(len(symbols_to_process), 48)  # Use up to 48 threads (numpy releases GIL for CPU-bound ops)
    if n_workers > 1:
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {executor.submit(_process_symbol_data, sym): sym for sym in symbols_to_process}
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result is not None:
                        feats, t3, t5, w, ts = result
                        all_features.append(feats)
                        all_targets_3.append(t3)
                        all_targets_5.append(t5)
                        all_reward_weights.append(w)
                        all_timestamps.append(ts)
                except Exception as e:
                    logger.debug("Symbol feature computation failed", symbol=futures[future], error=str(e))
    else:
        for sym in symbols_to_process:
            result = _process_symbol_data(sym)
            if result is not None:
                feats, t3, t5, w, ts = result
                all_features.append(feats)
                all_targets_3.append(t3)
                all_targets_5.append(t5)
                all_reward_weights.append(w)
                all_timestamps.append(ts)

    if not all_features:
        logger.warning("No features computed")
        return

    features = np.concatenate(all_features)
    targets_3 = np.concatenate(all_targets_3)
    targets_5 = np.concatenate(all_targets_5)
    reward_weights = np.concatenate(all_reward_weights)
    sample_timestamps = np.concatenate(all_timestamps)

    # v5: Apply per-sample PnL-based weights from recent trade history
    pnl_sample_weights = await fetch_trade_sample_weights(redis, len(features), sample_timestamps)
    reward_weights = reward_weights * pnl_sample_weights  # Combine recency + PnL weights

    logger.info(f"Training data: {len(features)} samples, {features.shape[1]} features, "
                f"PnL-weighted samples: {int((pnl_sample_weights > 1.0).sum())}")

    # v2: Always use RL weighting (warm start) and always try incremental learning
    tcn_existing = str(MODELS_DIR / "tcn_latest.pt")
    xgb_existing = str(MODELS_DIR / "xgboost_latest.json")

    # Load current model accuracy for performance gating
    current_tcn_acc = 0.0
    current_xgb_acc = 0.0
    if GATE_MODELS:
        try:
            tcn_meta_path = MODELS_DIR / "tcn_metadata.json"
            if tcn_meta_path.exists():
                with open(tcn_meta_path) as f:
                    current_tcn_acc = json.load(f).get("accuracy", 0)
            xgb_meta_path = MODELS_DIR / "xgboost_metadata.json"
            if xgb_meta_path.exists():
                with open(xgb_meta_path) as f:
                    current_xgb_acc = json.load(f).get("accuracy", 0)
        except Exception:
            pass

    # v5: Train ALL multi-timeframe TCN variants with FULL epochs — GPU can handle it
    # Each variant uses different sequence length and hidden channels
    TCN_VARIANT_CONFIGS = [
        {"name": "tcn_micro",  "seq_length": 15,  "hidden_channels": 256},
        {"name": "tcn_short",  "seq_length": 30,  "hidden_channels": 384},
        {"name": "tcn_medium", "seq_length": 60,  "hidden_channels": 512},
        {"name": "tcn_long",   "seq_length": 120, "hidden_channels": 512},
    ]

    # Train primary TCN using tcn_short config as default
    tcn_meta = await asyncio.to_thread(
        train_tcn_rl,
        features, targets_3,
        reward_weights,
        tcn_existing,
        MODELS_DIR,
        TCN_EPOCHS_PER_CYCLE,
        LEARNING_RATE_TCN,
        hidden_channels=192,
        seq_length=30,
        variant_name="tcn",
    )

    async def _train_variant(variant_cfg):
        """Train a single TCN variant with its own architecture config."""
        vname = variant_cfg["name"]
        v_hc = variant_cfg["hidden_channels"]
        v_sl = variant_cfg["seq_length"]
        v_existing = str(MODELS_DIR / f"{vname}_latest.pt")
        try:
            meta = await asyncio.to_thread(
                train_tcn_rl,
                features, targets_3,
                reward_weights,
                v_existing if os.path.isfile(v_existing) else None,
                MODELS_DIR,
                TCN_EPOCHS_PER_CYCLE,
                LEARNING_RATE_TCN,
                hidden_channels=v_hc,
                seq_length=v_sl,
                variant_name=vname,
            )
            logger.info(f"TCN variant {vname} trained (full epochs)",
                        accuracy=meta.get("accuracy", 0),
                        hidden_channels=v_hc, seq_length=v_sl)
            return meta
        except Exception as e:
            logger.warning(f"TCN variant {vname} training failed", error=str(e))
            return {"status": "failed", "variant": vname}

    # v5: Train ALL variants sequentially (they share GPU) — every variant gets full training
    variant_metas = []
    for vcfg in TCN_VARIANT_CONFIGS:
        vmeta = await _train_variant(vcfg)
        variant_metas.append(vmeta)
        logger.info(f"Variant {vcfg['name']} complete, moving to next")

    # Train XGBoost with RL
    xgb_meta = await asyncio.to_thread(
        train_xgboost_rl,
        features, targets_5,
        reward_weights,
        xgb_existing,
        MODELS_DIR,
        XGB_BOOST_ROUNDS_PER_CYCLE,
        LEARNING_RATE_XGB,
    )

    # v6: Performance gating — rolling window + staleness override
    tcn_deployed = True
    xgb_deployed = True
    MIN_ACCURACY_FLOOR_3CLASS = 0.40  # Better than random for 3-class (random=33%)
    MIN_ACCURACY_FLOOR_5CLASS = 0.25  # Better than random for 5-class (random=20%)
    STALENESS_MINUTES = 30

    def _should_deploy(new_acc, meta_pattern, model_label, min_floor=None):
        """Check if new model should be deployed using rolling window of last 3 models."""
        if min_floor is None:
            min_floor = MIN_ACCURACY_FLOOR_3CLASS
        MIN_ACCURACY_FLOOR = min_floor  # local alias for this call
        import glob as _glob

        # Check staleness of current model
        current_meta_path = MODELS_DIR / f"{model_label}_metadata.json"
        is_stale = False
        if current_meta_path.exists():
            try:
                with open(current_meta_path) as f:
                    trained_at = json.load(f).get("trained_at", "")
                if trained_at:
                    trained_time = datetime.fromisoformat(trained_at)
                    age_minutes = (datetime.now(timezone.utc) - trained_time).total_seconds() / 60
                    if age_minutes > STALENESS_MINUTES:
                        is_stale = True
                        logger.info(f"{model_label} model is stale ({age_minutes:.0f}min old), lowering deploy bar")
            except Exception:
                pass

        # If stale, always deploy (force refresh)
        if is_stale:
            return True

        # Collect accuracy history from last 3 versioned models
        version_pattern = str(MODELS_DIR / meta_pattern)
        versioned_files = sorted(_glob.glob(version_pattern))[-3:]

        if not versioned_files:
            # No previous models — deploy if above minimum floor
            if new_acc >= MIN_ACCURACY_FLOOR:
                return True
            logger.warning(f"{model_label} accuracy {new_acc:.4f} below floor {MIN_ACCURACY_FLOOR}")
            return False

        # Load accuracy from versioned model files
        recent_accs = []
        for vf in versioned_files:
            try:
                import torch
                state = torch.load(vf, map_location="cpu", weights_only=True)
                acc_val = state.get("accuracy", 0.0)
                if acc_val > 0:
                    recent_accs.append(acc_val)
            except Exception:
                pass

        if not recent_accs:
            return new_acc >= MIN_ACCURACY_FLOOR

        avg_recent = sum(recent_accs) / len(recent_accs)
        if new_acc >= avg_recent:
            logger.info(f"{model_label} beats rolling avg ({new_acc:.4f} >= {avg_recent:.4f}), deploying")
            return True
        else:
            logger.warning(f"{model_label} below rolling avg ({new_acc:.4f} < {avg_recent:.4f}), skipping deploy")
            return False

    if GATE_MODELS:
        new_tcn_acc = tcn_meta.get("accuracy", 0)
        new_xgb_acc = xgb_meta.get("accuracy", 0)
        if not _should_deploy(new_tcn_acc, "tcn_20*.pt", "tcn", min_floor=MIN_ACCURACY_FLOOR_3CLASS):
            tcn_deployed = False
        if not _should_deploy(new_xgb_acc, "xgboost_20*.json", "xgboost", min_floor=MIN_ACCURACY_FLOOR_5CLASS):
            xgb_deployed = False

    # Update registry and signal reload only if at least one model improved
    if tcn_deployed or xgb_deployed:
        update_registry(MODELS_DIR, tcn_meta if tcn_deployed else {}, xgb_meta if xgb_deployed else {})
        await redis.set("model:reload_signal", datetime.now(timezone.utc).isoformat())
        await redis.publish("model:reload", "updated")
        logger.info("Models deployed", tcn=tcn_deployed, xgb=xgb_deployed)
    else:
        logger.info("No model improvements — skipping deployment")

    # Save training summary
    summary = {
        "cycle": cycle_num,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "total_samples": len(features),
        "symbols": int(candles_df["symbol"].nunique()),
        "reward_summary": {k: round(v, 4) for k, v in reward_summary.items()},
        "pnl_signals": {k: round(v, 4) for k, v in pnl_signals.items()},
        "tcn": tcn_meta,
        "tcn_variants": [m for m in variant_metas if isinstance(m, dict)],
        "xgboost": xgb_meta,
        "tcn_deployed": tcn_deployed,
        "xgb_deployed": xgb_deployed,
        "recency_half_life_days": RECENCY_HALF_LIFE_DAYS,
        "outcome_window_minutes": REWARD_LOOKBACK_CANDLES * 5,
        "pnl_weighted_samples": int((pnl_sample_weights > 1.0).sum()),
        "version": "v5.0",
        "training_config": {
            "tcn_epochs": TCN_EPOCHS_PER_CYCLE,
            "xgb_rounds": XGB_BOOST_ROUNDS_PER_CYCLE,
            "batch_size": TCN_BATCH_SIZE,
            "gradient_accumulation": GRADIENT_ACCUMULATION_STEPS,
            "learning_rate_tcn": LEARNING_RATE_TCN,
            "pnl_big_win_mult": PNL_BIG_WIN_MULTIPLIER,
            "pnl_big_loss_mult": PNL_BIG_LOSS_MULTIPLIER,
        },
    }
    with open(MODELS_DIR / "training_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    await log_to_nerve_monitor(
        redis,
        f"RL cycle {cycle_num} complete — TCN acc: {tcn_meta.get('accuracy', 0):.1%}, "
        f"XGB acc: {xgb_meta.get('accuracy', 0):.1%}",
        {
            "cycle": cycle_num,
            "tcn_accuracy": tcn_meta.get("accuracy", 0),
            "xgb_accuracy": xgb_meta.get("accuracy", 0),
            "tcn_dir_accuracy": tcn_meta.get("directional_accuracy", 0),
            "xgb_dir_accuracy": xgb_meta.get("directional_accuracy", 0),
            "rl_weighted": cycle_num > 1,
            "samples": len(features),
        },
        level="info",
    )

    logger.info(f"=== Training cycle {cycle_num} complete ===")


async def listen_for_predictions(redis: aioredis.Redis, reward_tracker: RewardTracker):
    """Subscribe to all prediction channels and record them for reward evaluation.

    This closes the RL feedback loop: predictions are recorded with their price,
    then later evaluated against actual outcome to compute reward signals.
    """
    backoff = 1
    while running:
        try:
            pubsub = redis.pubsub()
            await pubsub.psubscribe("predictions:*")
            logger.info("Prediction listener started — recording predictions for RL rewards")
            backoff = 1

            async for message in pubsub.listen():
                if not running:
                    break
                if message["type"] != "pmessage":
                    continue
                try:
                    pred = json.loads(message["data"])
                    symbol = pred.get("symbol", "")
                    direction = pred.get("direction", "hold")
                    confidence = float(pred.get("confidence", 0))
                    price = float(pred.get("current_price", pred.get("price", 0)))

                    if symbol and price > 0 and confidence > 0.3:
                        await reward_tracker.record_prediction(
                            symbol=symbol, direction=direction,
                            confidence=confidence, price=price,
                        )
                except Exception:
                    pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Prediction listener error, reconnecting", error=str(e), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def listen_for_trade_closes(redis: aioredis.Redis, pool: asyncpg.Pool):
    """Subscribe to trade close events and trigger micro-training.

    v5: When a trade closes, we:
    1. Extract its feature vector and PnL outcome
    2. Add it to the in-memory buffer
    3. Run a quick micro-training on the TCN with buffered data
    This gives the model near-instant feedback from every trade.
    """
    backoff = 1
    while running:
        try:
            pubsub = redis.pubsub()
            # Listen for trade close notifications
            await pubsub.subscribe("trade:closed", "trade_closed")
            logger.info("Trade close listener started — micro-training enabled")
            backoff = 1

            async for message in pubsub.listen():
                if not running:
                    break
                if message["type"] != "message":
                    continue
                try:
                    trade = json.loads(message["data"])
                    symbol = trade.get("symbol", "")
                    realized_pnl = float(trade.get("realized_pnl", 0))
                    entry_price = float(trade.get("entry_price", trade.get("price", 0)))
                    entry_time_str = trade.get("entry_time", "")

                    if not symbol or entry_price <= 0:
                        continue

                    pnl_pct = realized_pnl / entry_price if entry_price > 0 else 0

                    # Compute PnL multiplier
                    if pnl_pct > PNL_BIG_WIN_THRESHOLD:
                        pnl_weight = PNL_BIG_WIN_MULTIPLIER
                    elif pnl_pct > 0:
                        pnl_weight = PNL_SMALL_WIN_MULTIPLIER
                    elif pnl_pct > PNL_BIG_LOSS_THRESHOLD:
                        pnl_weight = PNL_SMALL_LOSS_MULTIPLIER
                    else:
                        pnl_weight = PNL_BIG_LOSS_MULTIPLIER

                    # Try to get recent candle features for this symbol
                    try:
                        async with pool.acquire() as conn:
                            rows = await conn.fetch(
                                """SELECT time, open, high, low, close, volume
                                   FROM candles WHERE symbol = $1
                                   ORDER BY time DESC LIMIT 100""",
                                symbol,
                            )
                        if rows and len(rows) >= 20:
                            df = pd.DataFrame([dict(r) for r in reversed(rows)])
                            feats = compute_features_for_df(df)
                            if len(feats) > 0:
                                # Use the last feature vector as representative of this trade
                                last_feat = feats[-1]
                                # Determine target from actual trade outcome
                                target_3 = 0 if pnl_pct > 0.001 else (1 if pnl_pct < -0.001 else 2)
                                target_5 = (4 if pnl_pct > 0.015 else 3) if pnl_pct > 0.003 else \
                                           (0 if pnl_pct < -0.015 else 1) if pnl_pct < -0.003 else 2

                                ts = datetime.now(timezone.utc).timestamp()
                                _trade_buffer.add(last_feat, target_3, target_5, pnl_weight, ts)

                                logger.info("Trade added to micro-training buffer",
                                            symbol=symbol, pnl_pct=round(pnl_pct * 100, 2),
                                            weight=pnl_weight, buffer_size=len(_trade_buffer))

                                # Trigger micro-training if buffer has enough data
                                if len(_trade_buffer) >= 30:
                                    model_path = str(MODELS_DIR / "tcn_latest.pt")
                                    micro_result = await asyncio.to_thread(
                                        micro_train_tcn, _trade_buffer, model_path
                                    )
                                    if micro_result:
                                        await redis.publish("model:reload", "micro_updated")
                                        await log_to_nerve_monitor(
                                            redis,
                                            f"Micro-training on {symbol} trade (PnL: {pnl_pct*100:.1f}%)",
                                            micro_result,
                                            level="info",
                                            category="model",
                                        )
                    except Exception as e:
                        logger.debug("Failed to compute features for micro-training",
                                     symbol=symbol, error=str(e))

                except Exception as e:
                    logger.debug("Trade close processing error", error=str(e))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Trade close listener error, reconnecting", error=str(e), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def main():
    global DEFAULT_SYMBOLS

    logger.info("Goblin Continuous Learner v5.0 starting — MAX GPU utilization mode",
                interval_min=TRAIN_INTERVAL_MINUTES,
                tcn_epochs=TCN_EPOCHS_PER_CYCLE,
                xgb_rounds=XGB_BOOST_ROUNDS_PER_CYCLE,
                batch_size=TCN_BATCH_SIZE,
                grad_accum=GRADIENT_ACCUMULATION_STEPS,
                lr_tcn=LEARNING_RATE_TCN,
                pnl_big_win=PNL_BIG_WIN_MULTIPLIER,
                pnl_big_loss=PNL_BIG_LOSS_MULTIPLIER,
                recency_half_life=RECENCY_HALF_LIFE_DAYS,
                outcome_window_min=REWARD_LOOKBACK_CANDLES * 5,
                models_dir=str(MODELS_DIR))

    pool = await asyncpg.create_pool(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        database=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, min_size=5, max_size=20,
    )

    redis = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        password=REDIS_PASSWORD, decode_responses=True,
    )
    await redis.ping()

    # Load symbols with actual data from DB
    DEFAULT_SYMBOLS = await _load_symbols_from_db(pool)
    logger.info("Training symbols loaded", count=len(DEFAULT_SYMBOLS),
                first_five=DEFAULT_SYMBOLS[:5])

    reward_tracker = RewardTracker(redis)

    # v2: Start prediction listener in background (closes the RL feedback loop)
    prediction_task = asyncio.create_task(listen_for_predictions(redis, reward_tracker))

    # v5: Start trade close listener for micro-training
    trade_close_task = asyncio.create_task(listen_for_trade_closes(redis, pool))

    cycle = 0

    # Run first training immediately
    try:
        cycle += 1
        await training_cycle(pool, redis, reward_tracker, cycle)
    except Exception as e:
        logger.error("Initial training cycle failed", error=str(e))

    # Then loop on schedule — every 1 minute, GPU should NEVER be idle
    while running:
        try:
            # Sleep in small increments so we can respond to signals
            for _ in range(TRAIN_INTERVAL_MINUTES * 60):
                if not running:
                    break
                await asyncio.sleep(1)

            if not running:
                break

            cycle += 1
            await training_cycle(pool, redis, reward_tracker, cycle)

        except Exception as e:
            logger.error("Training cycle failed", cycle=cycle, error=str(e))
            # Wait a bit before retrying
            await asyncio.sleep(30)  # v5: shorter retry wait (was 60)

    logger.info("Continuous learner shutting down")
    prediction_task.cancel()
    trade_close_task.cancel()
    try:
        await prediction_task
    except asyncio.CancelledError:
        pass
    try:
        await trade_close_task
    except asyncio.CancelledError:
        pass
    await pool.close()
    await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
