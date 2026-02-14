"""
Database layer for the Backtesting service.
Manages asyncpg connection pool and provides CRUD operations
for backtest runs and trade records in TimescaleDB.
"""
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


async def ensure_tables():
    """Create backtest-specific tables if they do not exist."""
    if not _pool:
        return

    async with _pool.acquire() as conn:
        # backtest_runs may already exist from init-db.sql, but be safe
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id SERIAL PRIMARY KEY,
                strategy_name TEXT NOT NULL,
                symbols TEXT[] NOT NULL,
                start_date TIMESTAMPTZ NOT NULL,
                end_date TIMESTAMPTZ NOT NULL,
                initial_capital DOUBLE PRECISION DEFAULT 10000,
                final_capital DOUBLE PRECISION,
                total_trades INT,
                win_rate DOUBLE PRECISION,
                sharpe_ratio DOUBLE PRECISION,
                max_drawdown DOUBLE PRECISION,
                profit_factor DOUBLE PRECISION,
                params JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # Individual trade records for detailed analysis
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id SERIAL PRIMARY KEY,
                run_id INT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_time TIMESTAMPTZ NOT NULL,
                exit_time TIMESTAMPTZ,
                entry_price DOUBLE PRECISION NOT NULL,
                exit_price DOUBLE PRECISION,
                quantity DOUBLE PRECISION NOT NULL,
                pnl DOUBLE PRECISION DEFAULT 0,
                pnl_pct DOUBLE PRECISION DEFAULT 0,
                fees DOUBLE PRECISION DEFAULT 0,
                slippage DOUBLE PRECISION DEFAULT 0,
                signal_confidence DOUBLE PRECISION DEFAULT 0
            );
        """)

        # Equity curve snapshots
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_equity (
                id SERIAL PRIMARY KEY,
                run_id INT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
                timestamp TIMESTAMPTZ NOT NULL,
                equity DOUBLE PRECISION NOT NULL,
                drawdown DOUBLE PRECISION DEFAULT 0,
                positions_open INT DEFAULT 0
            );
        """)

    logger.info("Backtest tables ensured")


# ---------------------------------------------------------------------------
# Backtest run CRUD
# ---------------------------------------------------------------------------

async def create_run(
    strategy_name: str,
    symbols: List[str],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    params: Optional[Dict[str, Any]] = None,
) -> int:
    """Insert a new backtest run and return its id."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO backtest_runs
                (strategy_name, symbols, start_date, end_date, initial_capital, params)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING id
            """,
            strategy_name,
            symbols,
            start_date,
            end_date,
            initial_capital,
            json.dumps(params) if params else None,
        )
    return row["id"]


async def update_run_results(
    run_id: int,
    final_capital: float,
    total_trades: int,
    win_rate: float,
    sharpe_ratio: float,
    max_drawdown: float,
    profit_factor: float,
):
    """Update a backtest run with computed results."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE backtest_runs
            SET final_capital = $2,
                total_trades = $3,
                win_rate = $4,
                sharpe_ratio = $5,
                max_drawdown = $6,
                profit_factor = $7
            WHERE id = $1
            """,
            run_id,
            final_capital,
            total_trades,
            win_rate,
            sharpe_ratio,
            max_drawdown,
            profit_factor,
        )


async def get_run(run_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single backtest run by id."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM backtest_runs WHERE id = $1", run_id
        )
    if row is None:
        return None
    return dict(row)


async def list_runs(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """List backtest runs ordered by creation time descending."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM backtest_runs
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Trade records
# ---------------------------------------------------------------------------

async def insert_trades(run_id: int, trades: List[Dict[str, Any]]):
    """Bulk-insert trade records for a backtest run."""
    if not trades:
        return

    async with _pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO backtest_trades
                (run_id, symbol, side, entry_time, exit_time,
                 entry_price, exit_price, quantity, pnl, pnl_pct, fees,
                 slippage, signal_confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
            [
                (
                    run_id,
                    t["symbol"],
                    t["side"],
                    t["entry_time"],
                    t.get("exit_time"),
                    t["entry_price"],
                    t.get("exit_price"),
                    t["quantity"],
                    t.get("pnl", 0),
                    t.get("pnl_pct", 0),
                    t.get("fees", 0),
                    t.get("slippage", 0),
                    t.get("signal_confidence", 0),
                )
                for t in trades
            ],
        )


async def get_trades(run_id: int) -> List[Dict[str, Any]]:
    """Fetch all trades for a backtest run."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM backtest_trades
            WHERE run_id = $1
            ORDER BY entry_time ASC
            """,
            run_id,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------

async def insert_equity_points(run_id: int, points: List[Dict[str, Any]]):
    """Bulk-insert equity curve data points."""
    if not points:
        return

    async with _pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO backtest_equity (run_id, timestamp, equity, drawdown, positions_open)
            VALUES ($1, $2, $3, $4, $5)
            """,
            [
                (
                    run_id,
                    p["timestamp"],
                    p["equity"],
                    p.get("drawdown", 0),
                    p.get("positions_open", 0),
                )
                for p in points
            ],
        )


async def get_equity_curve(run_id: int) -> List[Dict[str, Any]]:
    """Fetch equity curve for a backtest run."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT timestamp, equity, drawdown, positions_open
            FROM backtest_equity
            WHERE run_id = $1
            ORDER BY timestamp ASC
            """,
            run_id,
        )
    return [dict(r) for r in rows]
