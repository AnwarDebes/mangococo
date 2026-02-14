"""
Exchange metrics collector - funding rates, open interest, long/short ratios via ccxt.
"""
import asyncio
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binance")
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")


class ExchangeMetrics(BaseModel):
    symbol: str
    funding_rate: Optional[float] = None
    open_interest_change: Optional[float] = None
    long_short_ratio: Optional[float] = None
    timestamp: datetime


class ExchangeMetricsCollector:
    """Collects exchange-specific metrics using ccxt."""

    def __init__(self, exchange_id: Optional[str] = None, pairs: Optional[List[str]] = None):
        self.exchange_id = exchange_id or EXCHANGE_ID
        self.pairs = pairs or TRADING_PAIRS
        self._exchange = None
        self._prev_oi: Dict[str, float] = {}

    async def _get_exchange(self):
        if self._exchange is None:
            try:
                import ccxt.async_support as ccxt

                exchange_class = getattr(ccxt, self.exchange_id, None)
                if exchange_class is None:
                    logger.error("ccxt_exchange_not_found", exchange=self.exchange_id)
                    return None
                self._exchange = exchange_class({
                    "enableRateLimit": True,
                    "options": {"defaultType": "swap"},
                })
                await self._exchange.load_markets()
            except ImportError:
                logger.error("ccxt_import_error", msg="ccxt not installed")
                return None
            except Exception as e:
                logger.error("ccxt_init_error", error=str(e))
                return None
        return self._exchange

    async def close(self):
        if self._exchange:
            await self._exchange.close()
            self._exchange = None

    async def fetch(self) -> Dict[str, ExchangeMetrics]:
        """Fetch exchange metrics for all configured pairs."""
        exchange = await self._get_exchange()
        if exchange is None:
            return {}

        results: Dict[str, ExchangeMetrics] = {}
        now = datetime.now(timezone.utc)

        for pair in self.pairs:
            pair = pair.strip()
            try:
                metrics = ExchangeMetrics(symbol=pair, timestamp=now)

                # Fetch funding rate
                try:
                    funding = await exchange.fetch_funding_rate(pair)
                    if funding and "fundingRate" in funding:
                        metrics.funding_rate = float(funding["fundingRate"])
                except Exception as e:
                    logger.debug("funding_rate_unavailable", symbol=pair, error=str(e))

                # Fetch open interest
                try:
                    if hasattr(exchange, "fetch_open_interest"):
                        oi_data = await exchange.fetch_open_interest(pair)
                        if oi_data and "openInterestValue" in oi_data:
                            current_oi = float(oi_data["openInterestValue"])
                            prev_oi = self._prev_oi.get(pair)
                            if prev_oi is not None and prev_oi > 0:
                                metrics.open_interest_change = round(
                                    (current_oi - prev_oi) / prev_oi * 100, 4
                                )
                            self._prev_oi[pair] = current_oi
                except Exception as e:
                    logger.debug("open_interest_unavailable", symbol=pair, error=str(e))

                # Fetch long/short ratio (exchange-specific, not all support this)
                try:
                    if hasattr(exchange, "fetch_long_short_ratio_history"):
                        ls_data = await exchange.fetch_long_short_ratio_history(pair, limit=1)
                        if ls_data and len(ls_data) > 0:
                            latest = ls_data[-1]
                            metrics.long_short_ratio = float(latest.get("longShortRatio", 1.0))
                except Exception as e:
                    logger.debug("long_short_unavailable", symbol=pair, error=str(e))

                results[pair] = metrics
                logger.debug(
                    "exchange_metrics_fetched",
                    symbol=pair,
                    funding=metrics.funding_rate,
                    oi_change=metrics.open_interest_change,
                    ls_ratio=metrics.long_short_ratio,
                )
            except Exception as e:
                logger.error("exchange_metrics_error", symbol=pair, error=str(e))

        logger.info("exchange_metrics_total", count=len(results))
        return results
