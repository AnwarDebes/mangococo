"""
Load historical data from TimescaleDB and prepare training datasets.

Responsibilities:
  - Load candles and sentiment from the ``candles`` / ``sentiment`` hypertables.
  - Generate forward-looking return labels at multiple horizons.
  - Map continuous returns to discrete 5-class targets.
  - Provide train / val / test splits (time-ordered, no shuffling).
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import asyncpg
import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

DB_DSN = os.getenv("TIMESCALEDB_DSN", "postgresql://postgres:postgres@timescaledb:5432/mangococo")

# Class thresholds (percentage return)
STRONG_BUY_THRESHOLD = 0.5
BUY_THRESHOLD = 0.1
SELL_THRESHOLD = -0.1
STRONG_SELL_THRESHOLD = -0.5

CLASS_LABELS = ["strong_sell", "sell", "hold", "buy", "strong_buy"]


def _return_to_class(ret_pct: float) -> int:
    """Map a percentage return to class index (0-4)."""
    if ret_pct <= STRONG_SELL_THRESHOLD:
        return 0  # strong_sell
    if ret_pct <= SELL_THRESHOLD:
        return 1  # sell
    if ret_pct < BUY_THRESHOLD:
        return 2  # hold
    if ret_pct < STRONG_BUY_THRESHOLD:
        return 3  # buy
    return 4  # strong_buy


class DataLoader:
    """Async loader that reads from TimescaleDB and builds training datasets."""

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or DB_DSN
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Candle data
    # ------------------------------------------------------------------

    async def load_candles(
        self,
        symbol: str,
        days: int = 90,
        interval: str = "1m",
    ) -> pd.DataFrame:
        """
        Load OHLCV candles from TimescaleDB.

        Returns DataFrame with columns: timestamp, open, high, low, close, volume.
        """
        await self.connect()
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
            SELECT time AS timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = $1 AND interval = $2 AND time >= $3
            ORDER BY time ASC
        """
        rows = await self._pool.fetch(query, symbol, interval, since)
        if not rows:
            logger.warning("No candle data returned", symbol=symbol, days=days)
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame([dict(r) for r in rows])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    # ------------------------------------------------------------------
    # Sentiment data
    # ------------------------------------------------------------------

    async def load_sentiment(
        self,
        symbol: str,
        days: int = 90,
    ) -> pd.DataFrame:
        """Load historical sentiment scores."""
        await self.connect()
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
            SELECT time AS timestamp, sentiment_score, fear_greed_index
            FROM sentiment
            WHERE symbol = $1 AND time >= $2
            ORDER BY time ASC
        """
        rows = await self._pool.fetch(query, symbol, since)
        if not rows:
            return pd.DataFrame(columns=["timestamp", "sentiment_score", "fear_greed_index"])
        df = pd.DataFrame([dict(r) for r in rows])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    # ------------------------------------------------------------------
    # Label generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_labels(
        df: pd.DataFrame,
        horizons: Optional[List[int]] = None,
    ) -> pd.DataFrame:
        """
        Add forward-return columns and a target class column.

        Parameters
        ----------
        df : DataFrame with a ``close`` column.
        horizons : list of int lookforward periods (default [5, 15, 30]).

        Returns
        -------
        DataFrame with extra columns:
          future_return_5m, future_return_15m, future_return_30m, target
        """
        horizons = horizons or [5, 15, 30]
        close = df["close"].astype(float)

        for h in horizons:
            col = f"future_return_{h}m"
            df[col] = (close.shift(-h) - close) / close * 100

        # Primary target: 15-minute horizon
        primary = "future_return_15m" if "future_return_15m" in df.columns else f"future_return_{horizons[0]}m"
        df["target"] = df[primary].apply(lambda r: _return_to_class(r) if pd.notna(r) else np.nan)

        # Drop rows where label is NaN (end of series)
        df = df.dropna(subset=["target"])
        df["target"] = df["target"].astype(int)
        return df

    # ------------------------------------------------------------------
    # Train / val / test splits
    # ------------------------------------------------------------------

    @staticmethod
    def split(
        df: pd.DataFrame,
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Time-ordered split (no shuffling to prevent look-ahead bias).
        """
        n = len(df)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))
        return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]
