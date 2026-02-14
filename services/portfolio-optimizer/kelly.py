"""
Kelly Criterion position sizing module.

Implements full, half, and quarter Kelly fraction calculations with
dynamic adjustments based on model confidence, drawdown state, and
volatility regime.
"""
import os

import structlog

logger = structlog.get_logger()

# Caps
MAX_POSITION_PCT = float(os.getenv("PORTFOLIO_MAX_POSITION_PCT", 0.05))
MIN_POSITION_USD = 10.0


def calculate_kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Full Kelly criterion:  f* = (p * b - q) / b
    where p = win probability, q = 1 - p, b = avg_win / avg_loss.

    Returns a fraction of bankroll to wager (0.0 .. 1.0, clamped).
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0

    p = max(0.0, min(1.0, win_rate))
    q = 1.0 - p
    b = avg_win / avg_loss

    kelly = (p * b - q) / b
    return max(0.0, min(1.0, kelly))


def calculate_half_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Half Kelly -- the pragmatic default. Reduces variance substantially."""
    return calculate_kelly_fraction(win_rate, avg_win, avg_loss) * 0.5


def calculate_quarter_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Quarter Kelly -- ultra-conservative."""
    return calculate_kelly_fraction(win_rate, avg_win, avg_loss) * 0.25


def _drawdown_multiplier(current_drawdown: float) -> float:
    """
    Scale position size down during drawdowns.
      0-10% drawdown  -> 100% of Kelly
      10-20% drawdown -> 50% of Kelly
      >20% drawdown   -> 25% of Kelly
    """
    dd = abs(current_drawdown)
    if dd <= 0.10:
        return 1.0
    elif dd <= 0.20:
        return 0.5
    else:
        return 0.25


def _volatility_multiplier(current_atr: float, normal_atr: float) -> float:
    """
    Reduce size in high-volatility regimes.
    If ATR > 2x the normal ATR, cut position by 50%.
    """
    if normal_atr <= 0:
        return 1.0
    ratio = current_atr / normal_atr
    if ratio > 2.0:
        return 0.5
    return 1.0


def dynamic_kelly(
    symbol: str,
    confidence: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    current_drawdown: float = 0.0,
    current_atr: float = 0.0,
    normal_atr: float = 0.0,
    kelly_mode: str = "half",
) -> float:
    """
    Compute a position-size fraction that accounts for:
      1. Base Kelly (full / half / quarter)
      2. Model confidence scaling
      3. Drawdown regime
      4. Volatility regime
      5. Hard cap at MAX_POSITION_PCT per trade

    Returns the fraction of total portfolio to allocate (0.0 .. MAX_POSITION_PCT).
    """
    # 1. Base Kelly
    if kelly_mode == "full":
        base = calculate_kelly_fraction(win_rate, avg_win, avg_loss)
    elif kelly_mode == "quarter":
        base = calculate_quarter_kelly(win_rate, avg_win, avg_loss)
    else:
        base = calculate_half_kelly(win_rate, avg_win, avg_loss)

    # 2. Scale by model confidence (0..1)
    conf = max(0.0, min(1.0, confidence))
    sized = base * conf

    # 3. Drawdown adjustment
    sized *= _drawdown_multiplier(current_drawdown)

    # 4. Volatility adjustment
    if current_atr > 0 and normal_atr > 0:
        sized *= _volatility_multiplier(current_atr, normal_atr)

    # 5. Hard cap
    sized = min(sized, MAX_POSITION_PCT)

    logger.debug(
        "dynamic_kelly",
        symbol=symbol,
        kelly_mode=kelly_mode,
        base=round(base, 5),
        confidence=round(conf, 3),
        drawdown=round(current_drawdown, 4),
        final_fraction=round(sized, 5),
    )
    return sized


def fraction_to_usd(fraction: float, portfolio_value: float) -> float:
    """Convert a Kelly fraction to a USD position size, enforcing min/max."""
    usd = fraction * portfolio_value
    if usd < MIN_POSITION_USD:
        return 0.0  # skip trade -- below minimum
    return usd
