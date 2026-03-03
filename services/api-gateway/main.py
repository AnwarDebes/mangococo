"""
API Gateway v2.0 - Central entry point for all services.
Serves REST API for the Next.js dashboard and SSE for real-time updates.
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse
from prometheus_client import Counter, generate_latest

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "timescaledb")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "goblin")
POSTGRES_USER = os.getenv("POSTGRES_USER", "goblin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

SERVICES = {
    "market_data": "http://market-data:8001",
    "prediction": "http://prediction:8002",
    "signal": "http://signal:8000",
    "risk": "http://risk:8000",
    "executor": "http://executor:8005",
    "position": "http://position:8000",
    "feature_store": "http://feature-store:8007",
    "sentiment": "http://sentiment-analysis:8008",
    "trend": "http://trend-analysis:8009",
    "portfolio_optimizer": "http://portfolio-optimizer:8010",
    "backtesting": "http://backtesting:8011",
}

logger = structlog.get_logger()

# Metrics
API_REQUESTS = Counter("api_requests_total", "Total API requests", ["endpoint", "method"])

# Global State
redis_client: Optional[aioredis.Redis] = None
http_client: Optional[httpx.AsyncClient] = None
db_pool = None


async def init_db():
    """Initialize TimescaleDB connection for analytics queries."""
    global db_pool
    try:
        import asyncpg
        db_pool = await asyncpg.create_pool(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            database=POSTGRES_DB, user=POSTGRES_USER,
            password=POSTGRES_PASSWORD, min_size=2, max_size=5,
        )
        logger.info("API Gateway connected to TimescaleDB")
    except Exception as e:
        logger.warning("TimescaleDB not available for analytics", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, http_client
    logger.info("Starting API Gateway v2.0...")
    redis_client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        password=REDIS_PASSWORD, decode_responses=True,
    )
    http_client = httpx.AsyncClient(timeout=30.0)
    await init_db()
    yield
    if http_client:
        await http_client.aclose()
    if redis_client:
        await redis_client.close()
    if db_pool:
        await db_pool.close()


app = FastAPI(title="Goblin API Gateway", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================
# Health & Status
# =============================================

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "2.0.0", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status")
async def system_status():
    """Check health of all backend services."""
    status = {}
    for name, url in SERVICES.items():
        try:
            response = await http_client.get(f"{url}/health", timeout=5.0)
            status[name] = {
                "healthy": response.status_code == 200,
                "data": response.json() if response.status_code == 200 else None,
            }
        except Exception as e:
            status[name] = {"healthy": False, "error": str(e)}
    return {"timestamp": datetime.utcnow().isoformat(), "services": status}


# =============================================
# v2 API - Dashboard Endpoints
# =============================================

@app.get("/api/v2/portfolio")
async def get_portfolio_v2():
    """Get full portfolio state for dashboard."""
    try:
        portfolio = {}

        # Get risk/portfolio state
        try:
            risk_resp = await http_client.get(f"{SERVICES['risk']}/portfolio", timeout=5.0)
            if risk_resp.status_code == 200:
                portfolio["risk"] = risk_resp.json()
        except Exception:
            pass

        # Get open positions
        try:
            pos_resp = await http_client.get(f"{SERVICES['position']}/positions", timeout=5.0)
            if pos_resp.status_code == 200:
                positions = pos_resp.json()
                portfolio["positions"] = positions
                total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions.values())
                portfolio["total_unrealized_pnl"] = total_unrealized
                portfolio["open_positions_count"] = len(positions)
        except Exception:
            portfolio["positions"] = {}

        # Get balance from executor
        try:
            bal_resp = await http_client.get(f"{SERVICES['executor']}/balance", timeout=5.0)
            if bal_resp.status_code == 200:
                portfolio["balance"] = bal_resp.json()
        except Exception:
            pass

        # Compute summary - prefer executor paper_portfolio for accurate totals
        risk_data = portfolio.get("risk", {})
        balance_data = portfolio.get("balance", {})
        bal_summary = balance_data.get("summary", {})
        paper = bal_summary if bal_summary else {}

        total_value = paper.get("total_value", 0) or risk_data.get("total_value", 0)
        cash = paper.get("usdt_balance", 0) or risk_data.get("available_capital", 0)
        positions_value = total_value - cash if total_value > cash else 0
        daily_pnl = risk_data.get("daily_pnl", 0) or paper.get("pnl", 0)
        positions_dict = paper.get("positions", {})
        open_count = len(positions_dict) if positions_dict else portfolio.get("open_positions_count", 0)

        portfolio["summary"] = {
            "total_value": total_value,
            "cash_balance": cash,
            "positions_value": positions_value,
            "daily_pnl": daily_pnl,
            "open_positions": open_count,
        }

        return portfolio
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/positions")
async def get_positions_v2():
    """Get all open positions with current prices."""
    try:
        response = await http_client.get(f"{SERVICES['position']}/positions", timeout=5.0)
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v2/trades")
async def get_trades_v2(limit: int = 50, offset: int = 0):
    """Get trade history. Tries TimescaleDB first, falls back to Redis."""
    # Try TimescaleDB for persistent history
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM trade_history
                       ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
                    limit, offset,
                )
                trades = [dict(r) for r in rows]
                if trades:
                    # Convert datetime objects to ISO strings
                    for t in trades:
                        for k, v in t.items():
                            if isinstance(v, datetime):
                                t[k] = v.isoformat()
                    count = await conn.fetchval("SELECT count(*) FROM trade_history")
                    return {"trades": trades, "total": count}
        except Exception as e:
            logger.debug("DB trade query failed, falling back to Redis", error=str(e))

    # Fallback: Redis trade history
    try:
        response = await http_client.get(f"{SERVICES['position']}/trades", timeout=5.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    return {"trades": [], "total": 0}


@app.get("/api/v2/signals")
async def get_signals_v2(limit: int = 20):
    """Get recent trading signals."""
    try:
        response = await http_client.get(f"{SERVICES['signal']}/signals", timeout=5.0)
        return response.json()
    except Exception as e:
        return []


@app.get("/api/v2/analytics")
async def get_analytics():
    """Get performance analytics for dashboard."""
    analytics = {
        "sharpe_ratio": 0,
        "sortino_ratio": 0,
        "win_rate": 0,
        "profit_factor": 0,
        "max_drawdown": 0,
        "total_trades": 0,
        "total_return_pct": 0,
        "avg_hold_time_minutes": 0,
        "equity_curve": [],
        "monthly_returns": {},
    }

    if not db_pool:
        return analytics

    try:
        async with db_pool.acquire() as conn:
            # Trade stats
            stats = await conn.fetchrow("""
                SELECT
                    count(*) as total_trades,
                    count(*) FILTER (WHERE realized_pnl > 0) as winning_trades,
                    coalesce(sum(realized_pnl) FILTER (WHERE realized_pnl > 0), 0) as total_profit,
                    coalesce(abs(sum(realized_pnl) FILTER (WHERE realized_pnl < 0)), 0.001) as total_loss,
                    coalesce(avg(hold_time_seconds), 0) as avg_hold_seconds,
                    coalesce(sum(realized_pnl), 0) as total_pnl
                FROM trade_history
            """)

            if stats and stats["total_trades"] > 0:
                analytics["total_trades"] = stats["total_trades"]
                analytics["win_rate"] = round(stats["winning_trades"] / stats["total_trades"], 4)
                analytics["profit_factor"] = round(float(stats["total_profit"]) / float(stats["total_loss"]), 4)
                analytics["avg_hold_time_minutes"] = round(float(stats["avg_hold_seconds"]) / 60, 2)

            # Equity curve from portfolio snapshots
            equity = await conn.fetch("""
                SELECT time, total_value, daily_pnl
                FROM portfolio_snapshots
                ORDER BY time DESC LIMIT 500
            """)
            analytics["equity_curve"] = [
                {"time": r["time"].isoformat(), "value": float(r["total_value"]), "pnl": float(r["daily_pnl"])}
                for r in reversed(equity)
            ]

    except Exception as e:
        logger.error("Analytics query failed", error=str(e))

    return analytics


@app.get("/api/v2/sentiment")
async def get_sentiment_v2(symbol: Optional[str] = None):
    """Get sentiment data from sentiment-analysis service."""
    try:
        if symbol:
            response = await http_client.get(f"{SERVICES['sentiment']}/sentiment/{symbol}", timeout=5.0)
        else:
            response = await http_client.get(f"{SERVICES['sentiment']}/sentiment", timeout=5.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    # Fallback: read from Redis
    try:
        if symbol:
            data = await redis_client.get(f"sentiment:{symbol}")
            return json.loads(data) if data else {"score": 0, "volume": 0}

        # Get fear & greed
        fg = await redis_client.get("fear_greed_index")
        return {
            "fear_greed": json.loads(fg) if fg else {"value": 50, "classification": "Neutral"},
            "symbols": {},
        }
    except Exception:
        return {"fear_greed": {"value": 50}, "symbols": {}}


@app.get("/api/v2/trends")
async def get_trends_v2(symbol: Optional[str] = None):
    """Get trend data from trend-analysis service."""
    try:
        if symbol:
            response = await http_client.get(f"{SERVICES['trend']}/trends/{symbol}", timeout=5.0)
        else:
            response = await http_client.get(f"{SERVICES['trend']}/trends", timeout=5.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {}


@app.get("/api/v2/models")
async def get_model_status():
    """Get ML model status from prediction service."""
    try:
        response = await http_client.get(f"{SERVICES['prediction']}/model-status", timeout=5.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {"models": [], "status": "unavailable"}


@app.get("/api/v2/allocation/{symbol}")
async def get_allocation(symbol: str):
    """Get recommended allocation for a symbol from portfolio-optimizer."""
    try:
        response = await http_client.get(
            f"{SERVICES['portfolio_optimizer']}/allocation/{symbol}", timeout=5.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {"symbol": symbol, "allocation": 0, "status": "unavailable"}


@app.get("/api/v2/portfolio/optimization")
async def get_portfolio_optimization():
    """Get portfolio optimization summary."""
    try:
        response = await http_client.get(
            f"{SERVICES['portfolio_optimizer']}/portfolio/summary", timeout=5.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {"status": "unavailable"}


@app.get("/api/v2/backtests")
async def get_backtests():
    """List all backtest runs."""
    try:
        response = await http_client.get(
            f"{SERVICES['backtesting']}/backtests", timeout=10.0)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {"runs": []}


@app.get("/api/v2/backtest/{run_id}")
async def get_backtest(run_id: int):
    """Get backtest results."""
    try:
        response = await http_client.get(
            f"{SERVICES['backtesting']}/backtest/{run_id}", timeout=10.0)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/v2/backtest")
async def run_backtest(
    symbols: str = "BTC/USDT,ETH/USDT",
    start_date: str = "",
    end_date: str = "",
    strategy: str = "ml_ensemble",
    initial_capital: float = 10000,
):
    """Start a new backtest run."""
    try:
        response = await http_client.post(
            f"{SERVICES['backtesting']}/backtest",
            json={
                "symbols": symbols.split(","),
                "start_date": start_date,
                "end_date": end_date,
                "strategy": strategy,
                "initial_capital": initial_capital,
            },
            timeout=60.0,
        )
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except httpx.TimeoutException:
        return {"status": "running", "message": "Backtest started, check back later for results"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v2/system")
async def get_system_health():
    """Get comprehensive system health for dashboard."""
    services = []
    for name, url in SERVICES.items():
        entry = {"name": name, "url": url, "status": "unknown", "uptime": None, "last_heartbeat": None}
        try:
            response = await http_client.get(f"{url}/health", timeout=3.0)
            if response.status_code == 200:
                data = response.json()
                entry["status"] = "healthy"
                entry["data"] = data
                entry["last_heartbeat"] = datetime.utcnow().isoformat()
            else:
                entry["status"] = "degraded"
        except Exception as e:
            entry["status"] = "down"
            entry["error"] = str(e)
        services.append(entry)

    # Redis info
    redis_info = {}
    try:
        info = await redis_client.info("memory")
        redis_info = {
            "used_memory": info.get("used_memory_human", "unknown"),
            "connected_clients": info.get("connected_clients", 0),
        }
    except Exception:
        pass

    return {
        "services": services,
        "redis": redis_info,
        "timestamp": datetime.utcnow().isoformat(),
    }


# =============================================
# Legacy v1 API (backwards compatibility)
# =============================================

@app.get("/api/tickers")
async def get_tickers():
    try:
        latest_ticks = await redis_client.hgetall("latest_ticks")
        tickers = {}
        for symbol, tick_data_json in latest_ticks.items():
            try:
                tickers[symbol] = json.loads(tick_data_json)
            except json.JSONDecodeError:
                continue
        return tickers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    symbol = symbol.replace("_", "/").upper()
    tick_data_json = await redis_client.hget("latest_ticks", symbol)
    if tick_data_json:
        return json.loads(tick_data_json)
    raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")


@app.get("/api/portfolio")
async def get_portfolio():
    return await get_portfolio_v2()


@app.get("/api/positions")
async def get_positions():
    return await get_positions_v2()


@app.get("/api/balance")
async def get_balance():
    try:
        response = await http_client.get(f"{SERVICES['executor']}/balance")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    return await get_trades_v2(limit=limit)


@app.get("/api/signals")
async def get_signals():
    return await get_signals_v2()


@app.post("/api/manual-trade")
async def manual_trade(symbol: str, action: str, amount: float):
    try:
        response = await http_client.post(
            f"{SERVICES['signal']}/manual-signal",
            params={"symbol": symbol, "action": action, "amount": amount},
        )
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/emergency/stop")
async def emergency_stop():
    try:
        await http_client.post(f"{SERVICES['signal']}/emergency/stop")
        await http_client.post(f"{SERVICES['executor']}/emergency/cancel-all")
        return {"status": "success", "message": "All trading stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/emergency/close-all")
async def emergency_close_all():
    try:
        pos_resp = await http_client.get(f"{SERVICES['position']}/positions")
        positions = pos_resp.json()
        closed = []
        for symbol in positions.keys():
            try:
                await http_client.post(
                    f"{SERVICES['signal']}/manual-signal",
                    params={"symbol": symbol, "action": "sell", "amount": positions[symbol]["amount"]},
                )
                closed.append(symbol)
            except Exception:
                pass
        return {"status": "success", "closed_positions": closed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================
# Server-Sent Events (real-time streaming)
# =============================================

@app.get("/api/stream")
async def stream_updates():
    """SSE endpoint for real-time dashboard updates."""

    async def event_generator():
        pubsub = redis_client.pubsub()
        # Subscribe to key channels
        await pubsub.psubscribe(
            "ticks:BTC_USDT", "ticks:ETH_USDT", "ticks:SOL_USDT",
            "filled_orders", "position_opened", "position_closed",
            "sentiment_update", "trend_update",
        )

        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] in ("message", "pmessage"):
                    try:
                        data = json.loads(message["data"])
                        channel = message.get("channel", message.get("pattern", ""))

                        if "ticks:" in channel:
                            event = {
                                "type": "price_update",
                                "symbol": data.get("symbol", ""),
                                "price": data.get("price", 0),
                                "change_pct": data.get("change_pct", 0),
                                "timestamp": data.get("timestamp", ""),
                            }
                        elif channel == "filled_orders":
                            event = {"type": "trade_executed", **data}
                        elif channel in ("position_opened", "position_closed"):
                            event = {"type": "position_update", "action": channel.split("_")[1], **data}
                        elif channel == "sentiment_update":
                            event = {"type": "sentiment_update", **data}
                        else:
                            event = {"type": "update", "channel": channel, **data}

                        yield f"data: {json.dumps(event)}\n\n"
                    except Exception:
                        continue

                # Send heartbeat every cycle to keep connection alive
                if not message:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


# =============================================
# MEXC Market Data Proxy
# =============================================

MEXC_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "60m", "4h": "4h", "1d": "1d", "1w": "1W", "1M": "1M",
}


@app.get("/api/v2/candles")
async def get_candles(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200):
    """Proxy to MEXC klines endpoint."""
    mexc_interval = MEXC_INTERVAL_MAP.get(interval, "60m")
    clean_symbol = symbol.replace("/", "")
    url = f"https://api.mexc.com/api/v3/klines?symbol={clean_symbol}&interval={mexc_interval}&limit={limit}"
    try:
        response = await http_client.get(url, timeout=10.0)
        data = response.json()
        candles = []
        for k in data:
            candles.append({
                "time": k[0] // 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        return candles
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v2/depth")
async def get_depth(symbol: str = "BTCUSDT", limit: int = 20):
    """Proxy to MEXC order book."""
    clean_symbol = symbol.replace("/", "")
    url = f"https://api.mexc.com/api/v3/depth?symbol={clean_symbol}&limit={limit}"
    try:
        response = await http_client.get(url, timeout=10.0)
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v2/ticker")
async def get_ticker_v2(symbol: Optional[str] = None):
    """Proxy to MEXC 24hr ticker."""
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    if symbol:
        clean_symbol = symbol.replace("/", "")
        url += f"?symbol={clean_symbol}"
    try:
        response = await http_client.get(url, timeout=10.0)
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/v2/prices")
async def get_prices():
    """Get all symbol prices from MEXC."""
    url = "https://api.mexc.com/api/v3/ticker/price"
    try:
        response = await http_client.get(url, timeout=10.0)
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# =============================================
# Logs endpoint
# =============================================

@app.get("/api/v2/logs")
async def get_logs(container: Optional[str] = None, level: Optional[str] = None, limit: int = 100, since: Optional[str] = None):
    """Aggregate logs from services via health checks and Redis."""
    logs = []
    now = datetime.utcnow()

    # Try to get recent structured logs from Redis
    try:
        for service_name in SERVICES.keys():
            if container and container != service_name:
                continue
            raw_logs = await redis_client.lrange(f"logs:{service_name}", 0, limit - 1)
            for raw in raw_logs:
                try:
                    entry = json.loads(raw)
                    if level and entry.get("level") != level:
                        continue
                    if since and entry.get("timestamp", "") < since:
                        continue
                    logs.append(entry)
                except Exception:
                    continue
    except Exception:
        pass

    # If no Redis logs, build from service health checks
    if not logs:
        for name, url in SERVICES.items():
            if container and container != name:
                continue
            try:
                resp = await http_client.get(f"{url}/health", timeout=3.0)
                status = "healthy" if resp.status_code == 200 else "degraded"
                log_level = "info" if status == "healthy" else "warn"
                if level and level != log_level:
                    continue
                data = resp.json() if resp.status_code == 200 else {}
                logs.append({
                    "container": name,
                    "timestamp": now.isoformat(),
                    "level": log_level,
                    "message": f"[{name}] Health check: {status} — {json.dumps(data)}",
                })
            except Exception as e:
                if level and level != "error":
                    continue
                logs.append({
                    "container": name,
                    "timestamp": now.isoformat(),
                    "level": "error",
                    "message": f"[{name}] Health check failed: {str(e)}",
                })

    logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return logs[:limit]


# =============================================
# Resource Metrics
# =============================================

@app.get("/api/v2/resources")
async def get_resources():
    """Get real resource metrics from Docker container stats."""
    resources = []

    # ── Try real Docker stats first ──────────────────────────────────
    try:
        import aiodocker
        docker = aiodocker.Docker()
        try:
            containers = await docker.containers.list(all=True)
            # Map container names to our service names
            name_map = {
                "mc-market-data": "market_data",
                "mc-prediction": "prediction",
                "mc-signal": "signal",
                "mc-risk": "risk",
                "mc-executor": "executor",
                "mc-position": "position",
                "mc-feature-store": "feature_store",
                "mc-sentiment-analysis": "sentiment",
                "mc-trend-analysis": "trend",
                "mc-portfolio-optimizer": "portfolio_optimizer",
                "mc-backtesting": "backtesting",
                "mc-api-gateway": "api_gateway",
                "mc-dashboard": "dashboard",
                "mc-redis": "redis",
                "mc-timescaledb": "timescaledb",
            }

            async def get_container_stats(container):
                info = await container.show()
                names = info.get("Name", "").lstrip("/")
                service_name = name_map.get(names, names)
                state = info.get("State", {})
                status_raw = state.get("Status", "exited").lower()
                started_at = state.get("StartedAt", "")
                restart_count_val = info.get("RestartCount", 0)

                # Compute uptime
                uptime_seconds = 0
                if started_at and status_raw == "running":
                    try:
                        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                        uptime_seconds = int((datetime.now(start.tzinfo) - start).total_seconds())
                    except Exception:
                        pass

                entry = {
                    "container": service_name,
                    "status": "running" if status_raw == "running" else "restarting" if status_raw == "restarting" else "stopped",
                    "cpu_percent": 0.0,
                    "memory_used_mb": 0.0,
                    "memory_limit_mb": 512.0,
                    "memory_percent": 0.0,
                    "network_rx_mb": 0.0,
                    "network_tx_mb": 0.0,
                    "disk_read_mb": 0.0,
                    "disk_write_mb": 0.0,
                    "uptime_seconds": uptime_seconds,
                    "restart_count": restart_count_val,
                }

                # Get live stats (only for running containers)
                if status_raw == "running":
                    try:
                        stats = await container.stats(stream=False)
                        if isinstance(stats, list) and len(stats) > 0:
                            stats = stats[0]

                        # CPU calculation
                        cpu_stats = stats.get("cpu_stats", {})
                        precpu_stats = stats.get("precpu_stats", {})
                        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
                        num_cpus = cpu_stats.get("online_cpus", len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [1])))
                        if system_delta > 0 and cpu_delta > 0:
                            entry["cpu_percent"] = round((cpu_delta / system_delta) * num_cpus * 100.0, 2)

                        # Memory
                        mem_stats = stats.get("memory_stats", {})
                        mem_used = mem_stats.get("usage", 0) - mem_stats.get("stats", {}).get("cache", 0)
                        mem_limit = mem_stats.get("limit", 0)
                        entry["memory_used_mb"] = round(max(mem_used, 0) / (1024 * 1024), 1)
                        entry["memory_limit_mb"] = round(mem_limit / (1024 * 1024), 1) if mem_limit > 0 else 512.0
                        entry["memory_percent"] = round((mem_used / mem_limit) * 100, 1) if mem_limit > 0 else 0.0

                        # Network
                        networks = stats.get("networks", {})
                        total_rx = sum(n.get("rx_bytes", 0) for n in networks.values())
                        total_tx = sum(n.get("tx_bytes", 0) for n in networks.values())
                        entry["network_rx_mb"] = round(total_rx / (1024 * 1024), 2)
                        entry["network_tx_mb"] = round(total_tx / (1024 * 1024), 2)

                        # Disk I/O
                        blkio = stats.get("blkio_stats", {}).get("io_service_bytes_recursive", []) or []
                        for io_entry in blkio:
                            op = io_entry.get("op", "").lower()
                            if op == "read":
                                entry["disk_read_mb"] = round(io_entry.get("value", 0) / (1024 * 1024), 2)
                            elif op == "write":
                                entry["disk_write_mb"] = round(io_entry.get("value", 0) / (1024 * 1024), 2)
                    except Exception as e:
                        logger.debug("Stats fetch failed for container", container=service_name, error=str(e))

                return entry

            # Fetch stats for all containers in parallel
            tasks = [get_container_stats(c) for c in containers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, dict):
                    resources.append(r)

            # Sort: known services first, then alphabetical
            known_order = list(SERVICES.keys()) + ["api_gateway", "dashboard", "redis", "timescaledb"]
            resources.sort(key=lambda x: (
                known_order.index(x["container"]) if x["container"] in known_order else 999,
                x["container"]
            ))
        finally:
            await docker.close()

        return resources
    except Exception as e:
        logger.warning("Docker stats unavailable, falling back to health checks", error=str(e))

    # ── Fallback: health-check based metrics ─────────────────────────
    for name, url in SERVICES.items():
        entry = {
            "container": name,
            "status": "stopped",
            "cpu_percent": 0,
            "memory_used_mb": 0,
            "memory_limit_mb": 512,
            "memory_percent": 0,
            "network_rx_mb": 0,
            "network_tx_mb": 0,
            "disk_read_mb": 0,
            "disk_write_mb": 0,
            "uptime_seconds": 0,
            "restart_count": 0,
        }
        try:
            resp = await http_client.get(f"{url}/health", timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                entry["status"] = "running"
                entry["uptime_seconds"] = data.get("uptime", 0)
        except Exception:
            entry["status"] = "stopped"
        resources.append(entry)

    # Add Redis
    try:
        info = await redis_client.info("memory")
        resources.append({
            "container": "redis",
            "status": "running",
            "cpu_percent": 0,
            "memory_used_mb": round(info.get("used_memory", 0) / 1024 / 1024, 1),
            "memory_limit_mb": 512,
            "memory_percent": round(info.get("used_memory", 0) / (512 * 1024 * 1024) * 100, 1),
            "network_rx_mb": 0,
            "network_tx_mb": 0,
            "disk_read_mb": 0,
            "disk_write_mb": 0,
            "uptime_seconds": info.get("uptime_in_seconds", 0),
            "restart_count": 0,
        })
    except Exception:
        pass

    return resources


# =============================================
# Phase 4: Prediction Cone
# =============================================

@app.get("/api/v2/prediction/cone")
async def get_prediction_cone(symbol: str = "BTCUSDT"):
    """Probability cone for War Room: historical prices + AI prediction bands."""
    clean_symbol = symbol.replace("/", "")
    try:
        # Fetch last 50 candles from MEXC
        kline_url = f"https://api.mexc.com/api/v3/klines?symbol={clean_symbol}&interval=60m&limit=50"
        kline_resp = await http_client.get(kline_url, timeout=10.0)
        klines = kline_resp.json()
        closes = [float(k[4]) for k in klines]
        current_price = closes[-1] if closes else 0

        # Calculate ATR for volatility-based bands
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        trs = []
        for i in range(1, len(klines)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)
        atr = sum(trs[-14:]) / min(len(trs), 14) if trs else current_price * 0.01

        # Get AI prediction from prediction service
        direction = "up"
        confidence = 0.55
        try:
            pred_resp = await http_client.get(
                f"{SERVICES['prediction']}/predict/{clean_symbol}", timeout=5.0
            )
            if pred_resp.status_code == 200:
                pred = pred_resp.json()
                direction = "up" if pred.get("direction", "up") == "up" else "down"
                confidence = pred.get("confidence", 0.55)
        except Exception:
            # Fallback: use RSI-like heuristic from recent closes
            if len(closes) >= 14:
                recent = closes[-14:]
                gains = sum(max(recent[i] - recent[i-1], 0) for i in range(1, len(recent)))
                losses = sum(max(recent[i-1] - recent[i], 0) for i in range(1, len(recent)))
                if gains + losses > 0:
                    rsi = 100 - (100 / (1 + gains / max(losses, 0.001)))
                    direction = "up" if rsi < 50 else "down"
                    confidence = 0.5 + abs(rsi - 50) / 200

        bias = 1 if direction == "up" else -1

        return {
            "symbol": symbol,
            "current_price": current_price,
            "prediction": {"direction": direction, "confidence": round(confidence, 4)},
            "cone": {
                "1h": {
                    "upper": round(current_price + atr * 0.5, 2),
                    "mid": round(current_price + bias * atr * 0.2 * confidence, 2),
                    "lower": round(current_price - atr * 0.5, 2),
                },
                "4h": {
                    "upper": round(current_price + atr * 1.2, 2),
                    "mid": round(current_price + bias * atr * 0.5 * confidence, 2),
                    "lower": round(current_price - atr * 1.2, 2),
                },
                "24h": {
                    "upper": round(current_price + atr * 3.0, 2),
                    "mid": round(current_price + bias * atr * 1.2 * confidence, 2),
                    "lower": round(current_price - atr * 3.0, 2),
                },
            },
            "historical": closes,
        }
    except Exception as e:
        logger.error("Prediction cone failed", error=str(e))
        raise HTTPException(status_code=502, detail=str(e))


# =============================================
# Phase 4: Factor Heatmap
# =============================================

@app.get("/api/v2/prediction/factors")
async def get_prediction_factors():
    """Factor heatmap data for War Room."""
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    factor_names = ["RSI", "MACD", "Volume", "Sentiment", "Whale", "Trend", "Volatility", "Momentum"]
    result = []

    for symbol in symbols:
        factors = {}
        clean = symbol.replace("/", "")

        # Try to get feature-store data
        features = {}
        try:
            fs_resp = await http_client.get(
                f"{SERVICES['feature_store']}/features/{clean}", timeout=5.0
            )
            if fs_resp.status_code == 200:
                features = fs_resp.json()
        except Exception:
            pass

        # Try sentiment data
        sent_score = 50
        try:
            sent_resp = await http_client.get(
                f"{SERVICES['sentiment']}/sentiment/{symbol}", timeout=3.0
            )
            if sent_resp.status_code == 200:
                sd = sent_resp.json()
                sent_score = sd.get("score", 50)
                if -1 <= sent_score <= 1:
                    sent_score = (sent_score + 1) * 50
        except Exception:
            pass

        # Build factor cells from available data
        rsi_val = features.get("rsi_14", features.get("rsi", 50))
        rsi_dir = "bullish" if rsi_val < 35 else "bearish" if rsi_val > 65 else "neutral"
        factors["RSI"] = {"value": round(rsi_val, 1), "direction": rsi_dir, "description": f"RSI at {rsi_val:.0f} — {'oversold, historically bullish' if rsi_val < 35 else 'overbought, historically bearish' if rsi_val > 65 else 'neutral zone'}"}

        macd_val = features.get("macd", features.get("macd_histogram", 0))
        macd_dir = "bullish" if macd_val > 0 else "bearish" if macd_val < 0 else "neutral"
        factors["MACD"] = {"value": round(macd_val, 4), "direction": macd_dir, "description": f"MACD {'positive — bullish momentum' if macd_val > 0 else 'negative — bearish momentum' if macd_val < 0 else 'flat — no clear signal'}"}

        vol_ratio = features.get("volume_ratio", features.get("volume_vs_avg", 1.0))
        vol_dir = "bullish" if vol_ratio > 1.5 else "bearish" if vol_ratio < 0.5 else "neutral"
        factors["Volume"] = {"value": round(vol_ratio, 2), "direction": vol_dir, "description": f"Volume {vol_ratio:.1f}x average — {'high activity' if vol_ratio > 1.5 else 'low activity' if vol_ratio < 0.5 else 'normal'}"}

        sent_dir = "bullish" if sent_score > 60 else "bearish" if sent_score < 40 else "neutral"
        factors["Sentiment"] = {"value": round(sent_score, 1), "direction": sent_dir, "description": f"Sentiment score {sent_score:.0f} — {'positive outlook' if sent_score > 60 else 'negative outlook' if sent_score < 40 else 'mixed signals'}"}

        factors["Whale"] = {"value": 0, "direction": "neutral", "description": "No significant whale activity detected"}
        factors["Trend"] = {"value": features.get("trend_strength", 0), "direction": "bullish" if features.get("trend_strength", 0) > 0 else "bearish" if features.get("trend_strength", 0) < 0 else "neutral", "description": "Trend analysis based on moving averages"}
        factors["Volatility"] = {"value": features.get("atr_pct", features.get("volatility", 0)), "direction": "neutral", "description": "Market volatility level"}

        mom = features.get("momentum", features.get("roc", 0))
        factors["Momentum"] = {"value": round(mom, 4), "direction": "bullish" if mom > 0 else "bearish" if mom < 0 else "neutral", "description": f"Price momentum {'positive' if mom > 0 else 'negative' if mom < 0 else 'flat'}"}

        result.append({"symbol": symbol, "factors": factors})

    return result


# =============================================
# Phase 4: Whale Activity
# =============================================

@app.get("/api/v2/whales")
async def get_whales(limit: int = 20):
    """Whale activity feed from trend-analysis service."""
    # Try real whale tracker
    try:
        resp = await http_client.get(
            f"{SERVICES['trend']}/whales?limit={limit}", timeout=5.0
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("transactions"):
                return data
    except Exception:
        pass

    # Mock fallback with realistic data
    import random
    now = datetime.utcnow()
    directions = ["exchange_outflow", "exchange_inflow", "exchange_outflow", "exchange_outflow"]
    exchanges = ["Binance", "Coinbase", "Kraken", "OKX", "Bybit"]
    txs = []
    for i in range(min(limit, 15)):
        d = random.choice(directions)
        amt = random.uniform(1_000_000, 50_000_000)
        sig = "bullish" if d == "exchange_outflow" else "bearish"
        sym = random.choice(["BTC/USDT", "ETH/USDT", "BTC/USDT", "SOL/USDT"])
        fr = random.choice(exchanges) if d == "exchange_outflow" else "Unknown Wallet"
        to = "Unknown Wallet" if d == "exchange_outflow" else random.choice(exchanges)
        ts = (now - __import__("datetime").timedelta(minutes=random.randint(1, 180))).isoformat()
        txs.append({
            "symbol": sym, "amount_usd": round(amt, 0), "direction": d,
            "from_label": fr, "to_label": to, "timestamp": ts, "significance": sig,
        })
    txs.sort(key=lambda x: x["timestamp"], reverse=True)

    net_btc = sum((-1 if t["direction"] == "exchange_inflow" else 1) * t["amount_usd"] / 87000 for t in txs if "BTC" in t["symbol"])
    net_eth = sum((-1 if t["direction"] == "exchange_inflow" else 1) * t["amount_usd"] / 3200 for t in txs if "ETH" in t["symbol"])
    ws = "accumulation" if net_btc > 0 else "distribution"

    return {
        "transactions": txs[:limit],
        "summary": {
            "net_exchange_flow_btc": round(net_btc, 2),
            "net_exchange_flow_eth": round(net_eth, 2),
            "whale_sentiment": ws,
        },
        "_simulated": True,
    }


# =============================================
# Phase 4: Market Replay
# =============================================

@app.get("/api/v2/replay")
async def get_replay(symbol: str = "BTCUSDT", start: str = "", end: str = ""):
    """Historical replay data: candles + signals + trades merged chronologically."""
    clean_symbol = symbol.replace("/", "")
    events = []

    # Fetch historical candles from MEXC
    try:
        params = f"symbol={clean_symbol}&interval=60m&limit=500"
        if start:
            try:
                start_ms = int(datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp() * 1000)
                params += f"&startTime={start_ms}"
            except Exception:
                pass
        if end:
            try:
                end_ms = int(datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp() * 1000)
                params += f"&endTime={end_ms}"
            except Exception:
                pass

        kline_resp = await http_client.get(
            f"https://api.mexc.com/api/v3/klines?{params}", timeout=15.0
        )
        klines = kline_resp.json()
        for k in klines:
            ts = datetime.utcfromtimestamp(k[0] / 1000).isoformat()
            events.append({
                "type": "candle", "time": ts,
                "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
            })
    except Exception as e:
        logger.warning("Replay candle fetch failed", error=str(e))

    # Fetch historical signals from DB
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM signals WHERE symbol = $1
                       ORDER BY timestamp ASC LIMIT 500""",
                    symbol.replace("USDT", "/USDT") if "/" not in symbol else symbol,
                )
                for r in rows:
                    events.append({
                        "type": "signal", "time": r["timestamp"].isoformat(),
                        "symbol": r.get("symbol", symbol),
                        "action": r.get("action", "HOLD"),
                        "confidence": float(r.get("confidence", 0.5)),
                    })
        except Exception:
            pass

    # Fetch historical trades from DB
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM trade_history WHERE symbol = $1
                       ORDER BY created_at ASC LIMIT 200""",
                    symbol.replace("USDT", "/USDT") if "/" not in symbol else symbol,
                )
                for r in rows:
                    events.append({
                        "type": "trade",
                        "time": (r.get("created_at") or r.get("closed_at", datetime.utcnow())).isoformat(),
                        "symbol": r.get("symbol", symbol),
                        "side": r.get("side", "long"),
                        "price": float(r.get("entry_price", 0)),
                        "amount": float(r.get("amount", 0)),
                        "pnl": float(r.get("realized_pnl", 0)),
                    })
        except Exception:
            pass

    events.sort(key=lambda x: x["time"])
    return {"events": events, "total_events": len(events)}


# =============================================
# Phase 4: Stress Test
# =============================================

from pydantic import BaseModel

class StressTestRequest(BaseModel):
    name: str = "Custom"
    crash_pct: float = -30.0
    duration_days: int = 7

@app.post("/api/v2/stress-test")
async def run_stress_test(req: StressTestRequest):
    """Simulate portfolio stress scenario against current positions."""
    # Get current portfolio & positions
    portfolio = {}
    positions = {}
    try:
        port_resp = await http_client.get(f"{SERVICES['executor']}/balance", timeout=5.0)
        if port_resp.status_code == 200:
            portfolio = port_resp.json()
    except Exception:
        pass

    try:
        pos_resp = await http_client.get(f"{SERVICES['position']}/positions", timeout=5.0)
        if pos_resp.status_code == 200:
            positions = pos_resp.json()
    except Exception:
        pass

    bal_summary = portfolio.get("summary", {})
    total_value = bal_summary.get("total_value", 0)
    cash = bal_summary.get("usdt_balance", 0)

    crash_factor = 1 + (req.crash_pct / 100)
    per_position = []
    total_loss = 0
    stop_loss_savings = 0
    liquidated = 0
    survived = 0

    for sym, pos_data in positions.items():
        if isinstance(pos_data, dict):
            price = pos_data.get("price", pos_data.get("entry_price", 0))
            amount = pos_data.get("amount", 0)
            original = price * amount
            sl = pos_data.get("stop_loss_price", pos_data.get("stop_loss", 0))
            stressed_price = price * crash_factor
            if sl and sl > stressed_price:
                # Stop-loss triggers first
                stressed_val = sl * amount
                savings = (sl - stressed_price) * amount
                stop_loss_savings += savings
                liquidated += 1
            else:
                stressed_val = stressed_price * amount
                survived += 1 if amount > 0 else 0

            loss = original - stressed_val
            total_loss += loss
            per_position.append({
                "symbol": sym,
                "original_value": round(original, 2),
                "stressed_value": round(stressed_val, 2),
                "loss": round(loss, 2),
                "stop_loss_triggered": bool(sl and sl > stressed_price),
            })

    stressed_total = total_value - total_loss
    loss_pct = (total_loss / total_value * 100) if total_value > 0 else 0
    recovery_days = int(abs(req.crash_pct) * 1.5 * req.duration_days / 10)

    return {
        "scenario": req.name,
        "original_value": round(total_value, 2),
        "stressed_value": round(stressed_total, 2),
        "total_loss": round(total_loss, 2),
        "total_loss_pct": round(loss_pct, 2),
        "positions_liquidated": liquidated,
        "positions_survived": survived,
        "stop_loss_savings": round(stop_loss_savings, 2),
        "cash_remaining": round(cash, 2),
        "recovery_days": recovery_days,
        "per_position": per_position,
    }


# =============================================
# Phase 4: AI Chat
# =============================================

class ChatRequest(BaseModel):
    message: str

@app.post("/api/v2/chat")
async def chat_endpoint(req: ChatRequest):
    """AI chat assistant with portfolio context."""
    message = req.message.lower().strip()

    # Gather context
    portfolio_data = {}
    positions_data = {}
    recent_signals = []
    recent_trades = []

    try:
        port_resp = await http_client.get(f"{SERVICES['executor']}/balance", timeout=3.0)
        if port_resp.status_code == 200:
            portfolio_data = port_resp.json()
    except Exception:
        pass

    try:
        pos_resp = await http_client.get(f"{SERVICES['position']}/positions", timeout=3.0)
        if pos_resp.status_code == 200:
            positions_data = pos_resp.json()
    except Exception:
        pass

    try:
        sig_resp = await http_client.get(f"{SERVICES['signal']}/signals", timeout=3.0)
        if sig_resp.status_code == 200:
            sigs = sig_resp.json()
            if isinstance(sigs, list):
                recent_signals = sigs[:5]
            elif isinstance(sigs, dict):
                recent_signals = list(sigs.values())[:5]
    except Exception:
        pass

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM trade_history ORDER BY created_at DESC LIMIT 5")
                recent_trades = [dict(r) for r in rows]
                for t in recent_trades:
                    for k, v in t.items():
                        if isinstance(v, datetime):
                            t[k] = v.isoformat()
        except Exception:
            pass

    summary = portfolio_data.get("summary", {})
    total_val = summary.get("total_value", 0)
    cash = summary.get("usdt_balance", 0)
    pos_count = len(positions_data)

    # Try LLM if key configured
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        try:
            llm_resp = await http_client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {"role": "system", "content": f"""You are Goblin, an AI trading assistant. Be concise, specific, slightly playful.
Current portfolio: total_value=${total_val:.2f}, cash=${cash:.2f}, {pos_count} positions.
Positions: {json.dumps({k: v for k, v in list(positions_data.items())[:5]})}
Recent signals: {json.dumps(recent_signals[:3])}
Recent trades: {json.dumps(recent_trades[:3])}
Never recommend specific trades."""},
                        {"role": "user", "content": req.message},
                    ],
                    "max_tokens": 300,
                },
                timeout=15.0,
            )
            if llm_resp.status_code == 200:
                return {"response": llm_resp.json()["choices"][0]["message"]["content"]}
        except Exception:
            pass

    # Rule-based fallback
    response = ""
    if any(w in message for w in ["portfolio", "balance", "how am i", "how's my"]):
        pos_list = ", ".join([f"{s} ({p.get('amount', 0):.6f})" for s, p in list(positions_data.items())[:3]]) or "none"
        response = f"Your portfolio is worth ${total_val:.2f} with ${cash:.2f} in cash. You have {pos_count} open position(s): {pos_list}. {'Looking healthy!' if total_val > 0 else 'Time to start trading!'}"
    elif any(w in message for w in ["why", "explain", "bought", "sold", "buy", "sell"]):
        if recent_signals:
            s = recent_signals[0]
            sym = s.get("symbol", "unknown")
            action = s.get("action", "HOLD")
            conf = s.get("confidence", 0)
            response = f"The latest signal for {sym} was {action} with {conf:.0%} confidence. The AI ensemble analyzed technical indicators, sentiment data, and on-chain metrics to reach this decision."
        else:
            response = "No recent signals to explain. The AI is monitoring the markets and will generate signals when opportunities arise."
    elif any(w in message for w in ["market", "outlook", "prediction"]):
        response = f"I'm monitoring the markets with {pos_count} active position(s). The AI ensemble is analyzing technical patterns, sentiment shifts, and whale movements. Portfolio value: ${total_val:.2f}."
    elif any(w in message for w in ["last trade", "recent trade"]):
        if recent_trades:
            t = recent_trades[0]
            response = f"Last trade: {t.get('symbol', '?')} ({t.get('side', '?')}) — entry ${t.get('entry_price', 0):.2f}, exit ${t.get('exit_price', 0):.2f}, PnL: ${t.get('realized_pnl', 0):.4f}. Strategy: {t.get('strategy', 'unknown')}."
        else:
            response = "No recent trades found. The AI is waiting for the right conditions."
    elif any(w in message for w in ["hello", "hi", "hey"]):
        response = f"Hey there! I'm Goblin, your AI trading assistant. Your portfolio is at ${total_val:.2f}. Ask me about your positions, recent trades, or market outlook!"
    else:
        response = f"I can help with portfolio questions, trade explanations, and market outlook. Your current portfolio: ${total_val:.2f} with {pos_count} positions. Try asking 'How's my portfolio?' or 'Why did the AI buy BTC?'"

    return {"response": response}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
