"""
Fetch on-chain features from the feature-store service or Redis.

Returns a flat dict of on-chain metrics normalised for model consumption.
"""

import json
from typing import Dict, Optional

import httpx
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

FEATURE_STORE_URL = "http://feature-store:8003"

ONCHAIN_KEYS = [
    "whale_activity_score",
    "exchange_netflow",
    "funding_rate",
    "google_trends_score",
    "social_volume_zscore",
]


def _defaults() -> Dict[str, float]:
    return {k: 0.0 for k in ONCHAIN_KEYS}


async def fetch_onchain_features(
    symbol: str,
    redis_client: Optional[aioredis.Redis] = None,
    feature_store_url: Optional[str] = None,
) -> Dict[str, float]:
    """
    Fetch on-chain features for *symbol*.

    Strategy:
    1. Try the feature-store REST endpoint ``GET /features/{symbol}``.
    2. Fall back to Redis hash ``onchain:{symbol}``.
    3. Return zeros on failure.
    """
    url = feature_store_url or FEATURE_STORE_URL

    # Attempt 1: feature-store HTTP
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{url}/features/{symbol}")
            if resp.status_code == 200:
                data = resp.json()
                return {k: float(data.get(k, 0.0)) for k in ONCHAIN_KEYS}
    except Exception:
        pass

    # Attempt 2: Redis
    if redis_client is not None:
        try:
            raw = await redis_client.hgetall(f"onchain:{symbol}")
            if raw:
                return {k: float(raw.get(k, 0.0)) for k in ONCHAIN_KEYS}
        except Exception:
            pass

    logger.debug("On-chain features unavailable, returning defaults", symbol=symbol)
    return _defaults()
