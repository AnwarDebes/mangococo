"""
Market Data Service v2.0 - WebSocket primary with REST fallback.
Streams real-time prices and writes to both Redis and TimescaleDB.
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest

from exchanges import MexcAdapter

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
TRADING_PAIRS_LIMIT_STR = os.getenv("TRADING_PAIRS_LIMIT", "0")
TRADING_PAIRS_LIMIT = int(TRADING_PAIRS_LIMIT_STR) if TRADING_PAIRS_LIMIT_STR and int(TRADING_PAIRS_LIMIT_STR) > 0 else None
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")

# TimescaleDB config
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "timescaledb")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "mangococo")
POSTGRES_USER = os.getenv("POSTGRES_USER", "mangococo")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
DB_ENABLED = os.getenv("DB_ENABLED", "true").lower() == "true"

# WebSocket config
WS_ENABLED = os.getenv("WS_ENABLED", "true").lower() == "true"
WS_TOP_SYMBOLS = int(os.getenv("WS_TOP_SYMBOLS", 100))  # Number of symbols for WebSocket
REST_POLL_INTERVAL = float(os.getenv("REST_POLL_INTERVAL", 10.0))  # REST fallback interval
REST_ONLY_POLL_INTERVAL = 1.0  # faster polling when WS is not available

logger = structlog.get_logger()

# Metrics
TICKS_RECEIVED = Counter("market_data_ticks_total", "Total ticks received", ["symbol", "source"])
WS_CONNECTED = Gauge("market_data_ws_connected", "WebSocket connection status")
REST_CONNECTED = Gauge("market_data_rest_connected", "REST polling status")
LAST_PRICE = Gauge("market_data_last_price", "Last price", ["symbol"])
TICK_LATENCY = Histogram("market_data_tick_latency_seconds", "Tick processing latency")
DB_WRITES = Counter("market_data_db_writes_total", "Total DB writes")
DB_ERRORS = Counter("market_data_db_errors_total", "Total DB write errors")

# Global State
exchange_adapter: Optional[MexcAdapter] = None
redis_client: Optional[aioredis.Redis] = None
db_pool = None
last_ticks = {}
ws_task = None
rest_task = None
ws_symbols: List[str] = []
rest_symbols: List[str] = []

# Tick buffer for batch DB writes
tick_buffer: List[dict] = []
TICK_BUFFER_SIZE = 100
TICK_FLUSH_INTERVAL = 1.0  # flush every 1 second


async def init_db():
    """Initialize TimescaleDB connection pool."""
    global db_pool
    if not DB_ENABLED:
        logger.info("TimescaleDB disabled (DB_ENABLED=false)")
        return

    try:
        import asyncpg
        db_pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            min_size=2,
            max_size=10,
        )
        logger.info("TimescaleDB connected")
    except Exception as e:
        logger.error("TimescaleDB connection failed - continuing without DB", error=str(e))
        db_pool = None


async def flush_ticks_to_db():
    """Periodically flush tick buffer to TimescaleDB."""
    global tick_buffer
    while True:
        await asyncio.sleep(TICK_FLUSH_INTERVAL)
        if not tick_buffer or not db_pool:
            continue

        batch = tick_buffer[:]
        tick_buffer = []

        try:
            async with db_pool.acquire() as conn:
                await conn.executemany(
                    """INSERT INTO ticks (time, symbol, price, bid, ask, volume)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT DO NOTHING""",
                    [
                        (
                            datetime.fromisoformat(t["timestamp"]),
                            t["symbol"],
                            t["price"],
                            t["bid"],
                            t["ask"],
                            t["volume"],
                        )
                        for t in batch
                    ],
                )
            DB_WRITES.inc(len(batch))
        except Exception as e:
            DB_ERRORS.inc(len(batch))
            logger.error("Failed to flush ticks to DB", error=str(e), batch_size=len(batch))
            # Put failed ticks back (up to a limit to prevent memory growth)
            if len(tick_buffer) < 5000:
                tick_buffer = batch + tick_buffer


async def on_tick(symbol: str, ticker: dict, source: str = "ws"):
    """Process a single ticker update: Redis + DB buffer."""
    price = ticker.get("last", 0.0)
    if price <= 0:
        return

    tick_data = {
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat(),
        "price": price,
        "bid": ticker.get("bid", 0.0),
        "ask": ticker.get("ask", 0.0),
        "volume": ticker.get("quoteVolume", 0.0),
        "change_pct": ticker.get("percentage", 0.0),
    }

    # Update Redis
    await redis_client.hset("latest_ticks", symbol, json.dumps(tick_data))
    await redis_client.publish(f"ticks:{symbol.replace('/', '_')}", json.dumps(tick_data))

    # Buffer for DB write
    if db_pool:
        tick_buffer.append(tick_data)

    last_ticks[symbol] = tick_data
    TICKS_RECEIVED.labels(symbol=symbol, source=source).inc()
    LAST_PRICE.labels(symbol=symbol).set(price)


async def run_ws_stream():
    """Run WebSocket stream for top liquid symbols."""
    if not ws_symbols or not WS_ENABLED:
        return

    try:
        WS_CONNECTED.set(1)
        logger.info(f"Starting WebSocket stream for {len(ws_symbols)} symbols")

        async def ws_on_tick(symbol, ticker):
            await on_tick(symbol, ticker, source="ws")

        await exchange_adapter.stream_tickers_ws(ws_symbols, ws_on_tick)
    except Exception as e:
        WS_CONNECTED.set(0)
        logger.error("WebSocket stream ended", error=str(e))


async def run_rest_poll():
    """Run REST polling for remaining symbols (or all if WS unavailable)."""
    symbols = rest_symbols if ws_symbols else TRADING_PAIRS
    interval = REST_POLL_INTERVAL if ws_symbols else REST_ONLY_POLL_INTERVAL

    # Adjust interval based on symbol count when REST-only
    if not ws_symbols:
        if len(symbols) > 1500:
            interval = 5.0
        elif len(symbols) > 1000:
            interval = 4.0
        elif len(symbols) > 200:
            interval = 3.0

    logger.info(f"Starting REST polling for {len(symbols)} symbols (interval={interval}s)")

    while True:
        try:
            REST_CONNECTED.set(1)
            poll_start = datetime.utcnow()

            async def rest_on_tick(symbol, ticker):
                await on_tick(symbol, ticker, source="rest")

            await exchange_adapter.poll_tickers_rest(symbols, rest_on_tick)

            duration = (datetime.utcnow() - poll_start).total_seconds()
            logger.info(
                f"REST poll completed: {len(symbols)} symbols in {duration:.2f}s"
            )

        except Exception as e:
            REST_CONNECTED.set(0)
            logger.error("REST poll error", error=str(e))

        await asyncio.sleep(interval)


def load_symbols_from_file(filepath: str) -> list:
    """Load symbols from file (one per line)."""
    out = []
    with open(filepath, "r") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return out


def split_symbols_for_streaming(all_symbols: List[str], ws_count: int) -> tuple:
    """
    Split symbols into WebSocket (top liquid) and REST (remaining).
    For now, uses first N symbols alphabetically; will be replaced with
    volume-based ranking once we have historical data in TimescaleDB.
    """
    # Prioritize major pairs for WebSocket
    priority = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
                 "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT",
                 "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "FIL/USDT"]

    ws = [s for s in priority if s in all_symbols]
    remaining_for_ws = [s for s in all_symbols if s not in ws]
    ws.extend(remaining_for_ws[: ws_count - len(ws)])

    rest = [s for s in all_symbols if s not in ws]
    return ws[:ws_count], rest


@asynccontextmanager
async def lifespan(app: FastAPI):
    global exchange_adapter, redis_client, ws_task, rest_task, TRADING_PAIRS
    global ws_symbols, rest_symbols

    logger.info("Starting Market Data Service v2.0...")

    # Redis
    redis_client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        password=REDIS_PASSWORD, decode_responses=True,
    )
    await redis_client.ping()
    logger.info("Redis connected")

    # TimescaleDB
    await init_db()

    # Exchange adapter
    exchange_adapter = MexcAdapter()
    await exchange_adapter.connect()

    # Load symbols
    if TRADING_PAIRS_FILE:
        try:
            symbols = await exchange_adapter.fetch_usdt_symbols(TRADING_PAIRS_LIMIT)
            d = os.path.dirname(TRADING_PAIRS_FILE)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(TRADING_PAIRS_FILE, "w") as f:
                for s in symbols:
                    f.write(s + "\n")
            TRADING_PAIRS = symbols
            logger.info(f"Fetched {len(symbols)} USDT spot symbols from MEXC")
        except Exception as e:
            logger.warning("MEXC fetch failed, using fallback", error=str(e))
            if os.path.isfile(TRADING_PAIRS_FILE):
                TRADING_PAIRS = load_symbols_from_file(TRADING_PAIRS_FILE)
    else:
        TRADING_PAIRS = [s.strip() for s in os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]

    # Split symbols between WebSocket and REST
    if WS_ENABLED and len(TRADING_PAIRS) > 0:
        ws_symbols, rest_symbols = split_symbols_for_streaming(TRADING_PAIRS, WS_TOP_SYMBOLS)
        logger.info(f"Symbol split: {len(ws_symbols)} WebSocket + {len(rest_symbols)} REST")
    else:
        ws_symbols = []
        rest_symbols = TRADING_PAIRS

    # Start data streams
    tasks = []
    if ws_symbols:
        ws_task = asyncio.create_task(run_ws_stream())
        tasks.append(ws_task)
    if rest_symbols or not ws_symbols:
        rest_task = asyncio.create_task(run_rest_poll())
        tasks.append(rest_task)

    # Start DB flush loop
    if db_pool:
        db_flush_task = asyncio.create_task(flush_ticks_to_db())
        tasks.append(db_flush_task)

    yield

    # Cleanup
    for t in tasks:
        t.cancel()
    await exchange_adapter.close()
    if db_pool:
        await db_pool.close()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Market Data Service", version="2.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    ws_active = ws_task and not ws_task.done() if ws_task else False
    rest_active = rest_task and not rest_task.done() if rest_task else False
    return {
        "status": "healthy" if (ws_active or rest_active) else "degraded",
        "websocket": ws_active,
        "rest_polling": rest_active,
        "symbols_total": len(TRADING_PAIRS),
        "symbols_ws": len(ws_symbols),
        "symbols_rest": len(rest_symbols),
        "ticks_cached": len(last_ticks),
        "db_enabled": db_pool is not None,
    }


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
