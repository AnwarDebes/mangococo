"""
Market Data Service - Streams real-time prices from MEXC
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

import ccxt
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, generate_latest

# Configuration
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_SECRET_KEY = os.getenv("MEXC_SECRET_KEY", "")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
# TRADING_PAIRS_LIMIT: If set to 0 or negative, fetches ALL available pairs. Otherwise limits to that number.
TRADING_PAIRS_LIMIT_STR = os.getenv("TRADING_PAIRS_LIMIT", "0")
TRADING_PAIRS_LIMIT = int(TRADING_PAIRS_LIMIT_STR) if TRADING_PAIRS_LIMIT_STR and int(TRADING_PAIRS_LIMIT_STR) > 0 else None
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")
POLL_INTERVAL = 1.0  # Set in lifespan based on symbol count

logger = structlog.get_logger()


def fetch_mexc_usdt_symbols(limit: Optional[int] = None) -> list:
    """Fetch ALL USDT spot symbols from MEXC (no API keys needed for load_markets). 
    If limit is None, fetches all available pairs. Sync for one-time startup."""
    ex = ccxt.mexc({"enableRateLimit": True})
    ex.load_markets()
    symbols = []
    for symbol, m in ex.markets.items():
        if m.get("quote") != "USDT":
            continue
        if not m.get("spot", True):
            continue
        # Include all spot USDT pairs - don't filter by 'active' flag as MEXC
        # marks many tradeable markets as inactive. The 'spot' check is sufficient.
        symbols.append(symbol)
    sorted_symbols = sorted(symbols)
    # Return all symbols if limit is None, otherwise limit
    if limit is None:
        return sorted_symbols
    return sorted_symbols[:limit]


def load_symbols_from_file(filepath: str) -> list:
    """Load symbols from file (one per line)."""
    out = []
    with open(filepath, "r") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return out


# Metrics
TICKS_RECEIVED = Counter("market_data_ticks_total", "Total ticks received", ["symbol"])
WS_CONNECTED = Gauge("market_data_ws_connected", "WebSocket connection status")
LAST_PRICE = Gauge("market_data_last_price", "Last price", ["symbol"])

# Global State
exchange: Optional[ccxt.mexc] = None
redis_client: Optional[aioredis.Redis] = None
is_connected = False
last_ticks = {}
polling_task = None


def safe_float(value, default=0.0):
    """Safely convert value to float, handling None and invalid types."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


async def process_ticker(symbol: str, ticker: dict):
    """Process individual ticker: write to Redis and pubsub so data is always latest (continuous real-time updates)."""
    global last_ticks
    
    # Safely extract ticker data with None handling
    price = safe_float(ticker.get("last"))
    bid = safe_float(ticker.get("bid"))
    ask = safe_float(ticker.get("ask"))
    volume = safe_float(ticker.get("quoteVolume"))
    change_pct = safe_float(ticker.get("percentage"))
    
    # Skip if price is invalid (0 or None) - indicates bad data from exchange
    if price <= 0:
        logger.debug(f"Skipping {symbol} - invalid price data (price={ticker.get('last')})")
        return
    
    tick_data = {
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat(),
        "price": price,
        "bid": bid,
        "ask": ask,
        "volume": volume,
        "change_pct": change_pct,
    }

    # Always update Redis so latest_ticks hash has the latest price for every symbol (continuous)
    await redis_client.hset("latest_ticks", symbol, json.dumps(tick_data))

    # Publish to pubsub so prediction service receives real-time ticks (all our trading pairs)
    await redis_client.publish(f"ticks:{symbol.replace('/', '_')}", json.dumps(tick_data))

    last_ticks[symbol] = tick_data
    TICKS_RECEIVED.labels(symbol=symbol).inc()
    LAST_PRICE.labels(symbol=symbol).set(tick_data["price"])


async def poll_market_data():
    """Continuous real-time price fetching: poll MEXC API in batches, update Redis every cycle (no manual step)."""
    global is_connected, last_ticks, exchange

    symbols = [s.strip() for s in TRADING_PAIRS]
    logger.info(f"Starting continuous market data polling for {len(symbols)} coins (Redis updated every {POLL_INTERVAL}s)")

    while True:
        try:
            is_connected = True
            WS_CONNECTED.set(1)

            # Poll tickers in optimized batches - adjust batch size based on total coins
            # Larger batch sizes for more coins to reduce API calls while staying under rate limits
            if len(symbols) > 1000:
                batch_size = 100  # Larger batches for 1000+ coins
            elif len(symbols) > 500:
                batch_size = 75  # Medium batches for 500-1000 coins
            else:
                batch_size = 50  # Standard batches for <500 coins
            poll_start = datetime.utcnow()

            for i in range(0, len(symbols), batch_size):
                batch_symbols = symbols[i:i + batch_size]
                try:
                    # Fetch multiple tickers at once if supported, otherwise individually
                    if hasattr(exchange, 'fetch_tickers'):
                        try:
                            tickers = exchange.fetch_tickers(batch_symbols)
                            for symbol, ticker in tickers.items():
                                await process_ticker(symbol, ticker)
                        except:
                            # Fallback to individual fetching
                            for symbol in batch_symbols:
                                try:
                                    ticker = exchange.fetch_ticker(symbol)
                                    await process_ticker(symbol, ticker)
                                    await asyncio.sleep(0.01)  # Small delay to avoid rate limits
                                except Exception as e:
                                    logger.debug(f"Failed to fetch {symbol}", error=str(e))
                    else:
                        # Individual fetching with rate limiting
                        for symbol in batch_symbols:
                            try:
                                ticker = exchange.fetch_ticker(symbol)
                                await process_ticker(symbol, ticker)
                                await asyncio.sleep(0.01)  # Small delay between requests
                            except Exception as e:
                                logger.debug(f"Failed to fetch {symbol}", error=str(e))

                except Exception as e:
                    logger.error(f"Batch processing failed for batch {i//batch_size + 1}", error=str(e))

            # Performance monitoring
            poll_duration = (datetime.utcnow() - poll_start).total_seconds()
            logger.info(f"Market data poll completed: {len(symbols)} coins in {poll_duration:.2f}s ({len(symbols)/poll_duration:.1f} coins/sec)")

            # Wait before next poll (slower for 1000 coins to stay under MEXC rate limit)
            await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            is_connected = False
            WS_CONNECTED.set(0)
            logger.error("Market data polling error", error=str(e))
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global exchange, redis_client, polling_task, TRADING_PAIRS, POLL_INTERVAL

    logger.info("Starting Market Data Service...")

    redis_client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        password=REDIS_PASSWORD, decode_responses=True
    )
    await redis_client.ping()
    logger.info("Redis connected")

    # Load symbol list: from file (MEXC fetch) or env
    if TRADING_PAIRS_FILE:
        try:
            # Fetch ALL available USDT spot pairs (TRADING_PAIRS_LIMIT=None means no limit)
            symbols = await asyncio.to_thread(fetch_mexc_usdt_symbols, TRADING_PAIRS_LIMIT)
            d = os.path.dirname(TRADING_PAIRS_FILE)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(TRADING_PAIRS_FILE, "w") as f:
                for s in symbols:
                    f.write(s + "\n")
            TRADING_PAIRS = symbols
            limit_msg = f" (limit: {TRADING_PAIRS_LIMIT})" if TRADING_PAIRS_LIMIT else " (ALL available)"
            logger.info(f"Fetched {len(symbols)} USDT spot symbols from MEXC{limit_msg}, wrote to {TRADING_PAIRS_FILE}")
        except Exception as e:
            logger.warning("MEXC fetch failed, using file or env fallback", error=str(e))
            if os.path.isfile(TRADING_PAIRS_FILE):
                TRADING_PAIRS = load_symbols_from_file(TRADING_PAIRS_FILE)
                logger.info(f"Loaded {len(TRADING_PAIRS)} symbols from existing file")
            else:
                logger.info("Using TRADING_PAIRS from env")
        
        # Adjust polling interval based on symbol count for rate limit safety
        # More symbols = longer interval to stay under MEXC rate limits
        if len(TRADING_PAIRS) > 1500:
            POLL_INTERVAL = 5.0  # Very conservative for 1500+ coins
            logger.info(f"Using poll interval {POLL_INTERVAL}s for {len(TRADING_PAIRS)} symbols (conservative rate limit)")
        elif len(TRADING_PAIRS) > 1000:
            POLL_INTERVAL = 4.0  # Conservative for 1000-1500 coins
            logger.info(f"Using poll interval {POLL_INTERVAL}s for {len(TRADING_PAIRS)} symbols (rate limit safe)")
        elif len(TRADING_PAIRS) > 200:
            POLL_INTERVAL = 3.0  # Standard for 200-1000 coins
            logger.info(f"Using poll interval {POLL_INTERVAL}s for {len(TRADING_PAIRS)} symbols (rate limit safe)")
    else:
        TRADING_PAIRS = [s.strip() for s in os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]
        if len(TRADING_PAIRS) > 200:
            POLL_INTERVAL = 3.0

    # Use MEXC exchange without API keys for public market data
    exchange = ccxt.mexc({
        "enableRateLimit": True,
    })
    logger.info("MEXC exchange initialized (REST mode)")

    polling_task = asyncio.create_task(poll_market_data())

    yield

    if polling_task:
        polling_task.cancel()
    if exchange:
        try:
            exchange.close()
        except Exception:
            pass
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Market Data Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy" if is_connected else "degraded", "websocket": is_connected, "symbols": len(last_ticks)}


@app.get("/tickers")
async def get_all_tickers():
    return last_ticks


@app.get("/ticker/{symbol}")
async def get_ticker(symbol: str):
    symbol = symbol.replace("_", "/").upper()
    if symbol in last_ticks:
        return last_ticks[symbol]
    return {"error": f"Symbol {symbol} not found"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
