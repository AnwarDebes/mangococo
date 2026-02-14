"""
Database layer for the Feature Store service.
Manages asyncpg connection pool and provides read access
to candles and sentiment data in TimescaleDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import structlog

logger = structlog.get_logger()

# Configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "timescaledb")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "mangococo")
POSTGRES_USER = os.getenv("POSTGRES_USER", "mangococo")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> asyncpg.Pool:
    """Create and return the asyncpg connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        min_size=2,
        max_size=10,
    )
    logger.info("TimescaleDB pool initialized", host=POSTGRES_HOST, db=POSTGRES_DB)
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("TimescaleDB pool closed")


def get_pool() -> Optional[asyncpg.Pool]:
    """Return the current pool (may be None if not initialized)."""
    return _pool


async def fetch_candles(
    symbol: str,
    timeframe: str = "1m",
    limit: int = 200,
) -> list[dict]:
    """
    Fetch the most recent candles for a symbol and timeframe.
    Returns list of dicts with keys: time, open, high, low, close, volume.
    """
    if not _pool:
        return []

    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, open, high, low, close, volume
                FROM candles
                WHERE symbol = $1 AND timeframe = $2
                ORDER BY time DESC
                LIMIT $3
                """,
                symbol,
                timeframe,
                limit,
            )
        # Return in chronological order (oldest first)
        return [
            {
                "time": row["time"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for row in reversed(rows)
        ]
    except Exception as e:
        logger.error("Failed to fetch candles", symbol=symbol, error=str(e))
        return []


async def fetch_sentiment_scores(
    symbol: str,
    hours: int = 24,
) -> list[dict]:
    """
    Fetch sentiment scores for a symbol over the last N hours.
    Returns list of dicts with keys: time, source, score, mentions.
    """
    if not _pool:
        return []

    try:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, source, score, mentions
                FROM sentiment_scores
                WHERE symbol = $1 AND time >= $2
                ORDER BY time ASC
                """,
                symbol,
                since,
            )
        return [
            {
                "time": row["time"],
                "source": row["source"],
                "score": row["score"],
                "mentions": row["mentions"],
            }
            for row in rows
        ]
    except asyncpg.UndefinedTableError:
        # Table doesn't exist yet - sentiment pipeline not deployed
        return []
    except Exception as e:
        logger.error("Failed to fetch sentiment scores", symbol=symbol, error=str(e))
        return []


async def store_features(
    symbol: str,
    features: dict,
):
    """
    Persist a computed feature vector to TimescaleDB for historical analysis.
    """
    if not _pool:
        return

    try:
        import json

        async with _pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_vectors (
                    time        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    symbol      TEXT NOT NULL,
                    features    JSONB NOT NULL
                );
                """,
            )
            # Try to make it a hypertable (idempotent)
            try:
                await conn.execute(
                    "SELECT create_hypertable('feature_vectors', 'time', if_not_exists => TRUE);"
                )
            except Exception:
                pass

            await conn.execute(
                """
                INSERT INTO feature_vectors (symbol, features)
                VALUES ($1, $2::jsonb)
                """,
                symbol,
                json.dumps(features),
            )
    except Exception as e:
        logger.error("Failed to store features", symbol=symbol, error=str(e))
