"""
Layer C.2 — Adaptive Exit Pressure

Enhances the existing exit-pressure system with regime-aware thresholds.
In strong trends, exits require MORE persistence (harder to exit = let winners run).
In choppy/high-vol regimes, exits require LESS persistence (easier to exit = cut fast).

Also adds a volatility-scaled risk floor: if unrealized loss exceeds
N * ATR, increase exit pressure significantly (data-driven downside control
instead of fixed stop-loss).

This module provides functions that the position manager calls to:
1. Get the adaptive exit threshold for a given regime/vol state
2. Compute volatility-based risk urgency
3. Produce an explainable exit decision with all context
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .regime import RegimeState


@dataclass
class AdaptiveExitParams:
    """Regime-adaptive parameters for the exit pressure system."""
    pressure_threshold: float     # cumulative pressure needed to exit
    min_consecutive_sells: int    # minimum consecutive sell signals
    decay_rate: float             # pressure decay per non-sell prediction
    sell_weight: float            # multiplier on sell signal pressure
    strong_sell_weight: float     # multiplier on strong_sell signal pressure
    vol_urgency: float            # 0-1 urgency from volatility risk floor
    regime: str                   # current regime for logging
    details: Dict[str, float] = field(default_factory=dict)


# ── Base Parameters ───────────────────────────────────────────────────

BASE_PRESSURE_THRESHOLD = 1.5
BASE_MIN_CONSECUTIVE = 2
BASE_DECAY_RATE = 0.3
BASE_SELL_WEIGHT = 0.6
BASE_STRONG_SELL_WEIGHT = 1.0

# Regime adjustments
# trending: harder to exit (let winners run)
# choppy/high_vol: easier to exit (cut fast)
REGIME_EXIT_PARAMS = {
    "trending_up": {
        "threshold_mult": 1.4,         # 40% harder to exit (let trend run)
        "min_consecutive_add": 1,      # need 3 consecutive sells, not 2
        "decay_mult": 0.7,             # pressure decays slower
        "sell_weight_mult": 0.8,       # each sell contributes less
    },
    "trending_down": {
        "threshold_mult": 1.4,
        "min_consecutive_add": 1,
        "decay_mult": 0.7,
        "sell_weight_mult": 0.8,
    },
    "choppy": {
        "threshold_mult": 0.7,         # 30% easier to exit
        "min_consecutive_add": 0,      # only need 2 consecutive sells
        "decay_mult": 1.3,             # pressure decays faster
        "sell_weight_mult": 1.3,       # each sell contributes more
    },
    "high_vol": {
        "threshold_mult": 0.6,         # 40% easier to exit
        "min_consecutive_add": -1,     # only need 1 consecutive sell
        "decay_mult": 1.5,             # pressure decays much faster
        "sell_weight_mult": 1.5,       # each sell contributes much more
    },
}

# Volatility risk floor: if loss > N * ATR, add urgency
VOL_RISK_ATR_MULTIPLIER = 3.0   # 3 ATR loss = significant
VOL_RISK_URGENCY_SCALE = 0.5    # how much urgency to add per ATR beyond threshold


def compute_adaptive_exit_params(
    regime: RegimeState,
    pnl_pct: float,
    atr_pct: float,
    hold_time_minutes: float = 0,
) -> AdaptiveExitParams:
    """
    Compute regime-adaptive exit parameters.

    Parameters
    ----------
    regime : RegimeState
        Current market regime.
    pnl_pct : float
        Current unrealized P&L as decimal (e.g., -0.02 = -2%).
    atr_pct : float
        Current ATR as percentage (e.g., 0.5 = 0.5%).
    hold_time_minutes : float
        How long the position has been held.

    Returns
    -------
    AdaptiveExitParams with adjusted thresholds.
    """
    params = REGIME_EXIT_PARAMS.get(regime.regime, {})

    threshold_mult = params.get("threshold_mult", 1.0)
    consec_add = params.get("min_consecutive_add", 0)
    decay_mult = params.get("decay_mult", 1.0)
    sell_weight_mult = params.get("sell_weight_mult", 1.0)

    # Base params adjusted by regime
    threshold = BASE_PRESSURE_THRESHOLD * threshold_mult
    min_consec = max(1, BASE_MIN_CONSECUTIVE + consec_add)
    decay = BASE_DECAY_RATE * decay_mult
    sell_w = BASE_SELL_WEIGHT * sell_weight_mult
    strong_sell_w = BASE_STRONG_SELL_WEIGHT * sell_weight_mult

    # Volatility risk floor: how many ATRs is our loss?
    atr_decimal = max(atr_pct / 100.0, 0.0001)
    if pnl_pct < 0:
        loss_in_atrs = abs(pnl_pct) / atr_decimal
    else:
        loss_in_atrs = 0

    vol_urgency = 0.0
    if loss_in_atrs > VOL_RISK_ATR_MULTIPLIER:
        # Loss exceeds risk floor → increase urgency
        excess_atrs = loss_in_atrs - VOL_RISK_ATR_MULTIPLIER
        vol_urgency = min(1.0, excess_atrs * VOL_RISK_URGENCY_SCALE)
        # Lower threshold proportionally
        threshold *= max(0.3, 1.0 - vol_urgency * 0.5)
        # Reduce consecutive requirement
        if vol_urgency > 0.5:
            min_consec = max(1, min_consec - 1)

    details = {
        "regime": regime.regime,
        "threshold_mult": round(threshold_mult, 3),
        "loss_in_atrs": round(loss_in_atrs, 2),
        "vol_urgency": round(vol_urgency, 3),
        "hold_minutes": round(hold_time_minutes, 1),
    }

    return AdaptiveExitParams(
        pressure_threshold=round(threshold, 4),
        min_consecutive_sells=min_consec,
        decay_rate=round(decay, 4),
        sell_weight=round(sell_w, 4),
        strong_sell_weight=round(strong_sell_w, 4),
        vol_urgency=round(vol_urgency, 4),
        regime=regime.regime,
        details=details,
    )


@dataclass
class ExitExplanation:
    """Fully explainable exit decision with all context."""
    should_exit: bool
    reason: str
    pressure: float
    threshold: float
    consecutive_sells: int
    pnl_pct: float
    regime: str
    atr_pct: float
    vol_urgency: float
    confidence: float
    direction: str
    hold_time_minutes: float


def explain_exit(
    should_exit: bool,
    reason: str,
    pressure: float,
    params: AdaptiveExitParams,
    consecutive_sells: int,
    pnl_pct: float,
    atr_pct: float,
    confidence: float,
    direction: str,
    hold_time_minutes: float,
) -> ExitExplanation:
    """Build a fully explainable exit record."""
    return ExitExplanation(
        should_exit=should_exit,
        reason=reason,
        pressure=round(pressure, 4),
        threshold=params.pressure_threshold,
        consecutive_sells=consecutive_sells,
        pnl_pct=round(pnl_pct, 6),
        regime=params.regime,
        atr_pct=round(atr_pct, 4),
        vol_urgency=params.vol_urgency,
        confidence=round(confidence, 4),
        direction=direction,
        hold_time_minutes=round(hold_time_minutes, 1),
    )
