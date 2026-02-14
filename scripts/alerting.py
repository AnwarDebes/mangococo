"""
Alerting Service - Sends notifications via Telegram and Discord webhooks.
Monitors system health, significant trades, and performance milestones.

Usage:
    python scripts/alerting.py  # Run as standalone monitor
    # Or import and use in other services:
    from scripts.alerting import send_alert

Environment:
    TELEGRAM_BOT_TOKEN - Telegram bot token
    TELEGRAM_CHAT_ID - Telegram chat/group ID
    DISCORD_WEBHOOK_URL - Discord webhook URL
"""
import asyncio
import json
import os
from datetime import datetime

import httpx
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

ALERT_COOLDOWN_SECONDS = 300  # 5 min cooldown per alert type
_last_alerts = {}


async def send_telegram(message: str):
    """Send message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
                timeout=10.0,
            )
    except Exception as e:
        logger.error("Telegram alert failed", error=str(e))


async def send_discord(message: str, color: int = 0xFF6B00):
    """Send message via Discord webhook."""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                DISCORD_WEBHOOK_URL,
                json={
                    "embeds": [{
                        "title": "MangoCoco Alert",
                        "description": message,
                        "color": color,
                        "timestamp": datetime.utcnow().isoformat(),
                    }]
                },
                timeout=10.0,
            )
    except Exception as e:
        logger.error("Discord alert failed", error=str(e))


async def send_alert(alert_type: str, message: str, severity: str = "info"):
    """Send alert with cooldown to prevent spam."""
    now = datetime.utcnow().timestamp()
    last = _last_alerts.get(alert_type, 0)

    if now - last < ALERT_COOLDOWN_SECONDS:
        return

    _last_alerts[alert_type] = now

    icon = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "success": "✅"}.get(severity, "📢")
    full_message = f"{icon} <b>[{alert_type}]</b>\n{message}"

    await asyncio.gather(
        send_telegram(full_message),
        send_discord(message, color={
            "info": 0x3498DB, "warning": 0xF39C12,
            "error": 0xE74C3C, "success": 0x2ECC71,
        }.get(severity, 0xFF6B00)),
    )

    logger.info("Alert sent", type=alert_type, severity=severity)


async def monitor_loop():
    """Main monitoring loop - subscribe to Redis channels and alert on events."""
    redis_client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        password=REDIS_PASSWORD, decode_responses=True,
    )
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("filled_orders", "position_opened", "position_closed")

    logger.info("Alerting monitor started")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                channel = message["channel"]

                if channel == "filled_orders":
                    symbol = data.get("symbol", "?")
                    side = data.get("side", "?")
                    cost = data.get("cost", 0)
                    mode = data.get("mode", "live")

                    if cost > 5:  # Only alert for significant trades
                        await send_alert(
                            f"trade_{symbol}",
                            f"{'🟢 BUY' if side == 'buy' else '🔴 SELL'} {symbol}\n"
                            f"Cost: ${cost:.2f} | Mode: {mode}",
                            severity="info",
                        )

                elif channel == "position_closed":
                    symbol = data.get("symbol", "?")
                    pnl = data.get("realized_pnl", 0)
                    pnl_pct = data.get("pnl_pct", 0)

                    severity = "success" if pnl > 0 else "warning"
                    await send_alert(
                        f"position_closed_{symbol}",
                        f"Position Closed: {symbol}\n"
                        f"PnL: ${pnl:.4f} ({pnl_pct:.2f}%)",
                        severity=severity,
                    )

            except Exception as e:
                logger.error("Failed to process alert", error=str(e))

    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe()
        await redis_client.close()


async def health_check_loop():
    """Periodically check system health and alert on issues."""
    http = httpx.AsyncClient(timeout=10.0)
    services = {
        "market-data": "http://market-data:8001/health",
        "prediction": "http://prediction:8002/health",
        "executor": "http://executor:8005/health",
        "api-gateway": "http://api-gateway:8000/health",
    }

    while True:
        for name, url in services.items():
            try:
                resp = await http.get(url)
                if resp.status_code != 200:
                    await send_alert(f"health_{name}", f"Service {name} unhealthy (HTTP {resp.status_code})", "error")
            except Exception:
                await send_alert(f"health_{name}", f"Service {name} is DOWN", "error")

        await asyncio.sleep(60)


async def main():
    await asyncio.gather(
        monitor_loop(),
        health_check_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
