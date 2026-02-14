"""
MEXC exchange adapter - WebSocket primary with REST fallback.
Uses ccxt.pro for WebSocket streaming and ccxt for REST polling.
"""
import asyncio
from typing import Optional, Callable, Awaitable, List

import ccxt
import structlog

from .base import ExchangeAdapter

logger = structlog.get_logger()

# Try to import ccxt.pro for WebSocket support
try:
    import ccxt.pro as ccxtpro
    HAS_WS = True
except ImportError:
    HAS_WS = False
    logger.warning("ccxt.pro not available - WebSocket streaming disabled, using REST only")


class MexcAdapter(ExchangeAdapter):
    """MEXC exchange adapter with WebSocket primary and REST fallback."""

    name = "mexc"

    def __init__(self, api_key: str = "", secret_key: str = ""):
        self._api_key = api_key
        self._secret_key = secret_key
        self._rest: Optional[ccxt.mexc] = None
        self._ws = None
        self._markets_loaded = False

    async def connect(self) -> None:
        self._rest = ccxt.mexc({"enableRateLimit": True})
        if HAS_WS:
            self._ws = ccxtpro.mexc({"enableRateLimit": True})
        logger.info("MEXC adapter connected", websocket=HAS_WS)

    async def close(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._rest:
            try:
                self._rest.close()
            except Exception:
                pass

    async def fetch_usdt_symbols(self, limit: Optional[int] = None) -> List[str]:
        """Fetch all USDT spot pairs from MEXC (public, no auth needed)."""
        await asyncio.to_thread(self._rest.load_markets)
        self._markets_loaded = True
        symbols = []
        for symbol, market in self._rest.markets.items():
            if market.get("quote") != "USDT":
                continue
            if not market.get("spot", True):
                continue
            symbols.append(symbol)
        symbols.sort()
        if limit:
            symbols = symbols[:limit]
        logger.info(f"Fetched {len(symbols)} USDT spot pairs from MEXC")
        return symbols

    async def stream_tickers_ws(
        self,
        symbols: List[str],
        on_tick: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        """
        Stream real-time tickers via MEXC WebSocket using ccxt.pro.
        Auto-reconnects on failure with exponential backoff.
        """
        if not HAS_WS or not self._ws:
            raise RuntimeError("WebSocket not available - install ccxt with pro support")

        reconnect_delay = 1.0
        max_reconnect_delay = 30.0

        while True:
            try:
                logger.info(f"Starting WebSocket stream for {len(symbols)} symbols")
                reconnect_delay = 1.0  # reset on successful connection

                while True:
                    # watch_tickers returns whenever any of the subscribed tickers update
                    tickers = await self._ws.watch_tickers(symbols)
                    for symbol, ticker in tickers.items():
                        await on_tick(symbol, self._normalize_ticker(ticker))

            except Exception as e:
                logger.error(
                    "WebSocket stream error, reconnecting",
                    error=str(e),
                    delay=reconnect_delay,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

                # Recreate the WebSocket connection
                try:
                    if self._ws:
                        await self._ws.close()
                except Exception:
                    pass
                self._ws = ccxtpro.mexc({"enableRateLimit": True})

    async def poll_tickers_rest(
        self,
        symbols: List[str],
        on_tick: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        """Single REST poll cycle: fetch tickers in batches."""
        batch_size = 100 if len(symbols) > 1000 else 75 if len(symbols) > 500 else 50

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            try:
                tickers = await asyncio.to_thread(self._rest.fetch_tickers, batch)
                for symbol, ticker in tickers.items():
                    await on_tick(symbol, self._normalize_ticker(ticker))
            except Exception as e:
                # Fallback to individual fetching on batch failure
                logger.debug(f"Batch fetch failed, falling back to individual", error=str(e))
                for symbol in batch:
                    try:
                        ticker = await asyncio.to_thread(self._rest.fetch_ticker, symbol)
                        await on_tick(symbol, self._normalize_ticker(ticker))
                        await asyncio.sleep(0.01)
                    except Exception as inner_e:
                        logger.debug(f"Failed to fetch {symbol}", error=str(inner_e))

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        since: Optional[int] = None,
        limit: int = 100,
    ) -> List[list]:
        """Fetch OHLCV candles via REST."""
        return await asyncio.to_thread(
            self._rest.fetch_ohlcv, symbol, timeframe, since, limit
        )

    @staticmethod
    def _normalize_ticker(ticker: dict) -> dict:
        """Normalize ccxt ticker to a standard dict with safe float handling."""
        def sf(v, default=0.0):
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        return {
            "last": sf(ticker.get("last")),
            "bid": sf(ticker.get("bid")),
            "ask": sf(ticker.get("ask")),
            "quoteVolume": sf(ticker.get("quoteVolume")),
            "percentage": sf(ticker.get("percentage")),
        }
