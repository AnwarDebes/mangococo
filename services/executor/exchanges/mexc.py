"""
MEXC live exchange executor - wraps ccxt async for real order execution.
"""
import ccxt.async_support as ccxt
import structlog
from typing import Optional, Dict

from .base import ExchangeExecutor

logger = structlog.get_logger()


class MexcExecutor(ExchangeExecutor):
    """Live MEXC exchange executor using ccxt."""

    name = "mexc"

    def __init__(self, api_key: str, secret_key: str):
        self._api_key = api_key
        self._secret_key = secret_key
        self._exchange: Optional[ccxt.mexc] = None

    async def connect(self) -> None:
        self._exchange = ccxt.mexc({
            "apiKey": self._api_key,
            "secret": self._secret_key,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        # Validate credentials
        if self._api_key and self._api_key != "your_mexc_api_key_here":
            try:
                await self._exchange.fetch_balance()
                logger.info("MEXC executor connected with valid API keys")
            except Exception as e:
                logger.warning("MEXC API key validation failed", error=str(e))
        else:
            logger.warning("MEXC executor initialized without valid API keys")

    async def close(self) -> None:
        if self._exchange:
            await self._exchange.close()

    async def get_balance(self, currency: str = "USDT") -> Dict:
        balance = await self._exchange.fetch_balance()
        return {
            "free": float(balance.get(currency, {}).get("free", 0)),
            "used": float(balance.get(currency, {}).get("used", 0)),
            "total": float(balance.get(currency, {}).get("total", 0)),
        }

    async def create_market_buy(self, symbol: str, cost: float) -> Dict:
        ticker = await self._exchange.fetch_ticker(symbol)
        price = ticker["last"]
        amount = cost / price

        order = await self._exchange.create_market_buy_order(symbol, amount)
        return self._normalize_order(order)

    async def create_market_sell(self, symbol: str, amount: float) -> Dict:
        order = await self._exchange.create_market_sell_order(symbol, amount)
        return self._normalize_order(order)

    async def fetch_ticker_price(self, symbol: str) -> float:
        ticker = await self._exchange.fetch_ticker(symbol)
        return float(ticker.get("last", 0))

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> list:
        orders = await self._exchange.fetch_open_orders(symbol)
        return [self._normalize_order(o) for o in orders]

    @staticmethod
    def _normalize_order(order: dict) -> Dict:
        return {
            "id": order.get("id", ""),
            "symbol": order.get("symbol", ""),
            "side": order.get("side", ""),
            "amount": float(order.get("amount", 0)),
            "price": float(order.get("price", 0) or order.get("average", 0) or 0),
            "cost": float(order.get("cost", 0)),
            "filled": float(order.get("filled", 0)),
            "status": order.get("status", "unknown"),
            "fee": float((order.get("fee") or {}).get("cost", 0)),
        }
