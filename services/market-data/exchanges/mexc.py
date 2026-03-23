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
        logger.info(
            "MEXC adapter connected",
            websocket=HAS_WS,
            watch_tickers_supported=self.supports_watch_tickers(),
        )

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

    # ── Volume / liquidity filter thresholds ──────────────────────────
    MIN_24H_VOLUME_USD = 5_000       # Minimum 24h quote volume in USD (relaxed: low vol pairs have big potential)
    MIN_PRICE_USD = 0.00001          # Reject dust tokens below this price (allow cheaper tokens)
    MAX_BID_ASK_SPREAD_PCT = 8.0     # Max bid-ask spread as % of mid price (more lenient)

    async def fetch_usdt_symbols(self, limit: Optional[int] = None) -> List[str]:
        """Fetch USDT spot pairs from MEXC, filtered by volume and liquidity.

        Applies three filters to avoid micro-cap garbage tokens:
        1. Minimum 24h quote volume ($50k USD default)
        2. Minimum last price ($0.0001 default)
        3. Maximum bid-ask spread (5% default) when bid/ask data is available
        """
        await asyncio.to_thread(self._rest.load_markets)
        self._markets_loaded = True

        # Step 1: collect all USDT spot symbols
        all_usdt_symbols = []
        for symbol, market in self._rest.markets.items():
            if market.get("quote") != "USDT":
                continue
            if not market.get("spot", True):
                continue
            all_usdt_symbols.append(symbol)

        total_before_filter = len(all_usdt_symbols)
        logger.info(
            "MEXC raw USDT spot pairs discovered",
            count=total_before_filter,
        )

        # Step 2: fetch tickers in bulk for volume/price/spread data
        try:
            tickers = await asyncio.to_thread(
                self._rest.fetch_tickers, all_usdt_symbols
            )
        except Exception as e:
            logger.warning(
                "Bulk ticker fetch failed, falling back to unfiltered list",
                error=str(e),
            )
            all_usdt_symbols.sort()
            if limit:
                all_usdt_symbols = all_usdt_symbols[:limit]
            return all_usdt_symbols

        # Step 3: apply volume, price, and spread filters
        symbols = []
        rejected_volume = 0
        rejected_price = 0
        rejected_spread = 0

        for symbol in all_usdt_symbols:
            ticker = tickers.get(symbol)
            if ticker is None:
                rejected_volume += 1  # no data = skip
                continue

            # --- 24h quote volume filter ---
            quote_volume = self._safe_float_val(ticker.get("quoteVolume"))
            if quote_volume < self.MIN_24H_VOLUME_USD:
                rejected_volume += 1
                continue

            # --- Minimum price filter ---
            last_price = self._safe_float_val(ticker.get("last"))
            if last_price < self.MIN_PRICE_USD:
                rejected_price += 1
                continue

            # --- Bid-ask spread filter (when data available) ---
            bid = self._safe_float_val(ticker.get("bid"))
            ask = self._safe_float_val(ticker.get("ask"))
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2.0
                spread_pct = ((ask - bid) / mid) * 100.0 if mid > 0 else 0.0
                if spread_pct > self.MAX_BID_ASK_SPREAD_PCT:
                    rejected_spread += 1
                    continue

            symbols.append(symbol)

        symbols.sort()
        if limit:
            symbols = symbols[:limit]

        total_rejected = total_before_filter - len(symbols)
        logger.info(
            "MEXC symbol filtering complete",
            total_raw=total_before_filter,
            passed=len(symbols),
            rejected_total=total_rejected,
            rejected_low_volume=rejected_volume,
            rejected_low_price=rejected_price,
            rejected_wide_spread=rejected_spread,
            min_volume_usd=self.MIN_24H_VOLUME_USD,
            min_price_usd=self.MIN_PRICE_USD,
            max_spread_pct=self.MAX_BID_ASK_SPREAD_PCT,
        )
        return symbols

    @staticmethod
    def _safe_float_val(v, default=0.0):
        """Convert a value to float, returning *default* on failure."""
        if v is None:
            return default
        try:
            f = float(v)
            return f if f == f else default  # NaN check
        except (ValueError, TypeError):
            return default

    def supports_watch_tickers(self) -> bool:
        """Return True only when ccxt.pro and exchange support watch_tickers."""
        if not HAS_WS or not self._ws:
            return False
        has = getattr(self._ws, "has", {}) or {}
        return bool(has.get("watchTickers"))

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
        if not self.supports_watch_tickers():
            raise RuntimeError("MEXC watch_tickers is not supported by current ccxt.pro adapter")

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
