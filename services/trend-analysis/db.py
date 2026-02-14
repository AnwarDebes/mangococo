"""
Database layer for trend analysis - asyncpg pool for TimescaleDB writes.
"""
import os
from datetime import datetime
from typing import List, Optional, Tuple

import asyncpg
import structlog

logger = structlog.get_logger()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "timescaledb")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "mangococo")
POSTGRES_USER = os.getenv("POSTGRES_USER", "mangococo")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
DB_ENABLED = os.getenv("DB_ENABLED", "true").lower() == "true"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS onchain_metrics (
    time                TIMESTAMPTZ NOT NULL,
    symbol              TEXT NOT NULL,
    metric_type         TEXT NOT NULL,
    value               DOUBLE PRECISION NOT NULL,
    metadata            JSONB
);

SELECT create_hypertable('onchain_metrics', 'time', if_not_exists => TRUE);
"""

INSERT_SQL = """
INSERT INTO onchain_metrics (time, symbol, metric_type, value, metadata)
VALUES ($1, $2, $3, $4, $5)
"""


class TrendDB:
    """Manages asyncpg connection pool for writing onchain/trend metrics."""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create connection pool and ensure table exists."""
        if not DB_ENABLED:
            logger.info("db_disabled")
            return

        try:
            self._pool = await asyncpg.create_pool(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                database=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                min_size=2,
                max_size=10,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
            logger.info("trend_db_connected")
        except Exception as e:
            logger.error("trend_db_connect_error", error=str(e))
            self._pool = None

    async def close(self):
        if self._pool:
            await self._pool.close()

    async def batch_insert(
        self,
        records: List[Tuple[datetime, str, str, float, Optional[str]]],
    ):
        """Batch insert metric records.

        Each record is: (time, symbol, metric_type, value, metadata_json)
        """
        if not self._pool or not records:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(INSERT_SQL, records)
            logger.info("trend_db_inserted", count=len(records))
        except Exception as e:
            logger.error("trend_db_insert_error", error=str(e), count=len(records))
