"""
Google Trends collector - tracks search interest for crypto coins.
"""
import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()

# Coin name to trading pair mapping
SEARCH_TERMS = {
    "bitcoin": "BTC/USDT",
    "ethereum": "ETH/USDT",
    "solana": "SOL/USDT",
    "bnb": "BNB/USDT",
    "xrp": "XRP/USDT",
    "cardano": "ADA/USDT",
    "dogecoin": "DOGE/USDT",
    "avalanche crypto": "AVAX/USDT",
    "polkadot": "DOT/USDT",
    "chainlink crypto": "LINK/USDT",
    "arbitrum": "ARB/USDT",
    "near protocol": "NEAR/USDT",
    "sui crypto": "SUI/USDT",
    "aptos": "APT/USDT",
}

# Google Trends only allows 5 keywords per request
BATCH_SIZE = 5


class GoogleTrendsCollector:
    """Collects Google Trends interest data for crypto search terms."""

    def __init__(self):
        self._pytrends = None

    def _get_pytrends(self):
        if self._pytrends is None:
            try:
                from pytrends.request import TrendReq

                self._pytrends = TrendReq(hl="en-US", tz=360)
            except ImportError:
                logger.error("pytrends_import_error", msg="pytrends not installed")
                return None
        return self._pytrends

    async def fetch(self) -> Dict[str, dict]:
        """Fetch Google Trends interest for crypto coins.

        Returns dict mapping symbol to trend data.
        Rate-limit friendly: batches of 5 with delays.
        """
        pytrends = self._get_pytrends()
        if pytrends is None:
            return {}

        results: Dict[str, dict] = {}
        terms = list(SEARCH_TERMS.keys())
        now = datetime.now(timezone.utc)

        for i in range(0, len(terms), BATCH_SIZE):
            batch = terms[i : i + BATCH_SIZE]
            try:
                # Run in executor to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda b=batch: pytrends.build_payload(b, timeframe="now 7-d"),
                )
                interest = await loop.run_in_executor(None, pytrends.interest_over_time)

                if interest is not None and not interest.empty:
                    for term in batch:
                        if term in interest.columns:
                            # Get the latest value (last row)
                            latest_value = int(interest[term].iloc[-1])
                            # Get average over period
                            avg_value = float(interest[term].mean())
                            symbol = SEARCH_TERMS[term]

                            results[symbol] = {
                                "symbol": symbol,
                                "search_term": term,
                                "current_interest": latest_value,
                                "avg_interest_7d": round(avg_value, 2),
                                "interest_change": round(
                                    (latest_value - avg_value) / max(avg_value, 1) * 100, 2
                                ),
                                "timestamp": now.isoformat(),
                            }

                logger.info("google_trends_batch_fetched", batch=batch, results=len(results))
            except Exception as e:
                logger.error("google_trends_batch_error", batch=batch, error=str(e))

            # Rate limiting: wait between batches
            if i + BATCH_SIZE < len(terms):
                await asyncio.sleep(10)

        logger.info("google_trends_total", count=len(results))
        return results
