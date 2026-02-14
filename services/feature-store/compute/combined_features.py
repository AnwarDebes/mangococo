"""
Combines technical and sentiment features into a unified feature vector.
Applies normalization where applicable.
"""
import redis.asyncio as aioredis

from .technical_features import compute_technical_features
from .sentiment_features import compute_sentiment_features


# Normalization ranges: (min_val, max_val) for mapping to 0-1
# Features not listed here are passed through as-is.
NORMALIZE_RANGES: dict[str, tuple[float, float]] = {
    "rsi_14": (0.0, 100.0),
    "rsi_7": (0.0, 100.0),
    "bb_percent_b": (-0.5, 1.5),  # Can exceed 0-1 in extreme moves
    "bb_bandwidth": (0.0, 0.5),
    "atr_pct": (0.0, 10.0),
    "stoch_rsi_k": (0.0, 100.0),
    "stoch_rsi_d": (0.0, 100.0),
    "williams_r": (-100.0, 0.0),
    "volume_ratio": (0.0, 5.0),
    "momentum_5m": (-5.0, 5.0),
    "momentum_15m": (-10.0, 10.0),
    "momentum_30m": (-15.0, 15.0),
    "momentum_60m": (-20.0, 20.0),
    "bid_ask_spread_pct": (0.0, 2.0),
    "vwap_deviation_pct": (-5.0, 5.0),
    "ema_cross_9_21": (-2.0, 2.0),
    "ema_cross_25_50": (-3.0, 3.0),
    "obv_trend": (-1.0, 1.0),
    "macd_histogram": (-0.01, 0.01),  # Relative to price
    "macd_signal": (-0.01, 0.01),
    "macd_line": (-0.01, 0.01),
    # Sentiment features
    "sentiment_score": (-1.0, 1.0),
    "sentiment_momentum_1h": (-1.0, 1.0),
    "sentiment_momentum_4h": (-1.0, 1.0),
    "sentiment_momentum_24h": (-1.0, 1.0),
    "sentiment_volume": (0.0, 1000.0),
    "fear_greed_index": (0.0, 100.0),
    "sentiment_divergence": (-1.0, 1.0),
}


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize a value to 0-1 range, clamping at boundaries."""
    if max_val == min_val:
        return 0.5
    normalized = (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, normalized))


async def compute_combined_features(
    symbol: str,
    redis_client: aioredis.Redis,
) -> dict[str, float]:
    """
    Compute the full feature vector for a symbol by merging
    technical and sentiment features, then normalizing to 0-1.

    Returns both raw and normalized features:
    - Raw features keyed as their original names
    - Normalized features keyed as "{name}_norm"
    """
    # Compute both feature sets
    technical = await compute_technical_features(symbol, redis_client)
    sentiment = await compute_sentiment_features(symbol, redis_client)

    # Merge into one dict (raw values)
    raw_features: dict[str, float] = {}
    raw_features.update(technical)
    raw_features.update(sentiment)

    # Build combined dict with both raw and normalized
    combined: dict[str, float] = {}
    for name, value in raw_features.items():
        combined[name] = value
        # Add normalized version
        if name in NORMALIZE_RANGES:
            min_val, max_val = NORMALIZE_RANGES[name]
            combined[f"{name}_norm"] = _normalize(value, min_val, max_val)

    return combined
