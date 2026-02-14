"""
Feature Store Service - Computes and serves real-time feature vectors
for trading signals. Combines technical indicators and sentiment data
into unified feature vectors stored in Redis and TimescaleDB.
"""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

import db
from compute import compute_combined_features

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
ACTIVE_SYMBOLS_KEY = os.getenv("ACTIVE_SYMBOLS_KEY", "latest_ticks")
COMPUTE_INTERVAL = float(os.getenv("FEATURE_COMPUTE_INTERVAL", 5.0))
FEATURE_TTL = int(os.getenv("FEATURE_TTL", 10))
DB_PERSIST_INTERVAL = int(os.getenv("DB_PERSIST_INTERVAL", 60))  # seconds

logger = structlog.get_logger()

# Prometheus metrics
FEATURES_COMPUTED = Counter(
    "feature_store_computed_total", "Total feature computations", ["symbol"]
)
COMPUTE_DURATION = Histogram(
    "feature_store_compute_seconds", "Feature computation duration"
)
COMPUTE_ERRORS = Counter(
    "feature_store_errors_total", "Feature computation errors", ["symbol"]
)
ACTIVE_SYMBOLS_GAUGE = Gauge(
    "feature_store_active_symbols", "Number of active symbols"
)
LAST_COMPUTE_TIME = Gauge(
    "feature_store_last_compute_epoch", "Last feature computation timestamp"
)

# Global state
redis_client: Optional[aioredis.Redis] = None
compute_task: Optional[asyncio.Task] = None
latest_features: dict[str, dict] = {}
_last_db_persist = 0.0


async def get_active_symbols() -> list[str]:
    """Get list of active symbols from Redis latest_ticks hash."""
    if not redis_client:
        return []
    try:
        symbols = await redis_client.hkeys(ACTIVE_SYMBOLS_KEY)
        return sorted(symbols) if symbols else []
    except Exception as e:
        logger.error("Failed to get active symbols", error=str(e))
        return []


async def compute_all_features():
    """Background loop: compute features for all active symbols every N seconds."""
    global latest_features, _last_db_persist

    while True:
        try:
            symbols = await get_active_symbols()
            ACTIVE_SYMBOLS_GAUGE.set(len(symbols))

            if not symbols:
                await asyncio.sleep(COMPUTE_INTERVAL)
                continue

            cycle_start = time.monotonic()
            should_persist = (time.monotonic() - _last_db_persist) >= DB_PERSIST_INTERVAL

            for symbol in symbols:
                try:
                    start = time.monotonic()
                    features = await compute_combined_features(symbol, redis_client)
                    duration = time.monotonic() - start

                    COMPUTE_DURATION.observe(duration)
                    FEATURES_COMPUTED.labels(symbol=symbol).inc()

                    # Add metadata
                    features["_symbol"] = symbol
                    features["_computed_at"] = datetime.now(timezone.utc).isoformat()
                    features["_compute_ms"] = round(duration * 1000, 2)

                    # Store in memory
                    latest_features[symbol] = features

                    # Store in Redis with TTL
                    await redis_client.set(
                        f"features:{symbol}",
                        json.dumps(features),
                        ex=FEATURE_TTL,
                    )

                    # Periodically persist to TimescaleDB
                    if should_persist:
                        # Strip metadata keys for DB storage
                        db_features = {
                            k: v for k, v in features.items()
                            if not k.startswith("_") and isinstance(v, (int, float))
                        }
                        await db.store_features(symbol, db_features)

                except Exception as e:
                    COMPUTE_ERRORS.labels(symbol=symbol).inc()
                    logger.error(
                        "Feature computation failed",
                        symbol=symbol,
                        error=str(e),
                    )

            if should_persist:
                _last_db_persist = time.monotonic()

            cycle_duration = time.monotonic() - cycle_start
            LAST_COMPUTE_TIME.set(time.time())
            logger.info(
                "Feature compute cycle complete",
                symbols=len(symbols),
                duration_s=round(cycle_duration, 3),
                persisted=should_persist,
            )

        except Exception as e:
            logger.error("Feature compute loop error", error=str(e))

        await asyncio.sleep(COMPUTE_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, compute_task

    logger.info("Starting Feature Store Service...")

    # Connect to Redis
    redis_client = aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )
    await redis_client.ping()
    logger.info("Redis connected", host=REDIS_HOST)

    # Connect to TimescaleDB
    try:
        await db.init_pool()
    except Exception as e:
        logger.warning("TimescaleDB connection failed, continuing without persistence", error=str(e))

    # Start background compute loop
    compute_task = asyncio.create_task(compute_all_features())
    logger.info("Feature compute loop started", interval=COMPUTE_INTERVAL)

    yield

    # Cleanup
    if compute_task:
        compute_task.cancel()
        try:
            await compute_task
        except asyncio.CancelledError:
            pass

    await db.close_pool()
    if redis_client:
        await redis_client.close()

    logger.info("Feature Store Service stopped")


app = FastAPI(
    title="Feature Store Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    pool = db.get_pool()
    symbols = list(latest_features.keys())
    return {
        "status": "healthy" if compute_task and not compute_task.done() else "degraded",
        "redis_connected": redis_client is not None,
        "db_connected": pool is not None,
        "active_symbols": len(symbols),
        "compute_interval_s": COMPUTE_INTERVAL,
        "feature_ttl_s": FEATURE_TTL,
    }


@app.get("/features/{symbol}")
async def get_features(symbol: str):
    """Return latest feature vector for a specific symbol."""
    symbol = symbol.replace("_", "/").upper()

    # Try in-memory cache first
    if symbol in latest_features:
        return latest_features[symbol]

    # Try Redis fallback
    if redis_client:
        try:
            raw = await redis_client.get(f"features:{symbol}")
            if raw:
                return json.loads(raw)
        except Exception:
            pass

    return {"error": f"No features available for {symbol}"}


@app.get("/features")
async def get_all_features():
    """Return all computed feature vectors."""
    return {
        "count": len(latest_features),
        "symbols": sorted(latest_features.keys()),
        "features": latest_features,
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint."""
    return generate_latest()
