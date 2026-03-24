"""
Smart Adaptive Stop-Loss System (v3.0)

Multi-factor dynamic stop that adapts to market conditions in real-time.
Combines research from quantitative finance and crypto-specific studies.

v3.0 changes:
  - Hard floor widened to 7% for normal regimes, 5% only in high-vol
  - Momentum override: strong upward momentum widens trailing stop temporarily
  - Time-based guard: positions < 2 min only use hard floor (no trailing)
  - Volatility-adaptive trailing: high-vol coins get wider stops automatically
  - Profit lock: up 3%+ → stop never below breakeven; up 5%+ → lock 2% profit
  - ATR multiplier widened to 3x for more breathing room

Architecture (6 layers):
  1. Regime Detection    — master switch for all parameters
  2. ATR-Based Stop      — Chandelier Exit style, anchored to peak price
  3. Momentum Check      — RSI + multi-timeframe momentum assess dip quality
  4. Volume Confirmation — volume surge on dip = real selling, low volume = noise
  5. Trend Health        — EMA crosses + MACD confirm if trend is intact
  6. AI Integration      — prediction pressure modulates stop aggressiveness

The system outputs a single stop_distance_pct per position per tick.
Position manager compares (peak_price - current_price) / peak_price against this.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SmartStopResult:
    """Output of the smart stop calculation."""
    stop_distance_pct: float       # Final adaptive stop distance (0.01 = 1%)
    should_exit: bool              # Whether current price breaches the stop
    base_atr_stop: float           # Raw ATR-based stop distance
    regime_mult: float             # Regime multiplier applied
    momentum_mult: float           # Momentum adjustment
    volume_mult: float             # Volume adjustment
    trend_mult: float              # Trend health adjustment
    ai_mult: float                 # AI prediction adjustment
    reason: str                    # Human-readable explanation
    hard_floor_pct: float          # Absolute maximum loss allowed
    profit_lock_pct: float = 0.0   # Minimum locked profit (0 = no lock)


# ── Configuration ─────────────────────────────────────────────────────

# Chandelier Exit: stop = peak_price - (ATR_MULT * ATR)
ATR_STOP_MULT = 3.0              # Base: 3x ATR from peak (was 2.5)

# Regime multipliers (scales the ATR stop distance)
REGIME_STOP_MULTS = {
    "trending_up":  1.3,          # Trending: give room to run
    "trending_down": 0.7,         # Counter-trend longs: tight stop
    "choppy":       0.6,          # Choppy: get out fast
    "high_vol":     1.5,          # High vol: need room for swings
    "unknown":      1.0,
}

# Hard floor: absolute maximum loss regardless of other factors.
# Position manager has a 3% hard stop. These are backup disaster limits only.
# Research: tight floors (1-2%) destroy edge in crypto where 2% swings are normal noise.
HARD_FLOOR_LOSS_PCT_NORMAL = 0.04    # 4% — backup behind position manager's 3%
HARD_FLOOR_LOSS_PCT_HIGH_VOL = 0.03  # 3% — tighter in high vol

# Minimum stop: dynamic — used only for trailing after profit
# v13: Widened trailing to let winners breathe. 0.3% was getting shaken out by noise.
MIN_STOP_FLOOR = 0.005           # 0.5% trailing stop once profitable
MIN_STOP_ATR_MULT = 0.5          # trailing = 0.5x ATR (was 0.3)

# Trailing activation: don't start trailing until position has real profit
TRAIL_ACTIVATION_FLOOR = 0.015   # 1.5% profit activates trailing — let winners develop
TRAIL_ACTIVATION_ATR_MULT = 1.2  # activate trailing after 1.2x ATR profit

# Time guard: positions held less than this many minutes only use hard floor
YOUNG_POSITION_MINUTES = 1.0     # 1 min guard (was 2)

# Momentum override: widen stop when position shows strong upward momentum
MOMENTUM_OVERRIDE_WIDEN = 1.2    # 20% wider stop when momentum is strong (was 40%)

# Profit lock thresholds — protect big winners, but let trades breathe.
# Old values (0.5% breakeven) locked profits too early, causing premature exits on winners.
PROFIT_LOCK_BREAKEVEN_THRESHOLD = 0.02   # 2%+ profit → stop at breakeven
PROFIT_LOCK_TIER1_THRESHOLD = 0.03       # 3%+ profit → lock 1% profit
PROFIT_LOCK_TIER1_FLOOR = 0.01           # Minimum locked profit at tier 1
PROFIT_LOCK_TIER2_THRESHOLD = 0.05       # 5%+ profit → lock 2.5% profit
PROFIT_LOCK_TIER2_FLOOR = 0.025          # Minimum locked profit at tier 2
PROFIT_LOCK_TIER3_THRESHOLD = 0.08       # 8%+ profit → lock 5% profit
PROFIT_LOCK_TIER3_FLOOR = 0.05           # Minimum locked profit at tier 3

# Patience exit: only for positions stuck losing for extended time.
# AI exit pressure handles normal adverse trades. This is for forgotten positions.
PATIENCE_MAX_MINUTES = 60.0      # After 60 min at a loss with no recovery
PATIENCE_MIN_LOSS_PCT = 0.015    # Cut if losing > 1.5% after patience period

# Volatility-adaptive trailing: scale trailing stop width by recent vol
VOL_TRAIL_WIDEN_THRESHOLD = 1.5  # If vol_ratio > 1.5, widen trailing stop
VOL_TRAIL_WIDEN_MULT = 1.2       # Widen by 20% for high-vol coins (was 30%)


def compute_smart_stop(
    pnl_pct: float,
    peak_pnl_pct: float,
    atr_pct: float,
    rsi_14: float,
    volume_ratio: float,
    momentum_5m: float,
    momentum_15m: float,
    momentum_30m: float,
    macd_histogram: float,
    ema_cross_9_21: float,
    ema_cross_25_50: float,
    regime: str,
    ai_pressure: float,
    ai_threshold: float,
    hold_time_minutes: float,
    bollinger_b: float = 0.5,
    side: str = "long",
    normal_atr_pct: float = 0.5,
) -> SmartStopResult:
    """
    Compute the adaptive stop-loss distance for a position.

    Returns a SmartStopResult with the final stop distance and whether
    the position should be exited.
    """

    # ══════════════════════════════════════════════════════════════════
    # LAYER 1: Base ATR Stop (Chandelier Exit style)
    # ══════════════════════════════════════════════════════════════════
    # atr_pct is already expressed as % of price (e.g., 0.5 = 0.5%)
    # Convert to decimal: 0.5% → 0.005
    atr_decimal = max(atr_pct / 100, 0.001)  # floor at 0.1%
    base_atr_stop = ATR_STOP_MULT * atr_decimal

    # Dynamic minimum stop: scales with volatility
    min_stop_pct = max(MIN_STOP_FLOOR, MIN_STOP_ATR_MULT * atr_decimal)

    # Dynamic trailing activation: scales with volatility
    trail_activation_pct = max(TRAIL_ACTIVATION_FLOOR, TRAIL_ACTIVATION_ATR_MULT * atr_decimal)

    # ══════════════════════════════════════════════════════════════════
    # Regime-dependent hard floor
    # ══════════════════════════════════════════════════════════════════
    if regime == "high_vol":
        hard_floor_pct = HARD_FLOOR_LOSS_PCT_HIGH_VOL
    else:
        hard_floor_pct = HARD_FLOOR_LOSS_PCT_NORMAL

    # ══════════════════════════════════════════════════════════════════
    # LAYER 2: Regime Multiplier
    # ══════════════════════════════════════════════════════════════════
    regime_mult = REGIME_STOP_MULTS.get(regime, 1.0)

    # ══════════════════════════════════════════════════════════════════
    # LAYER 3: Momentum Assessment
    # ══════════════════════════════════════════════════════════════════
    momentum_mult = 1.0
    strong_favorable_momentum = False

    if side == "long":
        mom_signals = [momentum_5m, momentum_15m, momentum_30m]
        positive_count = sum(1 for m in mom_signals if m > 0)

        if positive_count >= 2:
            momentum_mult = 1.2
        elif positive_count == 0:
            momentum_mult = 0.7

        if rsi_14 < 30:
            momentum_mult *= 1.15
        elif rsi_14 > 70:
            momentum_mult *= 0.8

        # Detect strong upward momentum for override:
        # all 3 timeframes positive AND short-term is strongest
        if positive_count == 3 and momentum_5m > 0 and momentum_5m >= momentum_15m:
            strong_favorable_momentum = True

    else:  # short
        mom_signals = [momentum_5m, momentum_15m, momentum_30m]
        negative_count = sum(1 for m in mom_signals if m < 0)

        if negative_count >= 2:
            momentum_mult = 1.2
        elif negative_count == 0:
            momentum_mult = 0.7

        if rsi_14 > 70:
            momentum_mult *= 1.15
        elif rsi_14 < 30:
            momentum_mult *= 0.8

        # Strong downward momentum for short positions
        if negative_count == 3 and momentum_5m < 0 and momentum_5m <= momentum_15m:
            strong_favorable_momentum = True

    # ══════════════════════════════════════════════════════════════════
    # LAYER 4: Volume Confirmation
    # ══════════════════════════════════════════════════════════════════
    volume_mult = 1.0

    if pnl_pct < 0:  # Position is currently losing
        if volume_ratio > 2.0:
            volume_mult = 0.7
        elif volume_ratio > 1.5:
            volume_mult = 0.85
        elif volume_ratio < 0.5:
            volume_mult = 1.2
    elif pnl_pct > 0 and volume_ratio > 1.5:
        volume_mult = 1.15

    # ══════════════════════════════════════════════════════════════════
    # LAYER 5: Trend Health (EMA + MACD)
    # ══════════════════════════════════════════════════════════════════
    trend_mult = 1.0

    if side == "long":
        trend_score = 0
        if ema_cross_9_21 > 0:
            trend_score += 1
        if ema_cross_25_50 > 0:
            trend_score += 1
        if macd_histogram > 0:
            trend_score += 1

        if trend_score == 3:
            trend_mult = 1.25
        elif trend_score == 0:
            trend_mult = 0.6
        elif trend_score == 1:
            trend_mult = 0.85
    else:
        trend_score = 0
        if ema_cross_9_21 < 0:
            trend_score += 1
        if ema_cross_25_50 < 0:
            trend_score += 1
        if macd_histogram < 0:
            trend_score += 1

        if trend_score == 3:
            trend_mult = 1.25
        elif trend_score == 0:
            trend_mult = 0.6
        elif trend_score == 1:
            trend_mult = 0.85

    # ══════════════════════════════════════════════════════════════════
    # LAYER 6: AI Prediction Integration
    # ══════════════════════════════════════════════════════════════════
    ai_mult = 1.0

    if ai_threshold > 0:
        pressure_ratio = ai_pressure / ai_threshold
        if pressure_ratio > 0.7:
            ai_mult = 0.7
        elif pressure_ratio > 0.4:
            ai_mult = 0.85
        elif pressure_ratio < 0.15:
            ai_mult = 1.2

    # ══════════════════════════════════════════════════════════════════
    # COMBINE: Final stop distance
    # ══════════════════════════════════════════════════════════════════
    combined_mult = regime_mult * momentum_mult * volume_mult * trend_mult * ai_mult
    combined_mult = max(combined_mult, 0.5)  # Cap compounding — never crush stop below 50%
    raw_stop = base_atr_stop * combined_mult

    # ── Momentum override: widen stop if position has strong favorable momentum
    if strong_favorable_momentum and pnl_pct > 0:
        raw_stop *= MOMENTUM_OVERRIDE_WIDEN

    # ── Volatility-adaptive trailing: widen for high-vol coins
    vol_ratio = atr_pct / normal_atr_pct if normal_atr_pct > 0 else 1.0
    if vol_ratio > VOL_TRAIL_WIDEN_THRESHOLD:
        raw_stop *= VOL_TRAIL_WIDEN_MULT

    # Apply dynamic floor and hard ceiling
    stop_distance = max(raw_stop, min_stop_pct)
    stop_distance = min(stop_distance, hard_floor_pct)

    # ══════════════════════════════════════════════════════════════════
    # PROFIT LOCK v7: "Never let a winner become a loser" — multi-tier
    # ══════════════════════════════════════════════════════════════════
    profit_lock_pct = 0.0

    # Determine current required lock level based on peak profit
    if peak_pnl_pct >= PROFIT_LOCK_TIER3_THRESHOLD:
        profit_lock_pct = PROFIT_LOCK_TIER3_FLOOR      # 3%+ peak → lock 1.5%
    elif peak_pnl_pct >= PROFIT_LOCK_TIER2_THRESHOLD:
        profit_lock_pct = PROFIT_LOCK_TIER2_FLOOR       # 2%+ peak → lock 0.8%
    elif peak_pnl_pct >= PROFIT_LOCK_TIER1_THRESHOLD:
        profit_lock_pct = PROFIT_LOCK_TIER1_FLOOR       # 1%+ peak → lock 0.3%
    elif peak_pnl_pct >= PROFIT_LOCK_BREAKEVEN_THRESHOLD:
        profit_lock_pct = 0.0                           # 0.5%+ peak → lock breakeven

    # ══════════════════════════════════════════════════════════════════
    # DETERMINE EXIT
    # ══════════════════════════════════════════════════════════════════
    drop_from_peak = peak_pnl_pct - pnl_pct if peak_pnl_pct > 0 else 0
    hard_floor_breached = pnl_pct <= -hard_floor_pct

    # Time guard: positions held < 1 minute only use hard floor, no trailing
    is_young_position = hold_time_minutes < YOUNG_POSITION_MINUTES
    trailing_breached = False
    if not is_young_position:
        trailing_breached = (peak_pnl_pct >= trail_activation_pct) and (drop_from_peak >= stop_distance)

    # Profit lock enforcement: check if current PnL dropped below lock level
    profit_lock_breached = False
    if peak_pnl_pct >= PROFIT_LOCK_BREAKEVEN_THRESHOLD and not is_young_position:
        if peak_pnl_pct >= PROFIT_LOCK_TIER3_THRESHOLD and pnl_pct < PROFIT_LOCK_TIER3_FLOOR:
            profit_lock_breached = True
            profit_lock_pct = PROFIT_LOCK_TIER3_FLOOR
        elif peak_pnl_pct >= PROFIT_LOCK_TIER2_THRESHOLD and pnl_pct < PROFIT_LOCK_TIER2_FLOOR:
            profit_lock_breached = True
            profit_lock_pct = PROFIT_LOCK_TIER2_FLOOR
        elif peak_pnl_pct >= PROFIT_LOCK_TIER1_THRESHOLD and pnl_pct < PROFIT_LOCK_TIER1_FLOOR:
            profit_lock_breached = True
            profit_lock_pct = PROFIT_LOCK_TIER1_FLOOR
        elif peak_pnl_pct >= PROFIT_LOCK_BREAKEVEN_THRESHOLD and pnl_pct < 0:
            profit_lock_breached = True
            profit_lock_pct = 0.0

    # v8: "Always win" — no quick kill, no stale exit at small losses
    # Only exit at a loss in catastrophic scenarios (>5% loss after 2 hours)
    patience_exit = False
    if hold_time_minutes > PATIENCE_MAX_MINUTES and pnl_pct < -PATIENCE_MIN_LOSS_PCT:
        patience_exit = True  # Only exit if losing big after long hold

    should_exit = hard_floor_breached or trailing_breached or profit_lock_breached or patience_exit

    # Build reason string (priority order)
    if profit_lock_breached:
        reason = f"profit_lock_{profit_lock_pct:.1%}_breached (peak={peak_pnl_pct:.2%}, now={pnl_pct:.2%})"
    elif trailing_breached:
        reason = f"adaptive_trail_{stop_distance:.2%}_from_peak"
    elif patience_exit:
        reason = f"patience_exit_{hold_time_minutes:.0f}m_loss_{pnl_pct:.2%}"
    elif hard_floor_breached:
        reason = f"hard_floor_{hard_floor_pct:.0%}_breached"
    elif is_young_position:
        reason = f"holding (young {hold_time_minutes:.1f}m)"
    else:
        reason = "holding"

    return SmartStopResult(
        stop_distance_pct=stop_distance,
        should_exit=should_exit,
        base_atr_stop=base_atr_stop,
        regime_mult=regime_mult,
        momentum_mult=round(momentum_mult, 3),
        volume_mult=round(volume_mult, 3),
        trend_mult=round(trend_mult, 3),
        ai_mult=round(ai_mult, 3),
        reason=reason,
        hard_floor_pct=hard_floor_pct,
        profit_lock_pct=profit_lock_pct,
    )
