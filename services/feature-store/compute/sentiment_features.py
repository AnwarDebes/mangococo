"""
Sentiment-derived features from Redis and TimescaleDB.
Returns sensible defaults (zeros) when no sentiment data is available.
"""
import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog

from db import fetch_sentiment_scores

logger = structlog.get_logger()


def _safe_float(v, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _time_weighted_average(scores: list[dict], decay_hours: float = 6.0) -> float:
    """
    Compute time-weighted average sentiment score.
    More recent scores get higher weight using exponential decay.
    """
    if not scores:
        return 0.0

    now = datetime.now(timezone.utc)
    weighted_sum = 0.0
    weight_sum = 0.0

    for entry in scores:
        t = entry["time"]
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age_hours = (now - t).total_seconds() / 3600.0
        weight = 2.0 ** (-age_hours / decay_hours)
        score = _safe_float(entry.get("score", 0.0))
        weighted_sum += score * weight
        weight_sum += weight

    if weight_sum == 0:
        return 0.0
    return max(-1.0, min(1.0, weighted_sum / weight_sum))


def _sentiment_momentum(scores: list[dict], hours: float) -> float:
    """
    Compute sentiment momentum: rate of change over the given window.
    Positive means sentiment is improving, negative means worsening.
    """
    if len(scores) < 2:
        return 0.0

    now = datetime.now(timezone.utc)
    cutoff_seconds = hours * 3600

    recent = []
    older = []
    for entry in scores:
        t = entry["time"]
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age = (now - t).total_seconds()
        score = _safe_float(entry.get("score", 0.0))
        if age <= cutoff_seconds:
            recent.append(score)
        elif age <= cutoff_seconds * 2:
            older.append(score)

    if not recent or not older:
        return 0.0

    avg_recent = sum(recent) / len(recent)
    avg_older = sum(older) / len(older)
    return max(-1.0, min(1.0, avg_recent - avg_older))


async def compute_sentiment_features(
    symbol: str,
    redis_client: aioredis.Redis,
) -> dict[str, float]:
    """
    Compute sentiment features for a given symbol.
    Reads from Redis keys and TimescaleDB sentiment_scores table.
    Returns zeros/defaults if no sentiment data is available yet.
    """
    features: dict[str, float] = {
        "sentiment_score": 0.0,
        "sentiment_momentum_1h": 0.0,
        "sentiment_momentum_4h": 0.0,
        "sentiment_momentum_24h": 0.0,
        "sentiment_volume": 0.0,
        "fear_greed_index": 50.0,
        "sentiment_divergence": 0.0,
    }

    # Try to read real-time sentiment from Redis
    try:
        raw = await redis_client.get(f"sentiment:{symbol}")
        if raw:
            data = json.loads(raw)
            features["sentiment_score"] = max(
                -1.0, min(1.0, _safe_float(data.get("score", 0.0)))
            )
            features["sentiment_volume"] = _safe_float(data.get("mentions", 0.0))
    except Exception as e:
        logger.debug("No Redis sentiment data", symbol=symbol, error=str(e))

    # Fear & Greed Index from Redis
    try:
        fg_raw = await redis_client.get("fear_greed_index")
        if fg_raw:
            features["fear_greed_index"] = max(0.0, min(100.0, _safe_float(fg_raw)))
    except Exception as e:
        logger.debug("No fear/greed index in Redis", error=str(e))

    # Fetch historical sentiment from TimescaleDB for momentum calculation
    try:
        scores = await fetch_sentiment_scores(symbol, hours=48)
        if scores:
            # Override with time-weighted DB score if available
            features["sentiment_score"] = _time_weighted_average(scores)

            # Momentum at different horizons
            features["sentiment_momentum_1h"] = _sentiment_momentum(scores, 1.0)
            features["sentiment_momentum_4h"] = _sentiment_momentum(scores, 4.0)
            features["sentiment_momentum_24h"] = _sentiment_momentum(scores, 24.0)

            # Sentiment volume (total mentions in last 24h)
            total_mentions = sum(
                _safe_float(s.get("mentions", 0)) for s in scores
            )
            features["sentiment_volume"] = total_mentions

            # Sentiment divergence: news vs social sources
            news_scores = [
                _safe_float(s.get("score", 0))
                for s in scores
                if s.get("source", "").startswith("news")
            ]
            social_scores = [
                _safe_float(s.get("score", 0))
                for s in scores
                if s.get("source", "").startswith("social")
            ]
            if news_scores and social_scores:
                avg_news = sum(news_scores) / len(news_scores)
                avg_social = sum(social_scores) / len(social_scores)
                features["sentiment_divergence"] = max(
                    -1.0, min(1.0, avg_news - avg_social)
                )
    except Exception as e:
        logger.debug("No TimescaleDB sentiment data", symbol=symbol, error=str(e))

    return features
