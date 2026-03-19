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

# Module-level shared HTTP client — avoids creating a new TCP connection per call.
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=2.0)
    return _http_client


def _defaults() -> Dict[str, float]:
    d = {k: 0.0 for k in SENTIMENT_KEYS}
    d["_source"] = "default"
    return d


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
    client = _get_http_client()

    # Attempt 1: feature-store HTTP (single attempt, short timeout)
    try:
        resp = await client.get(f"{url}/features/{symbol}")
        if resp.status_code == 200:
            data = resp.json()
            result = {k: float(data.get(k, 0.0)) for k in SENTIMENT_KEYS}
            result["_source"] = "feature_store"
            return result
    except Exception:
        pass

    # Attempt 2: Redis
    if redis_client is not None:
        try:
            raw = await redis_client.hgetall(f"sentiment:{symbol}")
            if raw:
                result = {k: float(raw.get(k, 0.0)) for k in SENTIMENT_KEYS}
                result["_source"] = "redis"
                return result
        except Exception:
            pass

    return _defaults()
