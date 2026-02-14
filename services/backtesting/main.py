"""
Backtesting Service for MangoCoco Crypto Trading Platform.

FastAPI service (port 8011) that replays historical data through the
prediction/risk pipeline and computes performance metrics.  Supports
multiple strategies (ML ensemble, technical, sentiment) for comparison.
"""
import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

import db
from data_loader import build_backtest_dataframe
from engine import BacktestEngine
from strategies import get_strategy, STRATEGY_MAP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

BACKTEST_RUNS_TOTAL = Counter(
    "backtest_runs_total", "Total backtest runs started", ["strategy"],
)
BACKTEST_DURATION = Histogram(
    "backtest_duration_seconds", "Backtest run duration",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)
BACKTEST_ACTIVE = Gauge(
    "backtest_active_runs", "Currently running backtests",
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BacktestRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, description="Trading pair symbols")
    start_date: datetime = Field(..., description="Backtest start date")
    end_date: datetime = Field(..., description="Backtest end date")
    strategy: str = Field(default="ml_ensemble", description="Strategy name")
    initial_capital: float = Field(default=10000.0, gt=0)
    maker_fee: float = Field(default=0.001, ge=0)
    taker_fee: float = Field(default=0.001, ge=0)
    slippage_pct: float = Field(default=0.0003, ge=0)
    max_positions: int = Field(default=5, ge=1)
    position_size_pct: float = Field(default=0.20, gt=0, le=1.0)
    timeframe: str = Field(default="1m")
    strategy_params: Dict[str, Any] = Field(default_factory=dict)


class BacktestStatusResponse(BaseModel):
    run_id: int
    status: str
    strategy: str
    symbols: List[str]
    message: str = ""


class BacktestResultResponse(BaseModel):
    run_id: int
    strategy_name: str
    symbols: List[str]
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: Optional[float] = None
    total_trades: Optional[int] = None
    win_rate: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    profit_factor: Optional[float] = None
    params: Optional[Dict[str, Any]] = None
    report: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    status: str = "completed"


# ---------------------------------------------------------------------------
# In-memory tracking for running backtests
# ---------------------------------------------------------------------------

_running_backtests: Dict[int, str] = {}  # run_id -> status
_backtest_reports: Dict[int, Dict[str, Any]] = {}  # run_id -> full report


# ---------------------------------------------------------------------------
# Background backtest runner
# ---------------------------------------------------------------------------

async def _run_backtest(run_id: int, request: BacktestRequest):
    """Execute backtest in background and store results."""
    import time

    _running_backtests[run_id] = "running"
    BACKTEST_ACTIVE.inc()
    BACKTEST_RUNS_TOTAL.labels(strategy=request.strategy).inc()
    start_time = time.monotonic()

    try:
        pool = db.get_pool()
        if pool is None:
            _running_backtests[run_id] = "failed"
            logger.error("Database pool not available", run_id=run_id)
            return

        # Load data
        logger.info(
            "Loading backtest data",
            run_id=run_id,
            symbols=request.symbols,
            start=request.start_date.isoformat(),
            end=request.end_date.isoformat(),
        )
        features_df = await build_backtest_dataframe(
            pool,
            request.symbols,
            request.start_date,
            request.end_date,
            request.timeframe,
        )

        if features_df.empty:
            _running_backtests[run_id] = "failed"
            await db.update_run_results(run_id, request.initial_capital, 0, 0, 0, 0, 0)
            logger.warning("No data available for backtest", run_id=run_id)
            return

        # Generate signals using strategy
        strategy = get_strategy(request.strategy, **request.strategy_params)
        signals_df = strategy.generate_signals(features_df)

        logger.info(
            "Signals generated",
            run_id=run_id,
            strategy=request.strategy,
            total_signals=len(signals_df),
        )

        # Run engine
        engine = BacktestEngine(
            initial_capital=request.initial_capital,
            maker_fee=request.maker_fee,
            taker_fee=request.taker_fee,
            slippage_pct=request.slippage_pct,
            max_positions=request.max_positions,
            position_size_pct=request.position_size_pct,
        )

        result = engine.run(features_df, signals_df)

        # Store trades in DB
        trade_dicts = [t.to_dict() for t in result.trades]
        await db.insert_trades(run_id, trade_dicts)

        # Store equity curve
        equity_dicts = [e.to_dict() for e in result.equity_curve]
        await db.insert_equity_points(run_id, equity_dicts)

        # Update run with results
        report = result.report
        await db.update_run_results(
            run_id=run_id,
            final_capital=result.final_capital,
            total_trades=report.get("total_trades", 0),
            win_rate=report.get("win_rate", 0),
            sharpe_ratio=report.get("sharpe_ratio", 0),
            max_drawdown=report.get("max_drawdown", 0),
            profit_factor=report.get("profit_factor", 0),
        )

        _backtest_reports[run_id] = report
        _running_backtests[run_id] = "completed"

        elapsed = time.monotonic() - start_time
        BACKTEST_DURATION.observe(elapsed)

        logger.info(
            "Backtest completed",
            run_id=run_id,
            elapsed_s=round(elapsed, 2),
            trades=report.get("total_trades", 0),
            return_pct=report.get("total_return_pct", 0),
        )

    except Exception as exc:
        _running_backtests[run_id] = "failed"
        logger.error("Backtest failed", run_id=run_id, error=str(exc))
    finally:
        BACKTEST_ACTIVE.dec()


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Backtesting Service")

    await db.init_pool()
    await db.ensure_tables()

    yield

    await db.close_pool()
    logger.info("Backtesting Service stopped")


# ---------------------------------------------------------------------------
# FastAPI app + routes
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Backtesting Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    pool = db.get_pool()
    return {
        "status": "healthy",
        "database": "connected" if pool is not None else "disconnected",
        "active_backtests": int(BACKTEST_ACTIVE._value.get()),
        "strategies_available": list(STRATEGY_MAP.keys()),
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()


@app.post("/backtest", response_model=BacktestStatusResponse)
async def start_backtest(request: BacktestRequest):
    """Start a new backtest run."""
    # Validate strategy
    if request.strategy not in STRATEGY_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{request.strategy}'. Available: {list(STRATEGY_MAP.keys())}",
        )

    if request.start_date >= request.end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    # Create DB record
    params = {
        "maker_fee": request.maker_fee,
        "taker_fee": request.taker_fee,
        "slippage_pct": request.slippage_pct,
        "max_positions": request.max_positions,
        "position_size_pct": request.position_size_pct,
        "timeframe": request.timeframe,
        "strategy_params": request.strategy_params,
    }

    run_id = await db.create_run(
        strategy_name=request.strategy,
        symbols=request.symbols,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=request.initial_capital,
        params=params,
    )

    # Launch in background
    asyncio.create_task(_run_backtest(run_id, request))

    return BacktestStatusResponse(
        run_id=run_id,
        status="started",
        strategy=request.strategy,
        symbols=request.symbols,
        message=f"Backtest {run_id} started. Poll GET /backtest/{run_id} for results.",
    )


@app.get("/backtest/{run_id}", response_model=BacktestResultResponse)
async def get_backtest(run_id: int):
    """Get backtest results by run ID."""
    row = await db.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")

    status = _running_backtests.get(run_id, "completed" if row.get("final_capital") is not None else "pending")
    report = _backtest_reports.get(run_id)

    return BacktestResultResponse(
        run_id=row["id"],
        strategy_name=row["strategy_name"],
        symbols=row["symbols"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        initial_capital=row["initial_capital"],
        final_capital=row.get("final_capital"),
        total_trades=row.get("total_trades"),
        win_rate=row.get("win_rate"),
        sharpe_ratio=row.get("sharpe_ratio"),
        max_drawdown=row.get("max_drawdown"),
        profit_factor=row.get("profit_factor"),
        params=json.loads(row["params"]) if row.get("params") else None,
        report=report,
        created_at=row.get("created_at"),
        status=status,
    )


@app.get("/backtests")
async def list_backtests(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List all backtest runs."""
    runs = await db.list_runs(limit=limit, offset=offset)
    results = []
    for row in runs:
        status = _running_backtests.get(
            row["id"],
            "completed" if row.get("final_capital") is not None else "pending",
        )
        results.append({
            "run_id": row["id"],
            "strategy_name": row["strategy_name"],
            "symbols": row["symbols"],
            "start_date": row["start_date"].isoformat() if row.get("start_date") else None,
            "end_date": row["end_date"].isoformat() if row.get("end_date") else None,
            "initial_capital": row["initial_capital"],
            "final_capital": row.get("final_capital"),
            "total_trades": row.get("total_trades"),
            "win_rate": row.get("win_rate"),
            "sharpe_ratio": row.get("sharpe_ratio"),
            "max_drawdown": row.get("max_drawdown"),
            "profit_factor": row.get("profit_factor"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "status": status,
        })
    return results


@app.get("/backtest/{run_id}/trades")
async def get_backtest_trades(run_id: int):
    """Get all trades from a backtest run."""
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")

    trades = await db.get_trades(run_id)
    return {
        "run_id": run_id,
        "total_trades": len(trades),
        "trades": trades,
    }


@app.get("/backtest/{run_id}/equity_curve")
async def get_equity_curve(run_id: int):
    """Get equity curve data points from a backtest run."""
    run = await db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")

    points = await db.get_equity_curve(run_id)
    return {
        "run_id": run_id,
        "initial_capital": run["initial_capital"],
        "final_capital": run.get("final_capital"),
        "points": points,
    }


@app.get("/strategies")
async def list_strategies():
    """List available strategies and their parameters."""
    return {
        name: {
            "name": name,
            "description": cls.__doc__.strip().split("\n")[0] if cls.__doc__ else "",
        }
        for name, cls in STRATEGY_MAP.items()
    }
