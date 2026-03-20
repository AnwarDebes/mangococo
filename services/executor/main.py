"""
Order Executor Service v2.0 - Executes trades on MEXC or Paper Trading.
Supports portfolio-optimizer sized signals with fallback to risk-validated signals.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

import ccxt.async_support as ccxt
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Configuration
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
PAPER_MODE = os.getenv("PAPER_MODE", "false").lower() == "true"
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 1000.0))

# Signal channel: prefer sized_signals from portfolio-optimizer, fallback to validated_signals
SIGNAL_CHANNEL = os.getenv("SIGNAL_CHANNEL", "sized_signals")
FALLBACK_CHANNEL = "validated_signals"

logger = structlog.get_logger()

# Metrics
ORDERS_SUBMITTED = Counter("executor_orders_total", "Orders submitted", ["symbol", "side", "mode"])
ORDERS_FILLED = Counter("executor_orders_filled_total", "Orders filled", ["mode"])
ORDERS_FAILED = Counter("executor_orders_failed_total", "Orders failed", ["reason"])
ORDER_LATENCY = Histogram("executor_latency_seconds", "Order latency")
PAPER_PORTFOLIO_VALUE = Gauge("executor_paper_portfolio_value", "Paper portfolio total value")


class OrderRequest(BaseModel):
    signal_id: str = ""
    symbol: str
    side: str = Field(..., pattern="^(buy|sell)$")
    amount: float = Field(..., gt=0)
    price: Optional[float] = None
    order_type: str = "limit"
    position_size_usd: Optional[float] = None  # From portfolio-optimizer
    reason: str = ""


class OrderResponse(BaseModel):
    order_id: str
    exchange_order_id: Optional[str] = None
    status: str
    symbol: str
    side: str
    amount: float
    price: Optional[float] = None
    filled: float = 0
    cost: float = 0
    timestamp: str
    mode: str = "live"
    reason: str = ""


# Global State
exchange: Optional[ccxt.mexc] = None
redis_client: Optional[aioredis.Redis] = None
paper_executor = None


async def sync_portfolio_balance():
    """Sync portfolio state with actual MEXC balance (live mode only)."""
    if PAPER_MODE:
        return
    try:
        if hasattr(exchange, 'apiKey') and exchange.apiKey and exchange.apiKey != "your_mexc_api_key_here":
            balance = await exchange.fetch_balance()
            usdt_balance = balance.get("USDT", {}).get("free", 0) or 0

            portfolio_state_str = await redis_client.get("portfolio_state")
            portfolio_state = json.loads(portfolio_state_str) if portfolio_state_str else {}

            portfolio_state["available_capital"] = usdt_balance
            portfolio_state["usdt_free"] = usdt_balance
            portfolio_state["last_trade_time"] = datetime.utcnow().isoformat()

            total_value = usdt_balance
            for coin, coin_data in balance.items():
                if coin != "USDT" and isinstance(coin_data, dict):
                    free = coin_data.get("free", 0) or 0
                    if free > 0.0001:
                        try:
                            tick_data = await redis_client.hget("latest_ticks", f"{coin}/USDT")
                            if tick_data:
                                tick = json.loads(tick_data)
                                price = tick.get("price") or tick.get("last") or 0
                                if price > 0:
                                    total_value += free * price
                        except Exception:
                            pass

            portfolio_state["total_capital"] = total_value
            await redis_client.set("portfolio_state", json.dumps(portfolio_state))
            logger.debug("Portfolio balance synced", available_capital=usdt_balance, total_capital=total_value)
    except Exception as e:
        logger.error("Failed to sync portfolio balance", error=str(e))


async def execute_paper_order(request: OrderRequest) -> OrderResponse:
    """Execute order via paper trading adapter."""
    order_id = str(uuid.uuid4())[:8]
    start_time = datetime.utcnow()

    try:
        if request.side == "buy":
            # Use position_size_usd if provided by portfolio-optimizer, else use amount
            cost = request.position_size_usd or request.amount
            order = await paper_executor.create_market_buy(request.symbol, cost)
        else:
            order = await paper_executor.create_market_sell(request.symbol, request.amount)

        ORDER_LATENCY.observe((datetime.utcnow() - start_time).total_seconds())
        ORDERS_SUBMITTED.labels(symbol=request.symbol, side=request.side, mode="paper").inc()
        ORDERS_FILLED.labels(mode="paper").inc()

        response = OrderResponse(
            order_id=order_id,
            exchange_order_id=order.get("id"),
            status="closed",
            symbol=request.symbol,
            side=request.side,
            amount=order.get("filled", request.amount),
            price=order.get("price", 0),
            filled=order.get("filled", request.amount),
            cost=order.get("cost", 0),
            timestamp=datetime.utcnow().isoformat(),
            mode="paper",
            reason=request.reason,
        )

        # Store and publish
        if request.signal_id:
            await redis_client.hset("signal_orders", request.signal_id, response.model_dump_json())
        await redis_client.publish("order_updates", response.model_dump_json())
        await redis_client.publish("filled_orders", response.model_dump_json())
        await redis_client.hset("orders", order_id, response.model_dump_json())

        # Update paper portfolio metric
        summary = await paper_executor.get_portfolio_summary()
        PAPER_PORTFOLIO_VALUE.set(summary.get("total_value", 0))

        # Also update portfolio_state in Redis for risk manager
        portfolio_state = {
            "available_capital": summary.get("usdt_balance", 0),
            "total_capital": summary.get("total_value", 0),
            "starting_capital": STARTING_CAPITAL,
            "daily_pnl": summary.get("pnl", 0),
            "open_positions": len(summary.get("positions", {})),
            "last_trade_time": datetime.utcnow().isoformat(),
        }
        await redis_client.set("portfolio_state", json.dumps(portfolio_state))

        return response

    except Exception as e:
        ORDERS_FAILED.labels(reason=type(e).__name__).inc()
        logger.error("Paper order failed", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def execute_live_order(request: OrderRequest) -> OrderResponse:
    """Execute order on MEXC exchange."""
    order_id = str(uuid.uuid4())[:8]
    start_time = datetime.utcnow()

    logger.info("Executing live order", order_id=order_id, symbol=request.symbol,
                side=request.side, amount=request.amount, price=request.price)

    try:
        has_valid_keys = hasattr(exchange, 'apiKey') and exchange.apiKey and exchange.apiKey != "your_mexc_api_key_here"
        if not has_valid_keys:
            raise ValueError("No valid MEXC API keys configured for live trading")

        # Fetch real price
        ticker = await exchange.fetch_ticker(request.symbol)
        if request.side == "buy":
            current_price = ticker.get("ask") or ticker.get("last") or ticker.get("close")
        else:
            current_price = ticker.get("bid") or ticker.get("last") or ticker.get("close")

        if current_price is None:
            raise ValueError(f"Could not get price for {request.symbol}")

        if request.order_type != "market":
            request.price = current_price

        min_order_value = 1.40

        if request.side == "buy":
            # Use position_size_usd from portfolio-optimizer if available
            usdt_amount = request.position_size_usd or request.amount

            # Validate balance
            balance = await exchange.fetch_balance()
            usdt_balance = float(balance.get("USDT", {}).get("free", 0) or 0)

            if usdt_balance <= 0:
                raise ValueError(f"Insufficient USDT balance: ${usdt_balance:.2f}")
            if usdt_balance < min_order_value:
                raise ValueError(f"USDT balance ${usdt_balance:.2f} below minimum ${min_order_value:.2f}")
            if usdt_balance < usdt_amount:
                usdt_amount = usdt_balance * 0.99

            if usdt_amount < min_order_value:
                raise ValueError(f"Adjusted amount ${usdt_amount:.2f} below minimum ${min_order_value:.2f}")

            coin_quantity = usdt_amount / current_price
            request.amount = coin_quantity
            order_value = usdt_amount
        else:
            # Sell - validate coin balance
            coin_symbol = request.symbol.split("/")[0]
            balance = await exchange.fetch_balance()
            coin_balance = float(balance.get(coin_symbol, {}).get("free", 0) or 0)

            if coin_balance <= 0:
                raise ValueError(f"Insufficient {coin_symbol} balance: {coin_balance}")
            if coin_balance < request.amount:
                request.amount = coin_balance * 0.999

            order_value = request.amount * current_price

        if order_value < min_order_value:
            if request.side == "buy":
                raise ValueError(f"Order value ${order_value:.2f} below minimum ${min_order_value:.2f}")
            request.amount = min_order_value / current_price
            order_value = min_order_value

        # Idempotency check
        if request.signal_id:
            existing = await redis_client.hget("signal_orders", request.signal_id)
            if existing:
                logger.info("Signal already processed", signal_id=request.signal_id)
                return json.loads(existing)

        # Execute on exchange
        if request.order_type == "market":
            if request.side == "buy":
                order = await exchange.create_market_buy_order(request.symbol, request.amount)
            else:
                order = await exchange.create_market_sell_order(request.symbol, request.amount)
        else:
            order = await exchange.create_limit_order(request.symbol, request.side, request.amount, request.price)

        ORDER_LATENCY.observe((datetime.utcnow() - start_time).total_seconds())
        ORDERS_SUBMITTED.labels(symbol=request.symbol, side=request.side, mode="live").inc()

        order_status = order.get("status", "unknown")
        filled_amount = order.get("filled") if order.get("filled") is not None else request.amount
        order_price = order.get("price") or order.get("average") or current_price or 0
        if order_price is None or order_price == 0:
            order_price = current_price
        order_cost = order.get("cost")
        if order_cost is None or order_cost == 0:
            order_cost = (filled_amount or 0) * (order_price or current_price or 1)

        # Convert unfilled limit to market
        if request.order_type == "limit" and order_status in ["open", "new"]:
            try:
                if order.get("id"):
                    try:
                        await exchange.cancel_order(order.get("id"), request.symbol)
                    except Exception:
                        pass
                market_order = await exchange.create_market_order(request.symbol, request.side, request.amount)
                order_status = market_order.get("status", "closed")
                filled_amount = market_order.get("filled") if market_order.get("filled") is not None else request.amount
                order_price = market_order.get("price") or market_order.get("average") or current_price or 0
                order_cost = market_order.get("cost") or ((filled_amount or 0) * (order_price or 1))
                order = market_order
            except Exception as e:
                logger.warning("Market order conversion failed", error=str(e))

        is_filled = (order_status in ["closed", "filled"]) or (filled_amount > 0 and filled_amount >= request.amount * 0.99)
        if is_filled:
            ORDERS_FILLED.labels(mode="live").inc()
            order_status = "closed"

        response = OrderResponse(
            order_id=order_id, exchange_order_id=order.get("id"), status=order_status,
            symbol=request.symbol, side=request.side, amount=request.amount,
            price=order_price, filled=filled_amount, cost=order_cost,
            timestamp=datetime.utcnow().isoformat(), mode="live",
            reason=request.reason,
        )

        if request.signal_id:
            await redis_client.hset("signal_orders", request.signal_id, response.model_dump_json())

        await redis_client.publish("order_updates", response.model_dump_json())
        await redis_client.hset("orders", order_id, response.model_dump_json())

        if is_filled:
            await redis_client.publish("filled_orders", response.model_dump_json())
            await sync_portfolio_balance()

        return response

    except Exception as e:
        error_str = str(e).lower()
        if "insufficient position" in error_str or "30004" in str(e):
            reason = "insufficient_position"
        elif "minimum transaction volume" in error_str or "30002" in str(e):
            reason = "below_minimum_volume"
        else:
            reason = type(e).__name__

        ORDERS_FAILED.labels(reason=reason).inc()
        logger.error("Live order failed", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def execute_order(request: OrderRequest) -> OrderResponse:
    """Route to paper or live execution."""
    if PAPER_MODE:
        return await execute_paper_order(request)
    return await execute_live_order(request)


async def listen_for_signals():
    """Listen for sized_signals (from portfolio-optimizer) or validated_signals (fallback)."""
    pubsub = redis_client.pubsub()

    # Try to subscribe to both channels - portfolio-optimizer publishes to sized_signals,
    # risk manager publishes to validated_signals
    await pubsub.subscribe(SIGNAL_CHANNEL, FALLBACK_CHANNEL)
    logger.info("Executor subscribed to signal channels",
                primary=SIGNAL_CHANNEL, fallback=FALLBACK_CHANNEL, mode="paper" if PAPER_MODE else "live")

    processed_signal_ids = set()

    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                signal = json.loads(message["data"])
                signal_id = signal.get("signal_id", "")
                channel = message.get("channel", "")

                # Idempotency: skip already-processed signals
                if signal_id and signal_id in processed_signal_ids:
                    continue

                # If we got a validated_signal but already processed the same signal from sized_signals, skip
                if channel == FALLBACK_CHANNEL and signal_id in processed_signal_ids:
                    continue

                action = signal.get("action", "unknown")
                symbol = signal.get("symbol", "unknown")
                amount = signal.get("amount", 0)
                position_size_usd = signal.get("position_size_usd")

                logger.info(f"Signal received via {channel}: {action} {symbol}",
                           amount=amount, position_size_usd=position_size_usd,
                           confidence=signal.get("confidence"))

                request = OrderRequest(
                    signal_id=signal_id,
                    symbol=symbol,
                    side=action,
                    amount=amount,
                    price=signal.get("price"),
                    position_size_usd=position_size_usd,
                    reason=signal.get("reason", ""),
                )

                await execute_order(request)

                if signal_id:
                    processed_signal_ids.add(signal_id)
                    if len(processed_signal_ids) > 1000:
                        processed_signal_ids.pop()

            except Exception as e:
                logger.error("Failed to execute signal", error=str(e),
                           signal_data=message.get("data", "")[:200])


@asynccontextmanager
async def lifespan(app: FastAPI):
    global exchange, redis_client, paper_executor
    mode = "PAPER" if PAPER_MODE else "LIVE"
    logger.info(f"Starting Executor Service v2.0 ({mode} mode)...")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                                   password=REDIS_PASSWORD, decode_responses=True)
    await redis_client.ping()

    if PAPER_MODE:
        from exchanges.paper import PaperExecutor
        paper_executor = PaperExecutor(redis_client, starting_capital=STARTING_CAPITAL)
        await paper_executor.connect()
        logger.info("Paper trading executor initialized", capital=STARTING_CAPITAL)
        # Still init exchange for price fetching in paper mode
        exchange = ccxt.mexc({"enableRateLimit": True})
    else:
        if MEXC_API_KEY and MEXC_SECRET_KEY and MEXC_API_KEY != "your_mexc_api_key_here":
            exchange = ccxt.mexc({
                "apiKey": MEXC_API_KEY,
                "secret": MEXC_SECRET_KEY,
                "enableRateLimit": True,
                "options": {"createMarketBuyOrderRequiresPrice": False}
            })
            try:
                await exchange.load_markets()
                logger.info("MEXC exchange initialized with API keys")
            except Exception as e:
                logger.warning("Failed to load markets on startup", error=str(e))
        else:
            exchange = ccxt.mexc({"enableRateLimit": True})
            logger.warning("MEXC initialized WITHOUT API keys - trading disabled")

    # Sync balance on startup (live mode only)
    if not PAPER_MODE:
        await sync_portfolio_balance()

    listener_task = asyncio.create_task(listen_for_signals())

    # Periodic portfolio sync for paper mode (keeps Redis state consistent)
    async def periodic_portfolio_sync():
        while True:
            await asyncio.sleep(10)
            if paper_executor:
                try:
                    summary = await paper_executor.get_portfolio_summary()
                    ps = {
                        "available_capital": summary.get("usdt_balance", 0),
                        "total_capital": summary.get("total_value", 0),
                        "starting_capital": STARTING_CAPITAL,
                        "daily_pnl": summary.get("pnl", 0),
                        "open_positions": len(summary.get("positions", {})),
                    }
                    # Preserve last_trade_time from existing state
                    existing = await redis_client.get("portfolio_state")
                    if existing:
                        old = json.loads(existing)
                        ps["last_trade_time"] = old.get("last_trade_time")
                    await redis_client.set("portfolio_state", json.dumps(ps))
                except Exception:
                    pass

    if PAPER_MODE:
        sync_task = asyncio.create_task(periodic_portfolio_sync())

    logger.info("Executor ready", mode=mode)

    yield

    listener_task.cancel()
    if paper_executor:
        await paper_executor.close()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Order Executor Service", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    mode = "paper" if PAPER_MODE else "live"
    result = {"status": "healthy", "mode": mode}
    if PAPER_MODE and paper_executor:
        summary = await paper_executor.get_portfolio_summary()
        result["paper_portfolio"] = summary
    return result


@app.post("/orders", response_model=OrderResponse)
async def create_order(request: OrderRequest):
    return await execute_order(request)


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    data = await redis_client.hget("orders", order_id)
    if data:
        return json.loads(data)
    raise HTTPException(status_code=404, detail="Order not found")


@app.get("/balance")
async def get_balance():
    if PAPER_MODE and paper_executor:
        summary = await paper_executor.get_portfolio_summary()
        return {"balances": paper_executor._balances, "simulated": True, "summary": summary}
    try:
        has_valid_keys = hasattr(exchange, 'apiKey') and exchange.apiKey and exchange.apiKey != "your_mexc_api_key_here"
        if has_valid_keys:
            balance = await exchange.fetch_balance()
            balances = {}
            for coin, data in balance.items():
                if isinstance(data, dict) and (data.get("free", 0) > 0 or data.get("used", 0) > 0):
                    balances[coin] = {"free": data.get("free", 0), "used": data.get("used", 0),
                                      "total": data.get("total", 0)}
            return {"balances": balances, "simulated": False}
        else:
            return {"balances": {"USDT": {"free": 11.0, "used": 0, "total": 11.0}}, "simulated": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emergency/cancel-all")
async def emergency_cancel_all():
    """Cancel all pending orders."""
    if PAPER_MODE:
        return {"status": "success", "cancelled_orders": 0, "message": "Paper mode - no real orders"}
    try:
        orders = await exchange.fetch_open_orders()
        cancelled = []
        for order in orders:
            try:
                await exchange.cancel_order(order['id'], order['symbol'])
                cancelled.append(order['id'])
            except Exception:
                pass
        return {"status": "success", "cancelled_orders": len(cancelled)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
