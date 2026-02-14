"""
Abstract base class for execution adapters.
Supports both live exchange trading and paper trading.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict


class ExchangeExecutor(ABC):
    """Base class for order execution adapters."""

    name: str = "base"

    @abstractmethod
    async def connect(self) -> None:
        """Initialize exchange connection."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Shut down connections."""
        ...

    @abstractmethod
    async def get_balance(self, currency: str = "USDT") -> Dict:
        """Get available balance for a currency. Returns {'free': float, 'used': float, 'total': float}."""
        ...

    @abstractmethod
    async def create_market_buy(self, symbol: str, cost: float) -> Dict:
        """
        Place a market buy order spending `cost` USDT.
        Returns order dict: {id, symbol, side, amount, price, cost, filled, status, fee}
        """
        ...

    @abstractmethod
    async def create_market_sell(self, symbol: str, amount: float) -> Dict:
        """
        Place a market sell order for `amount` of the coin.
        Returns order dict: {id, symbol, side, amount, price, cost, filled, status, fee}
        """
        ...

    @abstractmethod
    async def fetch_ticker_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        ...

    @abstractmethod
    async def fetch_open_orders(self, symbol: Optional[str] = None) -> list:
        """Get open orders, optionally filtered by symbol."""
        ...
