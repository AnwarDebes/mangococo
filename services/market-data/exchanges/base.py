"""
Abstract base class for exchange adapters.
All exchanges must implement this interface to integrate with the market-data service.
"""
from abc import ABC, abstractmethod
from typing import Optional, Callable, Awaitable, List, Dict


class ExchangeAdapter(ABC):
    """Base class for exchange market data adapters."""

    name: str = "base"

    @abstractmethod
    async def connect(self) -> None:
        """Initialize exchange connections (REST client, load markets, etc.)."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Gracefully shut down all connections."""
        ...

    @abstractmethod
    async def fetch_usdt_symbols(self, limit: Optional[int] = None) -> List[str]:
        """Return all USDT spot trading pairs available on this exchange."""
        ...

    @abstractmethod
    async def stream_tickers_ws(
        self,
        symbols: List[str],
        on_tick: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        """
        Stream real-time tickers via WebSocket.
        Calls `on_tick(symbol, ticker_dict)` for every price update.
        Should reconnect automatically on disconnect.
        """
        ...

    @abstractmethod
    async def poll_tickers_rest(
        self,
        symbols: List[str],
        on_tick: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        """
        Single REST poll cycle for the given symbols.
        Calls `on_tick(symbol, ticker_dict)` for each returned ticker.
        """
        ...

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        since: Optional[int] = None,
        limit: int = 100,
    ) -> List[list]:
        """
        Fetch OHLCV candles for backtesting / feature engineering.
        Returns list of [timestamp, open, high, low, close, volume].
        """
        ...
