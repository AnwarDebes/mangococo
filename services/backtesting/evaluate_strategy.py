"""
Strategy Evaluation: Old (fixed exits) vs New (3-layer adaptive)

Generates realistic synthetic crypto market data with regime changes,
then simulates both strategies through identical conditions to produce
an honest before-vs-after comparison.

No mock numbers — all metrics are computed from simulated trade execution
with realistic fees (0.1%) and slippage (0.03%).

Usage:
    python evaluate_strategy.py
"""
import sys
import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np
import pandas as pd

# Add parent for strategy imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategy.regime import classify_regime, regime_allows_entry, RegimeState
from strategy.edge_gate import evaluate_edge, EdgeDecision
from strategy.vol_sizing import calculate_vol_targeted_size, SizingResult
from strategy.adaptive_exit import compute_adaptive_exit_params, AdaptiveExitParams

# Import metrics
sys.path.insert(0, os.path.dirname(__file__))
from metrics import generate_report

np.random.seed(42)

# -- Constants ------------------------------------------------------------
FEE_PCT = 0.001          # 0.1% per side
SLIPPAGE_PCT = 0.0003    # 0.03% slippage
INITIAL_CAPITAL = 10000.0
CANDLE_INTERVAL_S = 60   # 1-minute candles
PREDICTION_INTERVAL = 5  # predict every 5 candles (5 min)
TOTAL_DAYS = 14          # 2 weeks of data


# ===========================================================================
# PART 1: Synthetic Market Data Generator
# ===========================================================================

def generate_regime_schedule(n_candles: int) -> List[str]:
    """Generate a regime schedule with realistic regime changes."""
    regimes = []
    regime_options = ["trending_up", "trending_down", "choppy", "high_vol"]
    # Weighted: trends are less common than chop in crypto
    weights = [0.25, 0.15, 0.40, 0.20]

    current_regime = np.random.choice(regime_options, p=weights)
    regime_duration = np.random.randint(200, 800)  # 3-13 hours at 1min candles

    for i in range(n_candles):
        regimes.append(current_regime)
        regime_duration -= 1
        if regime_duration <= 0:
            current_regime = np.random.choice(regime_options, p=weights)
            regime_duration = np.random.randint(200, 800)

    return regimes


def generate_candles(n_candles: int, symbol: str = "BTC/USDT") -> pd.DataFrame:
    """Generate realistic 1-minute crypto candles with regime-driven dynamics."""
    regimes = generate_regime_schedule(n_candles)

    price = 65000.0  # Starting BTC price
    prices = []
    volumes = []
    timestamps = []

    base_time = datetime(2025, 3, 1, tzinfo=timezone.utc)

    for i in range(n_candles):
        regime = regimes[i]

        # Regime-specific drift and volatility
        if regime == "trending_up":
            drift = 0.00003    # ~0.003% per minute = ~4.3% per day
            vol = 0.0008
        elif regime == "trending_down":
            drift = -0.00003
            vol = 0.0009
        elif regime == "choppy":
            drift = 0.0
            vol = 0.0006
        elif regime == "high_vol":
            drift = np.random.choice([-0.00002, 0.00002])
            vol = 0.0018
        else:
            drift = 0.0
            vol = 0.0007

        # Generate OHLC from random walk within the minute
        returns = drift + vol * np.random.randn(4)
        intra = price * np.cumprod(1 + returns)

        o = price
        h = max(o, *intra)
        l = min(o, *intra)
        c = intra[-1]
        price = c

        volume = np.random.lognormal(10, 1.5) * (2.0 if regime == "high_vol" else 1.0)

        ts = base_time + timedelta(seconds=i * CANDLE_INTERVAL_S)
        timestamps.append(ts)
        prices.append({"open": o, "high": h, "low": l, "close": c, "volume": volume})

    df = pd.DataFrame(prices)
    df["time"] = timestamps
    df["symbol"] = symbol
    df["regime"] = regimes
    return df


def compute_features_from_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical features from candle data (mirrors feature-store)."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values

    n = len(close)
    features = []

    for i in range(n):
        lookback = max(0, i - 30)
        window = close[lookback:i + 1]

        if len(window) < 14:
            features.append({})
            continue

        # ATR (14-period)
        tr_vals = []
        for j in range(max(1, lookback), i + 1):
            tr = max(
                high[j] - low[j],
                abs(high[j] - close[j - 1]),
                abs(low[j] - close[j - 1]),
            )
            tr_vals.append(tr)
        atr = np.mean(tr_vals[-14:]) if len(tr_vals) >= 14 else np.mean(tr_vals) if tr_vals else 0
        atr_pct = (atr / close[i] * 100) if close[i] > 0 else 0

        # RSI (14-period)
        if len(window) >= 15:
            deltas = np.diff(window[-15:])
            gains = np.mean(deltas[deltas > 0]) if np.any(deltas > 0) else 0
            losses = -np.mean(deltas[deltas < 0]) if np.any(deltas < 0) else 0.0001
            rs = gains / losses if losses > 0 else 100
            rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50

        # Bollinger Bandwidth (20-period)
        bb_window = window[-20:] if len(window) >= 20 else window
        bb_mean = np.mean(bb_window)
        bb_std = np.std(bb_window)
        bb_bandwidth = (2 * bb_std / bb_mean) if bb_mean > 0 else 0

        # Momentum (5m, 15m, 30m in % terms)
        mom_5 = ((close[i] - close[max(0, i - 5)]) / close[max(0, i - 5)] * 100) if i >= 5 else 0
        mom_15 = ((close[i] - close[max(0, i - 15)]) / close[max(0, i - 15)] * 100) if i >= 15 else 0
        mom_30 = ((close[i] - close[max(0, i - 30)]) / close[max(0, i - 30)] * 100) if i >= 30 else 0

        # EMA crosses (simplified)
        ema_9 = np.mean(window[-9:]) if len(window) >= 9 else close[i]
        ema_21 = np.mean(window[-21:]) if len(window) >= 21 else close[i]
        ema_25 = np.mean(window[-25:]) if len(window) >= 25 else close[i]
        ema_50 = np.mean(window[-min(50, len(window)):])
        ema_9_21_cross = 1 if ema_9 > ema_21 else -1
        ema_25_50_cross = 1 if ema_25 > ema_50 else -1

        # Volume ratio
        vol_window = volume[max(0, i - 20):i + 1]
        vol_ratio = volume[i] / np.mean(vol_window) if np.mean(vol_window) > 0 else 1.0

        features.append({
            "atr_pct": atr_pct,
            "rsi_14": rsi,
            "bb_bandwidth": bb_bandwidth,
            "momentum_5m": mom_5,
            "momentum_15m": mom_15,
            "momentum_30m": mom_30,
            "ema_9_21_cross": ema_9_21_cross,
            "ema_25_50_cross": ema_25_50_cross,
            "volume_ratio": vol_ratio,
            "spread_pct": np.random.uniform(0.01, 0.15),  # realistic spread
        })

    return pd.DataFrame(features)


def generate_predictions(
    candles: pd.DataFrame,
    features_df: pd.DataFrame,
    prediction_interval: int = 5,
) -> pd.DataFrame:
    """Simulate ML ensemble predictions with realistic accuracy (~55% directional)."""
    predictions = []
    n = len(candles)

    for i in range(30, n, prediction_interval):  # skip warmup
        regime = candles.iloc[i]["regime"]
        close = candles.iloc[i]["close"]
        future_close = candles.iloc[min(i + 10, n - 1)]["close"]  # 10-min lookahead
        actual_direction = "up" if future_close > close else "down"

        feat = features_df.iloc[i].to_dict() if i < len(features_df) and not features_df.iloc[i].isna().all() else {}
        rsi = feat.get("rsi_14", 50)

        # Simulate model accuracy: ~55% correct direction (realistic for crypto ML)
        correct = np.random.random() < 0.55

        if correct:
            if actual_direction == "up":
                direction = np.random.choice(["buy", "strong_buy"], p=[0.7, 0.3])
            else:
                direction = np.random.choice(["sell", "strong_sell"], p=[0.7, 0.3])
        else:
            # Wrong prediction
            if actual_direction == "up":
                direction = np.random.choice(["sell", "hold", "strong_sell"], p=[0.4, 0.4, 0.2])
            else:
                direction = np.random.choice(["buy", "hold", "strong_buy"], p=[0.4, 0.4, 0.2])

        confidence = np.clip(np.random.beta(3, 3), 0.2, 0.95)

        # Simulate model breakdown
        tcn_score = np.random.uniform(0.3, 0.7)
        xgb_score = np.random.uniform(0.3, 0.7)
        agreement = 1 if np.sign(tcn_score - 0.5) == np.sign(xgb_score - 0.5) else 0

        predictions.append({
            "time": candles.iloc[i]["time"],
            "symbol": candles.iloc[i]["symbol"],
            "direction": direction,
            "confidence": round(confidence, 3),
            "score": round((tcn_score + xgb_score) / 2, 3),
            "breakdown": {
                "tcn": round(tcn_score, 3),
                "xgboost": round(xgb_score, 3),
                "sentiment_available": float(np.random.random() > 0.3),
                "onchain_available": float(np.random.random() > 0.4),
                "agreement_bonus": agreement * 0.15,
            },
        })

    return pd.DataFrame(predictions)


# ===========================================================================
# PART 2: Strategy Simulators
# ===========================================================================

@dataclass
class SimPosition:
    symbol: str
    side: str
    entry_price: float
    entry_time: datetime
    amount_usd: float
    quantity: float


@dataclass
class SimTrade:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees: float
    exit_reason: str
    hold_minutes: float
    regime_at_exit: str = ""


def _exec_price(price: float, side: str) -> float:
    """Apply slippage."""
    if side == "buy":
        return price * (1 + SLIPPAGE_PCT)
    return price * (1 - SLIPPAGE_PCT)


def _fee(notional: float) -> float:
    return notional * FEE_PCT


# -- OLD STRATEGY: Fixed exits (the system before our changes) ----------

def simulate_old_strategy(
    candles: pd.DataFrame,
    predictions: pd.DataFrame,
    features_df: pd.DataFrame,
) -> Tuple[List[SimTrade], List[float]]:
    """
    Old strategy: take every buy/sell signal, fixed 0.5% SL / 0.1% TP / 30min max hold.
    This simulates the pre-improvement behavior.
    """
    cash = INITIAL_CAPITAL
    position: Optional[SimPosition] = None
    trades: List[SimTrade] = []
    equity_curve: List[float] = [INITIAL_CAPITAL]

    # Index predictions by time
    pred_by_time = {}
    for _, p in predictions.iterrows():
        pred_by_time[p["time"]] = p

    for i in range(len(candles)):
        row = candles.iloc[i]
        ts = row["time"]
        price = row["close"]
        regime = row["regime"]

        # Update equity
        if position:
            if position.side == "long":
                mtm = position.quantity * price
            else:
                mtm = position.quantity * (2 * position.entry_price - price)
            equity_curve.append(cash + mtm)
        else:
            equity_curve.append(cash)

        # Check fixed exits first (this is the old behavior)
        if position:
            pnl_pct = ((price - position.entry_price) / position.entry_price
                       if position.side == "long"
                       else (position.entry_price - price) / position.entry_price)
            hold_min = (ts - position.entry_time).total_seconds() / 60

            exit_reason = None
            # Fixed stop-loss: -0.5%
            if pnl_pct <= -0.005:
                exit_reason = "stop_loss"
            # Fixed take-profit: +0.1%
            elif pnl_pct >= 0.001:
                exit_reason = "take_profit"
            # Max hold time: 30 minutes
            elif hold_min >= 30:
                exit_reason = "max_hold_time"

            if exit_reason:
                exec_p = _exec_price(price, "sell" if position.side == "long" else "buy")
                notional = position.quantity * exec_p
                fee = _fee(notional) + _fee(position.quantity * position.entry_price)
                if position.side == "long":
                    pnl = (exec_p - position.entry_price) * position.quantity - fee
                else:
                    pnl = (position.entry_price - exec_p) * position.quantity - fee
                actual_pnl_pct = pnl / (position.entry_price * position.quantity)

                trades.append(SimTrade(
                    symbol=position.symbol, side=position.side,
                    entry_time=position.entry_time, exit_time=ts,
                    entry_price=position.entry_price, exit_price=exec_p,
                    quantity=position.quantity, pnl=pnl, pnl_pct=actual_pnl_pct,
                    fees=fee, exit_reason=exit_reason,
                    hold_minutes=hold_min, regime_at_exit=regime,
                ))
                cash += notional - _fee(notional)
                position = None

        # Check for new signal
        pred = pred_by_time.get(ts)
        if pred is not None and position is None:
            direction = pred["direction"]
            confidence = pred["confidence"]

            if direction in ("buy", "strong_buy"):
                # Old strategy: fixed 8% position for strong, 4% for normal
                size_pct = 0.08 if direction == "strong_buy" else 0.04
                alloc = cash * size_pct
                exec_p = _exec_price(price, "buy")
                qty = alloc / exec_p
                fee = _fee(alloc)
                if alloc + fee <= cash:
                    cash -= alloc + fee
                    position = SimPosition(
                        symbol=row["symbol"], side="long",
                        entry_price=exec_p, entry_time=ts,
                        amount_usd=alloc, quantity=qty,
                    )

        # If we have a prediction that says sell and we're in a long, exit immediately (old behavior)
        if pred is not None and position and position.side == "long":
            direction = pred["direction"]
            if direction in ("sell", "strong_sell"):
                exec_p = _exec_price(price, "sell")
                notional = position.quantity * exec_p
                fee = _fee(notional) + _fee(position.quantity * position.entry_price)
                pnl = (exec_p - position.entry_price) * position.quantity - fee
                actual_pnl_pct = pnl / (position.entry_price * position.quantity)
                hold_min = (ts - position.entry_time).total_seconds() / 60

                trades.append(SimTrade(
                    symbol=position.symbol, side=position.side,
                    entry_time=position.entry_time, exit_time=ts,
                    entry_price=position.entry_price, exit_price=exec_p,
                    quantity=position.quantity, pnl=pnl, pnl_pct=actual_pnl_pct,
                    fees=fee, exit_reason="ai_sell_immediate",
                    hold_minutes=hold_min, regime_at_exit=regime,
                ))
                cash += notional - _fee(notional)
                position = None

    # Close any remaining position
    if position:
        last_price = candles.iloc[-1]["close"]
        exec_p = _exec_price(last_price, "sell" if position.side == "long" else "buy")
        notional = position.quantity * exec_p
        fee = _fee(notional) + _fee(position.quantity * position.entry_price)
        if position.side == "long":
            pnl = (exec_p - position.entry_price) * position.quantity - fee
        else:
            pnl = (position.entry_price - exec_p) * position.quantity - fee
        actual_pnl_pct = pnl / (position.entry_price * position.quantity)
        hold_min = (candles.iloc[-1]["time"] - position.entry_time).total_seconds() / 60
        trades.append(SimTrade(
            symbol=position.symbol, side=position.side,
            entry_time=position.entry_time, exit_time=candles.iloc[-1]["time"],
            entry_price=position.entry_price, exit_price=exec_p,
            quantity=position.quantity, pnl=pnl, pnl_pct=actual_pnl_pct,
            fees=fee, exit_reason="end_of_data",
            hold_minutes=hold_min, regime_at_exit=candles.iloc[-1]["regime"],
        ))

    return trades, equity_curve


# -- NEW STRATEGY: 3-layer adaptive -------------------------------------

def simulate_new_strategy(
    candles: pd.DataFrame,
    predictions: pd.DataFrame,
    features_df: pd.DataFrame,
) -> Tuple[List[SimTrade], List[float]]:
    """
    New strategy: Layer A (regime) -> Layer B (edge gate) -> Layer C (vol sizing + adaptive exits).
    """
    cash = INITIAL_CAPITAL
    position: Optional[SimPosition] = None
    trades: List[SimTrade] = []
    equity_curve: List[float] = [INITIAL_CAPITAL]

    # Exit pressure state
    pressure: float = 0.0
    consecutive_sells: int = 0

    # Index predictions by time
    pred_by_time = {}
    for _, p in predictions.iterrows():
        pred_by_time[p["time"]] = p

    for i in range(len(candles)):
        row = candles.iloc[i]
        ts = row["time"]
        price = row["close"]
        regime_name = row["regime"]

        # Get features for this candle
        feat = features_df.iloc[i].to_dict() if i < len(features_df) and not features_df.iloc[i].isna().all() else {}

        # Classify regime from features
        regime = classify_regime(feat, symbol=row["symbol"])

        # Update equity
        if position:
            if position.side == "long":
                mtm = position.quantity * price
            else:
                mtm = position.quantity * (2 * position.entry_price - price)
            equity_curve.append(cash + mtm)
        else:
            equity_curve.append(cash)

        pred = pred_by_time.get(ts)

        # -- EXIT LOGIC: Adaptive pressure-based exits ------------------
        if position and pred is not None:
            direction = pred["direction"]
            confidence = pred["confidence"]

            pnl_pct = ((price - position.entry_price) / position.entry_price
                       if position.side == "long"
                       else (position.entry_price - price) / position.entry_price)
            hold_min = (ts - position.entry_time).total_seconds() / 60
            atr_pct = feat.get("atr_pct", 0.5)

            # Compute adaptive exit parameters
            adaptive = compute_adaptive_exit_params(
                regime=regime, pnl_pct=pnl_pct,
                atr_pct=atr_pct, hold_time_minutes=hold_min,
            )

            if direction in ("sell", "strong_sell"):
                weight = adaptive.strong_sell_weight if direction == "strong_sell" else adaptive.sell_weight
                base = confidence * weight
                if pnl_pct < -0.02:
                    base *= 1.3
                elif pnl_pct > 0.01:
                    base *= 0.8
                if confidence > 0.7:
                    base *= 1.2
                if adaptive.vol_urgency > 0:
                    base *= (1.0 + adaptive.vol_urgency * 0.5)
                pressure += base
                consecutive_sells += 1
            else:
                decay_mult = 1.5 if direction in ("buy", "strong_buy") else 1.0
                pressure = max(0, pressure - adaptive.decay_rate * decay_mult)
                consecutive_sells = 0

            should_exit = (
                pressure >= adaptive.pressure_threshold and
                consecutive_sells >= adaptive.min_consecutive_sells
            )

            # Circuit breaker
            if pnl_pct <= -0.15:
                should_exit = True

            if should_exit:
                exec_p = _exec_price(price, "sell" if position.side == "long" else "buy")
                notional = position.quantity * exec_p
                fee = _fee(notional) + _fee(position.quantity * position.entry_price)
                if position.side == "long":
                    pnl = (exec_p - position.entry_price) * position.quantity - fee
                else:
                    pnl = (position.entry_price - exec_p) * position.quantity - fee
                actual_pnl_pct = pnl / (position.entry_price * position.quantity)

                exit_reason = "adaptive_exit"
                if pnl_pct <= -0.15:
                    exit_reason = "circuit_breaker"
                elif direction == "strong_sell" and confidence >= 0.6:
                    exit_reason = "ai_strong_sell"
                elif pnl_pct < -0.01:
                    exit_reason = "ai_sell_cut_loss"
                elif pnl_pct > 0.005:
                    exit_reason = "ai_sell_take_profit"

                trades.append(SimTrade(
                    symbol=position.symbol, side=position.side,
                    entry_time=position.entry_time, exit_time=ts,
                    entry_price=position.entry_price, exit_price=exec_p,
                    quantity=position.quantity, pnl=pnl, pnl_pct=actual_pnl_pct,
                    fees=fee, exit_reason=exit_reason,
                    hold_minutes=hold_min, regime_at_exit=regime.regime,
                ))
                cash += notional - _fee(notional)
                position = None
                pressure = 0.0
                consecutive_sells = 0

        # -- ENTRY LOGIC: Regime -> Edge Gate -> Vol Sizing ---------------
        if pred is not None and position is None:
            direction = pred["direction"]
            confidence = pred["confidence"]

            if direction not in ("buy", "strong_buy"):
                continue

            # Layer A: Regime filter
            if not regime_allows_entry(regime, "buy"):
                continue

            # Layer B: Edge gate
            edge = evaluate_edge(
                prediction=pred.to_dict() if hasattr(pred, 'to_dict') else dict(pred),
                regime=regime,
                features=feat,
            )
            if not edge.take:
                continue

            # Layer C: Vol-targeted sizing
            portfolio_value = cash  # simplified: no open positions at entry
            sizing = calculate_vol_targeted_size(
                portfolio_value=portfolio_value,
                current_price=price,
                atr_pct=feat.get("atr_pct", 0.5),
                confidence=confidence,
                regime=regime,
                edge_multiplier=edge.size_multiplier,
                open_risk_usd=0.0,
            )
            if sizing.skip:
                continue

            alloc = min(sizing.position_usd, cash * 0.95)
            exec_p = _exec_price(price, "buy")
            qty = alloc / exec_p
            fee = _fee(alloc)

            if alloc + fee <= cash and alloc >= 5.0:
                cash -= alloc + fee
                position = SimPosition(
                    symbol=row["symbol"], side="long",
                    entry_price=exec_p, entry_time=ts,
                    amount_usd=alloc, quantity=qty,
                )
                pressure = 0.0
                consecutive_sells = 0

    # Close any remaining position
    if position:
        last_price = candles.iloc[-1]["close"]
        exec_p = _exec_price(last_price, "sell")
        notional = position.quantity * exec_p
        fee = _fee(notional) + _fee(position.quantity * position.entry_price)
        pnl = (exec_p - position.entry_price) * position.quantity - fee
        actual_pnl_pct = pnl / (position.entry_price * position.quantity)
        hold_min = (candles.iloc[-1]["time"] - position.entry_time).total_seconds() / 60
        trades.append(SimTrade(
            symbol=position.symbol, side=position.side,
            entry_time=position.entry_time, exit_time=candles.iloc[-1]["time"],
            entry_price=position.entry_price, exit_price=exec_p,
            quantity=position.quantity, pnl=pnl, pnl_pct=actual_pnl_pct,
            fees=fee, exit_reason="end_of_data",
            hold_minutes=hold_min, regime_at_exit=candles.iloc[-1]["regime"],
        ))

    return trades, equity_curve


# -- DO-NOTHING BASELINE -------------------------------------------------

def simulate_hold_baseline(candles: pd.DataFrame) -> Tuple[List[SimTrade], List[float]]:
    """Buy-and-hold baseline: buy at start, hold to end."""
    start_price = candles.iloc[30]["close"]  # after warmup
    end_price = candles.iloc[-1]["close"]

    exec_entry = _exec_price(start_price, "buy")
    exec_exit = _exec_price(end_price, "sell")
    qty = INITIAL_CAPITAL * 0.95 / exec_entry
    fee = _fee(qty * exec_entry) + _fee(qty * exec_exit)
    pnl = (exec_exit - exec_entry) * qty - fee
    pnl_pct = pnl / (exec_entry * qty)

    trade = SimTrade(
        symbol=candles.iloc[0]["symbol"], side="long",
        entry_time=candles.iloc[30]["time"], exit_time=candles.iloc[-1]["time"],
        entry_price=exec_entry, exit_price=exec_exit,
        quantity=qty, pnl=pnl, pnl_pct=pnl_pct, fees=fee,
        exit_reason="end_of_data",
        hold_minutes=(candles.iloc[-1]["time"] - candles.iloc[30]["time"]).total_seconds() / 60,
    )

    # Equity curve: just track price changes
    equity_curve = []
    for i in range(len(candles)):
        price = candles.iloc[i]["close"]
        if i < 30:
            equity_curve.append(INITIAL_CAPITAL)
        else:
            mtm = qty * price + (INITIAL_CAPITAL * 0.05)  # cash reserve
            equity_curve.append(mtm)

    return [trade], equity_curve


# ===========================================================================
# PART 3: Report Generation
# ===========================================================================

def compute_metrics(trades: List[SimTrade], equity_curve: List[float]) -> Dict:
    """Compute comprehensive metrics from trade list and equity curve."""
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0, "profit_factor": 0,
            "total_return_pct": 0, "max_drawdown_pct": 0,
            "sharpe_ratio": 0, "avg_hold_minutes": 0,
            "total_fees": 0, "avg_trade_pnl": 0,
            "trades_per_day": 0,
        }

    equity = np.array(equity_curve, dtype=np.float64)
    returns = np.diff(equity) / np.where(equity[:-1] > 0, equity[:-1], 1.0)

    total_return = (equity[-1] - equity[0]) / equity[0] if equity[0] > 0 else 0
    running_max = np.maximum.accumulate(equity)
    drawdowns = (running_max - equity) / np.where(running_max > 0, running_max, 1.0)
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))

    # Time span in days
    if len(trades) >= 2:
        time_span = (trades[-1].exit_time - trades[0].entry_time).total_seconds() / 86400
    else:
        time_span = 1

    # Sharpe (annualized from per-minute returns)
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(365 * 24 * 60))
    else:
        sharpe = 0

    return {
        "total_trades": len(trades),
        "winning_trades": len(winners),
        "losing_trades": len(losers),
        "win_rate": round(len(winners) / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else float("inf"),
        "total_return_pct": round(total_return * 100, 3),
        "max_drawdown_pct": round(max_dd * 100, 3),
        "sharpe_ratio": round(sharpe, 3),
        "avg_hold_minutes": round(np.mean([t.hold_minutes for t in trades]), 1),
        "total_fees": round(sum(t.fees for t in trades), 4),
        "avg_trade_pnl": round(np.mean([t.pnl for t in trades]), 4),
        "total_pnl": round(sum(t.pnl for t in trades), 4),
        "trades_per_day": round(len(trades) / max(time_span, 0.1), 1),
    }


def print_exit_distribution(trades: List[SimTrade], label: str):
    """Print exit reason distribution."""
    reasons = defaultdict(int)
    for t in trades:
        reasons[t.exit_reason] += 1

    print(f"\n  Exit Reason Distribution ({label}):")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = count / len(trades) * 100 if trades else 0
        print(f"    {reason:30s} {count:4d} ({pct:5.1f}%)")


def print_regime_distribution(trades: List[SimTrade], label: str):
    """Print regime distribution at exit."""
    regimes = defaultdict(lambda: {"count": 0, "pnl": 0})
    for t in trades:
        r = t.regime_at_exit or "unknown"
        regimes[r]["count"] += 1
        regimes[r]["pnl"] += t.pnl

    print(f"\n  Regime Distribution at Exit ({label}):")
    for regime, data in sorted(regimes.items()):
        avg_pnl = data["pnl"] / data["count"] if data["count"] > 0 else 0
        print(f"    {regime:20s} {data['count']:4d} trades  avg_pnl=${avg_pnl:+.4f}  total=${data['pnl']:+.4f}")


def print_example_trades(trades: List[SimTrade], label: str, n: int = 5):
    """Print example trade logs."""
    print(f"\n  Example Trades ({label}, first {n}):")
    for t in trades[:n]:
        print(f"    {t.entry_time.strftime('%m/%d %H:%M')} -> {t.exit_time.strftime('%m/%d %H:%M')} "
              f"| {t.side:5s} | entry=${t.entry_price:.2f} exit=${t.exit_price:.2f} "
              f"| pnl=${t.pnl:+.4f} ({t.pnl_pct:+.4%}) | fees=${t.fees:.4f} "
              f"| hold={t.hold_minutes:.0f}min | exit={t.exit_reason} | regime={t.regime_at_exit}")


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("=" * 80)
    print("  GOBLIN AI TRADING PLATFORM — Strategy Evaluation")
    print("  Old (Fixed Exits) vs New (3-Layer Adaptive) vs Hold Baseline")
    print("=" * 80)

    # Generate data
    n_candles = TOTAL_DAYS * 24 * 60  # 1-min candles for N days
    print(f"\nGenerating {n_candles:,} candles ({TOTAL_DAYS} days of 1-min data)...")

    candles = generate_candles(n_candles)
    print(f"  Price range: ${candles['close'].min():.2f} - ${candles['close'].max():.2f}")
    print(f"  Start: ${candles.iloc[0]['close']:.2f}  End: ${candles.iloc[-1]['close']:.2f}")

    # Regime distribution in data
    regime_counts = candles["regime"].value_counts()
    print(f"\n  Market Regime Distribution (ground truth):")
    for regime, count in regime_counts.items():
        print(f"    {regime:20s} {count:6d} candles ({count/len(candles)*100:.1f}%)")

    print("\nComputing features...")
    features_df = compute_features_from_candles(candles)

    print("Generating ML predictions (55% directional accuracy)...")
    predictions = generate_predictions(candles, features_df)
    print(f"  Total predictions: {len(predictions)}")

    direction_counts = predictions["direction"].value_counts()
    print(f"  Direction distribution:")
    for d, c in direction_counts.items():
        print(f"    {d:15s} {c:5d} ({c/len(predictions)*100:.1f}%)")

    # -- Run simulations ----------------------------------------------
    print("\n" + "-" * 80)
    print("  Running Simulations...")
    print("-" * 80)

    print("\n  [1/3] Old Strategy (fixed exits: 0.5% SL, 0.1% TP, 30min max hold)...")
    old_trades, old_equity = simulate_old_strategy(candles, predictions, features_df)

    print(f"  [2/3] New Strategy (3-layer: regime->gate->vol sizing + adaptive exits)...")
    new_trades, new_equity = simulate_new_strategy(candles, predictions, features_df)

    print(f"  [3/3] Buy-and-Hold baseline...")
    hold_trades, hold_equity = simulate_hold_baseline(candles)

    # -- Compute metrics ----------------------------------------------
    old_metrics = compute_metrics(old_trades, old_equity)
    new_metrics = compute_metrics(new_trades, new_equity)
    hold_metrics = compute_metrics(hold_trades, hold_equity)

    # -- Print comparison ---------------------------------------------
    print("\n" + "=" * 80)
    print("  RESULTS COMPARISON")
    print("=" * 80)

    header = f"{'Metric':<30s} {'Old (Fixed)':<18s} {'New (Adaptive)':<18s} {'Hold Baseline':<18s}"
    print(f"\n{header}")
    print("-" * 84)

    metrics_to_compare = [
        ("Total Trades", "total_trades", "", "d"),
        ("Trades/Day", "trades_per_day", "", ".1f"),
        ("Win Rate", "win_rate", "%", ".1f"),
        ("Profit Factor", "profit_factor", "", ".3f"),
        ("Total Return", "total_return_pct", "%", "+.3f"),
        ("Max Drawdown", "max_drawdown_pct", "%", ".3f"),
        ("Sharpe Ratio", "sharpe_ratio", "", ".3f"),
        ("Avg Hold (min)", "avg_hold_minutes", "", ".1f"),
        ("Avg Trade PnL", "avg_trade_pnl", "$", "+.4f"),
        ("Total PnL", "total_pnl", "$", "+.4f"),
        ("Total Fees", "total_fees", "$", ".4f"),
    ]

    for label, key, unit, fmt in metrics_to_compare:
        old_val = old_metrics.get(key, 0)
        new_val = new_metrics.get(key, 0)
        hold_val = hold_metrics.get(key, 0)

        old_str = f"{unit}{old_val:{fmt}}" if unit == "$" else f"{old_val:{fmt}}{unit}"
        new_str = f"{unit}{new_val:{fmt}}" if unit == "$" else f"{new_val:{fmt}}{unit}"
        hold_str = f"{unit}{hold_val:{fmt}}" if unit == "$" else f"{hold_val:{fmt}}{unit}"

        # Highlight improvement
        if key in ("win_rate", "profit_factor", "total_return_pct", "sharpe_ratio", "avg_trade_pnl", "total_pnl"):
            marker = " +" if new_val > old_val else " -" if new_val < old_val else ""
        elif key in ("max_drawdown_pct", "total_fees"):
            marker = " +" if new_val < old_val else " -" if new_val > old_val else ""
        else:
            marker = ""

        print(f"  {label:<28s} {old_str:<18s} {new_str + marker:<18s} {hold_str:<18s}")

    # -- Exit distributions -------------------------------------------
    print_exit_distribution(old_trades, "OLD")
    print_exit_distribution(new_trades, "NEW")

    # -- Regime distributions -----------------------------------------
    if new_trades:
        print_regime_distribution(new_trades, "NEW")

    # -- Example trades -----------------------------------------------
    print_example_trades(old_trades, "OLD")
    print_example_trades(new_trades, "NEW")

    # -- Summary ------------------------------------------------------
    print("\n" + "=" * 80)
    print("  ANALYSIS SUMMARY")
    print("=" * 80)

    return_diff = new_metrics["total_return_pct"] - old_metrics["total_return_pct"]
    wr_diff = new_metrics["win_rate"] - old_metrics["win_rate"]
    trade_diff = old_metrics["total_trades"] - new_metrics["total_trades"]
    fee_diff = old_metrics["total_fees"] - new_metrics["total_fees"]

    print(f"""
  Return improvement:  {return_diff:+.3f}% (old: {old_metrics['total_return_pct']:.3f}%, new: {new_metrics['total_return_pct']:.3f}%)
  Win rate change:     {wr_diff:+.1f}% (old: {old_metrics['win_rate']:.1f}%, new: {new_metrics['win_rate']:.1f}%)
  Trade reduction:     {trade_diff:+d} trades (old: {old_metrics['total_trades']}, new: {new_metrics['total_trades']})
  Fee savings:         ${fee_diff:.4f} (old: ${old_metrics['total_fees']:.4f}, new: ${new_metrics['total_fees']:.4f})
  Hold baseline:       {hold_metrics['total_return_pct']:.3f}% (buy & hold over {TOTAL_DAYS} days)

  Key improvements from 3-layer strategy:
    1. Regime filter prevents entries in choppy/adverse conditions
    2. Edge gate skips low-quality signals -> fewer losing trades
    3. Vol-targeted sizing keeps per-trade risk constant
    4. Adaptive exits: let winners run in trends, cut fast in chop
    5. Reduced trade frequency -> lower fee drag
""")

    # Save results to JSON
    results = {
        "evaluation_date": datetime.now().isoformat(),
        "data_params": {
            "total_days": TOTAL_DAYS,
            "candles": n_candles,
            "fee_pct": FEE_PCT,
            "slippage_pct": SLIPPAGE_PCT,
            "initial_capital": INITIAL_CAPITAL,
            "prediction_accuracy": "55% directional",
        },
        "old_strategy": old_metrics,
        "new_strategy": new_metrics,
        "hold_baseline": hold_metrics,
        "improvement": {
            "return_diff_pct": round(return_diff, 3),
            "win_rate_diff_pct": round(wr_diff, 1),
            "trade_reduction": trade_diff,
            "fee_savings": round(fee_diff, 4),
        },
    }

    output_path = os.path.join(os.path.dirname(__file__), "evaluation_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
