"""
Fear & Greed Index scraper - fetches the crypto market sentiment index.
"""
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

FEAR_GREED_API_URL = "https://api.alternative.me/fng/"


class FearGreedData(BaseModel):
    value: int
    classification: str
    normalized_score: float  # -1 (extreme fear) to 1 (extreme greed)
    timestamp: datetime


class FearGreedScraper:
    """Fetches the Crypto Fear & Greed Index from alternative.me."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch(self) -> Optional[FearGreedData]:
        """Fetch current Fear & Greed Index value."""
        client = await self._get_client()

        try:
            resp = await client.get(FEAR_GREED_API_URL, params={"limit": 1})
            resp.raise_for_status()
            data = resp.json()

            entries = data.get("data", [])
            if not entries:
                logger.warning("fear_greed_no_data")
                return None

            entry = entries[0]
            value = int(entry.get("value", 50))
            classification = entry.get("value_classification", "Neutral")
            ts_str = entry.get("timestamp", "")

            try:
                ts = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)

            # Normalize: map 0-100 to -1 to 1
            normalized = (value - 50) / 50.0

            result = FearGreedData(
                value=value,
                classification=classification,
                normalized_score=round(normalized, 4),
                timestamp=ts,
            )
            logger.info(
                "fear_greed_fetched",
                value=value,
                classification=classification,
                normalized=result.normalized_score,
            )
            return result

        except httpx.HTTPStatusError as e:
            logger.error("fear_greed_http_error", status=e.response.status_code, detail=str(e))
        except Exception as e:
            logger.error("fear_greed_error", error=str(e))

        return None
