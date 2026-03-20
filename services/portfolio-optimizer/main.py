"""
Portfolio Optimizer Service - Optimal position sizing via Kelly criterion
and mean-variance portfolio optimization with correlation-aware risk.

Subscribes to 'validated_signals', computes optimal position sizes,
and publishes 'sized_signals' for the executor.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import Counter, Gauge, Histogram, generate_latest

import db
from kelly import dynamic_kelly, fraction_to_usd, MIN_POSITION_USD
from correlation import compute_correlation_matrix, check_correlation_risk
from optimizer import optimize_allocations

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

PORTFOLIO_MAX_POSITION_PCT = float(os.getenv("PORTFOLIO_MAX_POSITION_PCT", 0.05))
PORTFOLIO_CASH_RESERVE_PCT = float(os.getenv("PORTFOLIO_CASH_RESERVE_PCT", 0.20))
KELLY_MODE = os.getenv("KELLY_MODE", "half")  # full / half / quarter

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
SIGNALS_RECEIVED = Counter("portopt_signals_received_total", "Validated signals received")
SIGNALS_SIZED = Counter("portopt_signals_sized_total", "Signals with position size attached")
SIGNALS_SKIPPED = Counter("portopt_signals_skipped_total", "Signals skipped", ["reason"])
KELLY_FRACTION = Gauge("portopt_kelly_fraction", "Last computed Kelly fraction", ["symbol"])
POSITION_SIZE_USD = Gauge("portopt_position_size_usd", "Last computed position size USD", ["symbol"])
PORTFOLIO_VALUE = Gauge("portopt_portfolio_value", "Current portfolio value")
OPTIMIZATION_DURATION = Histogram("portopt_optimization_seconds", "Time to run full optimization")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
redis_client: Optional[aioredis.Redis] = None

# Cached results refreshed periodically or on /optimize
_last_allocations: dict[str, float] = {}
_last_kelly_fractions: dict[str, float] = {}
_last_correlation_matrix: dict[str, dict[str, float]] = {}
_last_optimization_time: Optional[datetime] = None
_portfolio_value: float = 0.0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class AllocationResponse(BaseModel):
    symbol: str
    kelly_fraction: float
    recommended_allocation_pct: float
    position_size_usd: float
    correlation_risk: dict


class PortfolioSummary(BaseModel):
    portfolio_value: float
    cash_reserve_pct: float
    kelly_mode: str
    allocations: dict[str, float]
    kelly_fractions: dict[str, float]
    last_optimized: Optional[str]


# ---------------------------------------------------------------------------
# Core sizing logic
# ---------------------------------------------------------------------------
async def _get_portfolio_value() -> float:
    """Read portfolio value from Redis (set by risk / executor services)."""
    global _portfolio_value
    data = await redis_client.get("portfolio_state")
    if data:
        state = json.loads(data)
        _portfolio_value = float(state.get("total_capital", 0) or state.get("available_capital", 0))
    PORTFOLIO_VALUE.set(_portfolio_value)
    return _portfolio_value


async def _get_open_positions() -> dict[str, float]:
    """Return {symbol: usd_value} of currently open positions from Redis."""
    positions = await redis_client.hgetall("positions")
    result = {}
    for sym, raw in positions.items():
        pos = json.loads(raw)
        if pos.get("status") == "open":
            price = float(pos.get("current_price", 0) or pos.get("entry_price", 0))
            amount = float(pos.get("amount", 0))
            result[sym] = price * amount
    return result


async def _compute_drawdown() -> float:
    """Estimate current drawdown from portfolio state."""
    data = await redis_client.get("portfolio_state")
    if not data:
        return 0.0
    state = json.loads(data)
    total = float(state.get("total_capital", 0))
    starting = float(state.get("starting_capital", total))
    if starting <= 0:
        return 0.0
    dd = (starting - total) / starting
    return max(0.0, dd)


async def size_signal(signal: dict) -> Optional[dict]:
    """
    Take a validated signal and attach an optimal position size.
    Returns the enriched signal dict, or None if the trade should be skipped.
    """
    symbol = signal.get("symbol", "")
    confidence = float(signal.get("confidence", 0.5))
    action = signal.get("action", "buy")

    # For sell signals, pass through without resizing
    if action == "sell":
        signal["sized"] = True
        signal["sizing_method"] = "passthrough_sell"
        return signal

    portfolio_val = await _get_portfolio_value()
    if portfolio_val <= 0:
        SIGNALS_SKIPPED.labels(reason="zero_portfolio").inc()
        logger.warning("Portfolio value is zero, skipping signal", symbol=symbol)
        return None

    # 1. Fetch trade performance from DB
    perf = await db.fetch_trade_performance(symbol)
    win_rate = perf["win_rate"]
    avg_win = perf["avg_win"]
    avg_loss = perf["avg_loss"]

    # 2. Current drawdown
    drawdown = await _compute_drawdown()

    # 3. Kelly fraction
    fraction = dynamic_kelly(
        symbol=symbol,
        confidence=confidence,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        current_drawdown=drawdown,
        kelly_mode=KELLY_MODE,
    )
    KELLY_FRACTION.labels(symbol=symbol).set(fraction)
    _last_kelly_fractions[symbol] = fraction

    # 4. Correlation check
    open_positions = await _get_open_positions()
    corr_risk = {"action": "allow", "size_multiplier": 1.0, "max_corr": 0.0}
    if open_positions and _last_correlation_matrix:
        corr_risk = check_correlation_risk(
            new_symbol=symbol,
            open_positions=open_positions,
            correlation_matrix=_last_correlation_matrix,
            portfolio_value=portfolio_val,
        )
        if corr_risk["action"] == "skip":
            SIGNALS_SKIPPED.labels(reason="correlation").inc()
            logger.info("Trade skipped due to correlation", symbol=symbol, detail=corr_risk["reason"])
            return None

    # 5. Apply correlation multiplier
    effective_fraction = fraction * corr_risk["size_multiplier"]

    # 6. Convert to USD
    position_usd = fraction_to_usd(effective_fraction, portfolio_val)
    if position_usd <= 0:
        SIGNALS_SKIPPED.labels(reason="below_minimum").inc()
        logger.info("Position size below minimum, skipping", symbol=symbol, fraction=effective_fraction)
        return None

    POSITION_SIZE_USD.labels(symbol=symbol).set(position_usd)

    # 7. Enrich signal
    sized_signal = signal.copy()
    sized_signal["amount"] = position_usd
    sized_signal["sized"] = True
    sized_signal["sizing_method"] = "kelly_dynamic"
    sized_signal["kelly_fraction"] = round(effective_fraction, 6)
    sized_signal["correlation_risk"] = corr_risk
    sized_signal["portfolio_value"] = portfolio_val

    SIGNALS_SIZED.inc()
    logger.info(
        "Signal sized",
        symbol=symbol,
        kelly=round(effective_fraction, 5),
        usd=round(position_usd, 2),
        corr_mult=corr_risk["size_multiplier"],
    )
    return sized_signal


# ---------------------------------------------------------------------------
# Background listener
# ---------------------------------------------------------------------------
async def listen_for_validated_signals():
    """Subscribe to validated_signals and publish sized_signals."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("validated_signals")
    logger.info("Subscribed to validated_signals channel")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        SIGNALS_RECEIVED.inc()
        try:
            signal = json.loads(message["data"])
            sized = await size_signal(signal)
            if sized:
                await redis_client.publish("sized_signals", json.dumps(sized))
                logger.debug("Published sized_signal", signal_id=sized.get("signal_id"))
        except Exception as e:
            logger.error("Error sizing signal", error=str(e))


async def periodic_correlation_refresh():
    """Background correlation engine — refreshes every 30 seconds.

    Improvements over the original 5-minute cycle:
    - Runs every 30s instead of 5 min for near-real-time risk awareness
    - Tracks top candidate symbols (not just open positions)
    - Detects correlation regime shifts and logs warnings
    - Caches results in Redis for other services to consume
    """
    global _last_correlation_matrix
    _prev_avg_corr: Optional[float] = None

    while True:
        try:
            open_positions = await _get_open_positions()
            symbols = list(open_positions.keys())

            # Also include top trading pairs for pre-computed correlation
            try:
                top_pairs_raw = await redis_client.get("top_trading_pairs")
                if top_pairs_raw:
                    import json as _json
                    top_pairs = _json.loads(top_pairs_raw)
                    for pair in top_pairs[:20]:  # Top 20 candidates
                        if pair not in symbols:
                            symbols.append(pair)
            except Exception:
                pass

            # Need at least 2 symbols for correlation
            if len(symbols) >= 2:
                candle_data = await db.fetch_candles_multi(symbols, timeframe="1m", limit=200)
                _last_correlation_matrix = compute_correlation_matrix(symbols, candle_data)

                # Detect correlation regime shifts
                if _last_correlation_matrix:
                    corr_values = []
                    for sym_a, row in _last_correlation_matrix.items():
                        for sym_b, val in row.items():
                            if sym_a != sym_b and isinstance(val, (int, float)):
                                corr_values.append(abs(val))

                    if corr_values:
                        avg_corr = sum(corr_values) / len(corr_values)
                        if _prev_avg_corr is not None:
                            delta = avg_corr - _prev_avg_corr
                            if delta > 0.15:
                                logger.warning(
                                    "Correlation regime shift detected — correlations rising",
                                    avg_correlation=round(avg_corr, 3),
                                    delta=round(delta, 3),
                                    n_symbols=len(symbols),
                                )
                            elif avg_corr > 0.7:
                                logger.warning(
                                    "High correlation regime — risk of concentrated portfolio",
                                    avg_correlation=round(avg_corr, 3),
                                )
                        _prev_avg_corr = avg_corr

                    # Cache in Redis for other services
                    try:
                        await redis_client.set(
                            "correlation_matrix",
                            json.dumps(_last_correlation_matrix),
                            ex=120,  # 2-minute TTL
                        )
                    except Exception:
                        pass

                logger.debug("Correlation matrix refreshed",
                             n_symbols=len(symbols),
                             open_positions=len(open_positions))

        except Exception as e:
            logger.error("Correlation refresh failed", error=str(e))

        await asyncio.sleep(30)  # Every 30 seconds (was 300)


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logger.info("Starting Portfolio Optimizer Service...")

    # Redis
    redis_client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True
    )
    await redis_client.ping()
    logger.info("Redis connected")

    # TimescaleDB
    try:
        await db.init_pool()
    except Exception as e:
        logger.warning("TimescaleDB init failed, continuing without DB", error=str(e))

    # Background tasks
    listener_task = asyncio.create_task(listen_for_validated_signals())
    corr_task = asyncio.create_task(periodic_correlation_refresh())

    yield

    listener_task.cancel()
    corr_task.cancel()
    await db.close_pool()
    if redis_client:
        await redis_client.close()
    logger.info("Portfolio Optimizer Service stopped")


app = FastAPI(title="Portfolio Optimizer Service", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "kelly_mode": KELLY_MODE,
        "portfolio_value": _portfolio_value,
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()


@app.get("/allocation/{symbol}", response_model=AllocationResponse)
async def get_allocation(symbol: str):
    """Get recommended allocation for a specific symbol."""
    portfolio_val = await _get_portfolio_value()
    if portfolio_val <= 0:
        raise HTTPException(status_code=400, detail="Portfolio value is zero")

    perf = await db.fetch_trade_performance(symbol)
    drawdown = await _compute_drawdown()

    fraction = dynamic_kelly(
        symbol=symbol,
        confidence=0.5,
        win_rate=perf["win_rate"],
        avg_win=perf["avg_win"],
        avg_loss=perf["avg_loss"],
        current_drawdown=drawdown,
        kelly_mode=KELLY_MODE,
    )

    open_positions = await _get_open_positions()
    corr_risk = {"action": "allow", "size_multiplier": 1.0, "max_corr": 0.0}
    if open_positions and _last_correlation_matrix:
        corr_risk = check_correlation_risk(
            symbol, open_positions, _last_correlation_matrix, portfolio_val
        )

    alloc_pct = _last_allocations.get(symbol, fraction)
    position_usd = fraction_to_usd(fraction * corr_risk["size_multiplier"], portfolio_val)

    return AllocationResponse(
        symbol=symbol,
        kelly_fraction=round(fraction, 6),
        recommended_allocation_pct=round(alloc_pct, 6),
        position_size_usd=round(position_usd, 2),
        correlation_risk=corr_risk,
    )


@app.get("/portfolio/summary", response_model=PortfolioSummary)
async def portfolio_summary():
    """Current portfolio optimization state."""
    portfolio_val = await _get_portfolio_value()
    return PortfolioSummary(
        portfolio_value=portfolio_val,
        cash_reserve_pct=PORTFOLIO_CASH_RESERVE_PCT,
        kelly_mode=KELLY_MODE,
        allocations=_last_allocations,
        kelly_fractions=_last_kelly_fractions,
        last_optimized=_last_optimization_time.isoformat() if _last_optimization_time else None,
    )


@app.post("/optimize")
async def trigger_optimize():
    """Trigger a full portfolio rebalance calculation."""
    global _last_allocations, _last_correlation_matrix, _last_optimization_time

    import time as _time
    start = _time.monotonic()

    portfolio_val = await _get_portfolio_value()
    if portfolio_val <= 0:
        raise HTTPException(status_code=400, detail="Portfolio value is zero")

    open_positions = await _get_open_positions()

    # Gather symbols
    symbols = list(open_positions.keys())
    if not symbols:
        return {"status": "no_positions", "allocations": {}}

    # Fetch candle data
    candle_data = await db.fetch_candles_multi(symbols, timeframe="1m", limit=200)

    # Update correlation matrix
    if len(symbols) >= 2:
        _last_correlation_matrix = compute_correlation_matrix(symbols, candle_data)

    # Run mean-variance optimisation
    _last_allocations = optimize_allocations(
        portfolio_value=portfolio_val,
        open_positions=open_positions,
        pending_signals=[],
        candle_data=candle_data,
    )
    _last_optimization_time = datetime.now(timezone.utc)

    elapsed = _time.monotonic() - start
    OPTIMIZATION_DURATION.observe(elapsed)

    # Persist to DB
    await db.store_optimization_result(
        portfolio_value=portfolio_val,
        allocations=_last_allocations,
        kelly_fractions=_last_kelly_fractions,
        metadata={"elapsed_s": round(elapsed, 3), "kelly_mode": KELLY_MODE},
    )

    logger.info(
        "Portfolio optimization complete",
        n_symbols=len(symbols),
        elapsed_s=round(elapsed, 3),
    )

    return {
        "status": "optimized",
        "portfolio_value": portfolio_val,
        "allocations": _last_allocations,
        "elapsed_s": round(elapsed, 3),
    }
