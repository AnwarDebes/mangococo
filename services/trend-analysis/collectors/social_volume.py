"""
Social volume collector - aggregates mention counts from sentiment service data in Redis.
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class SocialVolumeCollector:
    """Aggregates mention counts from sentiment service Redis data."""

    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        # Rolling window of mention counts per symbol for z-score calculation
        self._history: Dict[str, list] = {}
        self._history_max = 168  # 7 days of hourly data points

    async def fetch(self) -> Dict[str, dict]:
        """Aggregate mention counts from Redis sentiment data.

        Reads sentiment keys and computes volume metrics per symbol.
        Returns dict mapping symbol to social volume data.
        """
        results: Dict[str, dict] = {}
        now = datetime.now(timezone.utc)

        try:
            # Scan all sentiment keys
            mention_counts: Dict[str, int] = {}
            async for key in self._redis.scan_iter(match="sentiment:*"):
                data = await self._redis.get(key)
                if data:
                    parsed = json.loads(data)
                    symbol = parsed.get("symbol", "")
                    count = parsed.get("sample_count", 0)
                    if symbol:
                        mention_counts[symbol] = count

            for symbol, current_count in mention_counts.items():
                # Update rolling history
                if symbol not in self._history:
                    self._history[symbol] = []
                self._history[symbol].append(current_count)
                if len(self._history[symbol]) > self._history_max:
                    self._history[symbol] = self._history[symbol][-self._history_max:]

                history = self._history[symbol]

                # Calculate z-score vs 7-day average
                if len(history) >= 2:
                    avg = sum(history) / len(history)
                    variance = sum((x - avg) ** 2 for x in history) / len(history)
                    std = variance ** 0.5
                    z_score = (current_count - avg) / std if std > 0 else 0.0
                else:
                    avg = float(current_count)
                    z_score = 0.0

                # Volume windows (approximations based on available data)
                h1_count = current_count
                h4_count = sum(history[-4:]) if len(history) >= 4 else current_count
                h24_count = sum(history[-24:]) if len(history) >= 24 else current_count

                results[symbol] = {
                    "symbol": symbol,
                    "mention_count_1h": h1_count,
                    "mention_count_4h": h4_count,
                    "mention_count_24h": h24_count,
                    "avg_mentions_7d": round(avg, 2),
                    "z_score": round(z_score, 4),
                    "is_unusual": abs(z_score) > 2.0,
                    "timestamp": now.isoformat(),
                }

            logger.info("social_volume_fetched", symbols=len(results))
        except Exception as e:
            logger.error("social_volume_error", error=str(e))

        return results
