"""
Layer C.1 — Dynamic Adaptive Position Sizing (v2.0)

Replaces the old fixed-cap approach with a multi-factor dynamic engine
inspired by CPPI (Constant Proportion Portfolio Insurance), Kelly Criterion,
and professional quant risk management.

Key principles:
  1. CPPI Cushion: Size up when equity grows above floor, size down when it shrinks
  2. Drawdown scaling: Smooth exponential reduction during drawdowns (not steps)
  3. Volatility targeting: Size inversely proportional to ATR (same dollar risk)
  4. Win streak momentum: Recent performance adjusts sizing (hot hand → bigger)
  5. Fear & Greed contrarian: Bigger in fear, smaller in greed
  6. Regime fit: Trending → full size, choppy/high-vol → reduced
  7. Confidence & edge: Model agreement scales the final size

No fixed caps — the maximum position size is computed dynamically from all
factors above. Range: ~3% (worst conditions) to ~15% (best conditions).

Research backing:
  - CPPI: scales exposure = Multiplier × (Portfolio - Floor), proven in
    institutional portfolio insurance since 1986
  - Fractional Kelly: optimal growth rate with reduced variance
  - Drawdown scaling: quant standard — cut size during drawdowns to survive
  - Contrarian F&G: buying at F&G<20 yielded 1,240% vs 680% buy-and-hold
"""
from dataclasses import dataclass
from typing import Dict, Optional
import math

try:
    from regime import RegimeState
except ImportError:
    from strategy.regime import RegimeState


@dataclass
class SizingResult:
    """Output of the dynamic sizing calculation."""
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


# ── Base Configuration ───────────────────────────────────────────────

# Risk targeting
BASE_RISK_PCT = 0.015            # Base: 1.5% of portfolio risk per trade
N_ATR_RISK = 2.0                 # risk = N * ATR (2 ATR = expected move)

# Dynamic position cap range (replaces fixed 8%)
MIN_POSITION_CAP_PCT = 0.03     # Floor: never go below 3% max cap
MAX_POSITION_CAP_PCT = 0.15     # Ceiling: never go above 15% max cap
BASE_POSITION_CAP_PCT = 0.10    # Starting point: 10% when neutral conditions

# CPPI cushion parameters
CPPI_FLOOR_PCT = 0.80           # Protect 80% of starting capital (floor)
CPPI_MULTIPLIER = 5.0           # Exposure = 5x the cushion above floor

# Portfolio heat
MIN_POSITION_USD = 5.0           # Exchange minimum
MAX_PORTFOLIO_HEAT_PCT = 0.30    # Max 30% of portfolio at risk simultaneously

# Regime adjustments
REGIME_SIZE_MULTIPLIERS = {
    "trending_up": 1.2,          # 20% boost in confirmed uptrends
    "trending_down": 0.7,        # Reduce in downtrends (counter-trend longs are risky)
    "choppy": 0.5,               # Half size in chop
    "high_vol": 0.4,             # 40% in high vol
    "unknown": 0.8,
}

# Confidence scaling
MIN_CONFIDENCE_FOR_FULL_SIZE = 0.7

# Fear & Greed contrarian multipliers
FEAR_GREED_SIZE_MULTIPLIERS = {
    "extreme_fear":  1.5,        # 50% larger — max contrarian opportunity
    "fear":          1.25,       # 25% larger
    "neutral":       1.0,        # Normal sizing
    "greed":         0.75,       # 25% smaller — market overheated
    "extreme_greed": 0.5,        # 50% smaller — high reversal risk
}


# ── Helper Functions ─────────────────────────────────────────────────

def _classify_fear_greed_zone(value: float) -> str:
    """Classify Fear & Greed index (0-100) into a zone."""
    if value < 20:
        return "extreme_fear"
    elif value < 40:
        return "fear"
    elif value < 60:
        return "neutral"
    elif value < 80:
        return "greed"
    else:
        return "extreme_greed"


def _drawdown_scale(drawdown_pct: float) -> float:
    """
    Smooth exponential drawdown scaling (replaces step function).
    - 0% drawdown → 1.0 (full size)
    - 5% drawdown → 0.86
    - 10% drawdown → 0.74
    - 15% drawdown → 0.64
    - 20% drawdown → 0.55
    - 30% drawdown → 0.41
    Formula: scale = e^(-3 * drawdown)
    Floored at 0.15 so we always trade something.
    """
    dd = max(0.0, min(1.0, abs(drawdown_pct)))
    return max(0.15, math.exp(-3.0 * dd))


def _cppi_position_cap(
    portfolio_value: float,
    starting_capital: float,
) -> float:
    """
    CPPI-inspired dynamic position cap.

    When portfolio is above floor, the "cushion" determines how aggressively
    we can size. As we win, cushion grows → bigger positions → compound faster.
    As we lose, cushion shrinks → smaller positions → protect capital.

    Returns position cap as fraction of portfolio (e.g. 0.12 = 12%).
    """
    if starting_capital <= 0 or portfolio_value <= 0:
        return BASE_POSITION_CAP_PCT

    floor = starting_capital * CPPI_FLOOR_PCT
    cushion = max(0.0, portfolio_value - floor)

    # CPPI exposure as fraction of portfolio
    if portfolio_value > 0:
        cppi_exposure = (CPPI_MULTIPLIER * cushion) / portfolio_value
    else:
        cppi_exposure = 0.0

    # Blend with base cap (50/50) so we don't go to zero if cushion is tiny
    blended = 0.5 * BASE_POSITION_CAP_PCT + 0.5 * cppi_exposure

    # Clamp to range
    return max(MIN_POSITION_CAP_PCT, min(MAX_POSITION_CAP_PCT, blended))


def _streak_factor(recent_win_rate: float, n_trades: int) -> float:
    """
    Adjust sizing based on recent trading performance.

    - Win rate > 60% → scale up (system is aligned with market)
    - Win rate < 40% → scale down (system is struggling)
    - Not enough trades → neutral

    Returns multiplier in range [0.6, 1.4].
    """
    if n_trades < 5:
        return 1.0  # Not enough data, stay neutral

    # Center around 50% win rate, scale linearly
    # 40% → 0.6x, 50% → 1.0x, 60% → 1.4x
    wr = max(0.0, min(1.0, recent_win_rate))
    factor = 0.6 + (wr - 0.3) * 2.0  # maps 0.3→0.6, 0.5→1.0, 0.7→1.4
    return max(0.6, min(1.4, factor))


def _dynamic_risk_pct(
    drawdown_pct: float,
    equity_ratio: float,
    regime_mult: float,
) -> float:
    """
    Compute dynamic risk-per-trade percentage.

    Instead of fixed 1% risk, scale based on:
    - Drawdown: reduce risk when drawing down
    - Equity growth: increase risk when portfolio is growing
    - Regime: trending → more risk, choppy → less risk

    Returns risk fraction (e.g. 0.02 = 2% risk per trade).
    Range: 0.005 (0.5%) to 0.025 (2.5%).
    """
    # Start with base risk
    risk = BASE_RISK_PCT

    # Scale by drawdown (smooth reduction)
    risk *= _drawdown_scale(drawdown_pct)

    # Scale by equity ratio (portfolio_value / starting_capital)
    # Growing portfolio → can take slightly more risk
    # Shrinking portfolio → reduce risk
    equity_boost = max(0.7, min(1.3, equity_ratio))
    risk *= equity_boost

    # Scale by regime
    risk *= regime_mult

    # Clamp to safe range
    return max(0.005, min(0.025, risk))


# ── Main Sizing Function ────────────────────────────────────────────

def calculate_vol_targeted_size(
    portfolio_value: float,
    current_price: float,
    atr_pct: float,
    confidence: float,
    regime: RegimeState,
    edge_multiplier: float = 1.0,
    open_risk_usd: float = 0.0,
    normal_atr_pct: float = 0.5,
    fear_greed_index: float = 50.0,
    starting_capital: float = 0.0,
    current_drawdown: float = 0.0,
    recent_win_rate: float = 0.5,
    recent_n_trades: int = 0,
) -> SizingResult:
    """
    Dynamic adaptive position sizing.

    Computes position size using multiple factors:
    1. ATR-based volatility targeting (constant risk per trade)
    2. CPPI cushion (dynamic cap based on equity growth)
    3. Drawdown scaling (smooth exponential reduction)
    4. Win streak momentum (recent performance factor)
    5. Fear & Greed contrarian (bigger in fear, smaller in greed)
    6. Regime fit (trending → bigger, choppy → smaller)
    7. Confidence & edge scaling (model agreement)

    Parameters
    ----------
    portfolio_value : float
        Total portfolio value in USD.
    current_price : float
        Current asset price.
    atr_pct : float
        Current ATR as percentage of price.
    confidence : float
        Model confidence (0-1).
    regime : RegimeState
        Current regime classification.
    edge_multiplier : float
        From edge gate (0-1).
    open_risk_usd : float
        Total ATR-based risk of currently open positions.
    normal_atr_pct : float
        "Normal" ATR for this symbol.
    fear_greed_index : float
        Current Fear & Greed index (0-100).
    starting_capital : float
        Initial portfolio capital (for CPPI cushion). If 0, uses portfolio_value.
    current_drawdown : float
        Current drawdown as decimal (0.10 = 10% drawdown).
    recent_win_rate : float
        Win rate of last N trades (0-1).
    recent_n_trades : int
        Number of recent trades for win rate calculation.

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

    # Default starting capital to portfolio value if not provided
    if starting_capital <= 0:
        starting_capital = portfolio_value

    # ── 1. Compute dynamic factors ───────────────────────────────────

    # ATR handling
    atr_decimal = max(atr_pct / 100.0, 0.0001)
    vol_ratio = atr_pct / normal_atr_pct if normal_atr_pct > 0 else 1.0

    # Regime multiplier
    regime_mult = REGIME_SIZE_MULTIPLIERS.get(regime.regime, 0.8)
    details["regime_multiplier"] = round(regime_mult, 3)

    # Equity ratio (how much we've grown/shrunk from start)
    equity_ratio = portfolio_value / starting_capital if starting_capital > 0 else 1.0
    details["equity_ratio"] = round(equity_ratio, 3)

    # ── 2. Dynamic risk per trade ────────────────────────────────────

    dynamic_risk = _dynamic_risk_pct(current_drawdown, equity_ratio, regime_mult)
    target_risk_usd = portfolio_value * dynamic_risk
    details["dynamic_risk_pct"] = round(dynamic_risk * 100, 3)
    details["target_risk_usd"] = round(target_risk_usd, 2)

    # ── 3. Portfolio heat check ──────────────────────────────────────

    max_risk_budget = portfolio_value * MAX_PORTFOLIO_HEAT_PCT
    remaining_risk = max_risk_budget - open_risk_usd
    details["remaining_risk_budget"] = round(remaining_risk, 2)
    details["open_risk_usd"] = round(open_risk_usd, 2)

    if remaining_risk < target_risk_usd * 0.5:
        return SizingResult(
            position_usd=0, risk_usd=0, atr_pct=atr_pct,
            vol_ratio=vol_ratio, regime_multiplier=regime_mult,
            edge_multiplier=edge_multiplier,
            skip=True,
            skip_reason=f"portfolio_heat_exceeded (open_risk=${open_risk_usd:.0f}, budget=${max_risk_budget:.0f})",
            details=details,
        )

    effective_risk = min(target_risk_usd, remaining_risk)

    # ── 4. ATR-based position size ───────────────────────────────────

    risk_per_unit = N_ATR_RISK * atr_decimal * current_price
    if risk_per_unit > 0:
        base_position_usd = effective_risk / risk_per_unit * current_price
    else:
        base_position_usd = portfolio_value * 0.02

    details["base_position_usd"] = round(base_position_usd, 2)

    # ── 5. Apply multiplier stack ────────────────────────────────────

    # Confidence scaling
    conf_mult = min(1.0, 0.5 + 0.5 * (confidence / MIN_CONFIDENCE_FOR_FULL_SIZE))
    details["confidence_multiplier"] = round(conf_mult, 3)

    # Edge multiplier
    details["edge_multiplier"] = round(edge_multiplier, 3)

    # Fear & Greed contrarian
    fg_zone = _classify_fear_greed_zone(fear_greed_index)
    fg_mult = FEAR_GREED_SIZE_MULTIPLIERS.get(fg_zone, 1.0)
    details["fear_greed_index"] = round(fear_greed_index, 1)
    details["fear_greed_zone"] = fg_zone
    details["fear_greed_multiplier"] = round(fg_mult, 3)

    # Win streak momentum
    streak_mult = _streak_factor(recent_win_rate, recent_n_trades)
    details["streak_multiplier"] = round(streak_mult, 3)
    details["recent_win_rate"] = round(recent_win_rate, 3)
    details["recent_n_trades"] = recent_n_trades

    # Drawdown scaling (smooth)
    dd_scale = _drawdown_scale(current_drawdown)
    details["drawdown_pct"] = round(current_drawdown * 100, 2)
    details["drawdown_scale"] = round(dd_scale, 3)

    # Combine all multipliers
    position_usd = (
        base_position_usd
        * conf_mult
        * edge_multiplier
        * fg_mult
        * streak_mult
        * dd_scale
    )
    # Note: regime_mult already applied via dynamic_risk_pct

    # ── 6. Dynamic position cap (CPPI-based) ─────────────────────────

    dynamic_cap_pct = _cppi_position_cap(portfolio_value, starting_capital)
    max_usd = portfolio_value * dynamic_cap_pct
    details["dynamic_cap_pct"] = round(dynamic_cap_pct * 100, 2)
    details["max_position_usd"] = round(max_usd, 2)

    position_usd = min(position_usd, max_usd)

    # ── 7. Floor check ───────────────────────────────────────────────

    if position_usd < MIN_POSITION_USD:
        return SizingResult(
            position_usd=0, risk_usd=0, atr_pct=atr_pct,
            vol_ratio=vol_ratio, regime_multiplier=regime_mult,
            edge_multiplier=edge_multiplier,
            skip=True,
            skip_reason=f"below_minimum (${position_usd:.2f} < ${MIN_POSITION_USD})",
            details=details,
        )

    # ── 8. Compute actual risk ───────────────────────────────────────

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
