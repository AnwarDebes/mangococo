"""
Historical OHLCV data backfill script for MEXC -> TimescaleDB.

Downloads candle data for specified symbols and timeframes,
with resume capability and rate limiting.
"""
import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import asyncpg
import ccxt
from tqdm import tqdm


# MEXC rate limit: be conservative
RATE_LIMIT_DELAY = 0.35  # seconds between API calls
BATCH_INSERT_SIZE = 1000
MAX_CANDLES_PER_REQUEST = 1000  # MEXC limit
MAX_RATE_LIMIT_RETRIES = 5  # Max retries before skipping symbol


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill OHLCV candle data from MEXC into TimescaleDB"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTC/USDT,ETH/USDT,SOL/USDT",
        help='Comma-separated symbols or "topN" (e.g. "top100") to fetch top N by volume',
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        default="1m",
        help="Comma-separated timeframes: 1m,5m,15m,1h,4h,1d",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Number of days to backfill (default: 180)",
    )
    parser.add_argument(
        "--db-host",
        type=str,
        default=os.getenv("POSTGRES_HOST", "localhost"),
    )
    parser.add_argument(
        "--db-port",
        type=int,
        default=int(os.getenv("POSTGRES_PORT", 5432)),
    )
    parser.add_argument(
        "--db-name",
        type=str,
        default=os.getenv("POSTGRES_DB", "mangococo"),
    )
    parser.add_argument(
        "--db-user",
        type=str,
        default=os.getenv("POSTGRES_USER", "mangococo"),
    )
    parser.add_argument(
        "--db-password",
        type=str,
        default=os.getenv("POSTGRES_PASSWORD", ""),
    )
    return parser.parse_args()


TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

VALID_TIMEFRAMES = list(TIMEFRAME_MS.keys())


async def ensure_table(pool: asyncpg.Pool):
    """Create candles table and hypertable if they don't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                time        TIMESTAMPTZ NOT NULL,
                symbol      TEXT NOT NULL,
                timeframe   TEXT NOT NULL,
                open        DOUBLE PRECISION NOT NULL,
                high        DOUBLE PRECISION NOT NULL,
                low         DOUBLE PRECISION NOT NULL,
                close       DOUBLE PRECISION NOT NULL,
                volume      DOUBLE PRECISION NOT NULL
            );
        """)
        # Try to create hypertable (idempotent with if_not_exists)
        try:
            await conn.execute("""
                SELECT create_hypertable('candles', 'time',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            """)
        except Exception:
            pass  # Table may already be a hypertable or TimescaleDB not installed

        # Create unique index for upsert support
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS candles_unique_idx
            ON candles (time, symbol, timeframe);
        """)


async def get_last_timestamp(
    pool: asyncpg.Pool, symbol: str, timeframe: str
) -> int | None:
    """Get the last candle timestamp in the DB for resume capability."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT EXTRACT(EPOCH FROM MAX(time))::BIGINT * 1000 AS last_ms
            FROM candles
            WHERE symbol = $1 AND timeframe = $2
            """,
            symbol,
            timeframe,
        )
        if row and row["last_ms"] is not None:
            return int(row["last_ms"])
    return None


async def insert_candles(
    pool: asyncpg.Pool,
    rows: list[tuple],
):
    """Batch insert candles with ON CONFLICT DO NOTHING."""
    if not rows:
        return 0

    async with pool.acquire() as conn:
        result = await conn.executemany(
            """
            INSERT INTO candles (time, symbol, timeframe, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (time, symbol, timeframe) DO NOTHING
            """,
            rows,
        )
    return len(rows)


def fetch_top_symbols(exchange: ccxt.mexc, n: int) -> list[str]:
    """Fetch top N USDT spot symbols by 24h quote volume."""
    print(f"Fetching top {n} symbols by volume from MEXC...")
    tickers = exchange.fetch_tickers()
    exchange.load_markets()

    usdt_tickers = []
    for symbol, ticker in tickers.items():
        market = exchange.markets.get(symbol)
        if not market:
            continue
        if market.get("quote") != "USDT" or not market.get("spot", True):
            continue
        vol = ticker.get("quoteVolume") or 0
        usdt_tickers.append((symbol, vol))

    usdt_tickers.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in usdt_tickers[:n]]
    print(f"Selected {len(symbols)} symbols (top by volume)")
    return symbols


async def backfill_symbol_timeframe(
    exchange: ccxt.mexc,
    pool: asyncpg.Pool,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    pbar: tqdm,
):
    """Download and store candles for one symbol+timeframe combination."""
    tf_ms = TIMEFRAME_MS[timeframe]

    # Check for resume point
    last_ts = await get_last_timestamp(pool, symbol, timeframe)
    if last_ts is not None and last_ts >= start_ms:
        # Resume from next candle after last stored
        current_ms = last_ts + tf_ms
        skipped = (current_ms - start_ms) // tf_ms
        pbar.update(skipped)
    else:
        current_ms = start_ms

    if current_ms >= end_ms:
        pbar.update(pbar.total - pbar.n)
        return

    batch_rows = []
    total_inserted = 0

    while current_ms < end_ms:
        try:
            candles = await asyncio.to_thread(
                exchange.fetch_ohlcv,
                symbol,
                timeframe,
                since=current_ms,
                limit=MAX_CANDLES_PER_REQUEST,
            )
        except ccxt.RateLimitExceeded:
            print(f"\nRate limited on {symbol} {timeframe}, waiting 10s...")
            await asyncio.sleep(10)
            continue
        except ccxt.NetworkError as e:
            print(f"\nNetwork error on {symbol} {timeframe}: {e}, retrying in 5s...")
            await asyncio.sleep(5)
            continue
        except Exception as e:
            print(f"\nError fetching {symbol} {timeframe}: {e}, skipping batch")
            current_ms += tf_ms * MAX_CANDLES_PER_REQUEST
            continue

        if not candles:
            break

        for c in candles:
            ts_ms, o, h, l, cl, vol = c[0], c[1], c[2], c[3], c[4], c[5]
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            batch_rows.append((dt, symbol, timeframe, o, h, l, cl, vol or 0.0))

        # Advance past the last candle we received
        last_candle_ms = candles[-1][0]
        new_ms = last_candle_ms + tf_ms
        candles_advanced = max(1, (new_ms - current_ms) // tf_ms)
        pbar.update(candles_advanced)
        current_ms = new_ms

        # Flush batch
        if len(batch_rows) >= BATCH_INSERT_SIZE:
            await insert_candles(pool, batch_rows)
            total_inserted += len(batch_rows)
            batch_rows = []

        # Rate limiting
        await asyncio.sleep(RATE_LIMIT_DELAY)

    # Final flush
    if batch_rows:
        await insert_candles(pool, batch_rows)
        total_inserted += len(batch_rows)

    return total_inserted


async def main():
    args = parse_args()

    # Parse timeframes
    timeframes = [tf.strip() for tf in args.timeframes.split(",")]
    for tf in timeframes:
        if tf not in VALID_TIMEFRAMES:
            print(f"Invalid timeframe: {tf}. Valid: {VALID_TIMEFRAMES}")
            sys.exit(1)

    # Initialize exchange
    exchange = ccxt.mexc({"enableRateLimit": True})

    # Resolve symbols
    symbols_arg = args.symbols.strip()
    if symbols_arg.lower().startswith("top"):
        try:
            n = int(symbols_arg[3:])
        except ValueError:
            print(f"Invalid top-N format: {symbols_arg}. Use e.g. 'top100'")
            sys.exit(1)
        symbols = fetch_top_symbols(exchange, n)
    else:
        symbols = [s.strip() for s in symbols_arg.split(",") if s.strip()]

    if not symbols:
        print("No symbols to process.")
        sys.exit(1)

    # Connect to TimescaleDB
    print(f"Connecting to TimescaleDB at {args.db_host}:{args.db_port}/{args.db_name}...")
    pool = await asyncpg.create_pool(
        host=args.db_host,
        port=args.db_port,
        database=args.db_name,
        user=args.db_user,
        password=args.db_password,
        min_size=2,
        max_size=10,
    )

    await ensure_table(pool)

    # Time range
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.days)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    print(f"\nBackfill Configuration:")
    print(f"  Symbols:    {len(symbols)} ({symbols[0]}...{symbols[-1] if len(symbols) > 1 else ''})")
    print(f"  Timeframes: {timeframes}")
    print(f"  Period:     {start_dt.date()} -> {end_dt.date()} ({args.days} days)")
    print()

    total_tasks = len(symbols) * len(timeframes)
    completed = 0
    start_time = time.time()

    for symbol in symbols:
        for tf in timeframes:
            tf_ms = TIMEFRAME_MS[tf]
            total_candles = (end_ms - start_ms) // tf_ms

            desc = f"{symbol} {tf}"
            with tqdm(total=total_candles, desc=desc, unit="candles", leave=False) as pbar:
                try:
                    inserted = await backfill_symbol_timeframe(
                        exchange, pool, symbol, tf, start_ms, end_ms, pbar
                    )
                except Exception as e:
                    print(f"\nFailed {symbol} {tf}: {e}")
                    continue

            completed += 1
            elapsed = time.time() - start_time
            rate = completed / elapsed if elapsed > 0 else 0
            remaining = (total_tasks - completed) / rate if rate > 0 else 0
            print(
                f"  [{completed}/{total_tasks}] {symbol} {tf} done "
                f"(~{remaining:.0f}s remaining)"
            )

    await pool.close()
    exchange.close()

    elapsed = time.time() - start_time
    print(f"\nBackfill complete in {elapsed:.1f}s ({completed}/{total_tasks} tasks)")


if __name__ == "__main__":
    asyncio.run(main())
