"""
Position Manager Service - AI-Driven Exit Strategy (v3.0)

Positions are opened/closed by AI prediction signals + dynamic trailing stops.
A circuit-breaker at -15% exists as an emergency data-integrity safety net.

v3.0: Added dynamic trailing stop to capture fleeting profit spikes.
  - Tracks peak price (high-water mark) per position every 500ms
  - Activates trailing stop once profit crosses activation threshold
  - Trail distance tightens as profit grows (tiered)
  - Works alongside AI exits — whichever triggers first wins

v2.0: Adaptive exit pressure — thresholds adjust per regime and volatility.
  - Trending markets: harder to exit (let winners run)
  - Choppy/high-vol: easier to exit (cut fast)
  - Volatility risk floor: large ATR-relative losses increase exit urgency
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from contextlib import asynccontextmanager
from collections import defaultdict

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import Gauge, Counter, generate_latest

# Import strategy modules for adaptive exits
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategy.regime import RegimeState
from strategy.adaptive_exit import compute_adaptive_exit_params, explain_exit

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
AI_EXIT_CONFIDENCE = float(os.getenv("AI_EXIT_CONFIDENCE", 0.20))  # Min confidence for AI-driven exit
CIRCUIT_BREAKER_PCT = float(os.getenv("CIRCUIT_BREAKER_PCT", 0.15))  # Emergency-only: -15% unrealized loss

# Dynamic trailing stop configuration (profit spike capture)
# Tiers: (activation_pct, base_trail_pct) — trail tightens as profit grows
# Trail distance is multiplied by ATR factor for volatility awareness
TRAILING_STOP_TIERS = [
    (0.035, 0.020),   # +3.5% profit → base trail 2.0% from peak
    (0.06, 0.013),    # +6% profit → base trail 1.3% from peak
    (0.10, 0.009),    # +10% profit → base trail 0.9% from peak
    (0.18, 0.006),    # +18% profit → base trail 0.6% from peak
]
TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
# ATR scaling: trail_pct = base_trail_pct * max(1.0, atr_pct / ATR_BASELINE)
# Volatile coins get wider trails so they don't get stopped out on noise
ATR_BASELINE = float(os.getenv("ATR_BASELINE", 0.5))  # "normal" ATR% — coins above this get wider trails
ATR_TRAIL_MAX_MULT = float(os.getenv("ATR_TRAIL_MAX_MULT", 2.5))  # Cap: trail can be at most 2.5x wider
# AI veto: if AI exit pressure is below this ratio of threshold, widen trail (AI says hold)
AI_VETO_PRESSURE_RATIO = float(os.getenv("AI_VETO_PRESSURE_RATIO", 0.3))  # Below 30% of threshold = AI says hold
AI_VETO_TRAIL_MULT = float(os.getenv("AI_VETO_TRAIL_MULT", 1.8))  # Widen trail 1.8x when AI says hold

# Exit pressure configuration (AI signal persistence)
EXIT_PRESSURE_THRESHOLD = float(os.getenv("EXIT_PRESSURE_THRESHOLD", 1.5))  # Cumulative pressure to trigger exit
EXIT_PRESSURE_DECAY = float(os.getenv("EXIT_PRESSURE_DECAY", 0.3))  # Pressure decay per non-sell prediction
MIN_SELL_SIGNALS_BEFORE_EXIT = int(os.getenv("MIN_SELL_SIGNALS_BEFORE_EXIT", 2))  # Minimum consecutive sell signals

logger = structlog.get_logger()

# Metrics
POSITION_VALUE = Gauge("position_value", "Position value", ["symbol"])
TOTAL_PNL = Gauge("position_total_pnl", "Total P&L")
AI_EXIT_PRESSURE = Gauge("position_ai_exit_pressure", "Current AI exit pressure", ["symbol"])
AI_EXITS_TOTAL = Counter("position_ai_exits_total", "AI-driven exits", ["reason"])
CIRCUIT_BREAKER_EXITS = Counter("position_circuit_breaker_exits_total", "Circuit breaker emergency exits")
TRAILING_STOP_EXITS = Counter("position_trailing_stop_exits_total", "Trailing stop profit-lock exits")


class Position(BaseModel):
    symbol: str
    side: str
    entry_price: float
    current_price: float
    amount: float
    unrealized_pnl: float = 0
    realized_pnl: float = 0
    status: str = "open"
    opened_at: str = ""
    peak_price: float = 0       # Highest price since entry (for longs), lowest for shorts
    peak_pnl_pct: float = 0     # Highest profit % reached
    trailing_active: bool = False  # Whether trailing stop is engaged


class ExitPressureTracker:
    """Tracks cumulative AI exit pressure per symbol with adaptive thresholds.

    v2.0: Thresholds adapt based on regime and volatility state:
      - Trending markets: higher threshold, slower decay (let winners run)
      - Choppy/high-vol: lower threshold, faster decay (cut fast)
      - Volatility risk floor: large ATR-relative losses boost urgency

    Pressure formula per prediction (uses adaptive weights from regime):
      sell:        +confidence * sell_weight (default 0.6, regime-adjusted)
      strong_sell: +confidence * strong_sell_weight (default 1.0, regime-adjusted)
      hold:        -decay_rate
      buy/strong_buy: -decay_rate * 1.5

    Context modifiers:
      Position losing > 2%: pressure * 1.3 (cut losers faster)
      Position profitable > 1%: pressure * 0.8 (let winners run)
      High confidence (>70%): pressure * 1.2
    """

    def __init__(self):
        self.pressure: Dict[str, float] = defaultdict(float)
        self.consecutive_sells: Dict[str, int] = defaultdict(int)
        self.last_directions: Dict[str, List[str]] = defaultdict(list)
        self.last_adaptive_params: Dict[str, dict] = {}  # Last params used per symbol

    def update(
        self, symbol: str, direction: str, confidence: float, pnl_pct: float,
        sell_weight: float = 0.6, strong_sell_weight: float = 1.0,
        decay_rate: float = 0.3, pressure_threshold: float = 1.5,
        min_consecutive_sells: int = 2, vol_urgency: float = 0.0,
    ) -> tuple[float, bool]:
        """Update exit pressure with adaptive parameters and return (pressure, should_exit)."""

        if direction in ("sell", "strong_sell"):
            # Base pressure contribution — using adaptive weights
            weight = strong_sell_weight if direction == "strong_sell" else sell_weight
            base = confidence * weight

            # Context modifiers
            if pnl_pct < -0.02:
                base *= 1.3
            elif pnl_pct > 0.01:
                base *= 0.8

            if confidence > 0.7:
                base *= 1.2

            # Volatility urgency boost: if vol_urgency > 0, loss exceeds ATR risk floor
            if vol_urgency > 0:
                base *= (1.0 + vol_urgency * 0.5)

            self.pressure[symbol] += base
            self.consecutive_sells[symbol] += 1
        else:
            # Non-sell prediction → decay pressure (adaptive decay rate)
            decay_mult = 1.5 if direction in ("buy", "strong_buy") else 1.0
            self.pressure[symbol] = max(0, self.pressure[symbol] - decay_rate * decay_mult)
            self.consecutive_sells[symbol] = 0

        # Track last 10 directions for analysis
        self.last_directions[symbol].append(direction)
        if len(self.last_directions[symbol]) > 10:
            self.last_directions[symbol] = self.last_directions[symbol][-10:]

        pressure = self.pressure[symbol]
        should_exit = (
            pressure >= pressure_threshold and
            self.consecutive_sells[symbol] >= min_consecutive_sells
        )

        # Store the adaptive params used for debugging/metrics
        self.last_adaptive_params[symbol] = {
            "pressure_threshold": pressure_threshold,
            "min_consecutive_sells": min_consecutive_sells,
            "decay_rate": decay_rate,
            "sell_weight": sell_weight,
            "strong_sell_weight": strong_sell_weight,
            "vol_urgency": vol_urgency,
        }

        return pressure, should_exit

    def reset(self, symbol: str):
        """Reset tracking for a symbol (after position closes)."""
        self.pressure.pop(symbol, None)
        self.consecutive_sells.pop(symbol, None)
        self.last_directions.pop(symbol, None)
        self.last_adaptive_params.pop(symbol, None)

    def get_state(self, symbol: str) -> dict:
        """Return current exit pressure state for debugging/metrics."""
        adaptive = self.last_adaptive_params.get(symbol, {})
        return {
            "pressure": round(self.pressure.get(symbol, 0), 4),
            "consecutive_sells": self.consecutive_sells.get(symbol, 0),
            "last_directions": self.last_directions.get(symbol, []),
            "threshold": adaptive.get("pressure_threshold", EXIT_PRESSURE_THRESHOLD),
            "min_consecutive": adaptive.get("min_consecutive_sells", MIN_SELL_SIGNALS_BEFORE_EXIT),
            "adaptive_params": adaptive,
        }


# Global State
redis_client: Optional[aioredis.Redis] = None
positions: Dict[str, Position] = {}
exit_tracker = ExitPressureTracker()


async def handle_filled_order(order: dict):
    global positions
    symbol = order["symbol"]
    side = "long" if order["side"] == "buy" else "short"
    filled_amount = order.get("filled", 0)
    order_price = order.get("price", 0)
    
    if filled_amount == 0:
        logger.warning("Order has no filled amount, skipping", symbol=symbol, order_id=order.get("order_id"))
        return

    # Check if we have an existing open or closing position
    if symbol in positions and positions[symbol].status in ("open", "closing"):
        pos = positions[symbol]
        # If closing position (sell when long, buy when short)
        if (pos.side == "long" and order["side"] == "sell") or (pos.side == "short" and order["side"] == "buy"):
            # Calculate realized P&L
            if pos.side == "long":
                realized = (order_price - pos.entry_price) * filled_amount
            else:
                realized = (pos.entry_price - order_price) * filled_amount
            
            pos.realized_pnl += realized
            pos.amount -= filled_amount
            
            # If position is fully closed
            if pos.amount <= 0.0001:  # Account for floating point precision
                pos.status = "closed"
                pos.amount = 0

                # Record trade in history
                trade_record = {
                    "symbol": symbol,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "exit_price": order_price,
                    "amount": filled_amount,
                    "realized_pnl": realized,
                    "total_pnl": pos.realized_pnl,
                    "entry_time": pos.opened_at,
                    "exit_time": datetime.utcnow().isoformat(),
                    "hold_time_minutes": (datetime.utcnow() - datetime.fromisoformat(pos.opened_at)).total_seconds() / 60,
                    "exit_reason": order.get("reason", "manual")
                }
                await redis_client.lpush("trade_history", json.dumps(trade_record))
                await redis_client.ltrim("trade_history", 0, 999)  # Keep last 1000 trades

                await redis_client.publish("position_closed", json.dumps({"symbol": symbol, "pnl": realized, "total_pnl": pos.realized_pnl}))
                logger.info("Position closed", symbol=symbol, pnl=realized, total_pnl=pos.realized_pnl)
            else:
                logger.info("Position partially closed", symbol=symbol, remaining=pos.amount, pnl=realized)
        else:
            # Adding to position (buying more when long, selling more when short)
            # Average the entry price
            total_cost = (pos.entry_price * pos.amount) + (order_price * filled_amount)
            pos.amount += filled_amount
            pos.entry_price = total_cost / pos.amount
            pos.peak_price = 0  # Reset peak — entry changed
            pos.peak_pnl_pct = 0
            pos.trailing_active = False
            logger.info("Position increased", symbol=symbol, new_amount=pos.amount, avg_entry=pos.entry_price)
    else:
        # Opening new position — AI controls all exits, no hardcoded thresholds
        positions[symbol] = Position(
            symbol=symbol, side=side, entry_price=order_price,
            current_price=order_price, amount=filled_amount, opened_at=datetime.utcnow().isoformat(),
        )
        # Reset exit pressure tracking for this symbol
        exit_tracker.reset(symbol)
        await redis_client.publish("position_opened", json.dumps({"symbol": symbol, "side": side, "amount": filled_amount, "price": order_price}))
        logger.info("Position opened (AI-exit mode)", symbol=symbol, side=side, amount=filled_amount, price=order_price)

    # Always update Redis with current position state
    await redis_client.hset("positions", symbol, positions[symbol].model_dump_json())
    
    # Update portfolio state automatically
    await update_portfolio_state()


async def update_portfolio_state():
    """Automatically update portfolio state in Redis when positions change"""
    try:
        # Calculate total portfolio value
        total_value = 0
        open_positions_count = 0
        
        # Get USDT balance from portfolio state (or calculate from positions)
        portfolio_state = await redis_client.get("portfolio_state")
        if portfolio_state:
            portfolio = json.loads(portfolio_state)
            total_value = portfolio.get("total_capital", 0)
            available_capital = portfolio.get("available_capital", 0)
        else:
            available_capital = 0
        
        # Calculate position values
        for symbol, pos in positions.items():
            if pos.status == "open":
                open_positions_count += 1
                # Position value is already included in total_value calculation
        
        # Update portfolio state (preserve existing last_trade_time)
        existing_last_trade = portfolio.get("last_trade_time") if portfolio_state else None
        new_portfolio_state = {
            "total_capital": total_value if total_value > 0 else available_capital,
            "available_capital": available_capital,
            "daily_pnl": sum(p.realized_pnl for p in positions.values()),
            "open_positions": open_positions_count,
            "last_trade_time": existing_last_trade,
        }
        
        await redis_client.set("portfolio_state", json.dumps(new_portfolio_state))
        logger.debug("Portfolio state updated", open_positions=open_positions_count)
    except Exception as e:
        logger.error("Failed to update portfolio state", error=str(e))


async def listen_for_orders():
    pubsub = redis_client.pubsub()
    # Only subscribe to filled_orders - avoid double-processing since executor publishes to both channels
    await pubsub.subscribe("filled_orders")
    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                order = json.loads(message["data"])
                # Handle filled orders - check if order has filled amount > 0
                filled_amount = order.get("filled", 0)
                order_status = order.get("status", "").lower()
                
                # Process if order is filled (status is closed/filled OR filled amount > 0)
                if order_status in ["closed", "filled"] or filled_amount > 0:
                    await handle_filled_order(order)
            except Exception as e:
                logger.error("Error processing order update", error=str(e), message=message.get("data", ""))


async def close_position(symbol: str, reason: str):
    """Close a position by publishing a sell signal"""
    if symbol not in positions or positions[symbol].status != "open":
        logger.debug("Position not eligible for closing", symbol=symbol, status=positions.get(symbol, {}).status)
        return

    # IDEMPOTENCY: Check Redis to ensure we haven't already started closing this position
    redis_pos_data = await redis_client.hget("positions", symbol)
    if redis_pos_data:
        redis_pos = json.loads(redis_pos_data)
        if redis_pos.get("status") in ["closing", "closed"]:
            logger.debug("Position already being closed", symbol=symbol, status=redis_pos.get("status"))
            return

    pos = positions[symbol]
    close_side = "sell" if pos.side == "long" else "buy"

    # ATOMIC IDEMPOTENT UPDATE: Use Redis transaction to ensure only one close operation
    close_id = f"close_{symbol}_{int(datetime.utcnow().timestamp() * 1000)}"

    # Check if this close operation has already been initiated
    existing_close = await redis_client.get(f"close_initiated:{symbol}")
    if existing_close and existing_close != close_id:
        logger.debug("Close operation already initiated", symbol=symbol, existing_close_id=existing_close)
        return

    # Mark as closing in Redis atomically
    await redis_client.set(f"close_initiated:{symbol}", close_id, ex=300)  # Expire in 5 minutes

    # Mark position as "closing" IMMEDIATELY to prevent repeated sell signals
    pos.status = "closing"
    positions[symbol] = pos
    await redis_client.hset("positions", symbol, pos.model_dump_json())
    
    # Create a close signal and publish it to raw_signals channel
    close_signal = {
        "signal_id": f"close_{symbol}_{datetime.utcnow().timestamp()}",
        "symbol": symbol,
        "action": close_side,
        "amount": pos.amount,
        "price": pos.current_price,
        "reason": reason,
        "order_type": "market",  # Use market order for immediate execution
        "timestamp": datetime.utcnow().isoformat()
    }
    
    await redis_client.publish("raw_signals", json.dumps(close_signal))
    logger.info("Position close signal published", symbol=symbol, reason=reason, side=close_side, amount=pos.amount)


async def update_prices():
    """Update position prices in real-time with dynamic trailing stop + circuit breaker.

    Exit priority (first match wins):
    1. Circuit breaker: -15% unrealized loss (emergency safety net)
    2. Trailing stop: locks in profit once threshold reached, sells on pullback from peak
    3. AI exit pressure: accumulates over many prediction cycles (handled elsewhere)
    """
    global positions
    while True:
        await asyncio.sleep(0.5)
        circuit_breaker_triggered = []
        trailing_stop_triggered = []

        for symbol, pos in list(positions.items()):
            if pos.status != "open":
                continue

            tick_data = await redis_client.hget("latest_ticks", symbol)
            if tick_data:
                tick = json.loads(tick_data)
                old_price = pos.current_price
                pos.current_price = tick["price"]
                pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.amount if pos.side == "long" else (pos.entry_price - pos.current_price) * pos.amount
                POSITION_VALUE.labels(symbol=symbol).set(pos.current_price * pos.amount)

                if pos.entry_price > 0:
                    pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) if pos.side == "long" else ((pos.entry_price - pos.current_price) / pos.entry_price)

                    # --- CIRCUIT BREAKER (emergency safety net) ---
                    if pnl_pct <= -CIRCUIT_BREAKER_PCT:
                        logger.error("CIRCUIT BREAKER triggered — emergency exit",
                                     symbol=symbol, pnl_pct=f"{pnl_pct:.2%}",
                                     threshold=f"-{CIRCUIT_BREAKER_PCT:.0%}",
                                     entry=pos.entry_price, current=pos.current_price)
                        circuit_breaker_triggered.append(symbol)
                        await redis_client.hset("positions", symbol, pos.model_dump_json())
                        continue

                    # --- DYNAMIC TRAILING STOP (volatility-aware + AI veto) ---
                    if TRAILING_STOP_ENABLED:
                        # Update peak price (high-water mark)
                        if pos.side == "long":
                            if pos.peak_price == 0:
                                pos.peak_price = pos.entry_price
                            if pos.current_price > pos.peak_price:
                                pos.peak_price = pos.current_price
                        else:
                            if pos.peak_price == 0:
                                pos.peak_price = pos.entry_price
                            if pos.current_price < pos.peak_price:
                                pos.peak_price = pos.current_price

                        # Track peak profit %
                        peak_pnl = ((pos.peak_price - pos.entry_price) / pos.entry_price) if pos.side == "long" else ((pos.entry_price - pos.peak_price) / pos.entry_price)
                        if peak_pnl > pos.peak_pnl_pct:
                            pos.peak_pnl_pct = peak_pnl

                        # Determine base trail distance from tiers
                        base_trail_pct = None
                        for activation_pct, tier_trail_pct in reversed(TRAILING_STOP_TIERS):
                            if pos.peak_pnl_pct >= activation_pct:
                                base_trail_pct = tier_trail_pct
                                break

                        if base_trail_pct is not None:
                            # --- ATR scaling: volatile coins get wider trails ---
                            atr_mult = 1.0
                            try:
                                features_data = await redis_client.get(f"features:{symbol}")
                                if features_data:
                                    atr_pct = float(json.loads(features_data).get("atr_pct", ATR_BASELINE))
                                    if atr_pct > ATR_BASELINE:
                                        atr_mult = min(atr_pct / ATR_BASELINE, ATR_TRAIL_MAX_MULT)
                            except Exception:
                                pass

                            # --- AI veto: if AI says "hold", widen the trail ---
                            ai_mult = 1.0
                            pressure_state = exit_tracker.get_state(symbol)
                            ai_pressure = pressure_state["pressure"]
                            ai_threshold = pressure_state["threshold"]
                            if ai_threshold > 0 and (ai_pressure / ai_threshold) < AI_VETO_PRESSURE_RATIO:
                                ai_mult = AI_VETO_TRAIL_MULT

                            # Final trail distance
                            trail_pct = base_trail_pct * atr_mult * ai_mult

                            if not pos.trailing_active:
                                pos.trailing_active = True
                                logger.info("Trailing stop ACTIVATED",
                                            symbol=symbol,
                                            peak_pnl=f"{pos.peak_pnl_pct:.2%}",
                                            base_trail=f"{base_trail_pct:.2%}",
                                            atr_mult=f"{atr_mult:.2f}",
                                            ai_mult=f"{ai_mult:.2f}",
                                            final_trail=f"{trail_pct:.2%}",
                                            peak_price=pos.peak_price,
                                            entry=pos.entry_price)

                            # Check if price has pulled back from peak beyond trail distance
                            if pos.side == "long":
                                drop_from_peak = (pos.peak_price - pos.current_price) / pos.peak_price
                            else:
                                drop_from_peak = (pos.current_price - pos.peak_price) / pos.peak_price

                            if drop_from_peak >= trail_pct:
                                logger.info("TRAILING STOP triggered — locking profit",
                                            symbol=symbol,
                                            pnl_pct=f"{pnl_pct:.2%}",
                                            peak_pnl=f"{pos.peak_pnl_pct:.2%}",
                                            peak_price=pos.peak_price,
                                            current=pos.current_price,
                                            base_trail=f"{base_trail_pct:.2%}",
                                            atr_mult=f"{atr_mult:.2f}",
                                            ai_mult=f"{ai_mult:.2f}",
                                            final_trail=f"{trail_pct:.2%}",
                                            drop_from_peak=f"{drop_from_peak:.2%}",
                                            profit_usd=f"{pos.unrealized_pnl:.2f}",
                                            ai_pressure=f"{ai_pressure:.3f}")
                                trailing_stop_triggered.append(symbol)
                                await redis_client.hset("positions", symbol, pos.model_dump_json())
                                continue

                await redis_client.hset("positions", symbol, pos.model_dump_json())

                # Publish real-time price update for instant dashboard refresh
                if old_price != pos.current_price:
                    await redis_client.publish("position_price_update", json.dumps({
                        "symbol": symbol,
                        "current_price": pos.current_price,
                        "unrealized_pnl": pos.unrealized_pnl,
                        "peak_pnl_pct": pos.peak_pnl_pct,
                        "trailing_active": pos.trailing_active,
                        "timestamp": datetime.utcnow().isoformat()
                    }))

                # Update exit pressure metric for dashboard
                pressure_state = exit_tracker.get_state(symbol)
                AI_EXIT_PRESSURE.labels(symbol=symbol).set(pressure_state["pressure"])

        # Execute exits outside the iteration loop
        for symbol in circuit_breaker_triggered:
            CIRCUIT_BREAKER_EXITS.inc()
            await close_position(symbol, "circuit_breaker")
        for symbol in trailing_stop_triggered:
            TRAILING_STOP_EXITS.inc()
            exit_tracker.reset(symbol)
            await close_position(symbol, "trailing_stop")


async def load_positions():
    global positions
    all_pos = await redis_client.hgetall("positions")

    for symbol, data in all_pos.items():
        pos_data = json.loads(data)
        # Strip legacy fields that no longer exist on the Position model
        for legacy_field in ("stop_loss_price", "take_profit_price", "max_hold_time_minutes",
                             "trailing_stop_activated", "highest_price", "trailing_stop_distance_pct"):
            pos_data.pop(legacy_field, None)
        pos = Position(**pos_data)
        if pos.status == "open":
            await redis_client.hset("positions", symbol, pos.model_dump_json())
            positions[symbol] = pos
            exit_tracker.reset(symbol)  # Fresh pressure tracking
            logger.info("Position loaded (AI-exit mode)", symbol=symbol, entry_price=pos.entry_price)


async def _get_regime_for_symbol(symbol: str) -> Optional[RegimeState]:
    """Read regime state from Redis (published by signal service)."""
    try:
        regime_data = await redis_client.hget("regime_state", symbol)
        if regime_data:
            data = json.loads(regime_data)
            return RegimeState(
                regime=data.get("regime", "choppy"),
                trend_strength=float(data.get("trend_strength", 0)),
                volatility_ratio=float(data.get("volatility_ratio", 1.0)),
                choppiness=float(data.get("choppiness", 0.5)),
                confidence=float(data.get("confidence", 0.5)),
                details=data.get("details", {}),
            )
    except Exception as e:
        logger.warning("Failed to read regime state", symbol=symbol, error=str(e))
    return None


async def listen_for_prediction_exits():
    """AI-driven exits with adaptive regime-aware thresholds.

    v2.0: Exit pressure thresholds adapt to market regime and volatility:
    - Reads regime state from Redis (published by signal service every 5s)
    - Computes adaptive exit params via compute_adaptive_exit_params()
    - Trending: harder to exit (threshold×1.4, need 3 consecutive sells)
    - Choppy: easier to exit (threshold×0.7, sell signals weighted 1.3×)
    - High vol: easiest to exit (threshold×0.6, sell signals weighted 1.5×)
    - Volatility risk floor: if loss > 3×ATR, urgency increases

    Falls back to fixed defaults if regime state is unavailable.
    """
    pubsub = redis_client.pubsub()
    await pubsub.psubscribe("predictions:*")
    logger.info("AI exit listener subscribed to predictions:* (adaptive pressure v2.0)",
                base_threshold=EXIT_PRESSURE_THRESHOLD,
                base_min_sells=MIN_SELL_SIGNALS_BEFORE_EXIT)

    async for message in pubsub.listen():
        if message["type"] != "pmessage":
            continue
        try:
            prediction = json.loads(message["data"])
            symbol = prediction.get("symbol")
            direction = prediction.get("direction", "hold")
            confidence = float(prediction.get("confidence", 0))

            # Only process predictions for symbols we hold
            if symbol not in positions or positions[symbol].status != "open":
                continue
            if confidence < AI_EXIT_CONFIDENCE:
                continue

            pos = positions[symbol]

            # Calculate current P&L percentage
            if pos.entry_price > 0:
                pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price
                           if pos.side == "long"
                           else (pos.entry_price - pos.current_price) / pos.entry_price)
            else:
                pnl_pct = 0

            # Calculate hold time
            try:
                opened_at = datetime.fromisoformat(pos.opened_at.replace('Z', '+00:00').replace('+00:00', ''))
                hold_time_minutes = (datetime.utcnow() - opened_at).total_seconds() / 60
            except Exception:
                hold_time_minutes = 0

            # Get regime state from Redis (published by signal service)
            regime = await _get_regime_for_symbol(symbol)

            # Get ATR from features (for volatility risk floor)
            atr_pct = 0.5  # default
            try:
                features_data = await redis_client.get(f"features:{symbol}")
                if features_data:
                    features = json.loads(features_data)
                    atr_pct = float(features.get("atr_pct", 0.5))
            except Exception:
                pass

            # Compute adaptive exit parameters
            if regime:
                adaptive = compute_adaptive_exit_params(
                    regime=regime,
                    pnl_pct=pnl_pct,
                    atr_pct=atr_pct,
                    hold_time_minutes=hold_time_minutes,
                )
                p_threshold = adaptive.pressure_threshold
                p_min_consec = adaptive.min_consecutive_sells
                p_decay = adaptive.decay_rate
                p_sell_w = adaptive.sell_weight
                p_strong_sell_w = adaptive.strong_sell_weight
                p_vol_urgency = adaptive.vol_urgency
                regime_name = adaptive.regime
            else:
                # Fallback to fixed defaults if no regime data
                p_threshold = EXIT_PRESSURE_THRESHOLD
                p_min_consec = MIN_SELL_SIGNALS_BEFORE_EXIT
                p_decay = EXIT_PRESSURE_DECAY
                p_sell_w = 0.6
                p_strong_sell_w = 1.0
                p_vol_urgency = 0.0
                regime_name = "unknown"

            # Feed every prediction into the adaptive exit pressure tracker
            pressure, should_exit = exit_tracker.update(
                symbol=symbol, direction=direction, confidence=confidence,
                pnl_pct=pnl_pct,
                sell_weight=p_sell_w, strong_sell_weight=p_strong_sell_w,
                decay_rate=p_decay, pressure_threshold=p_threshold,
                min_consecutive_sells=p_min_consec, vol_urgency=p_vol_urgency,
            )

            if direction in ("sell", "strong_sell"):
                state = exit_tracker.get_state(symbol)
                logger.info("AI exit pressure update (adaptive)",
                            symbol=symbol, direction=direction, confidence=f"{confidence:.2f}",
                            pnl_pct=f"{pnl_pct:.4%}", pressure=f"{pressure:.3f}",
                            consecutive_sells=state["consecutive_sells"],
                            threshold=f"{p_threshold:.3f}",
                            regime=regime_name, vol_urgency=f"{p_vol_urgency:.3f}",
                            should_exit=should_exit)

            if should_exit:
                # Determine specific exit reason for analytics
                state = exit_tracker.get_state(symbol)
                if direction == "strong_sell" and confidence >= 0.6:
                    reason = "ai_strong_sell"
                elif pnl_pct < -0.01:
                    reason = "ai_sell_cut_loss"
                elif pnl_pct > 0.005:
                    reason = "ai_sell_take_profit"
                else:
                    reason = "ai_sell_reversal"

                # Build explainable exit record
                if regime:
                    exit_explanation = explain_exit(
                        should_exit=True, reason=reason, pressure=pressure,
                        params=adaptive, consecutive_sells=state["consecutive_sells"],
                        pnl_pct=pnl_pct, atr_pct=atr_pct, confidence=confidence,
                        direction=direction, hold_time_minutes=hold_time_minutes,
                    )
                    logger.info("AI EXIT TRIGGERED — adaptive threshold reached",
                                symbol=symbol, reason=reason, pressure=f"{pressure:.3f}",
                                consecutive_sells=state["consecutive_sells"],
                                pnl_pct=f"{pnl_pct:.4%}", confidence=f"{confidence:.2f}",
                                regime=regime_name, threshold=f"{p_threshold:.3f}",
                                vol_urgency=f"{p_vol_urgency:.3f}",
                                hold_minutes=f"{hold_time_minutes:.1f}",
                                last_directions=state["last_directions"][-5:])

                    # Store exit explanation in Redis for dashboard/analysis
                    await redis_client.lpush("exit_explanations", json.dumps({
                        "symbol": symbol,
                        "reason": exit_explanation.reason,
                        "pressure": exit_explanation.pressure,
                        "threshold": exit_explanation.threshold,
                        "consecutive_sells": exit_explanation.consecutive_sells,
                        "pnl_pct": exit_explanation.pnl_pct,
                        "regime": exit_explanation.regime,
                        "atr_pct": exit_explanation.atr_pct,
                        "vol_urgency": exit_explanation.vol_urgency,
                        "confidence": exit_explanation.confidence,
                        "direction": exit_explanation.direction,
                        "hold_time_minutes": exit_explanation.hold_time_minutes,
                        "timestamp": datetime.utcnow().isoformat(),
                    }))
                    await redis_client.ltrim("exit_explanations", 0, 499)
                else:
                    logger.info("AI EXIT TRIGGERED — fixed threshold (no regime data)",
                                symbol=symbol, reason=reason, pressure=f"{pressure:.3f}",
                                consecutive_sells=state["consecutive_sells"],
                                pnl_pct=f"{pnl_pct:.4%}", confidence=f"{confidence:.2f}",
                                last_directions=state["last_directions"][-5:])

                AI_EXITS_TOTAL.labels(reason=reason).inc()
                exit_tracker.reset(symbol)
                await close_position(symbol, reason)

        except Exception as e:
            logger.error("Error in AI exit listener", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logger.info("Starting Position Manager...")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    await load_positions()
    logger.info("Positions loaded — AI-only exit mode active",
                open_positions=len([p for p in positions.values() if p.status == "open"]),
                circuit_breaker=f"-{CIRCUIT_BREAKER_PCT:.0%}",
                exit_pressure_threshold=EXIT_PRESSURE_THRESHOLD,
                min_sell_signals=MIN_SELL_SIGNALS_BEFORE_EXIT)

    order_task = asyncio.create_task(listen_for_orders())
    price_task = asyncio.create_task(update_prices())
    ai_exit_task = asyncio.create_task(listen_for_prediction_exits())

    yield

    order_task.cancel()
    price_task.cancel()
    ai_exit_task.cancel()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Position Manager", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "positions": len([p for p in positions.values() if p.status == "open"]),
        "exit_mode": "adaptive_regime_pressure_v2",
        "circuit_breaker": f"-{CIRCUIT_BREAKER_PCT:.0%}",
        "base_pressure_threshold": EXIT_PRESSURE_THRESHOLD,
    }


@app.get("/positions")
async def get_positions():
    return {k: v.model_dump(exclude_none=False) for k, v in positions.items() if v.status == "open"}


@app.get("/positions/{symbol}")
async def get_position(symbol: str):
    symbol = symbol.replace("_", "/").upper()
    if symbol in positions:
        return positions[symbol]
    raise HTTPException(status_code=404, detail="Position not found")


@app.get("/pnl")
async def get_total_pnl():
    unrealized = sum(p.unrealized_pnl for p in positions.values() if p.status == "open")
    realized = sum(p.realized_pnl for p in positions.values())
    total = unrealized + realized
    TOTAL_PNL.set(total)
    return {"unrealized_pnl": unrealized, "realized_pnl": realized, "total_pnl": total}


@app.get("/position-health")
async def get_position_health():
    """Check position health with AI exit pressure state"""
    health_report = []
    current_time = datetime.utcnow()

    for symbol, pos in positions.items():
        if pos.status == "open":
            opened_at = datetime.fromisoformat(pos.opened_at.replace('Z', '+00:00'))
            age_minutes = (current_time - opened_at).total_seconds() / 60
            pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100

            health_status = "healthy"
            issues = []

            if pnl_pct < -CIRCUIT_BREAKER_PCT * 100 * 0.7:  # Approaching circuit breaker
                health_status = "warning"
                issues.append(f"Approaching circuit breaker: {pnl_pct:.2f}%")
            elif pnl_pct < -5:
                health_status = "loss"
                issues.append(f"Significant loss: {pnl_pct:.2f}%")

            if pnl_pct > 1:
                issues.append(f"Profit: {pnl_pct:.2f}%")

            pressure_state = exit_tracker.get_state(symbol)

            health_report.append({
                "symbol": symbol,
                "status": health_status,
                "age_minutes": round(age_minutes, 1),
                "pnl_percent": round(pnl_pct, 4),
                "issues": issues,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "ai_exit_pressure": pressure_state,
            })

    return {"positions": health_report, "total_positions": len(health_report)}


@app.get("/exit-pressure")
async def get_exit_pressure():
    """Debug endpoint: view AI exit pressure for all open positions"""
    result = {}
    for symbol, pos in positions.items():
        if pos.status == "open":
            pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price
                       if pos.side == "long"
                       else (pos.entry_price - pos.current_price) / pos.entry_price) if pos.entry_price > 0 else 0
            result[symbol] = {
                **exit_tracker.get_state(symbol),
                "pnl_pct": round(pnl_pct, 6),
                "side": pos.side,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
            }
    return result


@app.get("/exit-explanations")
async def get_exit_explanations(limit: int = 20):
    """Get recent exit explanations with full context (regime, vol, pressure)."""
    try:
        explanations = await redis_client.lrange("exit_explanations", 0, limit - 1)
        return {"explanations": [json.loads(e) for e in explanations], "total": len(explanations)}
    except Exception as e:
        logger.error("Failed to get exit explanations", error=str(e))
        return {"explanations": [], "total": 0}


@app.get("/trades")
async def get_trades(limit: int = 50):
    """Get trade history with P&L information"""
    try:
        # Get trade history from Redis
        trade_history = await redis_client.lrange("trade_history", 0, limit - 1)
        trades = []

        for trade_json in trade_history:
            try:
                trade = json.loads(trade_json)
                trades.append(trade)
            except:
                continue

        return {"trades": trades, "total": len(trades)}
    except Exception as e:
        logger.error("Failed to get trade history", error=str(e))
        return {"trades": [], "total": 0}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
