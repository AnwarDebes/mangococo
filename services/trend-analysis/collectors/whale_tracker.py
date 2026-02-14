"""
Whale tracker - monitors large crypto transactions for market signals.
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import httpx
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

WHALE_ALERT_API_URL = "https://api.whale-alert.io/v1/transactions"
WHALE_ALERT_API_KEY = os.getenv("WHALE_ALERT_API_KEY", "")
MIN_TRANSACTION_USD = int(os.getenv("WHALE_MIN_USD", 100000))

# Known exchange wallet labels (simplified)
EXCHANGE_KEYWORDS = [
    "binance", "coinbase", "kraken", "okx", "bybit", "bitfinex",
    "huobi", "kucoin", "gate", "mexc", "bitstamp", "gemini",
]

# Symbol mapping for whale alert
BLOCKCHAIN_TO_SYMBOL = {
    "bitcoin": "BTC/USDT",
    "ethereum": "ETH/USDT",
    "solana": "SOL/USDT",
    "ripple": "XRP/USDT",
    "tron": "TRX/USDT",
    "litecoin": "LTC/USDT",
    "dogecoin": "DOGE/USDT",
    "cardano": "ADA/USDT",
    "polkadot": "DOT/USDT",
    "avalanche": "AVAX/USDT",
}


class WhaleTransaction(BaseModel):
    symbol: str
    amount_usd: float
    direction: str  # 'exchange_inflow', 'exchange_outflow', 'unknown'
    from_owner: str
    to_owner: str
    timestamp: datetime


class WhaleTracker:
    """Tracks large crypto transactions using Whale Alert API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or WHALE_ALERT_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
        self._recent_alerts: List[WhaleTransaction] = []
        self._max_alerts = 500

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _is_exchange(self, owner: str) -> bool:
        """Check if a wallet owner is a known exchange."""
        owner_lower = owner.lower()
        return any(ex in owner_lower for ex in EXCHANGE_KEYWORDS)

    def _classify_direction(self, from_owner: str, to_owner: str) -> str:
        """Classify transaction direction based on exchange involvement."""
        from_is_exchange = self._is_exchange(from_owner)
        to_is_exchange = self._is_exchange(to_owner)

        if to_is_exchange and not from_is_exchange:
            return "exchange_inflow"  # Bearish: coins moving to exchange
        elif from_is_exchange and not to_is_exchange:
            return "exchange_outflow"  # Bullish: coins leaving exchange
        else:
            return "unknown"

    async def fetch(self) -> List[WhaleTransaction]:
        """Fetch recent whale transactions."""
        if not self.api_key:
            logger.warning("whale_alert_no_api_key", msg="WHALE_ALERT_API_KEY not set, skipping")
            return []

        client = await self._get_client()
        transactions: List[WhaleTransaction] = []

        try:
            # Fetch transactions from last 10 minutes
            start_time = int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp())

            params = {
                "api_key": self.api_key,
                "min_value": MIN_TRANSACTION_USD,
                "start": start_time,
            }
            resp = await client.get(WHALE_ALERT_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            for tx in data.get("transactions", []):
                blockchain = tx.get("blockchain", "").lower()
                symbol = BLOCKCHAIN_TO_SYMBOL.get(blockchain)
                if not symbol:
                    continue

                amount_usd = float(tx.get("amount_usd", 0))
                if amount_usd < MIN_TRANSACTION_USD:
                    continue

                from_owner = tx.get("from", {}).get("owner", "unknown")
                to_owner = tx.get("to", {}).get("owner", "unknown")

                ts = datetime.fromtimestamp(tx.get("timestamp", 0), tz=timezone.utc)
                direction = self._classify_direction(from_owner, to_owner)

                whale_tx = WhaleTransaction(
                    symbol=symbol,
                    amount_usd=amount_usd,
                    direction=direction,
                    from_owner=from_owner,
                    to_owner=to_owner,
                    timestamp=ts,
                )
                transactions.append(whale_tx)

            # Store recent alerts
            self._recent_alerts.extend(transactions)
            if len(self._recent_alerts) > self._max_alerts:
                self._recent_alerts = self._recent_alerts[-self._max_alerts:]

            logger.info("whale_tracker_fetched", count=len(transactions))
        except httpx.HTTPStatusError as e:
            logger.error("whale_alert_http_error", status=e.response.status_code, detail=str(e))
        except Exception as e:
            logger.error("whale_alert_error", error=str(e))

        return transactions

    def get_net_flow(self) -> Dict[str, dict]:
        """Calculate net whale flow score per symbol from recent alerts.

        Positive = more outflows (bullish), Negative = more inflows (bearish).
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=1)

        flows: Dict[str, dict] = {}

        for tx in self._recent_alerts:
            if tx.timestamp < cutoff:
                continue

            if tx.symbol not in flows:
                flows[tx.symbol] = {
                    "symbol": tx.symbol,
                    "inflow_usd": 0.0,
                    "outflow_usd": 0.0,
                    "unknown_usd": 0.0,
                    "tx_count": 0,
                }

            flows[tx.symbol]["tx_count"] += 1

            if tx.direction == "exchange_inflow":
                flows[tx.symbol]["inflow_usd"] += tx.amount_usd
            elif tx.direction == "exchange_outflow":
                flows[tx.symbol]["outflow_usd"] += tx.amount_usd
            else:
                flows[tx.symbol]["unknown_usd"] += tx.amount_usd

        # Calculate net flow score
        for symbol, data in flows.items():
            net = data["outflow_usd"] - data["inflow_usd"]
            total = data["outflow_usd"] + data["inflow_usd"]
            # Normalize to -1 to 1 range
            data["net_flow_usd"] = net
            data["net_flow_score"] = round(net / total, 4) if total > 0 else 0.0
            data["signal"] = "bullish" if data["net_flow_score"] > 0.2 else "bearish" if data["net_flow_score"] < -0.2 else "neutral"
            data["timestamp"] = now.isoformat()

        return flows

    @property
    def recent_alerts(self) -> List[WhaleTransaction]:
        return self._recent_alerts[-50:]
