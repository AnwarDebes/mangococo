"""
Database layer for the Portfolio Optimizer service.
Manages asyncpg connection pool and provides access to trade history,
candle data, and optimization result storage in TimescaleDB.
"""
import json
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
    await _ensure_tables()
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


async def _ensure_tables():
    """Create optimization results table if it does not exist."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS optimization_results (
                    time            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    portfolio_value DOUBLE PRECISION,
                    allocations     JSONB NOT NULL,
                    kelly_fractions JSONB,
                    metadata        JSONB
                );
                """
            )
            try:
                await conn.execute(
                    "SELECT create_hypertable('optimization_results', 'time', if_not_exists => TRUE);"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error("Failed to ensure optimization_results table", error=str(e))


async def fetch_trade_performance(symbol: str, lookback_days: int = 30) -> dict:
    """
    Get historical trade performance for a symbol.
    Returns dict with win_rate, avg_win, avg_loss, total_trades.
    """
    if not _pool:
        return {"win_rate": 0.5, "avg_win": 0.01, "avg_loss": 0.01, "total_trades": 0}

    try:
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        async with _pool.acquire() as conn:
            # Try the trades table first (position service writes here)
            rows = await conn.fetch(
                """
                SELECT pnl FROM trades
                WHERE symbol = $1 AND closed_at >= $2 AND pnl IS NOT NULL
                ORDER BY closed_at DESC
                """,
                symbol,
                since,
            )

        if not rows:
            return {"win_rate": 0.5, "avg_win": 0.01, "avg_loss": 0.01, "total_trades": 0}

        wins = [r["pnl"] for r in rows if r["pnl"] > 0]
        losses = [abs(r["pnl"]) for r in rows if r["pnl"] <= 0]
        total = len(rows)
        win_rate = len(wins) / total if total > 0 else 0.5
        avg_win = sum(wins) / len(wins) if wins else 0.01
        avg_loss = sum(losses) / len(losses) if losses else 0.01

        return {
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "total_trades": total,
        }
    except asyncpg.UndefinedTableError:
        logger.warning("trades table does not exist yet", symbol=symbol)
        return {"win_rate": 0.5, "avg_win": 0.01, "avg_loss": 0.01, "total_trades": 0}
    except Exception as e:
        logger.error("Failed to fetch trade performance", symbol=symbol, error=str(e))
        return {"win_rate": 0.5, "avg_win": 0.01, "avg_loss": 0.01, "total_trades": 0}


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
        return [
            {
                "time": row["time"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            for row in reversed(rows)
        ]
    except Exception as e:
        logger.error("Failed to fetch candles", symbol=symbol, error=str(e))
        return []


async def fetch_candles_multi(
    symbols: list[str],
    timeframe: str = "1m",
    limit: int = 200,
) -> dict[str, list[dict]]:
    """Fetch candles for multiple symbols. Returns {symbol: [candle_dicts]}."""
    result = {}
    for sym in symbols:
        result[sym] = await fetch_candles(sym, timeframe, limit)
    return result


async def store_optimization_result(
    portfolio_value: float,
    allocations: dict,
    kelly_fractions: dict | None = None,
    metadata: dict | None = None,
):
    """Persist an optimization snapshot to TimescaleDB."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO optimization_results (portfolio_value, allocations, kelly_fractions, metadata)
                VALUES ($1, $2::jsonb, $3::jsonb, $4::jsonb)
                """,
                portfolio_value,
                json.dumps(allocations),
                json.dumps(kelly_fractions) if kelly_fractions else None,
                json.dumps(metadata) if metadata else None,
            )
    except Exception as e:
        logger.error("Failed to store optimization result", error=str(e))
