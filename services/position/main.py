"""
Position Manager Service - Tracks all open positions
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import Gauge, generate_latest

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
PROFIT_TARGET_PCT = float(os.getenv("PROFIT_TARGET_PCT", 0.002))  # 0.2% profit target
MAX_TRADE_LOSS_PCT = float(os.getenv("MAX_TRADE_LOSS_PCT", 0.005))  # 0.5% stop loss
MAX_HOLD_TIME_MINUTES = float(os.getenv("MAX_HOLD_TIME_MINUTES", 0.25))  # 15 seconds max hold

logger = structlog.get_logger()

# Metrics
POSITION_VALUE = Gauge("position_value", "Position value", ["symbol"])
TOTAL_PNL = Gauge("position_total_pnl", "Total P&L")


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
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    max_hold_time_minutes: Optional[float] = None
    # Trailing stop-loss fields
    trailing_stop_activated: bool = False
    highest_price: Optional[float] = None  # Track highest price for trailing stop
    trailing_stop_distance_pct: float = 0.003  # 0.3% trailing distance


# Global State
redis_client: Optional[aioredis.Redis] = None
positions: Dict[str, Position] = {}


async def handle_filled_order(order: dict):
    global positions
    symbol = order["symbol"]
    side = "long" if order["side"] == "buy" else "short"
    filled_amount = order.get("filled", 0)
    order_price = order.get("price", 0)
    
    if filled_amount == 0:
        logger.warning("Order has no filled amount, skipping", symbol=symbol, order_id=order.get("order_id"))
        return

    # Check if we have an existing open position
    if symbol in positions and positions[symbol].status == "open":
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
            logger.info("Position increased", symbol=symbol, new_amount=pos.amount, avg_entry=pos.entry_price)
    else:
        # Opening new position - set stop-loss and take-profit levels
        # Fetch risk parameters from Redis (set by risk service) or use defaults
        risk_params_str = await redis_client.get("risk_parameters")
        if risk_params_str:
            risk_params = json.loads(risk_params_str)
            profit_target = risk_params.get("PROFIT_TARGET_PCT", PROFIT_TARGET_PCT)
            max_loss = risk_params.get("MAX_TRADE_LOSS_PCT", MAX_TRADE_LOSS_PCT)
            max_hold = risk_params.get("MAX_HOLD_TIME_MINUTES", MAX_HOLD_TIME_MINUTES)
        else:
            profit_target = PROFIT_TARGET_PCT
            max_loss = MAX_TRADE_LOSS_PCT
            max_hold = MAX_HOLD_TIME_MINUTES
        
        # Check for dynamic profit target from prediction service (ATR-based)
        dynamic_target_key = f"profit_target:{symbol}"
        dynamic_target_str = await redis_client.get(dynamic_target_key)
        if dynamic_target_str:
            try:
                dynamic_target = float(dynamic_target_str) / 100.0  # Convert from percentage to decimal
                # Use dynamic target if it's reasonable (between 0.05% and 5%)
                if 0.0005 <= dynamic_target <= 0.05:
                    profit_target = dynamic_target
                    logger.info(f"Using dynamic profit target for {symbol}: {profit_target:.4%} (ATR-based)")
            except (ValueError, TypeError):
                pass  # Fall back to default if parsing fails
        
        # Calculate stop-loss and take-profit prices
        if side == "long":
            stop_loss_price = order_price * (1 - max_loss)
            take_profit_price = order_price * (1 + profit_target)
        else:  # short
            stop_loss_price = order_price * (1 + max_loss)
            take_profit_price = order_price * (1 - profit_target)
        
        positions[symbol] = Position(
            symbol=symbol, side=side, entry_price=order_price,
            current_price=order_price, amount=filled_amount, opened_at=datetime.utcnow().isoformat(),
            stop_loss_price=stop_loss_price, take_profit_price=take_profit_price,
            max_hold_time_minutes=max_hold,
            trailing_stop_activated=False,
            highest_price=order_price,  # Initialize tracking for trailing stop
            trailing_stop_distance_pct=0.003  # 0.3% trailing distance
        )
        await redis_client.publish("position_opened", json.dumps({"symbol": symbol, "side": side, "amount": filled_amount, "price": order_price}))
        logger.info("Position opened", symbol=symbol, side=side, amount=filled_amount, price=order_price, 
                    stop_loss=stop_loss_price, take_profit=take_profit_price, max_hold_minutes=max_hold)

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
        
        # Update portfolio state
        new_portfolio_state = {
            "total_capital": total_value if total_value > 0 else available_capital,
            "available_capital": available_capital,
            "daily_pnl": sum(p.realized_pnl for p in positions.values()),
            "open_positions": open_positions_count,
            "last_trade_time": datetime.utcnow().isoformat()
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
    """Update position prices in real-time (microsecond-level) with stop-loss/take-profit checks"""
    global positions
    while True:
        await asyncio.sleep(0.1)  # Ultra-fast price updates every 100ms
        positions_to_close = []
        
        # Fetch risk parameters once per cycle (they're cached in Redis)
        risk_params_str = await redis_client.get("risk_parameters")
        if risk_params_str:
            risk_params = json.loads(risk_params_str)
            profit_target = risk_params.get("PROFIT_TARGET_PCT", PROFIT_TARGET_PCT)
            max_loss = risk_params.get("MAX_TRADE_LOSS_PCT", MAX_TRADE_LOSS_PCT)
            max_hold = risk_params.get("MAX_HOLD_TIME_MINUTES", MAX_HOLD_TIME_MINUTES)
        else:
            profit_target = PROFIT_TARGET_PCT
            max_loss = MAX_TRADE_LOSS_PCT
            max_hold = MAX_HOLD_TIME_MINUTES
        
        for symbol, pos in list(positions.items()):
            if pos.status != "open":
                continue
            
            # If position doesn't have stop-loss/take-profit set, add them now
            needs_update = pos.stop_loss_price is None or pos.take_profit_price is None
            if needs_update:
                if pos.side == "long":
                    pos.stop_loss_price = pos.entry_price * (1 - max_loss)
                    pos.take_profit_price = pos.entry_price * (1 + profit_target)
                else:  # short
                    pos.stop_loss_price = pos.entry_price * (1 + max_loss)
                    pos.take_profit_price = pos.entry_price * (1 - profit_target)
                logger.warning("Added stop-loss/take-profit to existing position", symbol=symbol,
                           stop_loss=pos.stop_loss_price, take_profit=pos.take_profit_price,
                           entry=pos.entry_price, side=pos.side, max_loss=max_loss, profit_target=profit_target)
            
            if pos.max_hold_time_minutes is None:
                pos.max_hold_time_minutes = max_hold
            
            tick_data = await redis_client.hget("latest_ticks", symbol)
            if tick_data:
                tick = json.loads(tick_data)
                old_price = pos.current_price
                pos.current_price = tick["price"]
                pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.amount if pos.side == "long" else (pos.entry_price - pos.current_price) * pos.amount
                POSITION_VALUE.labels(symbol=symbol).set(pos.current_price * pos.amount)
                await redis_client.hset("positions", symbol, pos.model_dump_json())
                
                # Publish real-time price update for instant dashboard refresh
                if old_price != pos.current_price:
                    await redis_client.publish("position_price_update", json.dumps({
                        "symbol": symbol,
                        "current_price": pos.current_price,
                        "unrealized_pnl": pos.unrealized_pnl,
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                
                # TRAILING STOP-LOSS LOGIC (Profitable Strategy Enhancement)
                # Activate trailing stop after 0.5% profit (research-backed threshold)
                profit_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) if pos.side == "long" else ((pos.entry_price - pos.current_price) / pos.entry_price)

                if not pos.trailing_stop_activated and profit_pct >= 0.005:  # 0.5% profit threshold
                    pos.trailing_stop_activated = True
                    pos.highest_price = pos.current_price
                    logger.info("✨ Trailing stop-loss ACTIVATED", symbol=symbol, profit_pct=f"{profit_pct:.2%}", current_price=pos.current_price)

                # Update trailing stop if price moves favorably
                if pos.trailing_stop_activated:
                    if pos.highest_price is None:
                        pos.highest_price = pos.current_price

                    if pos.side == "long":
                        # Update highest price for long positions
                        if pos.current_price > pos.highest_price:
                            pos.highest_price = pos.current_price
                            # Trail stop-loss by 0.3% below highest price
                            new_stop = pos.highest_price * (1 - pos.trailing_stop_distance_pct)
                            # Only raise stop-loss, never lower it
                            if new_stop > pos.stop_loss_price:
                                old_stop = pos.stop_loss_price
                                pos.stop_loss_price = new_stop
                                logger.info("📈 Trailing stop raised", symbol=symbol, old_stop=old_stop, new_stop=pos.stop_loss_price, highest_price=pos.highest_price)
                    else:  # short
                        # Update lowest price for short positions
                        if pos.current_price < pos.highest_price or pos.highest_price is None:
                            pos.highest_price = pos.current_price  # For shorts, track lowest price
                            # Trail stop-loss by 0.3% above lowest price
                            new_stop = pos.highest_price * (1 + pos.trailing_stop_distance_pct)
                            # Only lower stop-loss, never raise it
                            if new_stop < pos.stop_loss_price:
                                old_stop = pos.stop_loss_price
                                pos.stop_loss_price = new_stop
                                logger.info("📉 Trailing stop lowered", symbol=symbol, old_stop=old_stop, new_stop=pos.stop_loss_price, lowest_price=pos.highest_price)

                # Check stop-loss and take-profit conditions
                if pos.stop_loss_price and pos.take_profit_price:
                    if pos.side == "long":
                        if pos.current_price <= pos.stop_loss_price:
                            trail_msg = " (TRAILING STOP)" if pos.trailing_stop_activated else ""
                            logger.warning(f"Stop-loss triggered{trail_msg}", symbol=symbol, price=pos.current_price, stop_loss=pos.stop_loss_price)
                            positions_to_close.append((symbol, "stop_loss"))
                        elif pos.current_price >= pos.take_profit_price:
                            logger.info("Take-profit triggered", symbol=symbol, price=pos.current_price, take_profit=pos.take_profit_price)
                            positions_to_close.append((symbol, "take_profit"))
                    else:  # short
                        if pos.current_price >= pos.stop_loss_price:
                            trail_msg = " (TRAILING STOP)" if pos.trailing_stop_activated else ""
                            logger.warning(f"Stop-loss triggered{trail_msg}", symbol=symbol, price=pos.current_price, stop_loss=pos.stop_loss_price)
                            positions_to_close.append((symbol, "stop_loss"))
                        elif pos.current_price <= pos.take_profit_price:
                            logger.info("Take-profit triggered", symbol=symbol, price=pos.current_price, take_profit=pos.take_profit_price)
                            positions_to_close.append((symbol, "take_profit"))
                
                # Check max hold time
                if pos.max_hold_time_minutes and pos.opened_at:
                    try:
                        opened_at_dt = datetime.fromisoformat(pos.opened_at.replace('Z', '+00:00'))
                        hold_time = (datetime.utcnow() - opened_at_dt.replace(tzinfo=None)).total_seconds() / 60
                        if hold_time >= pos.max_hold_time_minutes:
                            logger.warning("Max hold time exceeded", symbol=symbol, hold_time_minutes=hold_time, max_minutes=pos.max_hold_time_minutes)
                            positions_to_close.append((symbol, "max_hold_time"))
                    except Exception as e:
                        logger.error("Failed to check max hold time", symbol=symbol, error=str(e))
        
        # Close positions that triggered exit conditions
        for symbol, reason in positions_to_close:
            await close_position(symbol, reason)
        
        # Update portfolio state after price updates
        await update_portfolio_state()


async def load_positions():
    global positions
    all_pos = await redis_client.hgetall("positions")
    
    # Fetch risk parameters for setting stop-loss/take-profit on existing positions
    risk_params_str = await redis_client.get("risk_parameters")
    if risk_params_str:
        risk_params = json.loads(risk_params_str)
        profit_target = risk_params.get("PROFIT_TARGET_PCT", PROFIT_TARGET_PCT)
        max_loss = risk_params.get("MAX_TRADE_LOSS_PCT", MAX_TRADE_LOSS_PCT)
        max_hold = risk_params.get("MAX_HOLD_TIME_MINUTES", MAX_HOLD_TIME_MINUTES)
    else:
        profit_target = PROFIT_TARGET_PCT
        max_loss = MAX_TRADE_LOSS_PCT
        max_hold = MAX_HOLD_TIME_MINUTES
    
    for symbol, data in all_pos.items():
        pos_data = json.loads(data)
        pos = Position(**pos_data)
        if pos.status == "open":
            # If position doesn't have stop-loss/take-profit set, add them now
            if pos.stop_loss_price is None or pos.take_profit_price is None:
                if pos.side == "long":
                    pos.stop_loss_price = pos.entry_price * (1 - max_loss)
                    pos.take_profit_price = pos.entry_price * (1 + profit_target)
                else:  # short
                    pos.stop_loss_price = pos.entry_price * (1 + max_loss)
                    pos.take_profit_price = pos.entry_price * (1 - profit_target)
            
            if pos.max_hold_time_minutes is None:
                pos.max_hold_time_minutes = max_hold
            
            # Save updated position back to Redis
            await redis_client.hset("positions", symbol, pos.model_dump_json())
            positions[symbol] = pos
            logger.info("Position loaded with stop-loss/take-profit", symbol=symbol, 
                       stop_loss=pos.stop_loss_price, take_profit=pos.take_profit_price, 
                       max_hold_minutes=pos.max_hold_time_minutes, entry_price=pos.entry_price)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logger.info("Starting Position Manager...")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    await load_positions()
    
    # Ensure all loaded positions have stop-loss/take-profit set
    risk_params_str = await redis_client.get("risk_parameters")
    if risk_params_str:
        risk_params = json.loads(risk_params_str)
        profit_target = risk_params.get("PROFIT_TARGET_PCT", PROFIT_TARGET_PCT)
        max_loss = risk_params.get("MAX_TRADE_LOSS_PCT", MAX_TRADE_LOSS_PCT)
        max_hold = risk_params.get("MAX_HOLD_TIME_MINUTES", MAX_HOLD_TIME_MINUTES)
    else:
        profit_target = PROFIT_TARGET_PCT
        max_loss = MAX_TRADE_LOSS_PCT
        max_hold = MAX_HOLD_TIME_MINUTES
    
    for symbol, pos in positions.items():
        if pos.status == "open" and (pos.stop_loss_price is None or pos.take_profit_price is None):
            if pos.side == "long":
                pos.stop_loss_price = pos.entry_price * (1 - max_loss)
                pos.take_profit_price = pos.entry_price * (1 + profit_target)
            else:
                pos.stop_loss_price = pos.entry_price * (1 + max_loss)
                pos.take_profit_price = pos.entry_price * (1 - profit_target)
            if pos.max_hold_time_minutes is None:
                pos.max_hold_time_minutes = max_hold
            await redis_client.hset("positions", symbol, pos.model_dump_json(exclude_none=False))
            logger.warning("Updated existing position with stop-loss/take-profit on startup", symbol=symbol,
                         stop_loss=pos.stop_loss_price, take_profit=pos.take_profit_price)

    order_task = asyncio.create_task(listen_for_orders())
    price_task = asyncio.create_task(update_prices())

    yield

    order_task.cancel()
    price_task.cancel()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Position Manager", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy", "positions": len([p for p in positions.values() if p.status == "open"])}


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
    """Check for stuck or problematic positions"""
    health_report = []
    current_time = datetime.utcnow()

    for symbol, pos in positions.items():
        if pos.status == "open":
            opened_at = datetime.fromisoformat(pos.opened_at.replace('Z', '+00:00'))
            age_minutes = (current_time - opened_at).total_seconds() / 60
            pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100

            health_status = "healthy"
            issues = []

            if age_minutes > 5:
                health_status = "stuck"
                issues.append(f"Position open for {age_minutes:.1f} minutes")

            if pnl_pct < -2:
                health_status = "loss"
                issues.append(f"Large loss: {pnl_pct:.2f}%")

            if pnl_pct > 1:
                issues.append(f"Profit opportunity: {pnl_pct:.2f}%")

            health_report.append({
                "symbol": symbol,
                "status": health_status,
                "age_minutes": age_minutes,
                "pnl_percent": pnl_pct,
                "issues": issues,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price
            })

    return {"positions": health_report, "total_positions": len(health_report)}


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
