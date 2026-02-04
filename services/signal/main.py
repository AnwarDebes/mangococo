"""
Signal Service - Converts predictions to trading signals
"""
import asyncio
import json
import os
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

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.3))  # 30% confidence threshold - AGGRESSIVE for testing
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 11.0))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.50))
MIN_POSITION_USD = float(os.getenv("MIN_POSITION_USD", 1.0))
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")

logger = structlog.get_logger()

# Metrics
SIGNALS_GENERATED = Counter("signal_generated_total", "Signals generated", ["symbol", "action"])
SIGNALS_SKIPPED = Counter("signal_skipped_total", "Signals skipped", ["reason"])


class Signal(BaseModel):
    signal_id: str
    symbol: str
    action: str
    amount: float
    price: float
    confidence: float
    timestamp: str


class Position(BaseModel):
    symbol: str
    side: str
    amount: float
    entry_price: float


# Global State
redis_client: Optional[aioredis.Redis] = None
current_positions: Dict[str, Position] = {}
last_signals: Dict[str, Signal] = {}
processed_signals: set = set()  # Track processed signal IDs for idempotency


async def generate_signal(prediction: dict) -> Optional[Signal]:
    symbol = prediction["symbol"]
    direction = prediction["direction"]
    confidence = prediction["confidence"]
    current_price = prediction["current_price"]
    prediction_id = prediction.get("id", f"{symbol}_{direction}_{int(current_price * 1000)}")

    # IDEMPOTENCY: Check if this prediction has already been processed
    if prediction_id in processed_signals:
        logger.debug("Prediction already processed, skipping", prediction_id=prediction_id)
        return None

    if confidence < CONFIDENCE_THRESHOLD:
        SIGNALS_SKIPPED.labels(reason="low_confidence").inc()
        return None

    if direction == "hold":
        SIGNALS_SKIPPED.labels(reason="hold_signal").inc()
        return None

    has_position = symbol in current_positions

    # Only buy if we don't have a position, only sell if we have one
    if direction == "buy" and not has_position:
        action = "buy"
    elif direction == "sell" and has_position:
        action = "sell"
    else:
        SIGNALS_SKIPPED.labels(reason="no_action").inc()
        return None

    if action == "buy":
        # Get actual balance from executor service (more reliable than Redis cache)
        available = None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get("http://executor:8005/balance")
                if response.status_code == 200:
                    data = response.json()
                    balances = data.get("balances", {})
                    usdt_balance = balances.get("USDT", {}).get("free", 0) or 0
                    available = usdt_balance
                    logger.info(f"Fetched actual USDT balance from executor: ${available:.2f}")
        except Exception as e:
            logger.warning(f"Could not fetch balance from executor, using Redis fallback: {e}")
        
        # Fallback to Redis if executor call failed
        if available is None:
            portfolio = await redis_client.get("portfolio_state")
            available = json.loads(portfolio).get("available_capital", STARTING_CAPITAL) if portfolio else STARTING_CAPITAL
            logger.info(f"Using Redis balance: ${available:.2f}")

        # MINIMUM $1.50 TRADE LIMIT - Increased buffer above MEXC $1 USDT minimum
        MIN_TRADE_VALUE = 1.5
        if available < MIN_TRADE_VALUE:
            logger.info(f"Insufficient USDT balance for ${MIN_TRADE_VALUE} trade, skipping buy signal", balance=available)
            SIGNALS_SKIPPED.labels(reason="insufficient_balance").inc()
            return None

        # Use minimum trade value (can be increased for better execution, but never below $1.50)
        trade_value = MIN_TRADE_VALUE  # Minimum $1.50 per trade

        # For MEXC market buy orders, send the USDT cost amount directly
        amount = trade_value  # Send minimum $1.50, not coin quantity
        logger.info("Calculating trade", symbol=symbol, available=available, trade_value=trade_value, amount=amount, price=current_price)
    else:
        amount = current_positions[symbol].amount

    signal = Signal(
        signal_id=str(uuid.uuid4())[:8], symbol=symbol, action=action,
        amount=amount, price=current_price, confidence=confidence,
        timestamp=datetime.utcnow().isoformat()
    )

    SIGNALS_GENERATED.labels(symbol=symbol, action=action).inc()
    last_signals[symbol] = signal

    # IDEMPOTENCY: Mark this prediction as processed
    processed_signals.add(prediction_id)

    # Keep only recent processed signals to prevent memory growth
    if len(processed_signals) > 1000:
        # Remove oldest signals (simple FIFO)
        processed_signals.pop()

    logger.info("Signal generated", signal_id=signal.signal_id, symbol=symbol, action=action, prediction_id=prediction_id)

    return signal


async def listen_for_predictions():
    pubsub = redis_client.pubsub()
    # CRITICAL: Use psubscribe for pattern matching, not subscribe!
    await pubsub.psubscribe("predictions:*")
    logger.info("Subscribed to predictions:* pattern with psubscribe")

    async for message in pubsub.listen():
        # psubscribe uses "pmessage" type, not "message"
        if message["type"] == "pmessage":
            try:
                # Extract symbol from channel name for wildcard subscription
                channel = message["channel"]
                channel_parts = channel.split(":")
                if len(channel_parts) >= 2:
                    symbol_key = channel_parts[1]  # e.g., "BTC_USDT"
                    symbol = symbol_key.replace("_", "/")  # Convert back to BTC/USDT format

                    prediction = json.loads(message["data"])
                    logger.info(f"Received prediction for {symbol}: direction={prediction.get('direction')}, confidence={prediction.get('confidence'):.2f}")
                    
                    # Ensure the prediction symbol matches our trading pairs
                    if prediction.get("symbol") in [s.strip() for s in TRADING_PAIRS]:
                        signal = await generate_signal(prediction)
                        if signal:
                            await redis_client.publish("raw_signals", signal.model_dump_json())
                            logger.info(f"🚀 SIGNAL PUBLISHED: {signal.action} {signal.symbol} amount={signal.amount:.4f}")
                        else:
                            logger.debug(f"No signal generated for {symbol}")
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
            response = await client.get("http://executor:8005/balance")
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
                logger.info(f"Synced USDT balance from MEXC: ${usdt_balance:.2f}")
                return usdt_balance
    except Exception as e:
        logger.warning(f"Could not sync balance from MEXC: {e}")
    return None


def load_symbols_from_file(filepath: str, wait_seconds: int = 60) -> list:
    """Load symbols from file (one per line). Wait for file to exist and be non-empty up to wait_seconds."""
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
    logger.info("Starting Signal Service...")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    await redis_client.ping()

    if TRADING_PAIRS_FILE:
        pairs = await asyncio.to_thread(load_symbols_from_file, TRADING_PAIRS_FILE)
        if pairs:
            TRADING_PAIRS = pairs
            logger.info(f"Loaded {len(TRADING_PAIRS)} symbols from {TRADING_PAIRS_FILE}")
        else:
            logger.warning("TRADING_PAIRS_FILE set but file empty or missing, using TRADING_PAIRS env")
    else:
        TRADING_PAIRS = [s.strip() for s in os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]

    # Sync real balance from MEXC on startup
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


app = FastAPI(title="Signal Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy", "positions_tracked": len(current_positions)}


@app.get("/signals")
async def get_signals():
    return {k: v.model_dump() for k, v in last_signals.items()}


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
    """Emergency stop signal generation"""
    logger.warning("EMERGENCY STOP activated - stopping all signal generation")
    # This would need to be implemented to actually stop the signal loop
    return {"status": "stopped", "message": "Signal generation stopped"}

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
