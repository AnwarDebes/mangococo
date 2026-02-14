"""
CryptoPanic news scraper - fetches trending crypto news posts.
"""
import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

CRYPTOPANIC_API_URL = "https://cryptopanic.com/api/v1/posts/"
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")

# Map common currency symbols to trading pairs
SYMBOL_TO_PAIR = {
    "BTC": "BTC/USDT",
    "ETH": "ETH/USDT",
    "SOL": "SOL/USDT",
    "BNB": "BNB/USDT",
    "XRP": "XRP/USDT",
    "ADA": "ADA/USDT",
    "DOGE": "DOGE/USDT",
    "AVAX": "AVAX/USDT",
    "DOT": "DOT/USDT",
    "MATIC": "MATIC/USDT",
    "LINK": "LINK/USDT",
    "UNI": "UNI/USDT",
    "ATOM": "ATOM/USDT",
    "LTC": "LTC/USDT",
    "FIL": "FIL/USDT",
    "ARB": "ARB/USDT",
    "OP": "OP/USDT",
    "APT": "APT/USDT",
    "SUI": "SUI/USDT",
    "NEAR": "NEAR/USDT",
}


class NewsItem(BaseModel):
    text: str
    symbol: str
    source: str
    timestamp: datetime


class CryptoPanicScraper:
    """Fetches latest rising posts from CryptoPanic API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or CRYPTOPANIC_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch(self) -> List[NewsItem]:
        """Fetch latest rising posts from CryptoPanic."""
        if not self.api_key:
            logger.warning("cryptopanic_no_api_key", msg="CRYPTOPANIC_API_KEY not set, skipping")
            return []

        client = await self._get_client()
        items: List[NewsItem] = []

        try:
            params = {
                "auth_token": self.api_key,
                "filter": "rising",
                "kind": "news",
                "public": "true",
            }
            resp = await client.get(CRYPTOPANIC_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            for post in data.get("results", []):
                title = post.get("title", "")
                published = post.get("published_at", "")
                source_name = post.get("source", {}).get("title", "cryptopanic")
                currencies = post.get("currencies", []) or []

                try:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    ts = datetime.now(timezone.utc)

                if currencies:
                    for currency in currencies:
                        code = currency.get("code", "").upper()
                        pair = SYMBOL_TO_PAIR.get(code, f"{code}/USDT")
                        items.append(
                            NewsItem(
                                text=title,
                                symbol=pair,
                                source=source_name,
                                timestamp=ts,
                            )
                        )
                else:
                    # No specific currency tagged, try to detect from title
                    for sym, pair in SYMBOL_TO_PAIR.items():
                        if sym.lower() in title.lower() or pair.split("/")[0].lower() in title.lower():
                            items.append(
                                NewsItem(
                                    text=title,
                                    symbol=pair,
                                    source=source_name,
                                    timestamp=ts,
                                )
                            )
                            break

            logger.info("cryptopanic_fetched", count=len(items))
        except httpx.HTTPStatusError as e:
            logger.error("cryptopanic_http_error", status=e.response.status_code, detail=str(e))
        except Exception as e:
            logger.error("cryptopanic_error", error=str(e))

        return items
