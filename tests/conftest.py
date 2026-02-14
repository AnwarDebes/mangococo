"""
Shared pytest fixtures for the MangoCoco test suite.

All fixtures are self-contained and do not require running services.
Redis is mocked via an in-memory dict-based stub, and the database pool
is a lightweight AsyncMock.
"""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Redis mock -- lightweight async dict-based stub
# ---------------------------------------------------------------------------

class FakeRedis:
    """Minimal async Redis mock backed by plain dicts.

    Supports the subset of commands used across MangoCoco services:
    get / set / hget / hset / hgetall / publish / delete / pubsub.
    """

    def __init__(self):
        self._store: Dict[str, str] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._published: list = []  # (channel, message) pairs

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str, **kwargs) -> None:
        self._store[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)

    async def hget(self, name: str, key: str) -> Optional[str]:
        return self._hashes.get(name, {}).get(key)

    async def hset(self, name: str, key: str, value: str) -> None:
        self._hashes.setdefault(name, {})[key] = value

    async def hgetall(self, name: str) -> Dict[str, str]:
        return self._hashes.get(name, {}).copy()

    async def publish(self, channel: str, message: str) -> int:
        self._published.append((channel, message))
        return 1

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass

    async def info(self, section: str = "") -> dict:
        return {"used_memory_human": "1M", "connected_clients": 1}

    def pubsub(self):
        return FakePubSub()


class FakePubSub:
    """Minimal pubsub stub so integration-style wiring does not crash."""

    def __init__(self):
        self._channels: list = []

    async def subscribe(self, *channels: str) -> None:
        self._channels.extend(channels)

    async def psubscribe(self, *patterns: str) -> None:
        self._channels.extend(patterns)

    async def unsubscribe(self, *channels: str) -> None:
        pass

    async def close(self) -> None:
        pass

    async def listen(self):
        # Yields nothing -- tests that need messages should push them manually.
        return
        yield  # pragma: no cover – makes this an async generator

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        return None


@pytest.fixture
def mock_redis():
    """Return a fresh FakeRedis instance."""
    return FakeRedis()


# ---------------------------------------------------------------------------
# Database pool mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_pool():
    """Return an AsyncMock that mimics an asyncpg connection pool.

    Usage in tests:
        pool = mock_db_pool
        pool.acquire().__aenter__.return_value.fetch.return_value = [...]
    """
    pool = AsyncMock()
    conn = AsyncMock()

    # Make ``async with pool.acquire() as conn`` work
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    # Expose the connection for easy assertion setup
    pool._mock_conn = conn
    return pool


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_tick_data():
    """Sample tick data for BTC/USDT and ETH/USDT."""
    now = datetime.utcnow().isoformat()
    return {
        "BTC/USDT": {
            "symbol": "BTC/USDT",
            "timestamp": now,
            "price": 43250.50,
            "bid": 43250.00,
            "ask": 43251.00,
            "volume": 1_200_000.0,
            "change_pct": 1.25,
        },
        "ETH/USDT": {
            "symbol": "ETH/USDT",
            "timestamp": now,
            "price": 2280.75,
            "bid": 2280.50,
            "ask": 2281.00,
            "volume": 800_000.0,
            "change_pct": -0.45,
        },
    }


@pytest.fixture
def sample_candle_data():
    """Sample OHLCV candle data -- 100 rows of synthetic 1-minute bars."""
    import numpy as np
    import pandas as pd

    np.random.seed(42)
    n = 100
    base_price = 43000.0

    # Random walk for close prices
    returns = np.random.normal(0, 0.001, n)
    close = base_price * np.cumprod(1 + returns)

    # Derive OHLV from close
    high = close * (1 + np.abs(np.random.normal(0, 0.0005, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.0005, n)))
    open_ = np.roll(close, 1)
    open_[0] = base_price
    volume = np.random.uniform(100, 1000, n)

    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    return df


@pytest.fixture
def sample_signal():
    """Sample trading signal dict matching the Signal model in the risk service."""
    return {
        "signal_id": "sig_test_001",
        "symbol": "BTC/USDT",
        "action": "buy",
        "amount": 0.0005,
        "price": 43250.50,
        "confidence": 0.72,
    }


@pytest.fixture
def sample_portfolio_state():
    """Sample portfolio state as stored in Redis."""
    return {
        "total_capital": 11.0,
        "available_capital": 8.50,
        "daily_pnl": -0.15,
        "open_positions": 1,
        "last_trade_time": (datetime.utcnow() - timedelta(minutes=5)).isoformat(),
    }
