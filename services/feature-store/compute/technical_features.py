"""
Technical indicator features computed from candle and tick data.
"""
import json
from typing import Optional

import numpy as np
import redis.asyncio as aioredis
import structlog

from db import fetch_candles

logger = structlog.get_logger()


def _safe_float(v, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    """Compute RSI from an array of close prices."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Compute EMA over an array."""
    if len(data) == 0:
        return np.array([])
    alpha = 2.0 / (period + 1)
    result = np.empty_like(data)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def _macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Compute MACD line, signal, and histogram."""
    if len(closes) < slow + signal:
        return {"macd_histogram": 0.0, "macd_signal": 0.0, "macd_line": 0.0}
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {
        "macd_line": float(macd_line[-1]),
        "macd_signal": float(signal_line[-1]),
        "macd_histogram": float(histogram[-1]),
    }


def _bollinger_bands(closes: np.ndarray, period: int = 20, std_dev: float = 2.0) -> dict:
    """Compute Bollinger Band %B and bandwidth."""
    if len(closes) < period:
        return {"bb_percent_b": 0.5, "bb_bandwidth": 0.0}
    sma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    current = closes[-1]

    band_range = upper - lower
    if band_range == 0:
        return {"bb_percent_b": 0.5, "bb_bandwidth": 0.0}

    percent_b = (current - lower) / band_range
    bandwidth = band_range / sma if sma != 0 else 0.0
    return {"bb_percent_b": float(percent_b), "bb_bandwidth": float(bandwidth)}


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Compute ATR as percentage of current price."""
    if len(closes) < period + 1:
        return 0.0
    tr_values = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_values.append(tr)
    atr_val = np.mean(tr_values[-period:])
    price = closes[-1]
    return float(atr_val / price * 100) if price != 0 else 0.0


def _obv_trend(closes: np.ndarray, volumes: np.ndarray, period: int = 20) -> float:
    """Compute OBV trend direction as normalized slope."""
    if len(closes) < period + 1:
        return 0.0
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])

    obv_arr = np.array(obv[-period:])
    if len(obv_arr) < 2:
        return 0.0
    # Linear regression slope, normalized
    x = np.arange(len(obv_arr))
    slope = np.polyfit(x, obv_arr, 1)[0]
    obv_range = np.max(obv_arr) - np.min(obv_arr)
    if obv_range == 0:
        return 0.0
    return float(np.clip(slope / obv_range, -1.0, 1.0))


def _stochastic_rsi(
    closes: np.ndarray,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> dict:
    """Compute Stochastic RSI %K and %D."""
    if len(closes) < rsi_period + stoch_period:
        return {"stoch_rsi_k": 50.0, "stoch_rsi_d": 50.0}

    # Compute RSI series
    deltas = np.diff(closes)
    rsi_values = []
    for i in range(rsi_period, len(deltas) + 1):
        window = deltas[i - rsi_period : i]
        gains = np.where(window > 0, window, 0.0)
        losses = np.where(window < 0, -window, 0.0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

    if len(rsi_values) < stoch_period:
        return {"stoch_rsi_k": 50.0, "stoch_rsi_d": 50.0}

    rsi_arr = np.array(rsi_values)
    # Stochastic of RSI
    stoch_values = []
    for i in range(stoch_period - 1, len(rsi_arr)):
        window = rsi_arr[i - stoch_period + 1 : i + 1]
        low = np.min(window)
        high = np.max(window)
        if high == low:
            stoch_values.append(50.0)
        else:
            stoch_values.append((rsi_arr[i] - low) / (high - low) * 100.0)

    if len(stoch_values) < k_smooth:
        return {"stoch_rsi_k": 50.0, "stoch_rsi_d": 50.0}

    k_line = np.convolve(stoch_values, np.ones(k_smooth) / k_smooth, mode="valid")
    if len(k_line) < d_smooth:
        return {"stoch_rsi_k": float(k_line[-1]) if len(k_line) > 0 else 50.0, "stoch_rsi_d": 50.0}

    d_line = np.convolve(k_line, np.ones(d_smooth) / d_smooth, mode="valid")
    return {
        "stoch_rsi_k": float(k_line[-1]),
        "stoch_rsi_d": float(d_line[-1]) if len(d_line) > 0 else 50.0,
    }


def _williams_r(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Compute Williams %R."""
    if len(closes) < period:
        return -50.0
    highest = np.max(highs[-period:])
    lowest = np.min(lows[-period:])
    if highest == lowest:
        return -50.0
    return float((highest - closes[-1]) / (highest - lowest) * -100.0)


def _ema_crossover(closes: np.ndarray, fast: int, slow: int) -> float:
    """
    EMA crossover signal.
    Returns positive value if fast > slow (bullish), negative if fast < slow (bearish).
    Magnitude is the percentage difference.
    """
    if len(closes) < slow:
        return 0.0
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    diff = ema_fast[-1] - ema_slow[-1]
    price = closes[-1]
    if price == 0:
        return 0.0
    return float(diff / price * 100)


def _volume_ratio(volumes: np.ndarray, period: int = 20) -> float:
    """Current volume vs average volume ratio."""
    if len(volumes) < period + 1:
        return 1.0
    avg = np.mean(volumes[-period - 1 : -1])
    if avg == 0:
        return 1.0
    return float(volumes[-1] / avg)


def _price_momentum(closes: np.ndarray, periods: int) -> float:
    """Price change percentage over N periods."""
    if len(closes) <= periods:
        return 0.0
    old = closes[-periods - 1]
    if old == 0:
        return 0.0
    return float((closes[-1] - old) / old * 100)


async def compute_technical_features(
    symbol: str,
    redis_client: aioredis.Redis,
) -> dict[str, float]:
    """
    Compute all technical indicator features for a given symbol.
    Reads from Redis (latest_ticks) and TimescaleDB (candles).
    Returns a dict of feature_name -> float value.
    """
    features: dict[str, float] = {}

    # Fetch 1m candles from TimescaleDB (need ~200 for all indicators)
    candles = await fetch_candles(symbol, timeframe="1m", limit=200)

    if not candles:
        # Return all zeros if no data
        return {
            "rsi_14": 50.0, "rsi_7": 50.0,
            "macd_histogram": 0.0, "macd_signal": 0.0, "macd_line": 0.0,
            "bb_percent_b": 0.5, "bb_bandwidth": 0.0,
            "atr_pct": 0.0, "obv_trend": 0.0,
            "stoch_rsi_k": 50.0, "stoch_rsi_d": 50.0,
            "williams_r": -50.0,
            "ema_cross_9_21": 0.0, "ema_cross_25_50": 0.0,
            "volume_ratio": 1.0,
            "momentum_5m": 0.0, "momentum_15m": 0.0,
            "momentum_30m": 0.0, "momentum_60m": 0.0,
            "bid_ask_spread_pct": 0.0, "vwap_deviation_pct": 0.0,
        }

    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])

    # RSI
    features["rsi_14"] = _rsi(closes, 14)
    features["rsi_7"] = _rsi(closes, 7)

    # MACD
    macd = _macd(closes, 12, 26, 9)
    features.update(macd)

    # Bollinger Bands
    bb = _bollinger_bands(closes, 20, 2.0)
    features.update(bb)

    # ATR as % of price
    features["atr_pct"] = _atr(highs, lows, closes, 14)

    # OBV trend
    features["obv_trend"] = _obv_trend(closes, volumes, 20)

    # Stochastic RSI
    stoch = _stochastic_rsi(closes, 14, 14, 3, 3)
    features.update(stoch)

    # Williams %R
    features["williams_r"] = _williams_r(highs, lows, closes, 14)

    # EMA crossovers
    features["ema_cross_9_21"] = _ema_crossover(closes, 9, 21)
    features["ema_cross_25_50"] = _ema_crossover(closes, 25, 50)

    # Volume ratio
    features["volume_ratio"] = _volume_ratio(volumes, 20)

    # Price momentum at different horizons (1m candles)
    features["momentum_5m"] = _price_momentum(closes, 5)
    features["momentum_15m"] = _price_momentum(closes, 15)
    features["momentum_30m"] = _price_momentum(closes, 30)
    features["momentum_60m"] = _price_momentum(closes, 60)

    # Bid-ask spread from latest tick in Redis
    try:
        tick_raw = await redis_client.hget("latest_ticks", symbol)
        if tick_raw:
            tick = json.loads(tick_raw)
            bid = _safe_float(tick.get("bid"))
            ask = _safe_float(tick.get("ask"))
            mid = (bid + ask) / 2 if (bid + ask) > 0 else closes[-1]
            spread_pct = ((ask - bid) / mid * 100) if mid > 0 and ask > bid else 0.0
            features["bid_ask_spread_pct"] = spread_pct
        else:
            features["bid_ask_spread_pct"] = 0.0
    except Exception:
        features["bid_ask_spread_pct"] = 0.0

    # VWAP deviation
    try:
        if len(closes) >= 20 and np.sum(volumes[-20:]) > 0:
            vwap = np.sum(closes[-20:] * volumes[-20:]) / np.sum(volumes[-20:])
            features["vwap_deviation_pct"] = float((closes[-1] - vwap) / vwap * 100) if vwap != 0 else 0.0
        else:
            features["vwap_deviation_pct"] = 0.0
    except Exception:
        features["vwap_deviation_pct"] = 0.0

    return features
