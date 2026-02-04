"""
Order Executor Service - Executes trades on MEXC
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
from prometheus_client import Counter, Histogram, generate_latest

# Configuration
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"  # Enable mock trading for testing

logger = structlog.get_logger()

# Metrics
ORDERS_SUBMITTED = Counter("executor_orders_total", "Orders submitted", ["symbol", "side"])
ORDERS_FILLED = Counter("executor_orders_filled_total", "Orders filled")
ORDERS_FAILED = Counter("executor_orders_failed_total", "Orders failed", ["reason"])
ORDER_LATENCY = Histogram("executor_latency_seconds", "Order latency")


class OrderRequest(BaseModel):
    signal_id: str = ""
    symbol: str
    side: str = Field(..., pattern="^(buy|sell)$")
    amount: float = Field(..., gt=0)
    price: Optional[float] = None
    order_type: str = "limit"


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


# Global State
exchange: Optional[ccxt.mexc] = None
redis_client: Optional[aioredis.Redis] = None


async def sync_portfolio_balance():
    """Automatically sync portfolio state with actual MEXC balance (if API keys available)"""
    try:
        # Only sync if we have valid API keys
        if hasattr(exchange, 'apiKey') and exchange.apiKey and exchange.apiKey != "your_mexc_api_key_here":
            balance = await exchange.fetch_balance()
            usdt_balance = balance.get("USDT", {}).get("free", 0) or 0

            # Get current portfolio state
            portfolio_state_str = await redis_client.get("portfolio_state")
            if portfolio_state_str:
                portfolio_state = json.loads(portfolio_state_str)
            else:
                portfolio_state = {}

            # Update available capital with actual USDT free balance (for trading)
            # This is the amount available for new trades, not total portfolio value
            portfolio_state["available_capital"] = usdt_balance
            portfolio_state["usdt_free"] = usdt_balance  # Store USDT free separately
            portfolio_state["last_trade_time"] = datetime.utcnow().isoformat()
            
            # Calculate total portfolio value (USDT + holdings)
            total_value = usdt_balance
            for coin, coin_data in balance.items():
                if coin != "USDT" and isinstance(coin_data, dict):
                    free = coin_data.get("free", 0) or 0
                    if free > 0.0001:  # Only count significant holdings
                        try:
                            # Try to get current price from Redis
                            tick_key = f"ticker:{coin}/USDT"
                            tick_data = await redis_client.get(tick_key)
                            if tick_data:
                                tick = json.loads(tick_data)
                                price = tick.get("price") or tick.get("last") or 0
                                if price > 0:
                                    total_value += free * price
                        except:
                            pass  # Skip if price not available
            
            portfolio_state["total_capital"] = total_value

            # Save updated portfolio state
            await redis_client.set("portfolio_state", json.dumps(portfolio_state))
            logger.debug("Portfolio balance synced", available_capital=usdt_balance, total_capital=total_value)
        else:
            logger.debug("Skipping portfolio sync - no valid API keys")
    except Exception as e:
        logger.error("Failed to sync portfolio balance", error=str(e))


async def execute_order(request: OrderRequest) -> OrderResponse:
    order_id = str(uuid.uuid4())[:8]
    start_time = datetime.utcnow()

    logger.info("Executing order", order_id=order_id, symbol=request.symbol, side=request.side, amount=request.amount, price=request.price)

    try:
        # Check if we have valid API keys and not in mock mode
        has_valid_keys = hasattr(exchange, 'apiKey') and exchange.apiKey and exchange.apiKey != "your_mexc_api_key_here"
        use_real_trading = has_valid_keys and not MOCK_MODE

        if MOCK_MODE:
            logger.warning(f"MOCK MODE: Simulating {request.side} order for {request.symbol} - using REAL prices")

        # ALWAYS fetch real prices from MEXC (even in mock mode)
        try:
            ticker = await exchange.fetch_ticker(request.symbol)
            # Use ask for buy, bid for sell, fallback to last price if None
            if request.side == "buy":
                current_price = ticker.get("ask") or ticker.get("last") or ticker.get("close")
            else:
                current_price = ticker.get("bid") or ticker.get("last") or ticker.get("close")

            if current_price is None:
                raise ValueError(f"Could not get price for {request.symbol}")

            logger.info(f"Real MEXC price for {request.symbol}: ${current_price}")
        except Exception as price_error:
            logger.error(f"Failed to fetch real price for {request.symbol}: {price_error}")
            raise ValueError(f"Could not get real price for {request.symbol}: {price_error}")
        
        # Use current market price for limit orders
        if request.order_type != "market":
            request.price = current_price
        
        # Ensure order value is at least 1.40 USDT (increased buffer above MEXC $1 USDT minimum)
        min_order_value = 1.40

        # For BUY orders: amount from signal is USDT value, convert to coin quantity
        # For SELL orders: amount is already coin quantity
        if request.side == "buy":
            # Signal sends USDT value (e.g., 1.4 means $1.40), convert to coin quantity
            usdt_amount = request.amount
            
            # VALIDATE ACTUAL USDT BALANCE BEFORE BUYING - never place without valid balance
            try:
                balance = await exchange.fetch_balance()
                usdt_balance_data = balance.get("USDT", {})
                usdt_balance = float(usdt_balance_data.get("free", 0) or 0)
                
                logger.info("BUY order balance check", symbol=request.symbol,
                            requested_usdt=usdt_amount, available_usdt=usdt_balance)
                
                if usdt_balance <= 0:
                    raise ValueError(f"Insufficient USDT balance: have ${usdt_balance:.2f}, cannot buy ${usdt_amount:.2f}")
                
                if usdt_balance < min_order_value:
                    raise ValueError(
                        f"USDT balance ${usdt_balance:.2f} is below minimum order value ${min_order_value:.2f}; "
                        "cannot place buy order."
                    )
                
                # If we don't have enough USDT for requested amount, use what we have (with small buffer)
                if usdt_balance < usdt_amount:
                    original_requested = usdt_amount
                    usdt_amount = usdt_balance * 0.99
                    logger.warning(
                        "Reducing buy to available balance",
                        symbol=request.symbol,
                        requested=original_requested,
                        available=usdt_balance,
                        adjusted=usdt_amount,
                    )
                
                if usdt_amount < min_order_value:
                    raise ValueError(
                        f"Adjusted USDT amount ${usdt_amount:.2f} below minimum ${min_order_value:.2f}; "
                        "insufficient balance for a valid order."
                    )
            except ValueError:
                # Validation failure: do not place order
                raise
            except Exception as balance_error:
                logger.error("Failed to fetch balance for buy order", symbol=request.symbol, error=str(balance_error))
                raise ValueError(
                    f"Cannot place buy order: balance check failed ({balance_error}). "
                    "Order aborted for safety."
                ) from balance_error
            
            coin_quantity = usdt_amount / current_price
            request.amount = coin_quantity
            order_value = usdt_amount  # Original USDT value
            logger.info(f"BUY order: Converting ${usdt_amount:.4f} USDT to {coin_quantity:.8f} coins @ ${current_price}")
        else:
            # SELL orders: amount is coin quantity - VALIDATE ACTUAL BALANCE
            coin_symbol = request.symbol.split("/")[0]  # e.g., "BTC" from "BTC/USDT"
            
            try:
                balance = await exchange.fetch_balance()
                coin_balance_data = balance.get(coin_symbol, {})
                coin_balance = float(coin_balance_data.get("free", 0) or 0)
                
                logger.info("SELL order balance check", symbol=request.symbol, coin=coin_symbol,
                            requested_amount=request.amount, available_balance=coin_balance)
                
                if coin_balance <= 0:
                    raise ValueError(f"Insufficient {coin_symbol} balance: have {coin_balance}, cannot sell {request.amount}")
                
                original_requested = request.amount
                if coin_balance < request.amount:
                    request.amount = coin_balance * 0.999
                    logger.warning(
                        "Reducing sell to available balance",
                        symbol=request.symbol,
                        requested=original_requested,
                        available=coin_balance,
                        adjusted=request.amount,
                    )
                elif request.amount > coin_balance * 0.999:
                    request.amount = coin_balance * 0.999
                    logger.warning("Adjusted sell amount to available balance",
                                   original=original_requested, adjusted=request.amount, available=coin_balance)
            except ValueError:
                raise
            except Exception as balance_error:
                logger.error("Failed to fetch balance for sell order", symbol=request.symbol, error=str(balance_error))
                raise ValueError(
                    f"Cannot place sell order: balance check failed ({balance_error}). Order aborted for safety."
                ) from balance_error
            
            order_value = request.amount * current_price

        if order_value < min_order_value:
            if request.side == "buy":
                raise ValueError(
                    f"Order value ${order_value:.2f} is below minimum ${min_order_value:.2f} and "
                    "insufficient USDT balance to meet minimum. Order aborted."
                )
            # For sell: recalculate to meet exchange minimum if needed
            original_coin_amount = request.amount
            request.amount = min_order_value / current_price
            order_value = min_order_value
            logger.warning("Adjusted sell order to meet minimum", original_coin_amount=original_coin_amount, new_coin_amount=request.amount, order_value=order_value, price=current_price)
        
        logger.info("Order details", amount=request.amount, price=request.price, order_value=order_value)

        # IDEMPOTENCY: Check if this signal has already been executed
        if request.signal_id:
            existing_order = await redis_client.hget("signal_orders", request.signal_id)
            if existing_order:
                logger.info("Signal already processed, skipping duplicate order", signal_id=request.signal_id)
                # Return the existing order response
                return json.loads(existing_order)

        # Execute or simulate order
        if use_real_trading:
            # Real trading
            if request.order_type == "market":
                if request.side == "buy":
                    # For market buy orders, MEXC expects the cost amount
                    order = await exchange.create_market_buy_order(request.symbol, request.amount)
                else:
                    # For market sell orders, use amount of coins
                    order = await exchange.create_market_sell_order(request.symbol, request.amount)
            else:
                order = await exchange.create_limit_order(request.symbol, request.side, request.amount, request.price)
        else:
            # Simulate order for testing
            import time
            await asyncio.sleep(0.1)  # Simulate network delay
            order = {
                "id": f"simulated_{int(time.time())}",
                "status": "closed",
                "filled": request.amount,
                "cost": request.amount * current_price,
                "price": current_price,
                "average": current_price
            }
            logger.info("Simulated order executed", order_id=order_id, symbol=request.symbol, side=request.side)

        ORDER_LATENCY.observe((datetime.utcnow() - start_time).total_seconds())
        ORDERS_SUBMITTED.labels(symbol=request.symbol, side=request.side).inc()

        # For limit orders, check if they're filled immediately or poll status
        order_status = order.get("status", "unknown")
        # Handle None values properly - MEXC sometimes returns None for these fields
        filled_amount = order.get("filled") if order.get("filled") is not None else request.amount
        order_price = order.get("price") or order.get("average") or current_price or 0
        if order_price is None or order_price == 0:
            order_price = current_price  # Fallback to fetched price
        order_cost = order.get("cost")
        if order_cost is None or order_cost == 0:
            order_cost = (filled_amount or 0) * (order_price or current_price or 1)
        
        # If limit order is open, use market order for immediate execution
        if request.order_type == "limit" and order_status in ["open", "new"]:
            logger.info("Limit order placed, converting to market for immediate fill", order_id=order_id)
            try:
                # Cancel the limit order and place market order
                if order.get("id"):
                    try:
                        await exchange.cancel_order(order.get("id"), request.symbol)
                    except:
                        pass
                # Place market order for immediate execution
                if use_real_trading:
                    market_order = await exchange.create_market_order(request.symbol, request.side, request.amount)
                else:
                    # Simulate market order
                    market_order = {
                        "id": f"simulated_market_{int(time.time())}",
                        "status": "closed",
                        "filled": request.amount,
                        "cost": request.amount * current_price,
                        "price": current_price,
                        "average": current_price
                    }
                order_status = market_order.get("status", "closed")
                filled_amount = market_order.get("filled") if market_order.get("filled") is not None else request.amount
                order_price = market_order.get("price") or market_order.get("average") or current_price or 0
                if order_price is None or order_price == 0:
                    order_price = current_price
                order_cost = market_order.get("cost")
                if order_cost is None or order_cost == 0:
                    order_cost = (filled_amount or 0) * (order_price or current_price or 1)
                order = market_order
            except Exception as e:
                logger.warning("Market order conversion failed, using limit order", error=str(e))

        # Determine if order is filled
        is_filled = (order_status in ["closed", "filled"]) or (filled_amount > 0 and filled_amount >= request.amount * 0.99)
        
        if is_filled:
            ORDERS_FILLED.inc()
            order_status = "closed"  # Normalize to "closed" for position service

        response = OrderResponse(
            order_id=order_id, exchange_order_id=order.get("id"), status=order_status,
            symbol=request.symbol, side=request.side, amount=request.amount,
            price=order_price, filled=filled_amount, cost=order_cost,
            timestamp=datetime.utcnow().isoformat()
        )

        # IDEMPOTENCY: Store order response by signal_id to prevent duplicate processing
        if request.signal_id:
            await redis_client.hset("signal_orders", request.signal_id, response.model_dump_json())

        # Always publish order updates - position service will handle filled orders
        await redis_client.publish("order_updates", response.model_dump_json())
        await redis_client.hset("orders", order_id, response.model_dump_json())
        
        # If order is filled, also publish to a dedicated channel for immediate processing
        if is_filled:
            await redis_client.publish("filled_orders", response.model_dump_json())
            # Sync portfolio state with actual MEXC balance
            await sync_portfolio_balance()
            logger.info("Order filled and published", order_id=order_id, symbol=request.symbol, side=request.side, filled=filled_amount, cost=order_cost)

        logger.info("Order executed", order_id=order_id, status=response.status, filled=filled_amount)
        return response

    except Exception as e:
        error_str = str(e).lower()
        error_msg = str(e)
        
        # Handle specific MEXC errors with better messages
        if "insufficient position" in error_str or "30004" in error_msg:
            # This should not happen now with balance validation, but handle gracefully
            reason = "insufficient_position"
            detail_msg = f"Insufficient {request.symbol.split('/')[0]} balance. Balance validation should have prevented this. Error: {error_msg}"
            logger.error("Order failed - Insufficient position (should have been caught by validation)", 
                        order_id=order_id, symbol=request.symbol, side=request.side, amount=request.amount, error=error_msg)
        elif "minimum transaction volume" in error_str or "30002" in error_msg:
            reason = "below_minimum_volume"
            detail_msg = f"Order value below MEXC minimum ($1 USDT). Error: {error_msg}"
            logger.error("Order failed - Below minimum volume", order_id=order_id, symbol=request.symbol, error=error_msg)
        else:
            reason = type(e).__name__
            detail_msg = error_msg
        
        ORDERS_FAILED.labels(reason=reason).inc()
        logger.error("Order failed", order_id=order_id, symbol=request.symbol, side=request.side, error=error_msg)
        raise HTTPException(status_code=500, detail=detail_msg)


async def listen_for_validated_signals():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("raw_signals")  # Listen to the correct channel that signals publish to
    logger.info("Executor subscribed to raw_signals channel")

    processed_signal_ids = set()  # Track processed signals for idempotency

    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                signal = json.loads(message["data"])
                signal_id = signal.get("signal_id", "")

                # IDEMPOTENCY: Check if this signal has already been processed
                if signal_id and signal_id in processed_signal_ids:
                    logger.debug("Signal already processed, skipping", signal_id=signal_id)
                    continue

                action = signal.get("action", "unknown")
                symbol = signal.get("symbol", "unknown")
                amount = signal.get("amount", 0)

                # Log ALL received signals, especially sells
                if action == "sell":
                    logger.warning(f"SELL SIGNAL RECEIVED: {symbol} amount={amount}")
                else:
                    logger.debug(f"Signal received: {action} {symbol} amount={amount}")

                request = OrderRequest(
                    signal_id=signal_id, symbol=symbol,
                    side=action, amount=amount, price=signal.get("price")
                )

                # Execute order
                await execute_order(request)

                # IDEMPOTENCY: Mark signal as processed after execution attempt
                if signal_id:
                    processed_signal_ids.add(signal_id)
                    # Keep only recent signals to prevent memory growth
                    if len(processed_signal_ids) > 1000:
                        processed_signal_ids.pop()
            except Exception as e:
                logger.error("Failed to execute signal", error=str(e), signal_data=message.get("data", "")[:200])


@asynccontextmanager
async def lifespan(app: FastAPI):
    global exchange, redis_client
    logger.info("Starting Executor Service...")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    await redis_client.ping()

    # Initialize MEXC exchange - handle missing/invalid API keys gracefully
    if MEXC_API_KEY and MEXC_SECRET_KEY and MEXC_API_KEY != "your_mexc_api_key_here":
        exchange = ccxt.mexc({
            "apiKey": MEXC_API_KEY,
            "secret": MEXC_SECRET_KEY,
            "enableRateLimit": True,
            "options": {"createMarketBuyOrderRequiresPrice": False}
        })
        try:
            await exchange.load_markets()
            logger.info("MEXC exchange initialized with API keys and markets loaded")
        except Exception as e:
            logger.warning("Failed to load markets on startup (API keys may be invalid or IP not whitelisted)", error=str(e))
            logger.info("Service will continue - markets will be loaded on first trade attempt")
    else:
        # Create exchange without API keys for testing
        exchange = ccxt.mexc({"enableRateLimit": True})
        # Don't load markets to avoid API key requirement
        logger.warning("MEXC exchange initialized WITHOUT API keys - trading disabled for testing")

    listener_task = asyncio.create_task(listen_for_validated_signals())
    logger.info("Executor ready")

    yield

    listener_task.cancel()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Order Executor Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy"}


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
    try:
        has_valid_keys = hasattr(exchange, 'apiKey') and exchange.apiKey and exchange.apiKey != "your_mexc_api_key_here"
        if has_valid_keys:
            balance = await exchange.fetch_balance()
            # Return all non-zero balances
            balances = {}
            for coin, data in balance.items():
                if isinstance(data, dict) and (data.get("free", 0) > 0 or data.get("used", 0) > 0):
                    balances[coin] = {"free": data.get("free", 0), "used": data.get("used", 0), "total": data.get("total", 0)}
            return {"balances": balances, "simulated": False}
        else:
            return {"balances": {"USDT": {"free": 11.0, "used": 0, "total": 11.0}}, "simulated": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emergency/cancel-all")
async def emergency_cancel_all():
    """Cancel all pending orders"""
    try:
        # Get all open orders and cancel them
        orders = await exchange.fetch_open_orders()
        cancelled = []
        for order in orders:
            try:
                await exchange.cancel_order(order['id'], order['symbol'])
                cancelled.append(order['id'])
            except:
                pass
        return {"status": "success", "cancelled_orders": len(cancelled)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
