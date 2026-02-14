"""
Fetch sentiment features from the feature-store service or Redis.

Returns a flat dict of sentiment-related features normalised to [-1, 1] or [0, 100].
"""

import json
from typing import Dict, Optional

import httpx
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

FEATURE_STORE_URL = "http://feature-store:8003"

SENTIMENT_KEYS = [
    "sentiment_score",
    "sentiment_momentum_1h",
    "sentiment_momentum_4h",
    "sentiment_momentum_24h",
    "sentiment_volume",
    "fear_greed_index",
]


def _defaults() -> Dict[str, float]:
    return {k: 0.0 for k in SENTIMENT_KEYS}


async def fetch_sentiment_features(
    symbol: str,
    redis_client: Optional[aioredis.Redis] = None,
    feature_store_url: Optional[str] = None,
) -> Dict[str, float]:
    """
    Fetch sentiment features for *symbol*.

    Strategy:
    1. Try the feature-store REST endpoint ``GET /features/{symbol}``.
    2. Fall back to Redis hash ``sentiment:{symbol}``.
    3. Return zeros on failure.
    """
    url = feature_store_url or FEATURE_STORE_URL

    # Attempt 1: feature-store HTTP
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{url}/features/{symbol}")
            if resp.status_code == 200:
                data = resp.json()
                return {k: float(data.get(k, 0.0)) for k in SENTIMENT_KEYS}
    except Exception:
        pass

    # Attempt 2: Redis
    if redis_client is not None:
        try:
            raw = await redis_client.hgetall(f"sentiment:{symbol}")
            if raw:
                return {k: float(raw.get(k, 0.0)) for k in SENTIMENT_KEYS}
        except Exception:
            pass

    logger.debug("Sentiment features unavailable, returning defaults", symbol=symbol)
    return _defaults()
