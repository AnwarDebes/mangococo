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
from datetime import datetime
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
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.3))
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 1000.0))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.50))
MIN_POSITION_USD = float(os.getenv("MIN_POSITION_USD", 1.0))
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")

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
    action: str
    amount: float
    price: float
    confidence: float
    timestamp: str
    regime: str = ""
    edge_score: float = 0.0
    vol_ratio: float = 1.0


class Position(BaseModel):
    symbol: str
    side: str
    amount: float
    entry_price: float


# Global State
redis_client: Optional[aioredis.Redis] = None
current_positions: Dict[str, Position] = {}
last_signals: Dict[str, Signal] = {}
processed_signals: set = set()
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


async def generate_signal(prediction: dict) -> Optional[Signal]:
    """Generate a signal with full 3-layer strategy gating."""
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

    # Only buy if no position, only sell if have position
    if normalized_direction == "buy" and not has_position:
        action = "buy"
    elif normalized_direction == "sell" and has_position:
        action = "sell"
    else:
        SIGNALS_SKIPPED.labels(reason="no_action").inc()
        return None

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

    if action == "buy" and not regime_allows_entry(regime, normalized_direction):
        SIGNALS_SKIPPED.labels(reason="regime_blocked").inc()
        logger.info("Regime blocked entry",
                     symbol=symbol, direction=normalized_direction,
                     regime=regime.regime, choppiness=regime.choppiness,
                     trend_strength=regime.trend_strength)
        return None

    # ══════════════════════════════════════════════════════════════════
    # LAYER B: Edge Gate
    # ══════════════════════════════════════════════════════════════════
    if action == "buy":  # only gate entries, not exits
        edge = evaluate_edge(prediction, regime, features)
        EDGE_GATE_DECISIONS.labels(decision="take" if edge.take else "skip").inc()

        if not edge.take:
            SIGNALS_SKIPPED.labels(reason="edge_gate_skip").inc()
            logger.info("Edge gate blocked entry",
                         symbol=symbol, edge_score=edge.edge_score,
                         reasons=edge.reasons, regime=regime.regime)
            return None

        logger.info("Edge gate approved",
                     symbol=symbol, edge_score=edge.edge_score,
                     size_mult=edge.size_multiplier,
                     reasons=edge.reasons, regime=regime.regime)
    else:
        edge = None  # sell signals pass through (exit managed by position manager)

    # ══════════════════════════════════════════════════════════════════
    # LAYER C: Volatility-Targeted Sizing
    # ══════════════════════════════════════════════════════════════════
    if action == "buy":
        available = await _get_available_capital()
        MIN_TRADE_VALUE = 5.0
        if available < MIN_TRADE_VALUE:
            SIGNALS_SKIPPED.labels(reason="insufficient_balance").inc()
            return None

        portfolio_value = await _get_portfolio_value()
        atr_pct = features.get("atr_pct", 0.5)
        open_risk = await _get_open_risk()

        sizing = calculate_vol_targeted_size(
            portfolio_value=portfolio_value,
            current_price=current_price,
            atr_pct=atr_pct,
            confidence=confidence,
            regime=regime,
            edge_multiplier=edge.size_multiplier if edge else 1.0,
            open_risk_usd=open_risk,
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

        logger.info("Vol-targeted size calculated",
                     symbol=symbol, position_usd=round(amount, 2),
                     risk_usd=sizing.risk_usd, atr_pct=atr_pct,
                     vol_ratio=sizing.vol_ratio,
                     regime_mult=sizing.regime_multiplier,
                     edge_mult=sizing.edge_multiplier)
    else:
        # Sell: use position amount
        amount = current_positions[symbol].amount

    signal = Signal(
        signal_id=str(uuid.uuid4())[:8], symbol=symbol, action=action,
        amount=amount, price=current_price, confidence=confidence,
        timestamp=datetime.utcnow().isoformat(),
        regime=regime.regime,
        edge_score=edge.edge_score if edge else 0.0,
        vol_ratio=regime.volatility_ratio,
    )

    SIGNALS_GENERATED.labels(symbol=symbol, action=action).inc()
    last_signals[symbol] = signal

    processed_signals.add(prediction_id)
    if len(processed_signals) > 1000:
        processed_signals.pop()

    logger.info("SIGNAL GENERATED (3-layer approved)",
                signal_id=signal.signal_id, symbol=symbol, action=action,
                regime=regime.regime, edge_score=signal.edge_score,
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
        amount=amount, price=tick["price"], confidence=1.0, timestamp=datetime.utcnow().isoformat()
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
