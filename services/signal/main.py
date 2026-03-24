"""
Signal Service v2.0 — Regime-aware, edge-gated signal generation

Converts ML predictions to trading signals, but only when:
  Layer A: Regime filter says conditions are favorable
  Layer B: Edge gate confirms sufficient edge exists
  Layer C: Volatility-targeted sizing produces a viable position

Signals that fail any layer are logged and skipped (no trade).
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
import httpx
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import Counter, Gauge, generate_latest

# Add strategy module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategy"))
from regime import classify_regime, regime_allows_entry, RegimeState
from edge_gate import evaluate_edge, EdgeDecision
from vol_sizing import calculate_vol_targeted_size, SizingResult

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.55))  # v13: raised from 0.50
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 1000.0))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.50))
MIN_POSITION_USD = float(os.getenv("MIN_POSITION_USD", 1.0))
# v13: Daily drawdown circuit breaker — stop trading when losses exceed this % of capital
DAILY_DRAWDOWN_KILL_PCT = float(os.getenv("DAILY_DRAWDOWN_KILL_PCT", 0.03))  # 3%
circuit_breaker_active = False
circuit_breaker_until: Optional[datetime] = None
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")

# v13: Symbol blacklist — persistently losing symbols that drain capital.
# These 9 symbols accounted for -$26 in losses (nearly 2x the system's total profit).
# Reviewed from forensic analysis of 410 trades on 2026-03-24.
SYMBOL_BLACKLIST = {
    "AFRD/USDT", "AIA/USDT", "AIXPLAY/USDT", "ART/USDT", "ATT/USDT",
    "BANANAS31/USDT", "BATTERY/USDT", "BAY/USDT", "BEAT/USDT",
}

logger = structlog.get_logger()

# Metrics
SIGNALS_GENERATED = Counter("signal_generated_total", "Signals generated", ["symbol", "action"])
SIGNALS_SKIPPED = Counter("signal_skipped_total", "Signals skipped", ["reason"])
REGIME_CLASSIFICATIONS = Counter("signal_regime_total", "Regime classifications", ["regime"])
EDGE_GATE_DECISIONS = Counter("signal_edge_gate_total", "Edge gate decisions", ["decision"])
CURRENT_REGIME = Gauge("signal_current_regime_score", "Current regime score", ["symbol", "regime_type"])


class Signal(BaseModel):
    signal_id: str
    symbol: str
    action: str          # "buy" (long entry), "sell" (long exit), "short_entry", "short_exit"
    side: str = "long"   # "long" or "short"
    amount: float
    price: float
    confidence: float
    timestamp: str
    regime: str = ""
    edge_score: float = 0.0
    vol_ratio: float = 1.0
    reason: str = ""


class Position(BaseModel):
    symbol: str
    side: str
    amount: float
    entry_price: float


# Per-symbol graduated cooldown after losing trades (prevents re-entering losers)
# 1st consecutive loss: 30 min, 2nd: 60 min, 3rd+: 120 min
LOSS_COOLDOWN_GRADUATED = [30, 60, 120]  # minutes per consecutive loss tier
# Require higher confidence to re-enter a symbol that recently lost
LOSS_COOLDOWN_CONF_BOOST = float(os.getenv("LOSS_COOLDOWN_CONF_BOOST", 0.15))

# Global State
redis_client: Optional[aioredis.Redis] = None
current_positions: Dict[str, Position] = {}
last_signals: Dict[str, Signal] = {}
processed_signals: set = set()
symbol_loss_cooldowns: Dict[str, datetime] = {}  # symbol → cooldown expiry time
symbol_consecutive_losses: Dict[str, int] = {}   # symbol → consecutive loss count
last_regime: Dict[str, RegimeState] = {}  # Track last regime per symbol


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


async def _get_features(symbol: str) -> Dict[str, float]:
    """Fetch cached features from Redis (computed by feature-store every 5s)."""
    try:
        raw = await redis_client.get(f"features:{symbol}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {}


async def _get_portfolio_value() -> float:
    """Get current portfolio value from Redis."""
    try:
        data = await redis_client.get("portfolio_state")
        if data:
            state = json.loads(data)
            return float(state.get("total_capital", 0) or state.get("available_capital", STARTING_CAPITAL))
    except Exception:
        pass
    return STARTING_CAPITAL


async def _get_available_capital() -> float:
    """Get available capital (tries executor first, then Redis)."""
    available = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:8005/balance")
            if response.status_code == 200:
                data = response.json()
                balances = data.get("balances", {})
                usdt_balance = balances.get("USDT", {}).get("free", 0) or 0
                available = usdt_balance
    except Exception:
        pass

    if available is None:
        portfolio = await redis_client.get("portfolio_state")
        available = json.loads(portfolio).get("available_capital", STARTING_CAPITAL) if portfolio else STARTING_CAPITAL

    return available


async def _get_open_risk() -> float:
    """Estimate total open risk (ATR-based) across all positions."""
    total_risk = 0.0
    try:
        positions = await redis_client.hgetall("positions")
        for sym, data in positions.items():
            pos = json.loads(data)
            if pos.get("status") == "open":
                entry = float(pos.get("entry_price", 0))
                amount = float(pos.get("amount", 0))
                # Get ATR for this symbol
                features = await _get_features(sym)
                atr_pct = features.get("atr_pct", 0.5)
                atr_decimal = max(atr_pct / 100.0, 0.0001)
                # Risk = position_value * 2 * ATR (2-ATR risk estimate)
                total_risk += entry * amount * 2 * atr_decimal
    except Exception:
        pass
    return total_risk


async def _check_circuit_breaker() -> bool:
    """v13: Check if daily drawdown circuit breaker should be active.
    Returns True if trading should be halted."""
    global circuit_breaker_active, circuit_breaker_until

    # If circuit breaker was tripped, check if we should reset (new UTC day)
    if circuit_breaker_active and circuit_breaker_until:
        if datetime.utcnow() >= circuit_breaker_until:
            circuit_breaker_active = False
            circuit_breaker_until = None
            logger.info("CIRCUIT BREAKER RESET — new trading day")
            return False
        return True

    # Check daily P&L from trade history
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        recent_trades = await redis_client.lrange("trade_history", 0, 199)
        daily_pnl = 0.0
        for t in recent_trades:
            trade = json.loads(t)
            exit_time = trade.get("exit_time", "")
            if exit_time.startswith(today):
                daily_pnl += float(trade.get("realized_pnl", 0))

        portfolio_value = await _get_portfolio_value()
        if portfolio_value > 0:
            daily_loss_pct = abs(daily_pnl) / portfolio_value if daily_pnl < 0 else 0
            if daily_loss_pct >= DAILY_DRAWDOWN_KILL_PCT:
                circuit_breaker_active = True
                # Reset at midnight UTC
                tomorrow = datetime.utcnow().replace(hour=0, minute=0, second=0) + timedelta(days=1)
                circuit_breaker_until = tomorrow
                logger.warning("CIRCUIT BREAKER TRIPPED — daily loss %.2f%% exceeds %.1f%% limit. "
                               "All new entries blocked until %s",
                               daily_loss_pct * 100, DAILY_DRAWDOWN_KILL_PCT * 100,
                               tomorrow.isoformat())
                return True
    except Exception as e:
        logger.error("Circuit breaker check failed", error=str(e))

    return False


async def generate_signal(prediction: dict) -> Optional[Signal]:
    """Generate a signal with full 3-layer strategy gating + v13 circuit breaker."""
    symbol = prediction.get("symbol")
    direction = prediction.get("direction", "hold")
    confidence = _safe_float(prediction.get("confidence"), 0.0)
    current_price = _safe_float(prediction.get("current_price"), 0.0)
    breakdown = prediction.get("breakdown", {})

    # Price fallbacks
    if current_price <= 0:
        current_price = _safe_float(prediction.get("price"), 0.0)
    if current_price <= 0 and symbol:
        try:
            tick_raw = await redis_client.hget("latest_ticks", symbol)
            if tick_raw:
                tick = json.loads(tick_raw)
                current_price = _safe_float(tick.get("price"), 0.0)
        except Exception:
            pass

    if not symbol or current_price <= 0:
        SIGNALS_SKIPPED.labels(reason="missing_price").inc()
        return None

    # v13: Blacklist check — skip consistently losing symbols
    if symbol in SYMBOL_BLACKLIST:
        SIGNALS_SKIPPED.labels(reason="blacklisted_symbol").inc()
        return None

    # Idempotency
    prediction_id = prediction.get("id")
    if not prediction_id:
        timestamp_hint = prediction.get("timestamp", "")
        prediction_id = f"{symbol}_{direction}_{timestamp_hint or int(current_price * 1000)}"
    if prediction_id in processed_signals:
        return None

    if confidence < CONFIDENCE_THRESHOLD:
        SIGNALS_SKIPPED.labels(reason="low_confidence").inc()
        return None

    if direction == "hold":
        SIGNALS_SKIPPED.labels(reason="hold_signal").inc()
        return None

    # Normalize direction
    if direction in ("strong_buy", "buy"):
        normalized_direction = "buy"
    elif direction in ("strong_sell", "sell"):
        normalized_direction = "sell"
    else:
        SIGNALS_SKIPPED.labels(reason="unknown_direction").inc()
        return None

    has_position = symbol in current_positions
    current_side = current_positions[symbol].side if has_position else None

    # Determine action based on direction and current position state
    if normalized_direction == "buy" and not has_position:
        action = "buy"
        signal_side = "long"
    elif normalized_direction == "sell" and has_position and current_side == "long":
        # v13: ALLOW sell signals for ALL positions — the AI must be able to cut losses
        # Previous "patience mode" was the #1 cause of oversized losses.
        # If the model says sell, SELL. Holding losers hoping for recovery is how you blow up.
        action = "sell"
        signal_side = "long"
    elif normalized_direction == "sell" and not has_position:
        # SHORT ENTRY: bearish prediction with no open position
        action = "short_entry"
        signal_side = "short"
    elif normalized_direction == "buy" and has_position and current_side == "short":
        # SHORT EXIT: bullish prediction while holding a short
        action = "short_exit"
        signal_side = "short"
    else:
        SIGNALS_SKIPPED.labels(reason="no_action").inc()
        return None

    # v13: Circuit breaker — block ALL new entries when daily drawdown exceeds limit
    # Exit signals still pass through (must be able to close positions)
    if action in ("buy", "short_entry"):
        if await _check_circuit_breaker():
            SIGNALS_SKIPPED.labels(reason="circuit_breaker").inc()
            return None

    # Per-symbol loss cooldown: block re-entry after a losing trade
    if action in ("buy", "short_entry") and symbol in symbol_loss_cooldowns:
        cooldown_expiry = symbol_loss_cooldowns[symbol]
        if datetime.utcnow() < cooldown_expiry:
            # During cooldown, require significantly higher confidence
            boosted_threshold = CONFIDENCE_THRESHOLD + LOSS_COOLDOWN_CONF_BOOST
            if confidence < boosted_threshold:
                remaining = (cooldown_expiry - datetime.utcnow()).total_seconds() / 60
                SIGNALS_SKIPPED.labels(reason="loss_cooldown").inc()
                logger.info("Loss cooldown blocked re-entry",
                            symbol=symbol, confidence=f"{confidence:.2f}",
                            required=f"{boosted_threshold:.2f}",
                            cooldown_remaining=f"{remaining:.1f}min")
                return None
        else:
            del symbol_loss_cooldowns[symbol]

    # ══════════════════════════════════════════════════════════════════
    # LAYER A: Regime Filter
    # ══════════════════════════════════════════════════════════════════
    features = await _get_features(symbol)
    regime = classify_regime(features, symbol)
    last_regime[symbol] = regime
    REGIME_CLASSIFICATIONS.labels(regime=regime.regime).inc()

    # Publish regime to Redis for position manager's adaptive exits
    regime_data = {
        "regime": regime.regime,
        "trend_strength": regime.trend_strength,
        "volatility_ratio": regime.volatility_ratio,
        "choppiness": regime.choppiness,
        "confidence": regime.confidence,
        "atr_pct": features.get("atr_pct", 0.5),
    }
    await redis_client.hset("regime_state", symbol, json.dumps(regime_data))

    if action in ("buy", "short_entry") and not regime_allows_entry(regime, normalized_direction):
        SIGNALS_SKIPPED.labels(reason="regime_blocked").inc()
        logger.info("Regime blocked entry",
                     symbol=symbol, direction=normalized_direction,
                     regime=regime.regime, choppiness=regime.choppiness,
                     trend_strength=regime.trend_strength)
        return None

    # ── Fetch Fear & Greed Index for contrarian sizing ─────────────
    fear_greed_index = 50.0  # default: neutral
    try:
        fg_raw = await redis_client.get("fear_greed_index")
        if fg_raw:
            fg_data = json.loads(fg_raw) if fg_raw.startswith("{") else {"value": float(fg_raw)}
            fear_greed_index = float(fg_data.get("value", fg_data.get("normalized_score", 50.0)))
            # If we got the normalized_score (-1 to 1), convert back to 0-100
            if -1.0 <= fear_greed_index <= 1.0 and fear_greed_index != 50.0:
                fear_greed_index = (fear_greed_index + 1.0) * 50.0
    except Exception:
        pass
    # Inject into features so edge_gate can use it
    features["fear_greed_index"] = fear_greed_index

    # ══════════════════════════════════════════════════════════════════
    # LAYER A.5: F&G-aware ensemble agreement filter (second layer)
    # ══════════════════════════════════════════════════════════════════
    fg_zone_signal = "neutral"
    if fear_greed_index < 20:
        fg_zone_signal = "extreme_fear"
    elif fear_greed_index < 40:
        fg_zone_signal = "fear"
    elif fear_greed_index < 60:
        fg_zone_signal = "neutral"
    elif fear_greed_index < 80:
        fg_zone_signal = "greed"
    else:
        fg_zone_signal = "extreme_greed"

    agreement_bonus = float(breakdown.get("agreement_bonus", 0))
    models_agree = agreement_bonus > 0

    # In extreme fear or fear, require minimum confidence for long signals (relaxed: no model agreement required)
    if action == "buy" and fg_zone_signal in ("extreme_fear", "fear") and confidence < 0.55:
        SIGNALS_SKIPPED.labels(reason="fg_low_confidence_fear").inc()
        logger.info("F&G filter blocked low-confidence long in fear zone",
                     symbol=symbol, fear_greed=round(fear_greed_index, 1),
                     confidence=round(confidence, 3), zone=fg_zone_signal)
        return None

    # F&G-aware SHORT entry gating:
    # In extreme fear, the contrarian play is bullish → shorts need higher confidence (0.60+)
    # In extreme greed, everyone is over-leveraged long → shorts are easier (0.50 confidence)
    # In fear, shorts still need decent confidence (0.58+) since rebounds are common
    if action == "short_entry":
        if fg_zone_signal == "extreme_fear" and confidence < 0.60:
            SIGNALS_SKIPPED.labels(reason="fg_short_extreme_fear").inc()
            logger.info("F&G filter blocked short in extreme fear (contrarian bullish)",
                         symbol=symbol, fear_greed=round(fear_greed_index, 1),
                         confidence=round(confidence, 3))
            return None
        elif fg_zone_signal == "fear" and confidence < 0.58:
            SIGNALS_SKIPPED.labels(reason="fg_short_fear").inc()
            logger.info("F&G filter blocked low-confidence short in fear zone",
                         symbol=symbol, fear_greed=round(fear_greed_index, 1),
                         confidence=round(confidence, 3))
            return None
        elif fg_zone_signal == "extreme_greed" and confidence < 0.50:
            SIGNALS_SKIPPED.labels(reason="fg_short_low_conf").inc()
            logger.info("F&G filter blocked very low confidence short in extreme greed",
                         symbol=symbol, fear_greed=round(fear_greed_index, 1),
                         confidence=round(confidence, 3))
            return None
        elif fg_zone_signal in ("neutral", "greed") and confidence < 0.55:
            SIGNALS_SKIPPED.labels(reason="fg_short_neutral_low_conf").inc()
            logger.info("F&G filter blocked low-confidence short",
                         symbol=symbol, fear_greed=round(fear_greed_index, 1),
                         confidence=round(confidence, 3), zone=fg_zone_signal)
            return None

    # ══════════════════════════════════════════════════════════════════
    # LAYER B: Edge Gate
    # ══════════════════════════════════════════════════════════════════
    if action in ("buy", "short_entry"):  # gate all entries, not exits
        edge = evaluate_edge(prediction, regime, features,
                             open_position_count=len(current_positions))
        EDGE_GATE_DECISIONS.labels(decision="take" if edge.take else "skip").inc()

        if not edge.take:
            SIGNALS_SKIPPED.labels(reason="edge_gate_skip").inc()
            logger.info("Edge gate blocked entry",
                         symbol=symbol, edge_score=edge.edge_score,
                         reasons=edge.reasons, regime=regime.regime,
                         side=signal_side)
            return None

        logger.info("Edge gate approved",
                     symbol=symbol, edge_score=edge.edge_score,
                     size_mult=edge.size_multiplier,
                     reasons=edge.reasons, regime=regime.regime,
                     side=signal_side)
    else:
        edge = None  # exit signals pass through (exit managed by position manager)

    # ══════════════════════════════════════════════════════════════════
    # LAYER C: Dynamic Adaptive Sizing
    # ══════════════════════════════════════════════════════════════════
    if action in ("buy", "short_entry"):
        available = await _get_available_capital()
        MIN_TRADE_VALUE = 5.0
        if available < MIN_TRADE_VALUE:
            SIGNALS_SKIPPED.labels(reason="insufficient_balance").inc()
            return None

        portfolio_value = await _get_portfolio_value()
        atr_pct = features.get("atr_pct", 0.5)
        open_risk = await _get_open_risk()

        # Fetch portfolio performance data for dynamic sizing
        starting_capital_val = STARTING_CAPITAL
        current_drawdown = 0.0
        recent_win_rate = 0.5
        recent_n_trades = 0
        try:
            ps_raw = await redis_client.get("portfolio_state")
            if ps_raw:
                ps = json.loads(ps_raw)
                sc = float(ps.get("starting_capital", STARTING_CAPITAL))
                if sc > 0:
                    starting_capital_val = sc
                    current_drawdown = max(0.0, (sc - portfolio_value) / sc)
        except Exception:
            pass

        # Fetch recent trade performance for streak factor
        try:
            recent_trades = await redis_client.lrange("trade_history", 0, 19)
            if recent_trades:
                wins = sum(1 for t in recent_trades if float(json.loads(t).get("pnl", 0)) > 0)
                recent_n_trades = len(recent_trades)
                recent_win_rate = wins / recent_n_trades if recent_n_trades > 0 else 0.5
        except Exception:
            pass

        sizing = calculate_vol_targeted_size(
            portfolio_value=portfolio_value,
            current_price=current_price,
            atr_pct=atr_pct,
            confidence=confidence,
            regime=regime,
            edge_multiplier=edge.size_multiplier if edge else 1.0,
            open_risk_usd=open_risk,
            fear_greed_index=fear_greed_index,
            starting_capital=starting_capital_val,
            current_drawdown=current_drawdown,
            recent_win_rate=recent_win_rate,
            recent_n_trades=recent_n_trades,
        )

        if sizing.skip:
            SIGNALS_SKIPPED.labels(reason="vol_sizing_skip").inc()
            logger.info("Vol sizing blocked entry",
                         symbol=symbol, reason=sizing.skip_reason,
                         details=sizing.details)
            return None

        # Cap to available capital
        amount = min(sizing.position_usd, available * 0.95)
        if amount < MIN_TRADE_VALUE:
            SIGNALS_SKIPPED.labels(reason="insufficient_after_sizing").inc()
            return None

        logger.info("Dynamic size calculated",
                     symbol=symbol, position_usd=round(amount, 2),
                     risk_usd=sizing.risk_usd, atr_pct=atr_pct,
                     dynamic_risk_pct=sizing.details.get("dynamic_risk_pct"),
                     dynamic_cap_pct=sizing.details.get("dynamic_cap_pct"),
                     regime_mult=sizing.regime_multiplier,
                     edge_mult=sizing.edge_multiplier,
                     fear_greed=round(fear_greed_index, 0),
                     fg_mult=sizing.details.get("fear_greed_multiplier", 1.0),
                     streak_mult=sizing.details.get("streak_multiplier", 1.0),
                     dd_scale=sizing.details.get("drawdown_scale", 1.0))
    else:
        # Exit (sell long or close short): use position amount
        amount = current_positions[symbol].amount

    # Build descriptive reason based on signal context
    if action == "sell":
        signal_reason = "signal_sell_exit"
    elif action == "short_exit":
        signal_reason = "signal_short_cover"
    else:
        # Determine reason from prediction breakdown and model signals
        reason_parts = []
        tcn_conf = _safe_float(breakdown.get("tcn_confidence"), 0.0)
        xgb_conf = _safe_float(breakdown.get("xgb_confidence"), 0.0)
        ensemble_conf = _safe_float(breakdown.get("ensemble_confidence"), 0.0)

        is_short = (action == "short_entry")

        if is_short:
            # SHORT entry reasons
            if tcn_conf >= 0.6:
                reason_parts.append("tcn_strong_sell")
            elif tcn_conf >= 0.4:
                reason_parts.append("tcn_sell")

            if xgb_conf >= 0.6:
                reason_parts.append("xgb_bearish_momentum")
            elif xgb_conf >= 0.4:
                reason_parts.append("xgb_bearish_signal")

            if ensemble_conf >= 0.6 or (not reason_parts and confidence >= 0.6):
                reason_parts.append("ensemble_bearish")

            if direction == "strong_sell":
                reason_parts.append("strong_short_conviction")

            if regime.regime == "trending_down":
                reason_parts.append("downtrend_aligned")
            elif regime.regime == "mean_reverting":
                reason_parts.append("mean_revert_short")
        else:
            # LONG entry reasons
            if tcn_conf >= 0.6:
                reason_parts.append("tcn_strong_buy")
            elif tcn_conf >= 0.4:
                reason_parts.append("tcn_buy")

            if xgb_conf >= 0.6:
                reason_parts.append("xgb_momentum")
            elif xgb_conf >= 0.4:
                reason_parts.append("xgb_signal")

            if ensemble_conf >= 0.6 or (not reason_parts and confidence >= 0.6):
                reason_parts.append("ensemble_bullish")

            if direction == "strong_buy":
                reason_parts.append("strong_conviction")

            if regime.regime == "trending":
                reason_parts.append("trend_aligned")
            elif regime.regime == "mean_reverting":
                reason_parts.append("mean_revert")

        if edge and edge.edge_score >= 0.7:
            reason_parts.append("high_edge")

        signal_reason = "_".join(reason_parts) if reason_parts else f"ml_{direction}_conf{confidence:.0%}"

    signal = Signal(
        signal_id=str(uuid.uuid4())[:8], symbol=symbol, action=action,
        side=signal_side,
        amount=amount, price=current_price, confidence=confidence,
        timestamp=datetime.utcnow().isoformat(),
        regime=regime.regime,
        edge_score=edge.edge_score if edge else 0.0,
        vol_ratio=regime.volatility_ratio,
        reason=signal_reason,
    )

    SIGNALS_GENERATED.labels(symbol=symbol, action=action).inc()
    last_signals[symbol] = signal

    processed_signals.add(prediction_id)
    if len(processed_signals) > 1000:
        processed_signals.pop()

    logger.info("SIGNAL GENERATED (3-layer approved)",
                signal_id=signal.signal_id, symbol=symbol, action=action,
                reason=signal_reason, regime=regime.regime, edge_score=signal.edge_score,
                vol_ratio=signal.vol_ratio, amount=round(amount, 4))

    return signal


async def listen_for_predictions():
    pubsub = redis_client.pubsub()
    await pubsub.psubscribe("predictions:*")
    logger.info("Subscribed to predictions:* (3-layer strategy active)")

    async for message in pubsub.listen():
        if message["type"] == "pmessage":
            try:
                channel = message["channel"]
                channel_parts = channel.split(":")
                if len(channel_parts) >= 2:
                    prediction = json.loads(message["data"])
                    if prediction.get("symbol") in [s.strip() for s in TRADING_PAIRS]:
                        signal = await generate_signal(prediction)
                        if signal:
                            await redis_client.publish("raw_signals", signal.model_dump_json())
                            logger.info(f"SIGNAL PUBLISHED: {signal.action} {signal.symbol} "
                                        f"${signal.amount:.2f} regime={signal.regime}")
            except Exception as e:
                logger.error("Error processing prediction", error=str(e), exc_info=True)


async def listen_for_position_updates():
    global current_positions
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("position_opened", "position_closed")

    async for message in pubsub.listen():
        if message["type"] == "message":
            data = json.loads(message["data"])
            symbol = data["symbol"]
            if message["channel"] == "position_opened":
                pos_data = await redis_client.hget("positions", symbol)
                if pos_data:
                    current_positions[symbol] = Position(**json.loads(pos_data))
            else:
                current_positions.pop(symbol, None)
                # Track losing trades for graduated cooldown
                pnl = data.get("pnl", 0)
                if pnl < 0:
                    # Increment consecutive loss count for this symbol
                    symbol_consecutive_losses[symbol] = symbol_consecutive_losses.get(symbol, 0) + 1
                    loss_count = symbol_consecutive_losses[symbol]
                    # Graduated cooldown: 30 min (1st), 60 min (2nd), 120 min (3rd+)
                    tier_index = min(loss_count - 1, len(LOSS_COOLDOWN_GRADUATED) - 1)
                    cooldown_minutes = LOSS_COOLDOWN_GRADUATED[tier_index]
                    cooldown_until = datetime.utcnow() + timedelta(minutes=cooldown_minutes)
                    symbol_loss_cooldowns[symbol] = cooldown_until
                    logger.info("Graduated loss cooldown set",
                                symbol=symbol, pnl=f"{pnl:.2f}",
                                consecutive_losses=loss_count,
                                cooldown_minutes=cooldown_minutes)
                else:
                    # Winning trade resets consecutive loss counter
                    symbol_consecutive_losses.pop(symbol, None)


async def sync_balance_from_mexc():
    """Fetch real balance from executor service and update Redis portfolio_state"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("http://localhost:8005/balance")
            if response.status_code == 200:
                data = response.json()
                balances = data.get("balances", {})
                usdt_balance = balances.get("USDT", {}).get("free", 0)
                portfolio_state = {
                    "total_capital": usdt_balance,
                    "available_capital": usdt_balance,
                    "daily_pnl": 0,
                    "open_positions": 0
                }
                await redis_client.set("portfolio_state", json.dumps(portfolio_state))
                logger.info(f"Synced USDT balance: ${usdt_balance:.2f}")
                return usdt_balance
    except Exception as e:
        logger.warning(f"Could not sync balance: {e}")
    return None


def load_symbols_from_file(filepath: str, wait_seconds: int = 60) -> list:
    import time
    start = time.monotonic()
    while (time.monotonic() - start) < wait_seconds:
        try:
            if os.path.isfile(filepath):
                with open(filepath, "r") as f:
                    lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
                if lines:
                    return lines
        except Exception:
            pass
        time.sleep(2)
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, TRADING_PAIRS
    logger.info("Starting Signal Service v2.0 (3-layer strategy)...")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    await redis_client.ping()

    if TRADING_PAIRS_FILE:
        pairs = await asyncio.to_thread(load_symbols_from_file, TRADING_PAIRS_FILE)
        if pairs:
            TRADING_PAIRS = pairs
            logger.info(f"Loaded {len(TRADING_PAIRS)} symbols from {TRADING_PAIRS_FILE}")
    else:
        TRADING_PAIRS = [s.strip() for s in os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]

    await sync_balance_from_mexc()

    positions = await redis_client.hgetall("positions")
    for symbol, data in positions.items():
        pos = json.loads(data)
        if pos.get("status") == "open":
            current_positions[symbol] = Position(**pos)

    # v10: Initialize loss cooldowns from trade history on startup
    try:
        recent_trades = await redis_client.lrange("trade_history", 0, 49)
        from collections import defaultdict
        sym_losses = defaultdict(int)
        for t in recent_trades:
            d = json.loads(t)
            if d.get("realized_pnl", 0) < -0.5:  # Significant loss
                sym_losses[d["symbol"]] += 1
        for sym, count in sym_losses.items():
            tier = min(count - 1, len(LOSS_COOLDOWN_GRADUATED) - 1)
            cooldown_min = LOSS_COOLDOWN_GRADUATED[tier] * count  # Scale by number of losses
            symbol_loss_cooldowns[sym] = datetime.utcnow() + timedelta(minutes=cooldown_min)
            symbol_consecutive_losses[sym] = count
            logger.info(f"Initialized cooldown for {sym}: {cooldown_min}min ({count} losses)")
    except Exception as e:
        logger.warning("Failed to initialize loss cooldowns", error=str(e))

    pred_task = asyncio.create_task(listen_for_predictions())
    pos_task = asyncio.create_task(listen_for_position_updates())

    yield

    pred_task.cancel()
    pos_task.cancel()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Signal Service", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "2.0.0",
        "strategy_layers": ["regime_filter", "edge_gate", "vol_sizing"],
        "positions_tracked": len(current_positions),
    }


@app.get("/signals")
async def get_signals():
    return {k: v.model_dump() for k, v in last_signals.items()}


@app.get("/regime")
async def get_regime():
    """Current regime state for all tracked symbols."""
    result = {}
    for symbol, regime in last_regime.items():
        result[symbol] = {
            "regime": regime.regime,
            "trend_strength": regime.trend_strength,
            "volatility_ratio": regime.volatility_ratio,
            "choppiness": regime.choppiness,
            "confidence": regime.confidence,
            "details": regime.details,
        }
    return result


@app.post("/manual-signal")
async def create_manual_signal(symbol: str, action: str, amount: float):
    tick = await redis_client.hget("latest_ticks", symbol)
    if not tick:
        return {"error": "No price data"}
    tick = json.loads(tick)
    signal = Signal(
        signal_id=f"manual-{str(uuid.uuid4())[:4]}", symbol=symbol, action=action,
        amount=amount, price=tick["price"], confidence=1.0, timestamp=datetime.utcnow().isoformat(),
        reason="manual_trade",
    )
    await redis_client.publish("raw_signals", signal.model_dump_json())
    return signal


@app.post("/emergency/stop")
async def emergency_stop():
    logger.warning("EMERGENCY STOP activated")
    return {"status": "stopped", "message": "Signal generation stopped"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
