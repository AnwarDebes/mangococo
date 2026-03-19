"""
Layer A — Regime Classifier

Classifies the market into regimes using practical, robust indicators
computed from the feature-store's cached features (ATR, RSI, Bollinger
bandwidth, momentum, etc.) which are already available in Redis.

Regimes:
  trending_up   — strong uptrend, let longs run
  trending_down — strong downtrend, let shorts run (or avoid longs)
  choppy        — no clear direction, reduce or skip trading
  high_vol      — elevated volatility, reduce size, widen thresholds
  low_vol       — compressed volatility, normal sizing

The classifier uses:
  1. ADX proxy (via Bollinger bandwidth + momentum alignment)
  2. Choppiness detection (RSI mean-reversion zone + low momentum)
  3. Volatility regime (ATR% vs historical norm)
  4. Trend strength (EMA alignment + momentum direction)

All inputs come from the feature dict produced by the feature-store
service (stored in Redis as features:{symbol}).
"""
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np


@dataclass
class RegimeState:
    """Current market regime classification for a symbol."""
    regime: str           # trending_up, trending_down, choppy, high_vol
    trend_strength: float  # 0.0 (no trend) to 1.0 (strong trend)
    volatility_ratio: float  # current_vol / normal_vol (1.0 = normal)
    choppiness: float     # 0.0 (trending) to 1.0 (very choppy)
    confidence: float     # how confident we are in this classification
    details: Dict[str, float]  # all intermediate values for debugging


# ── Thresholds (tunable, but these are well-grounded defaults) ────────

# ADX proxy: Bollinger bandwidth is a reasonable vol/trend proxy.
# High bandwidth = price moving = likely trending; low = compressed = chop.
BB_BANDWIDTH_TREND_THRESHOLD = 0.03   # BB bandwidth > 3% → trending
BB_BANDWIDTH_CHOP_THRESHOLD = 0.015   # BB bandwidth < 1.5% → choppy

# Momentum alignment: if 5m/15m/30m momentum all agree, strong trend
MOMENTUM_TREND_THRESHOLD = 0.15  # absolute momentum > 0.15% → meaningful

# RSI: mid-range (40-60) = choppy; extreme = trending
RSI_CHOP_LOW = 40
RSI_CHOP_HIGH = 60

# Volatility: ATR% relative to "normal" (we'll use a running estimate)
VOL_HIGH_RATIO = 1.8   # ATR > 1.8x normal → high_vol
VOL_LOW_RATIO = 0.6    # ATR < 0.6x normal → low_vol
NORMAL_ATR_PCT = 0.5   # default "normal" ATR% for crypto (0.5%)

# EMA alignment: both 9/21 and 25/50 agree → trend confirmation
EMA_ALIGNMENT_WEIGHT = 0.3

# Historical ATR buffer for computing volatility regime
_atr_history: Dict[str, list] = {}
_ATR_HISTORY_MAX = 100


def _update_atr_history(symbol: str, atr_pct: float) -> float:
    """Track rolling ATR to compute 'normal' volatility for this symbol."""
    if symbol not in _atr_history:
        _atr_history[symbol] = []
    _atr_history[symbol].append(atr_pct)
    if len(_atr_history[symbol]) > _ATR_HISTORY_MAX:
        _atr_history[symbol] = _atr_history[symbol][-_ATR_HISTORY_MAX:]
    if len(_atr_history[symbol]) >= 10:
        return float(np.median(_atr_history[symbol]))
    return NORMAL_ATR_PCT


def classify_regime(features: Dict[str, float], symbol: str = "") -> RegimeState:
    """
    Classify the current market regime from feature-store features.

    Parameters
    ----------
    features : dict
        Feature dict from Redis (features:{symbol}). Expected keys:
        atr_pct, bb_bandwidth, rsi_14, momentum_5m, momentum_15m,
        momentum_30m, ema_9_21_cross, ema_25_50_cross, volume_ratio,
        spread_pct
    symbol : str
        For tracking per-symbol ATR history.

    Returns
    -------
    RegimeState with regime classification and supporting data.
    """
    atr_pct = features.get("atr_pct", 0.0)
    bb_bandwidth = features.get("bb_bandwidth", 0.0)
    rsi_14 = features.get("rsi_14", 50.0)
    mom_5 = features.get("momentum_5m", 0.0)
    mom_15 = features.get("momentum_15m", 0.0)
    mom_30 = features.get("momentum_30m", 0.0)
    ema_9_21 = features.get("ema_9_21_cross", 0.0)
    ema_25_50 = features.get("ema_25_50_cross", 0.0)
    volume_ratio = features.get("volume_ratio", 1.0)
    spread_pct = features.get("spread_pct", 0.0)

    # 1. Volatility regime
    normal_atr = _update_atr_history(symbol, atr_pct) if symbol else NORMAL_ATR_PCT
    vol_ratio = atr_pct / normal_atr if normal_atr > 0 else 1.0

    # 2. Trend strength composite
    # Momentum alignment: count how many timeframes agree on direction
    mom_signs = [
        np.sign(mom_5) if abs(mom_5) > MOMENTUM_TREND_THRESHOLD else 0,
        np.sign(mom_15) if abs(mom_15) > MOMENTUM_TREND_THRESHOLD else 0,
        np.sign(mom_30) if abs(mom_30) > MOMENTUM_TREND_THRESHOLD else 0,
    ]
    mom_alignment = sum(mom_signs) / 3.0  # -1 to +1
    mom_strength = abs(mom_alignment)     # 0 to 1

    # EMA alignment
    ema_alignment = 1.0 if ema_9_21 == ema_25_50 and ema_9_21 != 0 else 0.0
    ema_direction = ema_9_21  # +1 bullish, -1 bearish

    # Composite trend strength
    trend_strength = (
        mom_strength * 0.4 +
        ema_alignment * EMA_ALIGNMENT_WEIGHT +
        min(1.0, bb_bandwidth / BB_BANDWIDTH_TREND_THRESHOLD) * 0.3
    )
    trend_strength = min(1.0, trend_strength)

    # Trend direction: positive = up, negative = down
    trend_direction = np.sign(mom_alignment) if mom_strength > 0.3 else np.sign(ema_direction)

    # 3. Choppiness score
    rsi_chop = 1.0 if RSI_CHOP_LOW <= rsi_14 <= RSI_CHOP_HIGH else 0.0
    low_momentum = 1.0 if mom_strength < 0.2 else 0.0
    low_bandwidth = 1.0 if bb_bandwidth < BB_BANDWIDTH_CHOP_THRESHOLD else 0.0
    ema_disagree = 1.0 if ema_9_21 != ema_25_50 else 0.0

    choppiness = (rsi_chop * 0.3 + low_momentum * 0.3 + low_bandwidth * 0.2 + ema_disagree * 0.2)

    # 4. Classify
    if vol_ratio > VOL_HIGH_RATIO:
        regime = "high_vol"
        confidence = min(1.0, (vol_ratio - 1.0) / (VOL_HIGH_RATIO - 1.0))
    elif choppiness > 0.6:
        regime = "choppy"
        confidence = choppiness
    elif trend_strength > 0.5 and trend_direction > 0:
        regime = "trending_up"
        confidence = trend_strength
    elif trend_strength > 0.5 and trend_direction < 0:
        regime = "trending_down"
        confidence = trend_strength
    else:
        # Mild chop / indeterminate — conservative
        regime = "choppy"
        confidence = 0.5

    details = {
        "atr_pct": round(atr_pct, 4),
        "normal_atr": round(normal_atr, 4),
        "vol_ratio": round(vol_ratio, 3),
        "bb_bandwidth": round(bb_bandwidth, 4),
        "rsi_14": round(rsi_14, 1),
        "mom_alignment": round(mom_alignment, 3),
        "mom_strength": round(mom_strength, 3),
        "ema_alignment": round(ema_alignment, 1),
        "trend_direction": round(trend_direction, 1),
        "trend_strength": round(trend_strength, 3),
        "choppiness": round(choppiness, 3),
        "volume_ratio": round(volume_ratio, 2),
        "spread_pct": round(spread_pct, 4),
    }

    return RegimeState(
        regime=regime,
        trend_strength=round(trend_strength, 4),
        volatility_ratio=round(vol_ratio, 4),
        choppiness=round(choppiness, 4),
        confidence=round(confidence, 4),
        details=details,
    )


def regime_allows_entry(regime: RegimeState, direction: str) -> bool:
    """Quick check: does this regime allow entering a position?

    In choppy regime: only allow if choppiness < 0.8 (marginal chop OK
    with strong edge gate).
    In high_vol: allow (gate will reduce size), but flag it.
    In trending: allow if direction aligns.
    """
    if regime.regime == "choppy" and regime.choppiness > 0.8:
        return False
    if regime.regime == "trending_down" and direction == "buy":
        return False  # don't go long in a downtrend
    if regime.regime == "trending_up" and direction == "sell":
        return False  # don't short in an uptrend
    return True
