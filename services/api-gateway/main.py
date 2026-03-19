"""
API Gateway v2.0 - Central entry point for all services.
Serves REST API for the Next.js dashboard and SSE for real-time updates.
"""
import asyncio
import json
import os
import uuid
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
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "goblin")
POSTGRES_USER = os.getenv("POSTGRES_USER", "goblin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", 1000.0))

SERVICES = {
    "market_data": "http://localhost:8001",
    "prediction": "http://localhost:8002",
    "signal": "http://localhost:8003",
    "risk": "http://localhost:8004",
    "executor": "http://localhost:8005",
    "position": "http://localhost:8006",
    "feature_store": "http://localhost:8007",
    "sentiment": "http://localhost:8008",
    "trend": "http://localhost:8009",
    "portfolio_optimizer": "http://localhost:8010",
    "backtesting": "http://localhost:8011",
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


async def periodic_ai_summary():
    """Background task that logs a system summary every 5 minutes."""
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            # Gather basic system state
            healthy_count = 0
            total_count = len(SERVICES)
            for name, url in SERVICES.items():
                try:
                    resp = await http_client.get(f"{url}/health", timeout=3.0)
                    if resp.status_code == 200:
                        healthy_count += 1
                except Exception:
                    pass

            today = datetime.utcnow().strftime("%Y-%m-%d")
            total_events = 0
            try:
                total_events = int(await redis_client.hget(f"ai:stats:{today}", "total") or 0)
            except Exception:
                pass

            await log_ai_activity(
                category=AILogCategory.SYSTEM,
                action="periodic_summary",
                level=AILogLevel.INFO,
                details={
                    "healthy_services": healthy_count,
                    "total_services": total_count,
                    "ai_events_today": total_events,
                    "uptime_check": datetime.utcnow().isoformat(),
                },
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Periodic AI summary failed", error=str(e))


async def _take_portfolio_snapshot():
    """Insert a portfolio snapshot into TimescaleDB. Reused by periodic and event-driven triggers."""
    if db_pool is None or http_client is None:
        return

    total_value = 0.0
    cash = 0.0
    daily_pnl = 0.0

    # Fetch from executor (primary source)
    try:
        bal_resp = await http_client.get(f"{SERVICES['executor']}/balance", timeout=5.0)
        if bal_resp.status_code == 200:
            bal_data = bal_resp.json()
            summary = bal_data.get("summary", {})
            total_value = float(summary.get("total_value", 0))
            cash = float(summary.get("usdt_balance", 0))
            daily_pnl = float(summary.get("pnl", 0))
    except Exception:
        pass

    # Fallback to risk service
    if total_value == 0:
        try:
            risk_resp = await http_client.get(f"{SERVICES['risk']}/portfolio", timeout=5.0)
            if risk_resp.status_code == 200:
                risk_data = risk_resp.json()
                total_value = float(risk_data.get("total_value", 0))
                cash = float(risk_data.get("available_capital", 0))
                daily_pnl = float(risk_data.get("daily_pnl", 0))
        except Exception:
            pass

    positions_value = max(0.0, total_value - cash)

    if total_value > 0:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO portfolio_snapshots (time, total_value, cash_balance, positions_value, daily_pnl)
                   VALUES (NOW(), $1, $2, $3, $4)""",
                total_value, cash, positions_value, daily_pnl,
            )
        logger.debug("Portfolio snapshot saved", total_value=round(total_value, 2))


async def periodic_portfolio_snapshot():
    """Background task: write a portfolio snapshot every 5 minutes."""
    while True:
        try:
            await asyncio.sleep(300)
            await _take_portfolio_snapshot()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Portfolio snapshot failed", error=str(e))


async def trade_event_snapshot_listener():
    """Background task: listen for trade events on Redis and trigger immediate snapshots."""
    backoff = 1
    while True:
        pubsub = None
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("trade_events", "position_closed")
            backoff = 1
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        await _take_portfolio_snapshot()
                    except Exception as e:
                        logger.debug("Event-driven snapshot failed", error=str(e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Trade event listener error", error=str(e))
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


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

    # Log startup
    await log_ai_activity(
        category=AILogCategory.SYSTEM,
        action="startup",
        level=AILogLevel.INFO,
        details={
            "version": "2.0.0",
            "services_configured": list(SERVICES.keys()),
            "redis_host": REDIS_HOST,
        },
    )

    # Start background tasks
    summary_task = asyncio.create_task(periodic_ai_summary())
    snapshot_task = asyncio.create_task(periodic_portfolio_snapshot())
    trade_snapshot_task = asyncio.create_task(trade_event_snapshot_listener())

    yield

    # Cancel background tasks
    for task in (summary_task, snapshot_task, trade_snapshot_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

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
# AI Activity Logging Infrastructure
# =============================================

class AILogCategory:
    SIGNAL = "signal"
    PREDICTION = "prediction"
    TRADE = "trade"
    RISK = "risk"
    CHAT = "chat"
    SYSTEM = "system"
    SENTIMENT = "sentiment"
    PORTFOLIO = "portfolio"


class AILogLevel:
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


async def log_ai_activity(
    category: str,
    action: str,
    level: str = AILogLevel.INFO,
    symbol: str = "",
    confidence: float = 0.0,
    details: dict = None,
    chain_id: str = "",
):
    """
    Log an AI activity event to Redis. Stores in lists, publishes to SSE,
    and tracks daily stats. Never raises -- errors are silently logged.
    """
    try:
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "category": category,
            "action": action,
            "level": level,
            "symbol": symbol,
            "confidence": confidence,
            "details": details or {},
        }
        if chain_id:
            entry["chain_id"] = chain_id

        entry_json = json.dumps(entry)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        expire_seconds = 30 * 24 * 3600  # 30 days

        pipe = redis_client.pipeline()

        # Main log list (capped at 10000)
        pipe.lpush("ai:logs", entry_json)
        pipe.ltrim("ai:logs", 0, 9999)

        # Per-category list (capped at 1000)
        cat_key = f"ai:logs:{category}"
        pipe.lpush(cat_key, entry_json)
        pipe.ltrim(cat_key, 0, 999)

        # Publish to SSE channel
        pipe.publish("ai:activity", entry_json)

        # Daily stats hash
        stats_key = f"ai:stats:{today}"
        pipe.hincrby(stats_key, "total", 1)
        pipe.hincrby(stats_key, f"cat:{category}", 1)
        pipe.hincrby(stats_key, f"level:{level}", 1)
        if symbol:
            pipe.hincrby(stats_key, f"symbol:{symbol}", 1)
        pipe.expire(stats_key, expire_seconds)

        # Daily confidence tracking
        if confidence > 0:
            conf_key = f"ai:confidence:{today}"
            pipe.rpush(conf_key, json.dumps({"category": category, "confidence": confidence}))
            pipe.expire(conf_key, expire_seconds)

        await pipe.execute()
        logger.debug("AI activity logged", category=category, action=action, level=level)
    except Exception as e:
        logger.warning("Failed to log AI activity", error=str(e))


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
        daily_pnl = paper.get("pnl", 0) or risk_data.get("daily_pnl", 0)
        starting_capital = risk_data.get("starting_capital", 1000.0)
        positions_dict = paper.get("positions", {})
        open_count = len(positions_dict) if positions_dict else portfolio.get("open_positions_count", 0)

        # Merge executor positions into the positions list for complete view
        pos_service_positions = portfolio.get("positions", {})
        for sym, exec_pos in positions_dict.items():
            if sym not in pos_service_positions:
                pos_service_positions[sym] = {
                    "symbol": sym,
                    "side": "long",
                    "entry_price": exec_pos.get("price", 0),
                    "current_price": exec_pos.get("price", 0),
                    "amount": exec_pos.get("amount", 0),
                    "unrealized_pnl": 0,
                    "status": "open",
                }
        portfolio["positions"] = pos_service_positions
        portfolio["open_positions_count"] = len(pos_service_positions)

        # Calculate PnL percentage based on starting capital
        pnl_pct = (daily_pnl / starting_capital * 100) if starting_capital > 0 else 0

        portfolio["summary"] = {
            "total_value": total_value,
            "cash_balance": cash,
            "positions_value": positions_value,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": round(pnl_pct, 2),
            "starting_capital": starting_capital,
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
        data = response.json()
        # Log when signals contain actionable data
        if data:
            signal_count = len(data) if isinstance(data, list) else len(data) if isinstance(data, dict) else 0
            if signal_count > 0:
                await log_ai_activity(
                    category=AILogCategory.SIGNAL,
                    action="signals_fetched",
                    level=AILogLevel.INFO,
                    details={"signal_count": signal_count},
                )
        return data
    except Exception as e:
        return []


@app.get("/api/v2/analytics")
async def get_analytics():
    """Get performance analytics for dashboard."""
    analytics = {
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "win_rate": 0,
        "profit_factor": 0,
        "max_drawdown": None,
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

            # Fetch per-trade returns for Sharpe / Sortino
            pnl_rows = await conn.fetch(
                "SELECT pnl_pct FROM trade_history WHERE pnl_pct IS NOT NULL ORDER BY created_at ASC"
            )
            returns = [float(r["pnl_pct"]) for r in pnl_rows]

            if len(returns) >= 5:
                avg_ret = sum(returns) / len(returns)

                # Sharpe ratio: (mean / std) * sqrt(252)
                variance = sum((r - avg_ret) ** 2 for r in returns) / (len(returns) - 1)
                std_dev = variance ** 0.5 if variance > 0 else 0
                if std_dev > 0:
                    analytics["sharpe_ratio"] = round((avg_ret / std_dev) * 252 ** 0.5, 4)

                # Sortino ratio: (mean / downside_dev) * sqrt(252)
                negative_returns = [r for r in returns if r < 0]
                if negative_returns:
                    downside_var = sum(r ** 2 for r in negative_returns) / len(returns)
                    downside_dev = downside_var ** 0.5
                    if downside_dev > 0:
                        analytics["sortino_ratio"] = round((avg_ret / downside_dev) * 252 ** 0.5, 4)

            # Max drawdown from portfolio snapshots (walk peak-to-trough)
            snapshots = await conn.fetch(
                "SELECT time, total_value FROM portfolio_snapshots ORDER BY time ASC"
            )
            if len(snapshots) > 1:
                peak = 0.0
                max_dd = 0.0
                for snap in snapshots:
                    val = float(snap["total_value"])
                    if val > peak:
                        peak = val
                    if peak > 0:
                        dd = (val - peak) / peak * 100
                        if dd < max_dd:
                            max_dd = dd
                analytics["max_drawdown"] = round(max_dd, 4)
            elif returns:
                # Fallback: reconstruct equity from trades + starting capital
                equity_val = STARTING_CAPITAL
                peak = equity_val
                max_dd = 0.0
                for r in returns:
                    equity_val *= (1 + r / 100)
                    if equity_val > peak:
                        peak = equity_val
                    if peak > 0:
                        dd = (equity_val - peak) / peak * 100
                        if dd < max_dd:
                            max_dd = dd
                analytics["max_drawdown"] = round(max_dd, 4)

            # Total return percentage
            if len(snapshots) > 1:
                first_val = float(snapshots[0]["total_value"])
                last_val = float(snapshots[-1]["total_value"])
                if first_val > 0:
                    analytics["total_return_pct"] = round((last_val - first_val) / first_val * 100, 4)
            elif stats and float(stats["total_pnl"]) != 0:
                analytics["total_return_pct"] = round(float(stats["total_pnl"]) / STARTING_CAPITAL * 100, 4)

            # Monthly returns
            monthly_rows = await conn.fetch("""
                SELECT date_trunc('month', closed_at) as month,
                       sum(realized_pnl) as monthly_pnl
                FROM trade_history
                WHERE closed_at IS NOT NULL
                GROUP BY date_trunc('month', closed_at)
                ORDER BY month ASC
            """)
            analytics["monthly_returns"] = {
                r["month"].strftime("%Y-%m"): round(float(r["monthly_pnl"]), 4)
                for r in monthly_rows
            }

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
    import asyncio

    async def _check_service(name: str, url: str) -> dict:
        entry = {"name": name, "url": url, "status": "unknown", "uptime": None, "last_heartbeat": None}
        try:
            response = await http_client.get(f"{url}/health", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                # Respect the service's own reported status (e.g. "degraded")
                # instead of always marking 200 as healthy.
                reported = data.get("status", "healthy") if isinstance(data, dict) else "healthy"
                entry["status"] = reported if reported in ("healthy", "degraded") else "healthy"
                entry["data"] = data
                entry["last_heartbeat"] = datetime.utcnow().isoformat()
            else:
                entry["status"] = "degraded"
        except Exception as e:
            entry["status"] = "down"
            entry["error"] = str(e)
        return entry

    # Check all services in parallel instead of sequentially.
    # Worst case is now 5s (single timeout) instead of 55s (11 × 5s).
    services = await asyncio.gather(
        *[_check_service(name, url) for name, url in SERVICES.items()]
    )

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

    # Log system health check as AI activity
    healthy_count = sum(1 for s in services if s["status"] == "healthy")
    down_count = sum(1 for s in services if s["status"] == "down")
    if down_count > 0:
        await log_ai_activity(
            category=AILogCategory.SYSTEM,
            action="health_check",
            level=AILogLevel.WARNING,
            details={
                "healthy": healthy_count,
                "down": down_count,
                "down_services": [s["name"] for s in services if s["status"] == "down"],
            },
        )

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
        # Subscribe to key channels including AI activity
        await pubsub.psubscribe(
            "ticks:BTC_USDT", "ticks:ETH_USDT", "ticks:SOL_USDT",
            "filled_orders", "position_opened", "position_closed",
            "sentiment_update", "trend_update",
        )
        await pubsub.subscribe("ai:activity")

        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] in ("message", "pmessage"):
                    try:
                        data = json.loads(message["data"])
                        channel = message.get("channel", message.get("pattern", ""))

                        if channel == "ai:activity":
                            event = {"type": "ai_activity", **data}
                        elif "ticks:" in channel:
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
    """Get real resource metrics from supervisor-managed processes using psutil + nvidia-smi."""

    def _collect_metrics():
        import psutil
        import subprocess
        import time as _time

        resources = []

        # ── Map supervisor program names to service names and PIDs ──
        svc_pid_map = {}
        try:
            result = subprocess.run(
                ["supervisorctl", "status"], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "RUNNING":
                    raw_name = parts[0].split(":")[-1]
                    svc_name = raw_name.replace("goblin-", "").replace("-", "_")
                    pid_str = parts[3].rstrip(",")
                    try:
                        svc_pid_map[svc_name] = int(pid_str)
                    except ValueError:
                        pass
        except Exception:
            pass

        # ── System totals ──
        cpu_count = psutil.cpu_count(logical=True) or 96
        mem_info = psutil.virtual_memory()
        total_mem_mb = mem_info.total / (1024 * 1024)

        # ── Prime CPU measurement (first call returns 0, need two samples) ──
        all_procs = {}
        for svc_name, pid in svc_pid_map.items():
            try:
                proc = psutil.Process(pid)
                proc.cpu_percent()  # prime
                children = proc.children(recursive=True)
                for c in children:
                    try:
                        c.cpu_percent()  # prime
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                all_procs[svc_name] = (proc, children)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                all_procs[svc_name] = (None, [])

        _time.sleep(0.3)  # short interval for CPU measurement

        # ── Collect per-process metrics ──
        for svc_name, pid in svc_pid_map.items():
            entry = {
                "container": svc_name,
                "status": "running",
                "cpu_percent": 0.0,
                "memory_used_mb": 0.0,
                "memory_limit_mb": round(total_mem_mb, 0),
                "memory_percent": 0.0,
                "network_rx_mb": 0.0,
                "network_tx_mb": 0.0,
                "disk_read_mb": 0.0,
                "disk_write_mb": 0.0,
                "uptime_seconds": 0,
                "restart_count": 0,
            }
            try:
                proc, children = all_procs.get(svc_name, (None, []))
                if proc is None:
                    proc = psutil.Process(pid)
                    children = proc.children(recursive=True)

                # CPU percent (second call gives real value)
                cpu_pct = proc.cpu_percent()
                for child in children:
                    try:
                        cpu_pct += child.cpu_percent()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                entry["cpu_percent"] = round(cpu_pct, 2)

                # Memory (RSS including children)
                mem = proc.memory_info()
                rss = mem.rss
                for child in children:
                    try:
                        rss += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                rss_mb = rss / (1024 * 1024)
                entry["memory_used_mb"] = round(rss_mb, 1)
                entry["memory_percent"] = round((rss / mem_info.total) * 100, 2)

                # I/O counters
                try:
                    io = proc.io_counters()
                    entry["disk_read_mb"] = round(io.read_bytes / (1024 * 1024), 2)
                    entry["disk_write_mb"] = round(io.write_bytes / (1024 * 1024), 2)
                except (psutil.AccessDenied, AttributeError):
                    pass

                # Uptime
                entry["uptime_seconds"] = int(psutil.time.time() - proc.create_time())

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                entry["status"] = "stopped"

            resources.append(entry)

        # ── Add Redis (via psutil, find by port) ──
        redis_entry = {
            "container": "redis", "status": "stopped",
            "cpu_percent": 0, "memory_used_mb": 0, "memory_limit_mb": round(total_mem_mb, 0),
            "memory_percent": 0, "network_rx_mb": 0, "network_tx_mb": 0,
            "disk_read_mb": 0, "disk_write_mb": 0, "uptime_seconds": 0, "restart_count": 0,
        }
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if "redis-server" in (proc.info.get("name") or ""):
                    p = psutil.Process(proc.info["pid"])
                    redis_entry["status"] = "running"
                    redis_entry["cpu_percent"] = round(p.cpu_percent(interval=0), 2)
                    redis_entry["memory_used_mb"] = round(p.memory_info().rss / (1024 * 1024), 1)
                    redis_entry["memory_percent"] = round((p.memory_info().rss / mem_info.total) * 100, 2)
                    redis_entry["uptime_seconds"] = int(psutil.time.time() - p.create_time())
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        resources.append(redis_entry)

        # ── Add TimescaleDB/PostgreSQL ──
        pg_entry = {
            "container": "timescaledb", "status": "stopped",
            "cpu_percent": 0, "memory_used_mb": 0, "memory_limit_mb": round(total_mem_mb, 0),
            "memory_percent": 0, "network_rx_mb": 0, "network_tx_mb": 0,
            "disk_read_mb": 0, "disk_write_mb": 0, "uptime_seconds": 0, "restart_count": 0,
        }
        pg_total_rss = 0
        pg_total_cpu = 0.0
        pg_create_time = None
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if "postgres" in (proc.info.get("name") or ""):
                    p = psutil.Process(proc.info["pid"])
                    pg_total_rss += p.memory_info().rss
                    pg_total_cpu += p.cpu_percent(interval=0)
                    ct = p.create_time()
                    if pg_create_time is None or ct < pg_create_time:
                        pg_create_time = ct
                    pg_entry["status"] = "running"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if pg_entry["status"] == "running":
            pg_entry["cpu_percent"] = round(pg_total_cpu, 2)
            pg_entry["memory_used_mb"] = round(pg_total_rss / (1024 * 1024), 1)
            pg_entry["memory_percent"] = round((pg_total_rss / mem_info.total) * 100, 2)
            if pg_create_time:
                pg_entry["uptime_seconds"] = int(psutil.time.time() - pg_create_time)
        resources.append(pg_entry)

        # ── GPU metrics ──
        gpu_entry = None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = [p.strip() for p in result.stdout.strip().split(",")]
                if len(parts) >= 7:
                    gpu_entry = {
                        "gpu_name": parts[0],
                        "gpu_memory_total_mb": float(parts[1]),
                        "gpu_memory_used_mb": float(parts[2]),
                        "gpu_memory_free_mb": float(parts[3]),
                        "gpu_utilization_percent": float(parts[4]),
                        "gpu_temperature_c": float(parts[5]),
                        "gpu_power_watts": float(parts[6]),
                    }
        except Exception:
            pass

        # ── System summary ──
        system_summary = {
            "cpu_count": cpu_count,
            "cpu_percent_total": round(psutil.cpu_percent(interval=0), 1),
            "memory_total_mb": round(total_mem_mb, 0),
            "memory_used_mb": round(mem_info.used / (1024 * 1024), 0),
            "memory_available_mb": round(mem_info.available / (1024 * 1024), 0),
            "memory_percent": round(mem_info.percent, 1),
        }
        if gpu_entry:
            system_summary["gpu"] = gpu_entry

        # ── Network I/O totals ──
        try:
            net = psutil.net_io_counters()
            system_summary["network_rx_total_mb"] = round(net.bytes_recv / (1024 * 1024), 1)
            system_summary["network_tx_total_mb"] = round(net.bytes_sent / (1024 * 1024), 1)
        except Exception:
            pass

        # Sort: known services first
        known_order = list(SERVICES.keys()) + ["learner", "redis", "timescaledb"]
        resources.sort(key=lambda x: (
            known_order.index(x["container"]) if x["container"] in known_order else 999,
            x["container"]
        ))

        return {"services": resources, "system": system_summary}

    return await asyncio.to_thread(_collect_metrics)


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

    # Gather market prices from Redis for richer context
    market_context = {}
    for pair in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        try:
            price_data = await redis_client.hgetall(f"ticker:{pair}")
            if price_data:
                market_context[pair] = price_data
        except Exception:
            pass
    # Also try the ticks key format
    if not market_context:
        for pair in ["BTC_USDT", "ETH_USDT", "SOL_USDT"]:
            try:
                price_data = await redis_client.hgetall(f"price:{pair}")
                if price_data:
                    market_context[pair] = price_data
            except Exception:
                pass

    # Try Gemini AI (new google.genai SDK)
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    used_gemini = False
    if gemini_key:
        try:
            from google import genai as genai_client

            system_context = f"""You are Goblin AI, the intelligent assistant for the Goblin AI Trading Platform.
You have access to real-time portfolio data, market signals, and trading history.
You help traders understand their positions, market conditions, and AI model predictions.
Be concise, data-driven, and actionable. Use the provided context data in your responses.
Never recommend specific trades or give financial advice. Always remind users this is paper trading.

CURRENT PLATFORM DATA:
- Portfolio: total_value=${total_val:.2f}, cash=${cash:.2f}, {pos_count} open position(s)
- Positions: {json.dumps({k: v for k, v in list(positions_data.items())[:5]}) if positions_data else 'No open positions'}
- Recent signals: {json.dumps(recent_signals[:3]) if recent_signals else 'No recent signals'}
- Recent trades: {json.dumps(recent_trades[:3], default=str) if recent_trades else 'No recent trades'}
- Market prices: {json.dumps(market_context, default=str) if market_context else 'Prices loading...'}
- Mode: Paper trading (no real money at risk)"""

            client = genai_client.Client(api_key=gemini_key)
            # Try models in order of preference
            for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                try:
                    response = await asyncio.to_thread(
                        lambda mn=model_name: client.models.generate_content(
                            model=mn,
                            contents=f"{system_context}\n\nUser question: {req.message}",
                            config={"max_output_tokens": 400, "temperature": 0.7},
                        )
                    )
                    if response and response.text:
                        used_gemini = True
                        # Determine topic from user message
                        topic = message[:50] if len(message) > 50 else message
                        await log_ai_activity(
                            category=AILogCategory.CHAT,
                            action="chat_response",
                            level=AILogLevel.INFO,
                            details={
                                "topic": topic,
                                "engine": "gemini",
                                "model": model_name,
                                "message_length": len(req.message),
                            },
                        )
                        return {"response": response.text}
                except Exception as model_err:
                    logger.warning(f"Gemini model {model_name} failed", error=str(model_err))
                    continue
        except Exception as e:
            logger.warning("Gemini API failed, falling back to rule-based", error=str(e))

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

    if not used_gemini:
        topic = message[:50] if len(message) > 50 else message
        await log_ai_activity(
            category=AILogCategory.CHAT,
            action="chat_response",
            level=AILogLevel.INFO,
            details={
                "topic": topic,
                "engine": "rule_based",
                "message_length": len(req.message),
            },
        )

    return {"response": response}


# =============================================
# Phase 5: Market Intelligence Hub
# =============================================

FUTURES_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "DOTUSDT"]


@app.get("/api/v2/market/fear-greed")
async def get_fear_greed(limit: int = 30):
    """Fear & Greed Index from Alternative.me - free, no key required."""
    try:
        resp = await http_client.get(
            f"https://api.alternative.me/fng/?limit={limit}&format=json",
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - Alternative.me")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch fear & greed data: {str(e)}")


@app.get("/api/v2/market/global")
async def get_global_market():
    """Global market data from CoinGecko - free, no key required."""
    try:
        resp = await http_client.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - CoinGecko")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch global market data: {str(e)}")


@app.get("/api/v2/market/top-coins")
async def get_top_coins(limit: int = 20):
    """Top coins by market cap from CoinGecko - free, no key required."""
    try:
        resp = await http_client.get(
            f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page={limit}&sparkline=true&price_change_percentage=1h,24h,7d",
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - CoinGecko")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch top coins: {str(e)}")


@app.get("/api/v2/market/trending")
async def get_trending():
    """Trending coins from CoinGecko - free, no key required."""
    try:
        resp = await http_client.get(
            "https://api.coingecko.com/api/v3/search/trending",
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - CoinGecko")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch trending coins: {str(e)}")


@app.get("/api/v2/market/defi")
async def get_defi_overview():
    """DeFi overview from DeFiLlama - free, no key required."""
    try:
        protocols_resp = await http_client.get("https://api.llama.fi/protocols", timeout=10.0)
        chains_resp = await http_client.get("https://api.llama.fi/chains", timeout=10.0)
        protocols_resp.raise_for_status()
        chains_resp.raise_for_status()
        protocols = protocols_resp.json()
        chains = chains_resp.json()

        total_tvl = sum(c.get("tvl") or 0 for c in chains)
        top_protocols = sorted(protocols, key=lambda p: p.get("tvl") or 0, reverse=True)[:10]
        top_chains = sorted(chains, key=lambda c: c.get("tvl") or 0, reverse=True)[:10]

        return {
            "total_tvl": total_tvl,
            "top_protocols": [{"name": p["name"], "tvl": p.get("tvl") or 0, "change_1d": p.get("change_1d") or 0, "change_7d": p.get("change_7d") or 0, "category": p.get("category") or "", "logo": p.get("logo") or ""} for p in top_protocols],
            "top_chains": [{"name": c["name"], "tvl": c.get("tvl") or 0} for c in top_chains],
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - DeFiLlama")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch DeFi data: {str(e)}")


@app.get("/api/v2/market/stablecoins")
async def get_stablecoins():
    """Stablecoin data from DeFiLlama - free, no key required."""
    try:
        resp = await http_client.get(
            "https://stablecoins.llama.fi/stablecoins?includePrices=true",
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()
        pegged = data.get("peggedAssets", [])
        top = sorted(pegged, key=lambda s: s.get("circulating", {}).get("peggedUSD", 0), reverse=True)[:10]
        total = sum(s.get("circulating", {}).get("peggedUSD", 0) for s in pegged)
        return {
            "total_supply": total,
            "top_stablecoins": [{"name": s["name"], "symbol": s["symbol"], "supply": s.get("circulating", {}).get("peggedUSD", 0), "price": s.get("price", 1.0)} for s in top],
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - DeFiLlama")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch stablecoin data: {str(e)}")


@app.get("/api/v2/market/bitcoin-network")
async def get_bitcoin_network():
    """Bitcoin network data from Mempool.space - free, no key required."""
    try:
        fees_resp = await http_client.get("https://mempool.space/api/v1/fees/recommended", timeout=10.0)
        mempool_resp = await http_client.get("https://mempool.space/api/mempool", timeout=10.0)
        hashrate_resp = await http_client.get("https://mempool.space/api/v1/mining/hashrate/1m", timeout=10.0)
        diff_resp = await http_client.get("https://mempool.space/api/v1/difficulty-adjustment", timeout=10.0)

        fees_resp.raise_for_status()
        mempool_resp.raise_for_status()
        hashrate_resp.raise_for_status()
        diff_resp.raise_for_status()

        return {
            "fees": fees_resp.json(),
            "mempool": mempool_resp.json(),
            "mining": hashrate_resp.json(),
            "difficulty": diff_resp.json(),
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - Mempool.space")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Bitcoin network data: {str(e)}")


@app.get("/api/v2/market/dex-volume")
async def get_dex_volume():
    """DEX volume data from DeFiLlama - free, no key required."""
    try:
        resp = await http_client.get(
            "https://api.llama.fi/overview/dexs?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true",
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()
        protocols = sorted(data.get("protocols", []), key=lambda p: p.get("total24h", 0) or 0, reverse=True)[:10]
        return {
            "chart": data.get("totalDataChart", []),
            "total_24h": sum(p.get("total24h", 0) or 0 for p in data.get("protocols", [])),
            "top_dexs": [{"name": p["name"], "volume_24h": p.get("total24h", 0), "change_1d": p.get("change_1d", 0)} for p in protocols],
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - DeFiLlama")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch DEX volume data: {str(e)}")


# =============================================
# Phase 5: Derivatives Intelligence
# =============================================

@app.get("/api/v2/derivatives/funding")
async def get_derivatives_funding():
    """Funding rates from Binance Futures - public, no key required."""
    try:
        premium_resp = await http_client.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            timeout=10.0
        )
        premium_resp.raise_for_status()
        all_premium = premium_resp.json()

        tracked = {p["symbol"]: p for p in all_premium if p["symbol"] in FUTURES_SYMBOLS}

        result = []
        for sym in FUTURES_SYMBOLS:
            hist_resp = await http_client.get(
                f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=8",
                timeout=10.0
            )
            hist_resp.raise_for_status()
            history = hist_resp.json()

            current = tracked.get(sym, {})
            result.append({
                "symbol": sym,
                "mark_price": float(current.get("markPrice", 0)),
                "current_rate": float(current.get("lastFundingRate", 0)),
                "next_funding_time": current.get("nextFundingTime", 0),
                "history": [{"rate": float(h["fundingRate"]), "time": h["fundingTime"]} for h in history],
            })

        return {"symbols": result}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - Binance Futures")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch funding rates: {str(e)}")


@app.get("/api/v2/derivatives/open-interest")
async def get_open_interest(symbol: str = "BTCUSDT"):
    """Open interest from Binance Futures - public, no key required."""
    try:
        oi_resp = await http_client.get(
            f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}",
            timeout=10.0
        )
        oi_resp.raise_for_status()

        hist_resp = await http_client.get(
            f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=1h&limit=48",
            timeout=10.0
        )
        hist_resp.raise_for_status()

        return {
            "current": oi_resp.json(),
            "history": hist_resp.json(),
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - Binance Futures")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch open interest: {str(e)}")


@app.get("/api/v2/derivatives/long-short")
async def get_long_short(symbol: str = "BTCUSDT"):
    """Long/short ratio from Binance Futures - public, no key required."""
    try:
        ratio_resp = await http_client.get(
            f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={symbol}&period=1h&limit=24",
            timeout=10.0
        )
        taker_resp = await http_client.get(
            f"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={symbol}&period=1h&limit=24",
            timeout=10.0
        )
        ratio_resp.raise_for_status()
        taker_resp.raise_for_status()

        return {
            "long_short_ratio": ratio_resp.json(),
            "taker_volume": taker_resp.json(),
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - Binance Futures")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch long/short data: {str(e)}")


# =============================================
# Phase 5: Correlation Matrix
# =============================================

@app.get("/api/v2/analytics/correlations")
async def get_correlations(period: str = "30d"):
    """Compute Pearson correlation between tracked assets using MEXC candle data."""
    try:
        import numpy as np

        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        limit = min(days * 24, 1000)

        returns_map: dict = {}
        for sym in symbols:
            resp = await http_client.get(
                f"https://api.mexc.com/api/v3/klines?symbol={sym}&interval=60m&limit={limit}",
                timeout=15.0
            )
            resp.raise_for_status()
            klines = resp.json()
            closes = [float(k[4]) for k in klines]
            if len(closes) > 1:
                returns_map[sym] = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]

        min_len = min(len(r) for r in returns_map.values()) if returns_map else 0
        if min_len < 10:
            raise HTTPException(status_code=400, detail="Insufficient data for correlation")

        aligned = {s: r[-min_len:] for s, r in returns_map.items()}
        sym_list = list(aligned.keys())
        matrix = np.array([aligned[s] for s in sym_list])
        corr = np.corrcoef(matrix)

        result: dict = {}
        for i, s1 in enumerate(sym_list):
            result[s1] = {}
            for j, s2 in enumerate(sym_list):
                result[s1][s2] = round(float(corr[i][j]), 4)

        return {"symbols": sym_list, "matrix": result, "period": period, "data_points": min_len}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to compute correlations: {str(e)}")


# =============================================
# Phase 5: Multi-Timeframe Candles
# =============================================

@app.get("/api/v2/candles/multi")
async def get_multi_timeframe(symbol: str = "BTCUSDT"):
    """Fetch 4 timeframes at once from MEXC - free, no key required."""
    try:
        timeframes = {"5m": "5m", "15m": "15m", "1h": "60m", "4h": "4h"}
        result: dict = {}
        for label, interval in timeframes.items():
            resp = await http_client.get(
                f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100",
                timeout=10.0
            )
            resp.raise_for_status()
            klines = resp.json()
            result[label] = [{"time": k[0] // 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in klines]
        return result
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - MEXC")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch multi-timeframe data: {str(e)}")


# =============================================
# Phase 5: Benchmark Comparison
# =============================================

@app.get("/api/v2/analytics/benchmark")
async def get_benchmark(days: int = 90):
    """Fetch historical daily closes for BTC and ETH from MEXC for benchmark comparison."""
    try:
        result: dict = {"dates": [], "btc": [], "eth": []}
        for sym, key in [("BTCUSDT", "btc"), ("ETHUSDT", "eth")]:
            resp = await http_client.get(
                f"https://api.mexc.com/api/v3/klines?symbol={sym}&interval=1d&limit={days}",
                timeout=15.0
            )
            resp.raise_for_status()
            klines = resp.json()
            closes = [float(k[4]) for k in klines]
            if closes:
                start_price = closes[0]
                normalized = [round((c / start_price) * 100, 2) for c in closes]
                result[key] = normalized
                if key == "btc":
                    result["dates"] = [datetime.utcfromtimestamp(k[0] / 1000).strftime("%Y-%m-%d") for k in klines]

        result["data_points"] = len(result["btc"])
        return result
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="External API timeout - MEXC")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"External API error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch benchmark data: {str(e)}")


# =============================================
# AI Activity Log Endpoints
# =============================================

@app.get("/api/v2/ai/logs")
async def get_ai_logs(
    category: Optional[str] = None,
    level: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """Query AI activity logs with optional filters."""
    try:
        capped_limit = min(limit, 500)
        # Fetch more than needed to account for filtering
        fetch_count = (capped_limit + offset) * 3 if (category or level or symbol) else capped_limit + offset
        fetch_count = min(fetch_count, 10000)

        raw_logs = await redis_client.lrange("ai:logs", 0, fetch_count - 1)
        entries = []
        for raw in raw_logs:
            try:
                entry = json.loads(raw)
                if category and entry.get("category") != category:
                    continue
                if level and entry.get("level") != level:
                    continue
                if symbol and entry.get("symbol") != symbol:
                    continue
                entries.append(entry)
            except (json.JSONDecodeError, TypeError):
                continue

        # Apply offset and limit (entries are already newest-first from LPUSH)
        paginated = entries[offset:offset + capped_limit]
        return paginated
    except Exception as e:
        logger.error("Failed to fetch AI logs", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/ai/logs/stream")
async def stream_ai_logs():
    """SSE endpoint for real-time AI activity events."""

    async def ai_event_generator():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("ai:activity")
        heartbeat_interval = 2.0
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    try:
                        yield f"data: {message['data']}\n\n"
                    except Exception:
                        continue
                else:
                    # Heartbeat every ~2 seconds
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                    await asyncio.sleep(heartbeat_interval)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        ai_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/api/v2/ai/stats")
async def get_ai_stats():
    """Get aggregated AI activity stats for today."""
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        stats_key = f"ai:stats:{today}"
        conf_key = f"ai:confidence:{today}"

        raw_stats = await redis_client.hgetall(stats_key)
        total_events = int(raw_stats.get("total", 0))

        events_by_category = {}
        events_by_level = {}
        top_symbols = {}
        for k, v in raw_stats.items():
            if k.startswith("cat:"):
                events_by_category[k[4:]] = int(v)
            elif k.startswith("level:"):
                events_by_level[k[6:]] = int(v)
            elif k.startswith("symbol:"):
                top_symbols[k[7:]] = int(v)

        # Sort symbols by count descending
        top_symbols = dict(sorted(top_symbols.items(), key=lambda x: x[1], reverse=True)[:20])

        # Compute average confidence by category
        avg_confidence_by_category = {}
        raw_confs = await redis_client.lrange(conf_key, 0, -1)
        cat_confs = {}
        for raw in raw_confs:
            try:
                c = json.loads(raw)
                cat = c.get("category", "unknown")
                if cat not in cat_confs:
                    cat_confs[cat] = []
                cat_confs[cat].append(c.get("confidence", 0))
            except (json.JSONDecodeError, TypeError):
                continue
        for cat, vals in cat_confs.items():
            if vals:
                avg_confidence_by_category[cat] = round(sum(vals) / len(vals), 4)

        return {
            "date": today,
            "total_events_today": total_events,
            "events_by_category": events_by_category,
            "events_by_level": events_by_level,
            "top_symbols": top_symbols,
            "avg_confidence_by_category": avg_confidence_by_category,
        }
    except Exception as e:
        logger.error("Failed to fetch AI stats", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/ai/timeline")
async def get_ai_timeline():
    """Get decision chains from AI activity logs."""
    try:
        raw_logs = await redis_client.lrange("ai:logs", 0, 9999)
        chains = {}
        for raw in raw_logs:
            try:
                entry = json.loads(raw)
                cid = entry.get("chain_id")
                if not cid:
                    continue
                if cid not in chains:
                    chains[cid] = {
                        "chain_id": cid,
                        "events": [],
                        "first_seen": entry["timestamp"],
                        "last_seen": entry["timestamp"],
                    }
                chains[cid]["events"].append(entry)
                # Update timestamps (logs are newest-first, so adjust)
                if entry["timestamp"] < chains[cid]["first_seen"]:
                    chains[cid]["first_seen"] = entry["timestamp"]
                if entry["timestamp"] > chains[cid]["last_seen"]:
                    chains[cid]["last_seen"] = entry["timestamp"]
            except (json.JSONDecodeError, TypeError):
                continue

        # Build response: sort chains by most recent activity
        result = []
        for cid, chain_data in chains.items():
            # Sort events within each chain chronologically
            chain_data["events"].sort(key=lambda e: e.get("timestamp", ""))
            # Determine outcome from the last event
            last_event = chain_data["events"][-1] if chain_data["events"] else {}
            chain_data["outcome"] = last_event.get("action", "unknown")
            chain_data["event_count"] = len(chain_data["events"])
            result.append(chain_data)

        result.sort(key=lambda c: c.get("last_seen", ""), reverse=True)
        return result
    except Exception as e:
        logger.error("Failed to fetch AI timeline", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
