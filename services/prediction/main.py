"""
Prediction Service - Momentum + RSI Strategy for Short-Term Trading
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import Counter, Gauge, Histogram, generate_latest

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
STRATEGY_TYPE = os.getenv("STRATEGY_TYPE", "momentum_rsi")
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_OVERSOLD = int(os.getenv("RSI_OVERSOLD", 40))      # Very aggressive: buy at RSI 40
RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT", 60))   # Very aggressive: sell at RSI 60
VOLUME_SPIKE_THRESHOLD = float(os.getenv("VOLUME_SPIKE_THRESHOLD", 0.9))  # Very aggressive: no volume requirement
MOMENTUM_PERIOD = int(os.getenv("MOMENTUM_PERIOD", 2))  # Compare current price to 2 ticks ago - AGGRESSIVE for testing
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.25))  # More aggressive: 25% confidence threshold
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")

logger = structlog.get_logger()
device = "cpu"  # Using CPU for momentum strategy (no GPU needed)

# Metrics
PREDICTIONS_MADE = Counter("prediction_total", "Total predictions", ["symbol"])
PREDICTION_LATENCY = Histogram("prediction_latency_seconds", "Prediction latency")
MODEL_CONFIDENCE = Gauge("prediction_confidence", "Model confidence", ["symbol"])


# Removed LSTM model - using momentum + RSI strategy instead


class PredictionResponse(BaseModel):
    symbol: str
    timestamp: str
    direction: str  # "buy", "sell", or "hold"
    confidence: float
    rsi_value: float
    momentum_pct: float
    volume_ratio: float
    current_price: float
    macd_histogram: float = 0.0  # MACD indicator
    atr_pct: float = 0.0  # ATR as percentage of price
    spread_pct: float = 0.0  # Bid-ask spread percentage
    trend_bullish: bool = False  # Multi-timeframe trend direction
    dynamic_profit_target_pct: float = 0.0  # ATR-based profit target
    strategy_type: str = "momentum"  # "momentum", "mean_reversion", or "scalper"


# Global State
redis_client: Optional[aioredis.Redis] = None
price_history: Dict[str, List[dict]] = {}


def calculate_rsi(prices: List[float], period: int = RSI_PERIOD) -> float:
    """Calculate RSI (Relative Strength Index)"""
    if len(prices) < period + 1:
        return 50.0  # Neutral RSI

    gains = []
    losses = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    if len(gains) >= period:
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    return 50.0


def calculate_momentum(prices: List[float], period: int = MOMENTUM_PERIOD) -> float:
    """Calculate price momentum as percentage change"""
    if len(prices) < period + 1:
        return 0.0

    current_price = prices[-1]
    past_price = prices[-(period + 1)]
    return ((current_price - past_price) / past_price) * 100


def calculate_volume_ratio(volumes: List[float]) -> float:
    """Calculate volume ratio compared to recent average"""
    if len(volumes) < 10:
        return 1.0

    recent_volume = volumes[-1]
    avg_volume = sum(volumes[-10:]) / 10
    return recent_volume / avg_volume if avg_volume > 0 else 1.0


def calculate_macd(prices: List[float], fast_period: int = 8, slow_period: int = 17, signal_period: int = 9) -> tuple:
    """Calculate MACD (Moving Average Convergence Divergence) - crypto optimized"""
    if len(prices) < slow_period + signal_period:
        return 0.0, 0.0, 0.0  # MACD line, signal line, histogram

    # Calculate EMAs
    prices_array = np.array(prices)

    # Fast EMA
    fast_ema = pd.Series(prices_array).ewm(span=fast_period, adjust=False).mean().iloc[-1]
    # Slow EMA
    slow_ema = pd.Series(prices_array).ewm(span=slow_period, adjust=False).mean().iloc[-1]

    # MACD line
    macd_line = fast_ema - slow_ema

    # Calculate signal line (EMA of MACD line)
    # We need MACD values for signal calculation
    fast_ema_series = pd.Series(prices_array).ewm(span=fast_period, adjust=False).mean()
    slow_ema_series = pd.Series(prices_array).ewm(span=slow_period, adjust=False).mean()
    macd_series = fast_ema_series - slow_ema_series
    signal_line = macd_series.ewm(span=signal_period, adjust=False).mean().iloc[-1]

    # MACD histogram
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_atr(ticks: List[dict], period: int = 14) -> float:
    """Calculate Average True Range (ATR) for volatility measurement"""
    if len(ticks) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(ticks)):
        high = ticks[i].get("high", ticks[i].get("price", 0))
        low = ticks[i].get("low", ticks[i].get("price", 0))
        prev_close = ticks[i-1].get("close", ticks[i-1].get("price", 0))
        
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        true_range = max(tr1, tr2, tr3)
        true_ranges.append(true_range)
    
    if len(true_ranges) >= period:
        atr = sum(true_ranges[-period:]) / period
        return atr
    
    return 0.0


def calculate_ema(prices: List[float], period: int) -> float:
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    
    prices_series = pd.Series(prices)
    ema = prices_series.ewm(span=period, adjust=False).mean().iloc[-1]
    return ema


def calculate_vwap(ticks: List[dict]) -> float:
    """Calculate Volume Weighted Average Price (VWAP)"""
    if not ticks:
        return 0.0
    
    total_volume_price = 0.0
    total_volume = 0.0
    
    for tick in ticks:
        price = tick.get("close", tick.get("price", 0))
        volume = tick.get("volume", 0)
        total_volume_price += price * volume
        total_volume += volume
    
    if total_volume > 0:
        return total_volume_price / total_volume
    
    return ticks[-1].get("close", ticks[-1].get("price", 0)) if ticks else 0.0


def calculate_spread_pct(bid: float, ask: float, mid_price: float) -> float:
    """Calculate bid-ask spread as percentage"""
    if mid_price > 0 and ask > bid:
        spread = ((ask - bid) / mid_price) * 100
        return spread
    return 0.0


async def make_prediction(symbol: str) -> Optional[PredictionResponse]:
    """Generate trading signals using IMPROVED multi-strategy approach:
    1. Liquid-pair scalper (liquidity/spread filters, ATR-based targets)
    2. Multi-timeframe momentum + trend filter
    3. Mean-reversion for low-volatility markets
    """
    data_points = len(price_history.get(symbol, []))
    if symbol not in price_history or data_points < 20:  # Need more data for ATR/EMA calculations
        return None

    start_time = datetime.utcnow()

    # Get latest ticker data for bid/ask/spread
    tick_data_json = await redis_client.hget("latest_ticks", symbol)
    if not tick_data_json:
        return None
    
    tick_data = json.loads(tick_data_json)
    bid = tick_data.get("bid", 0)
    ask = tick_data.get("ask", 0)
    current_price = tick_data.get("price", 0)
    
    if current_price <= 0:
        return None

    # Extract price and volume data from history
    ticks = price_history[symbol][-50:]
    prices = [tick.get("close", tick.get("price", 0)) for tick in ticks]
    volumes = [tick.get("volume", 1) for tick in ticks]
    
    if not prices or prices[-1] <= 0:
        return None

    # Calculate base indicators
    rsi_value = calculate_rsi(prices)
    momentum_pct = calculate_momentum(prices)
    volume_ratio = calculate_volume_ratio(volumes)
    macd_line, macd_signal, macd_histogram = calculate_macd(prices)
    
    # Calculate new indicators for improved strategies
    atr = calculate_atr(ticks, period=14)
    atr_pct = (atr / current_price * 100) if current_price > 0 else 0.0
    
    # Multi-timeframe trend filter (using shorter periods for real-time data)
    # EMA50 equivalent: use ~25 ticks, EMA200 equivalent: use ~50 ticks
    ema_fast = calculate_ema(prices, period=25)  # Short-term trend
    ema_slow = calculate_ema(prices, period=50) if len(prices) >= 50 else ema_fast  # Longer-term trend
    trend_bullish = ema_fast > ema_slow
    
    # VWAP for mean-reversion detection
    vwap = calculate_vwap(ticks)
    price_vs_vwap_pct = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0.0
    
    # Spread and liquidity checks
    mid_price = (bid + ask) / 2 if bid > 0 and ask > 0 else current_price
    spread_pct = calculate_spread_pct(bid, ask, mid_price)
    
    # Liquidity filter: require tight spread (< 0.05% for liquid pairs)
    MAX_SPREAD_PCT = 0.05  # 0.05% max spread for liquid pairs
    if spread_pct > MAX_SPREAD_PCT:
        logger.debug(f"{symbol}: Spread too wide ({spread_pct:.4f}%), skipping")
        return None
    
    # Volume liquidity check (require minimum volume ratio)
    MIN_VOLUME_RATIO = 0.9  # At least 90% of average volume
    if volume_ratio < MIN_VOLUME_RATIO:
        logger.debug(f"{symbol}: Low volume ({volume_ratio:.2f}x), skipping")
        return None

    # DETECT MARKET REGIME: Trending vs Ranging (for strategy selection)
    # Low ATR relative to price = ranging market (use mean-reversion)
    # High ATR = trending market (use momentum)
    LOW_VOLATILITY_THRESHOLD = 0.3  # ATR < 0.3% of price = low volatility
    is_low_volatility = atr_pct < LOW_VOLATILITY_THRESHOLD
    
    # Mean-reversion detection: price far from VWAP in low-volatility market
    MEAN_REVERSION_THRESHOLD = 0.5  # Price > 0.5% away from VWAP
    is_mean_reversion_opportunity = is_low_volatility and abs(price_vs_vwap_pct) > MEAN_REVERSION_THRESHOLD

    # Determine trading direction using IMPROVED multi-strategy approach
    direction = "hold"
    confidence = 0.5
    buy_signals = []
    sell_signals = []

    # STRATEGY 1: MEAN-REVERSION (for low-volatility, ranging markets)
    if is_mean_reversion_opportunity:
        if price_vs_vwap_pct < -MEAN_REVERSION_THRESHOLD and rsi_value < 30:  # Price below VWAP, oversold
            buy_signals.append("mean_reversion")
            buy_signals.append("rsi_oversold")
            logger.info(f"📊 MEAN-REVERSION BUY: {symbol} (price {price_vs_vwap_pct:.2f}% below VWAP, RSI={rsi_value:.1f})")
        elif price_vs_vwap_pct > MEAN_REVERSION_THRESHOLD and rsi_value > 70:  # Price above VWAP, overbought
            sell_signals.append("mean_reversion")
            sell_signals.append("rsi_overbought")
            logger.info(f"📊 MEAN-REVERSION SELL: {symbol} (price {price_vs_vwap_pct:.2f}% above VWAP, RSI={rsi_value:.1f})")
    
    # STRATEGY 2 & 3: MOMENTUM + TREND FILTER (for trending markets)
    if not is_mean_reversion_opportunity or len(buy_signals) == 0:
        # Multi-timeframe trend filter: only trade with the trend
        if trend_bullish:
            # UPTREND: Look for buy signals
            # ATR-normalized momentum threshold
            momentum_threshold = max(0.15, atr_pct * 0.5)  # Dynamic threshold based on volatility
            
            if momentum_pct >= momentum_threshold:
                buy_signals.append("momentum")
                buy_signals.append("trend_bullish")
            
            if rsi_value < 60 and momentum_pct > 0:
                buy_signals.append("rsi_support")
            
            if macd_histogram > 0:
                buy_signals.append("macd")
            
            if volume_ratio >= VOLUME_SPIKE_THRESHOLD and momentum_pct > 0:
                buy_signals.append("volume")
        else:
            # DOWNTREND: Look for sell signals
            momentum_threshold = max(0.20, atr_pct * 0.5)
            
            if momentum_pct <= -momentum_threshold:
                sell_signals.append("momentum")
                sell_signals.append("trend_bearish")
            
            if rsi_value > RSI_OVERBOUGHT:
                sell_signals.append("rsi_overbought")
            
            if macd_histogram < 0:
                sell_signals.append("macd")
            
            if volume_ratio >= VOLUME_SPIKE_THRESHOLD and momentum_pct < 0:
                sell_signals.append("volume")

    # Determine signal based on confirmations
    buy_count = len(buy_signals)
    sell_count = len(sell_signals)

    if buy_count >= 2:  # Require at least 2 confirmations
        direction = "buy"
        confidence = min(0.95, 0.65 + (buy_count * 0.08))  # 65-95% confidence
        logger.info(f"🟢 BUY: {symbol} ({buy_count} confirmations: {', '.join(buy_signals)})")
    elif sell_count >= 2:  # Require at least 2 confirmations
        direction = "sell"
        confidence = min(0.95, 0.65 + (sell_count * 0.08))
        logger.info(f"🔴 SELL: {symbol} ({sell_count} confirmations: {', '.join(sell_signals)})")

    # Skip if confidence too low
    if confidence < CONFIDENCE_THRESHOLD:
        direction = "hold"
        confidence = 0.5

    # Calculate dynamic profit target based on ATR and spread
    # Formula: max(0.1%, spread + expected slippage, 0.5 × short-term ATR)
    expected_slippage = spread_pct * 0.5  # Estimate slippage as half of spread
    base_target = max(0.1, spread_pct + expected_slippage)  # At least spread + slippage
    atr_based_target = atr_pct * 0.5  # 0.5x ATR for scalping
    dynamic_profit_target_pct = max(base_target, atr_based_target)
    
    # Determine strategy type
    if is_mean_reversion_opportunity:
        strategy_type = "mean_reversion"
    elif is_low_volatility:
        strategy_type = "scalper"
    else:
        strategy_type = "momentum"
    
    # Store dynamic profit target in Redis for position service
    if direction in ["buy", "sell"]:
        target_key = f"profit_target:{symbol}"
        await redis_client.setex(target_key, 3600, str(dynamic_profit_target_pct))  # Expire in 1 hour

    PREDICTION_LATENCY.observe((datetime.utcnow() - start_time).total_seconds())
    PREDICTIONS_MADE.labels(symbol=symbol).inc()
    MODEL_CONFIDENCE.labels(symbol=symbol).set(confidence)

    response = PredictionResponse(
        symbol=symbol,
        timestamp=datetime.utcnow().isoformat(),
        direction=direction,
        confidence=confidence,
        rsi_value=rsi_value,
        momentum_pct=momentum_pct,
        volume_ratio=volume_ratio,
        current_price=current_price,
        macd_histogram=macd_histogram,
        atr_pct=atr_pct,
        spread_pct=spread_pct,
        trend_bullish=trend_bullish,
        dynamic_profit_target_pct=dynamic_profit_target_pct,
        strategy_type=strategy_type
    )

    await redis_client.publish(f"predictions:{symbol.replace('/', '_')}", response.model_dump_json())
    logger.info("Signal generated", symbol=symbol, direction=direction, confidence=f"{confidence:.2%}",
                rsi=rsi_value, momentum=momentum_pct, atr_pct=f"{atr_pct:.3f}%", 
                profit_target=f"{dynamic_profit_target_pct:.3f}%", strategy=strategy_type)

    return response


async def collect_market_data():
    global price_history
    pubsub = redis_client.pubsub()
    channels = [f"ticks:{s.strip().replace('/', '_')}" for s in TRADING_PAIRS]
    logger.info(f"Subscribing to {len(channels)} channels: {channels[:5]}...")
    await pubsub.subscribe(*channels)
    logger.info("Successfully subscribed to Redis channels")

    async for message in pubsub.listen():
        if message["type"] == "message":
            tick = json.loads(message["data"])
            symbol = tick["symbol"]
            data_point = {"timestamp": tick["timestamp"], "open": tick["price"], "high": tick["price"],
                         "low": tick["price"], "close": tick["price"], "volume": tick.get("volume", 0)}

            if symbol not in price_history:
                price_history[symbol] = []
            price_history[symbol].append(data_point)
            if len(price_history[symbol]) > 200:
                price_history[symbol] = price_history[symbol][-200:]

            logger.debug(f"Received data for {symbol}, total points: {len(price_history[symbol])}")


async def prediction_loop():
    """Generate predictions for all coins - batch size and delay tuned for ALL available symbols"""
    # Optimize batch sizes based on total number of pairs
    if len(TRADING_PAIRS) > 1000:
        batch_size = 100  # Larger batches for 1000+ coins
        batch_delay = 0.03  # Slightly longer delay to prevent overload
    elif len(TRADING_PAIRS) > 500:
        batch_size = 75  # Medium batches for 500-1000 coins
        batch_delay = 0.025
    elif len(TRADING_PAIRS) > 200:
        batch_size = 50  # Standard batches for 200-500 coins
        batch_delay = 0.02
    else:
        batch_size = 20  # Small batches for <200 coins
        batch_delay = 0.01
    while True:
        await asyncio.sleep(0.05)

        for i in range(0, len(TRADING_PAIRS), batch_size):
            batch = TRADING_PAIRS[i:i + batch_size]
            tasks = [make_prediction(symbol.strip()) for symbol in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for symbol, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error("Prediction failed", symbol=symbol, error=str(result))
                elif result:
                    logger.debug("Prediction completed", symbol=symbol, direction=result.direction)
            await asyncio.sleep(batch_delay)


def load_symbols_from_file(filepath: str, wait_seconds: int = 60) -> list:
    """Load symbols from file (one per line). Wait for file to exist and be non-empty up to wait_seconds."""
    import time
    start = time.monotonic()
    while (time.monotonic() - start) < wait_seconds:
        try:
            if os.path.isfile(filepath):
                with open(filepath, "r") as f:
                    lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
                if lines:
                    return lines
        except Exception:
            pass
        time.sleep(2)
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, TRADING_PAIRS
    logger.info("Starting Prediction Service (Momentum + RSI Strategy)")

    redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    await redis_client.ping()

    if TRADING_PAIRS_FILE:
        pairs = await asyncio.to_thread(load_symbols_from_file, TRADING_PAIRS_FILE)
        if pairs:
            TRADING_PAIRS = pairs
            logger.info(f"Loaded {len(TRADING_PAIRS)} symbols from {TRADING_PAIRS_FILE}")
        else:
            logger.warning("TRADING_PAIRS_FILE set but file empty or missing, using TRADING_PAIRS env")
    else:
        TRADING_PAIRS = [s.strip() for s in os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]

    data_task = asyncio.create_task(collect_market_data())
    pred_task = asyncio.create_task(prediction_loop())

    yield

    data_task.cancel()
    pred_task.cancel()
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Prediction Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy", "strategy": STRATEGY_TYPE,
            "symbols_tracked": len(price_history), "rsi_period": RSI_PERIOD,
            "oversold_threshold": RSI_OVERSOLD, "overbought_threshold": RSI_OVERBOUGHT,
            "device": device}


@app.post("/predict/{symbol}", response_model=PredictionResponse)
async def predict(symbol: str):
    symbol = symbol.replace("_", "/").upper()
    result = await make_prediction(symbol)
    if result is None:
        raise HTTPException(status_code=400, detail="Insufficient data")
    return result


@app.get("/predictions")
async def get_all_predictions():
    results = {}
    for symbol in TRADING_PAIRS:
        try:
            pred = await make_prediction(symbol.strip())
            if pred:
                results[symbol.strip()] = pred.model_dump()
        except:
            pass
    return results


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
