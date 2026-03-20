"""
Risk Manager Service - Validates all trading signals
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, generate_latest

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 1000.0))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.50))
MIN_POSITION_USD = float(os.getenv("MIN_POSITION_USD", 1.0))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", 0.20))
# MAX_OPEN_POSITIONS removed — the system dynamically limits positions based on
# available capital, MIN_POSITION_USD, and confidence.  No artificial cap.
MIN_TIME_BETWEEN_TRADES = int(os.getenv("MIN_TIME_BETWEEN_TRADES", 60))
# Legacy exit parameters — NO LONGER USED by position manager (AI controls exits).
# Kept here only so the risk_parameters Redis key doesn't break other services that read it.
PROFIT_TARGET_PCT = float(os.getenv("PROFIT_TARGET_PCT", 0.001))
MAX_TRADE_LOSS_PCT = float(os.getenv("MAX_TRADE_LOSS_PCT", 0.005))
MAX_HOLD_TIME_MINUTES = float(os.getenv("MAX_HOLD_TIME_MINUTES", 30))

logger = structlog.get_logger()

# Metrics
SIGNALS_RECEIVED = Counter("risk_signals_received_total", "Signals received")
SIGNALS_APPROVED = Counter("risk_signals_approved_total", "Signals approved")
SIGNALS_REJECTED = Counter("risk_signals_rejected_total", "Signals rejected", ["reason"])
CAPITAL = Gauge("risk_available_capital", "Available capital")


class Signal(BaseModel):
    signal_id: str
    symbol: str
    action: str = Field(..., pattern="^(buy|sell)$")
    amount: float
    price: float
    confidence: float = 0.5


class Portfolio(BaseModel):
    total_capital: float = STARTING_CAPITAL
    available_capital: float = STARTING_CAPITAL
    starting_capital: float = STARTING_CAPITAL
    daily_pnl: float = 0.0
    open_positions: int = 0
    last_trade_time: Optional[str] = None


# Global State
redis_client: Optional[aioredis.Redis] = None
portfolio = Portfolio()


async def validate_signal(signal: Signal) -> tuple[bool, str, float]:
    global portfolio

    # Sells (position closes) bypass ALL risk limits — they must execute in full
    if signal.action == "sell":
        return True, "approved", signal.amount

    # Check daily loss limit (buys only)
    if portfolio.daily_pnl <= -(STARTING_CAPITAL * MAX_DAILY_LOSS_PCT):
        return False, "daily_loss_limit_reached", 0

    # Dynamic position limit: reject if remaining capital can't fund a minimum-sized position
    if signal.action == "buy":
        remaining_after = portfolio.available_capital - signal.amount
        if remaining_after < MIN_POSITION_USD * 0.5:
            return False, "insufficient_capital_for_new_positions", 0

    # Check time between trades (buys only)
    if portfolio.last_trade_time:
        seconds_since = (datetime.utcnow() - datetime.fromisoformat(portfolio.last_trade_time)).total_seconds()
        if seconds_since < MIN_TIME_BETWEEN_TRADES:
            return False, f"too_soon_wait_{int(MIN_TIME_BETWEEN_TRADES - seconds_since)}s", 0

    # Check position size (buys only)
    # signal.amount is USDT value (e.g. $1.50) for buys
    trade_value = signal.amount

    max_position = portfolio.available_capital * MAX_POSITION_PCT

    if trade_value < MIN_POSITION_USD:
        return False, "below_minimum_position", 0

    adjusted_amount = signal.amount
    if trade_value > max_position:
        adjusted_amount = max_position  # Cap USDT amount

    if adjusted_amount > portfolio.available_capital:
        return False, "insufficient_capital", 0

    return True, "approved", adjusted_amount


async def process_signal(signal_data: dict):
    global portfolio
    SIGNALS_RECEIVED.inc()

    try:
        signal = Signal(**signal_data)
        approved, reason, adjusted_amount = await validate_signal(signal)

        if approved:
            SIGNALS_APPROVED.inc()
            validated = signal_data.copy()
            validated["amount"] = adjusted_amount
            await redis_client.publish("validated_signals", json.dumps(validated))
            portfolio.last_trade_time = datetime.utcnow().isoformat()
            await save_portfolio()
            logger.info("Signal approved", signal_id=signal.signal_id)
        else:
            SIGNALS_REJECTED.labels(reason=reason).inc()
            logger.warning("Signal rejected", signal_id=signal.signal_id, reason=reason)
    except Exception as e:
        logger.error("Error processing signal", error=str(e))


async def listen_for_signals():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("raw_signals")
    async for message in pubsub.listen():
        if message["type"] == "message":
            await process_signal(json.loads(message["data"]))


async def load_portfolio():
    global portfolio
    data = await redis_client.get("portfolio_state")
    if data:
        portfolio = Portfolio(**json.loads(data))
    CAPITAL.set(portfolio.available_capital)


async def save_portfolio():
    await redis_client.set("portfolio_state", portfolio.model_dump_json())
    CAPITAL.set(portfolio.available_capital)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logger.info("Starting Risk Manager Service...")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    await redis_client.ping()
    await load_portfolio()
    
    # Store risk parameters in Redis for position service to use
    risk_parameters = {
        "PROFIT_TARGET_PCT": PROFIT_TARGET_PCT,
        "MAX_TRADE_LOSS_PCT": MAX_TRADE_LOSS_PCT,
        "MAX_HOLD_TIME_MINUTES": MAX_HOLD_TIME_MINUTES,
        "MAX_POSITION_PCT": MAX_POSITION_PCT,
        "MIN_POSITION_USD": MIN_POSITION_USD,
        "MAX_DAILY_LOSS_PCT": MAX_DAILY_LOSS_PCT,
        "MAX_OPEN_POSITIONS": "dynamic",
        "MIN_TIME_BETWEEN_TRADES": MIN_TIME_BETWEEN_TRADES
    }
    await redis_client.set("risk_parameters", json.dumps(risk_parameters))
    logger.info("Risk parameters stored in Redis", parameters=risk_parameters)

    listener_task = asyncio.create_task(listen_for_signals())

    yield

    listener_task.cancel()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Risk Manager Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy", "capital": portfolio.available_capital}


@app.get("/portfolio")
async def get_portfolio():
    """Automatically calculate portfolio from positions and MEXC balance"""
    # Load current portfolio state from Redis (updated by executor/position services)
    portfolio_state_str = await redis_client.get("portfolio_state")
    if portfolio_state_str:
        portfolio_data = json.loads(portfolio_state_str)
        # Update local portfolio object from executor-synced state (authoritative)
        portfolio.available_capital = portfolio_data.get("available_capital", portfolio.available_capital)
        portfolio.total_capital = portfolio_data.get("total_capital", portfolio.total_capital)
        portfolio.open_positions = portfolio_data.get("open_positions", 0)
        portfolio.daily_pnl = portfolio_data.get("daily_pnl", 0.0)
        portfolio.last_trade_time = portfolio_data.get("last_trade_time", portfolio.last_trade_time)
    
    return portfolio


@app.get("/limits")
async def get_limits():
    return {"max_position_pct": MAX_POSITION_PCT, "min_position_usd": MIN_POSITION_USD,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT, "max_open_positions": "dynamic"}


@app.post("/update-capital")
async def update_capital(amount: float):
    global portfolio
    portfolio.available_capital = amount
    await save_portfolio()
    return {"available_capital": portfolio.available_capital}


@app.post("/position-opened")
async def position_opened():
    global portfolio
    portfolio.open_positions += 1
    await save_portfolio()
    return {"open_positions": portfolio.open_positions}


@app.post("/position-closed")
async def position_closed(pnl: float = 0):
    global portfolio
    portfolio.open_positions = max(0, portfolio.open_positions - 1)
    portfolio.daily_pnl += pnl
    await save_portfolio()
    return {"open_positions": portfolio.open_positions, "daily_pnl": portfolio.daily_pnl}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
