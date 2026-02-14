"""
Trend Analysis Service - Collects Google Trends, social volume,
whale transactions, and exchange metrics for crypto trading signals.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Dict, Optional

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest

from collectors import (
    GoogleTrendsCollector,
    SocialVolumeCollector,
    WhaleTracker,
    ExchangeMetricsCollector,
)
from db import TrendDB

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

GOOGLE_TRENDS_INTERVAL = int(os.getenv("GOOGLE_TRENDS_INTERVAL", 14400))  # 4 hours
SOCIAL_VOLUME_INTERVAL = int(os.getenv("SOCIAL_VOLUME_INTERVAL", 900))  # 15 minutes
WHALE_TRACKER_INTERVAL = int(os.getenv("WHALE_TRACKER_INTERVAL", 300))  # 5 minutes
EXCHANGE_METRICS_INTERVAL = int(os.getenv("EXCHANGE_METRICS_INTERVAL", 60))  # 1 minute

logger = structlog.get_logger()

# Prometheus metrics
COLLECT_COUNT = Counter("trend_collections_total", "Total collection runs", ["source"])
COLLECT_ERRORS = Counter("trend_collection_errors_total", "Collection errors", ["source"])
PROCESSING_TIME = Histogram("trend_processing_seconds", "Processing time per cycle", ["source"])
WHALE_FLOW_GAUGE = Gauge("trend_whale_flow_score", "Whale net flow score", ["symbol"])
FUNDING_RATE_GAUGE = Gauge("trend_funding_rate", "Exchange funding rate", ["symbol"])

# In-memory trend data cache
trend_cache: Dict[str, dict] = {}
redis_client: Optional[aioredis.Redis] = None

# Components
google_trends = GoogleTrendsCollector()
whale_tracker = WhaleTracker()
exchange_metrics = ExchangeMetricsCollector()
db = TrendDB()


async def _get_redis() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
        )
    return redis_client


async def _store_trends(symbol: str, data: dict, metric_type: str):
    """Store trend data in Redis, TimescaleDB, and local cache."""
    r = await _get_redis()
    now = datetime.now(timezone.utc)

    # Merge into cache
    if symbol not in trend_cache:
        trend_cache[symbol] = {"symbol": symbol}
    trend_cache[symbol][metric_type] = data
    trend_cache[symbol]["updated_at"] = now.isoformat()

    # Store full trend data in Redis
    await r.set(
        f"trends:{symbol}",
        json.dumps(trend_cache[symbol], default=str),
        ex=86400,
    )

    # Write to TimescaleDB
    value = data.get("score", data.get("value", data.get("z_score", 0.0)))
    if isinstance(value, (int, float)):
        metadata = json.dumps(data, default=str)
        await db.batch_insert([(now, symbol, metric_type, float(value), metadata)])


async def _publish_update(symbols: list, source: str):
    """Publish trend update to Redis pubsub."""
    r = await _get_redis()
    try:
        await r.publish("trend_update", json.dumps({
            "type": "trend_update",
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbols": symbols,
        }))
    except Exception as e:
        logger.error("redis_publish_error", error=str(e))


async def _collect_google_trends():
    """Periodic Google Trends collection task."""
    # Initial delay to let other services start
    await asyncio.sleep(30)
    while True:
        try:
            COLLECT_COUNT.labels(source="google_trends").inc()
            with PROCESSING_TIME.labels(source="google_trends").time():
                results = await google_trends.fetch()
                for symbol, data in results.items():
                    await _store_trends(symbol, data, "google_trends")
                if results:
                    await _publish_update(list(results.keys()), "google_trends")
        except Exception as e:
            COLLECT_ERRORS.labels(source="google_trends").inc()
            logger.error("google_trends_task_error", error=str(e))
        await asyncio.sleep(GOOGLE_TRENDS_INTERVAL)


async def _collect_social_volume():
    """Periodic social volume aggregation task."""
    await asyncio.sleep(60)  # Wait for sentiment service to populate data
    while True:
        try:
            COLLECT_COUNT.labels(source="social_volume").inc()
            r = await _get_redis()
            collector = SocialVolumeCollector(r)
            with PROCESSING_TIME.labels(source="social_volume").time():
                results = await collector.fetch()
                for symbol, data in results.items():
                    await _store_trends(symbol, data, "social_volume")
                if results:
                    await _publish_update(list(results.keys()), "social_volume")
        except Exception as e:
            COLLECT_ERRORS.labels(source="social_volume").inc()
            logger.error("social_volume_task_error", error=str(e))
        await asyncio.sleep(SOCIAL_VOLUME_INTERVAL)


async def _collect_whale_data():
    """Periodic whale transaction tracking task."""
    while True:
        try:
            COLLECT_COUNT.labels(source="whale_tracker").inc()
            with PROCESSING_TIME.labels(source="whale_tracker").time():
                transactions = await whale_tracker.fetch()
                flows = whale_tracker.get_net_flow()

                for symbol, data in flows.items():
                    await _store_trends(symbol, data, "whale_flow")
                    WHALE_FLOW_GAUGE.labels(symbol=symbol).set(data.get("net_flow_score", 0))

                if flows:
                    await _publish_update(list(flows.keys()), "whale_tracker")
        except Exception as e:
            COLLECT_ERRORS.labels(source="whale_tracker").inc()
            logger.error("whale_task_error", error=str(e))
        await asyncio.sleep(WHALE_TRACKER_INTERVAL)


async def _collect_exchange_metrics():
    """Periodic exchange metrics collection task."""
    while True:
        try:
            COLLECT_COUNT.labels(source="exchange_metrics").inc()
            with PROCESSING_TIME.labels(source="exchange_metrics").time():
                results = await exchange_metrics.fetch()
                for pair, metrics in results.items():
                    data = metrics.model_dump()
                    data["timestamp"] = data["timestamp"].isoformat()
                    await _store_trends(pair, data, "exchange_metrics")

                    if metrics.funding_rate is not None:
                        FUNDING_RATE_GAUGE.labels(symbol=pair).set(metrics.funding_rate)

                if results:
                    await _publish_update(list(results.keys()), "exchange_metrics")
        except Exception as e:
            COLLECT_ERRORS.labels(source="exchange_metrics").inc()
            logger.error("exchange_metrics_task_error", error=str(e))
        await asyncio.sleep(EXCHANGE_METRICS_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("trend_service_starting")

    # Connect to DB
    await db.connect()

    # Start background tasks
    tasks = [
        asyncio.create_task(_collect_google_trends()),
        asyncio.create_task(_collect_social_volume()),
        asyncio.create_task(_collect_whale_data()),
        asyncio.create_task(_collect_exchange_metrics()),
    ]
    logger.info("trend_service_started")

    yield

    # Shutdown
    logger.info("trend_service_stopping")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await whale_tracker.close()
    await exchange_metrics.close()
    await db.close()

    global redis_client
    if redis_client:
        await redis_client.aclose()
    logger.info("trend_service_stopped")


app = FastAPI(title="Trend Analysis Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "trend-analysis",
        "tracked_symbols": len(trend_cache),
    }


@app.get("/trends/{symbol}")
async def get_trends(symbol: str):
    """Get all trend data for a specific symbol."""
    r = await _get_redis()
    data = await r.get(f"trends:{symbol}")
    if not data and "/" not in symbol:
        data = await r.get(f"trends:{symbol}/USDT")
    if data:
        return json.loads(data)
    return {"symbol": symbol, "message": "no data"}


@app.get("/trends")
async def get_all_trends():
    """Get trend data for all tracked symbols."""
    r = await _get_redis()
    results = {}
    async for key in r.scan_iter(match="trends:*"):
        data = await r.get(key)
        if data:
            parsed = json.loads(data)
            symbol = parsed.get("symbol", key.replace("trends:", ""))
            results[symbol] = parsed
    return results


@app.get("/whale-alerts")
async def get_whale_alerts():
    """Get recent whale transaction alerts."""
    alerts = whale_tracker.recent_alerts
    flows = whale_tracker.get_net_flow()
    return {
        "recent_alerts": [a.model_dump() for a in alerts],
        "net_flows": flows,
        "count": len(alerts),
    }


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type="text/plain; charset=utf-8")
