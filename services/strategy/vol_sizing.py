"""
Layer C.1 — Volatility-Targeted Position Sizing

Instead of fixed position sizes, we target a constant per-trade risk
by scaling inversely with volatility:

  position_size = target_risk_usd / (ATR_pct * price * N_atr)

This means:
  - In calm markets: larger positions (same dollar risk)
  - In volatile markets: smaller positions (same dollar risk)
  - Per-trade risk stays constant regardless of volatility

We also enforce:
  - Portfolio heat cap: max total risk across all open positions
  - Per-position max: never exceed X% of portfolio in one trade
  - Minimum position: skip trades below the exchange minimum

This replaces the old approach of "8% of capital for strong, 4% for normal"
with a principled volatility-targeting framework.
"""
from dataclasses import dataclass
from typing import Dict, Optional

from .regime import RegimeState


@dataclass
class SizingResult:
    """Output of the volatility-targeted sizing calculation."""
    position_usd: float        # dollar amount to trade
    risk_usd: float            # expected dollar risk (ATR-based)
    atr_pct: float             # current ATR as % of price
    vol_ratio: float           # current_vol / normal_vol
    regime_multiplier: float   # regime-based size adjustment
    edge_multiplier: float     # edge gate size multiplier
    skip: bool                 # True if trade should be skipped
    skip_reason: str = ""
    details: Dict[str, float] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


# ── Configuration ─────────────────────────────────────────────────────

# Target: each trade risks this fraction of portfolio
TARGET_RISK_PCT = 0.01           # 1% of portfolio per trade
N_ATR_RISK = 2.0                 # risk = N * ATR (2 ATR = typical move)

# Caps
MAX_POSITION_PCT = 0.08          # never more than 8% of portfolio per trade
MIN_POSITION_USD = 5.0           # exchange minimum
MAX_PORTFOLIO_HEAT_PCT = 0.25    # max 25% of portfolio at risk simultaneously

# Regime adjustments
REGIME_SIZE_MULTIPLIERS = {
    "trending_up": 1.0,          # full size in trends
    "trending_down": 1.0,
    "choppy": 0.5,               # half size in chop
    "high_vol": 0.4,             # 40% in high vol
}

# Confidence scaling: size proportional to confidence
MIN_CONFIDENCE_FOR_FULL_SIZE = 0.7


def calculate_vol_targeted_size(
    portfolio_value: float,
    current_price: float,
    atr_pct: float,
    confidence: float,
    regime: RegimeState,
    edge_multiplier: float = 1.0,
    open_risk_usd: float = 0.0,
    normal_atr_pct: float = 0.5,
) -> SizingResult:
    """
    Calculate position size targeting constant risk per trade.

    Parameters
    ----------
    portfolio_value : float
        Total portfolio value in USD.
    current_price : float
        Current asset price.
    atr_pct : float
        Current ATR as percentage of price (from feature-store).
    confidence : float
        Model confidence (0-1).
    regime : RegimeState
        Current regime classification.
    edge_multiplier : float
        From edge gate (0-1).
    open_risk_usd : float
        Total ATR-based risk of currently open positions.
    normal_atr_pct : float
        "Normal" ATR for this symbol (median of recent history).

    Returns
    -------
    SizingResult
    """
    details = {}

    if portfolio_value <= 0 or current_price <= 0:
        return SizingResult(
            position_usd=0, risk_usd=0, atr_pct=atr_pct,
            vol_ratio=1.0, regime_multiplier=1.0, edge_multiplier=edge_multiplier,
            skip=True, skip_reason="zero_portfolio_or_price",
        )

    # Use ATR as measure of expected move
    atr_decimal = max(atr_pct / 100.0, 0.0001)  # convert from % to decimal, floor at 0.01%
    vol_ratio = atr_pct / normal_atr_pct if normal_atr_pct > 0 else 1.0

    # Target risk in USD
    target_risk_usd = portfolio_value * TARGET_RISK_PCT
    details["target_risk_usd"] = round(target_risk_usd, 2)

    # Portfolio heat check: don't exceed max concurrent risk
    max_risk_budget = portfolio_value * MAX_PORTFOLIO_HEAT_PCT
    remaining_risk = max_risk_budget - open_risk_usd
    details["remaining_risk_budget"] = round(remaining_risk, 2)
    details["open_risk_usd"] = round(open_risk_usd, 2)

    if remaining_risk < target_risk_usd * 0.5:
        return SizingResult(
            position_usd=0, risk_usd=0, atr_pct=atr_pct,
            vol_ratio=vol_ratio, regime_multiplier=1.0, edge_multiplier=edge_multiplier,
            skip=True, skip_reason=f"portfolio_heat_exceeded (open_risk=${open_risk_usd:.0f}, budget=${max_risk_budget:.0f})",
            details=details,
        )

    # Cap target risk to remaining budget
    effective_risk = min(target_risk_usd, remaining_risk)

    # Position size = risk / (N * ATR_decimal)
    # This is the dollar amount where N*ATR move = effective_risk
    risk_per_unit = N_ATR_RISK * atr_decimal * current_price
    if risk_per_unit > 0:
        base_position_usd = effective_risk / risk_per_unit * current_price
    else:
        base_position_usd = portfolio_value * 0.02  # fallback: 2% of portfolio

    details["base_position_usd"] = round(base_position_usd, 2)

    # Apply regime multiplier
    regime_mult = REGIME_SIZE_MULTIPLIERS.get(regime.regime, 0.7)
    details["regime_multiplier"] = round(regime_mult, 3)

    # Apply confidence scaling (linear scale from 0.5x at min to 1.0x at full)
    conf_mult = min(1.0, 0.5 + 0.5 * (confidence / MIN_CONFIDENCE_FOR_FULL_SIZE))
    details["confidence_multiplier"] = round(conf_mult, 3)

    # Apply edge multiplier from gate
    details["edge_multiplier"] = round(edge_multiplier, 3)

    # Final position
    position_usd = base_position_usd * regime_mult * conf_mult * edge_multiplier

    # Cap at max per-position
    max_usd = portfolio_value * MAX_POSITION_PCT
    position_usd = min(position_usd, max_usd)
    details["max_position_usd"] = round(max_usd, 2)

    # Floor at minimum
    if position_usd < MIN_POSITION_USD:
        return SizingResult(
            position_usd=0, risk_usd=0, atr_pct=atr_pct,
            vol_ratio=vol_ratio, regime_multiplier=regime_mult,
            edge_multiplier=edge_multiplier,
            skip=True, skip_reason=f"below_minimum (${position_usd:.2f} < ${MIN_POSITION_USD})",
            details=details,
        )

    # Actual risk for this position (for heat tracking)
    actual_risk = position_usd * N_ATR_RISK * atr_decimal
    details["actual_risk_usd"] = round(actual_risk, 2)
    details["position_usd"] = round(position_usd, 2)

    return SizingResult(
        position_usd=round(position_usd, 2),
        risk_usd=round(actual_risk, 2),
        atr_pct=round(atr_pct, 4),
        vol_ratio=round(vol_ratio, 3),
        regime_multiplier=round(regime_mult, 3),
        edge_multiplier=round(edge_multiplier, 3),
        skip=False,
        details=details,
    )
