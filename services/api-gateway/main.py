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
POSTGRES_DB = os.getenv("POSTGRES_DB", "mangococo")
POSTGRES_USER = os.getenv("POSTGRES_USER", "mangococo")
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


app = FastAPI(title="MangoCoco API Gateway", version="2.0.0", lifespan=lifespan)
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

        # Compute summary
        risk_data = portfolio.get("risk", {})
        portfolio["summary"] = {
            "total_value": risk_data.get("total_value", 0),
            "cash_balance": risk_data.get("available_capital", 0),
            "positions_value": portfolio.get("total_unrealized_pnl", 0),
            "daily_pnl": risk_data.get("daily_pnl", 0),
            "open_positions": portfolio.get("open_positions_count", 0),
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


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
