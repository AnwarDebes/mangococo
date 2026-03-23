"""
Layer B — Edge Gate (Meta-labeling style)

Decides whether to TAKE or SKIP a trade based on contextual quality:
- Model confidence and agreement
- Feature data quality (sentiment/onchain availability)
- Regime alignment with signal direction
- Spread/volatility conditions (don't trade in wide-spread or extreme vol)
- Fear & Greed contrarian signal (buy when others are fearful)
- Fast mover detection (lower threshold for coins moving fast with volume)
- Composite "edge score" that must exceed a threshold

This is the guard that prevents the system from trading when there
isn't genuine edge, even if the model says "buy."

The gate produces an EdgeDecision with:
  take: bool        — whether to take the trade
  edge_score: float — composite score (0-1), higher = more edge
  size_mult: float  — recommended size multiplier (0-1)
  reasons: list     — why the gate decided this way
"""
from dataclasses import dataclass, field
from typing import Dict, List

try:
    from regime import RegimeState
except ImportError:
    from strategy.regime import RegimeState


@dataclass
class EdgeDecision:
    """Output of the edge gate: take/skip + sizing hint."""
    take: bool
    edge_score: float          # 0.0 to 1.0
    size_multiplier: float     # 0.0 to 1.0 (applied on top of vol sizing)
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, float] = field(default_factory=dict)
    max_concurrent_positions: int = 8  # F&G-aware position limit


# ── Configuration ─────────────────────────────────────────────────────

EDGE_THRESHOLD = 0.50          # minimum edge score to take trade (raised from 0.40)
MIN_CONFIDENCE = 0.50          # model must be at least 50% confident (raised from 0.35)
AGREEMENT_BONUS = 0.15         # bonus when TCN + XGBoost agree

# Spread filter: tightened for normal entries, relaxed for fast movers
MAX_SPREAD_PCT = 0.25          # skip if spread > 0.25% for normal entries (relaxed from 0.15%)
MAX_SPREAD_PCT_FAST_MOVER = 0.40  # allow up to 0.40% for fast movers

# Fast mover detection thresholds
FAST_MOVER_PRICE_CHANGE_PCT = 0.02   # 2%+ price change in window
FAST_MOVER_VOLUME_RATIO_MIN = 1.5    # Volume must be increasing (1.5x+ normal)
FAST_MOVER_EDGE_REDUCTION = 0.10     # Lower edge threshold by 10% for fast movers

# Regime-based adjustments
REGIME_EDGE_PENALTIES = {
    "choppy": 0.10,            # 10% more edge in chop (lowered — system profits in chop with momentum TP)
    "high_vol": 0.20,          # need 20% more edge in high vol (raised from 0.15)
    "trending_up": 0.0,        # no penalty in trends
    "trending_down": 0.0,
}

# Fear & Greed contrarian thresholds
# Historical data: buying at F&G < 20 yields avg +62% in 90 days
# Contrarian strategy (buy <20, sell >80) returned 1,240% vs 680% buy-and-hold
FEAR_GREED_ZONES = {
    "extreme_fear":  (0,  20),   # Strong contrarian buy signal
    "fear":          (20, 40),   # Mild contrarian buy signal
    "neutral":       (40, 60),   # No adjustment
    "greed":         (60, 80),   # Caution — reduce edge
    "extreme_greed": (80, 100),  # Strong caution — high bar to enter
}

# Edge threshold adjustments based on Fear & Greed zone (negative = easier entry)
FEAR_GREED_THRESHOLD_ADJUSTMENTS = {
    "extreme_fear":  -0.15,   # Lower bar: easier to enter in extreme fear
    "fear":          -0.08,   # Slightly easier to enter
    "neutral":        0.0,    # No change
    "greed":          0.10,   # Harder to enter in greed
    "extreme_greed":  0.20,   # Much harder to enter in extreme greed
}

# Edge score bonus from Fear & Greed (added to composite score for buys)
FEAR_GREED_EDGE_BONUS = {
    "extreme_fear":   0.12,   # Boost edge score — contrarian opportunity
    "fear":           0.06,   # Small boost
    "neutral":        0.0,
    "greed":         -0.05,   # Penalize edge
    "extreme_greed": -0.10,   # Strong penalty
}

# F&G-aware minimum confidence thresholds (overrides MIN_CONFIDENCE per zone)
FEAR_GREED_MIN_CONFIDENCE = {
    "extreme_fear":  0.55,   # Relaxed from 0.70 to allow more entries in extreme fear
    "fear":          0.52,   # Relaxed from 0.60 to allow more entries in fear
    "neutral":       0.50,   # Normal operation
    "greed":         0.52,   # Relaxed from 0.60 to allow more entries in greed
    "extreme_greed": 0.55,   # Relaxed from 0.70 to allow more entries in extreme greed
}

# F&G-aware max concurrent position limits
FEAR_GREED_MAX_POSITIONS = {
    "extreme_fear":  10,
    "fear":          10,
    "neutral":       12,
    "greed":         8,
    "extreme_greed": 6,
}

# Direction preference by F&G zone: positive = prefer longs, negative = prefer shorts
# Applied as an extra confidence penalty for the disfavored direction
FEAR_GREED_DIRECTION_PENALTY = {
    "extreme_fear":  {"buy": 0.0,  "sell": 0.10},  # No extra penalty for buys in fear
    "fear":          {"buy": 0.0,  "sell": 0.05},
    "neutral":       {"buy": 0.0,  "sell": 0.0},
    "greed":         {"buy": 0.05, "sell": 0.0},    # Penalize longs in greed
    "extreme_greed": {"buy": 0.10, "sell": 0.0},    # Strong penalty for longs in extreme greed
}

# Feature quality weights (rebalanced to include fear/greed)
WEIGHT_CONFIDENCE = 0.30
WEIGHT_REGIME_FIT = 0.22
WEIGHT_DATA_QUALITY = 0.13
WEIGHT_SPREAD = 0.10
WEIGHT_AGREEMENT = 0.13
WEIGHT_FEAR_GREED = 0.12     # New: contrarian sentiment weight


def _detect_fast_mover(features: Dict[str, float]) -> bool:
    """
    Detect if a coin is a "fast mover" — significant price action with
    increasing volume, indicating a move worth capturing.

    Looks for 2%+ price change in the last 5 minutes with volume ratio >= 1.5x.
    """
    price_change_5m = abs(features.get("price_change_5m", 0.0))
    volume_ratio_5m = features.get("volume_ratio_5m", features.get("volume_ratio", 1.0))

    return (
        price_change_5m >= FAST_MOVER_PRICE_CHANGE_PCT
        and volume_ratio_5m >= FAST_MOVER_VOLUME_RATIO_MIN
    )


def evaluate_edge(
    prediction: dict,
    regime: RegimeState,
    features: Dict[str, float],
    open_position_count: int = 0,
) -> EdgeDecision:
    """
    Evaluate whether a trade signal has enough edge to take.

    Parameters
    ----------
    prediction : dict
        Prediction payload from the ML ensemble. Expected keys:
        direction, confidence, score, breakdown (with tcn/xgboost/
        sentiment/onchain/agreement_bonus/sentiment_available/onchain_available)
    regime : RegimeState
        Current regime classification.
    features : dict
        Features from Redis (features:{symbol}).
    open_position_count : int
        Number of currently open positions (for F&G position limits).

    Returns
    -------
    EdgeDecision
    """
    direction = prediction.get("direction", "hold")
    confidence = float(prediction.get("confidence", 0))
    score = float(prediction.get("score", 0))
    breakdown = prediction.get("breakdown", {})

    reasons: List[str] = []
    details: Dict[str, float] = {}

    # ── Fast mover detection ────────────────────────────────────────
    is_fast_mover = _detect_fast_mover(features)
    details["is_fast_mover"] = 1.0 if is_fast_mover else 0.0
    if is_fast_mover:
        reasons.append("fast_mover_detected")

    # Choose spread limit based on fast mover status
    active_max_spread = MAX_SPREAD_PCT_FAST_MOVER if is_fast_mover else MAX_SPREAD_PCT

    # ── 1. Model confidence score (0-1) ───────────────────────────────
    conf_score = min(1.0, confidence / 0.8)  # normalized: 80% confidence = 1.0
    details["confidence_raw"] = round(confidence, 3)
    details["confidence_score"] = round(conf_score, 3)

    if confidence < MIN_CONFIDENCE:
        reasons.append(f"low_confidence ({confidence:.2f} < {MIN_CONFIDENCE})")
        return EdgeDecision(
            take=False, edge_score=conf_score * 0.3,
            size_multiplier=0.0, reasons=reasons, details=details,
        )

    # ── 1b. F&G-aware confidence gating ──────────────────────────────
    # Determine F&G zone early for confidence and position limit checks
    fear_greed_value = features.get("fear_greed_index", 50.0)
    fg_zone_early = "neutral"
    for zone_name, (low, high) in FEAR_GREED_ZONES.items():
        if low <= fear_greed_value < high:
            fg_zone_early = zone_name
            break
    if fear_greed_value >= 100:
        fg_zone_early = "extreme_greed"

    # Apply F&G-aware minimum confidence threshold
    fg_min_confidence = FEAR_GREED_MIN_CONFIDENCE.get(fg_zone_early, MIN_CONFIDENCE)
    details["fg_min_confidence"] = fg_min_confidence
    details["fg_zone_early"] = fg_zone_early

    # Apply direction-specific penalty (e.g., penalize longs in extreme greed)
    direction_penalty = FEAR_GREED_DIRECTION_PENALTY.get(fg_zone_early, {})
    normalized_dir = "buy" if direction in ("buy", "strong_buy") else "sell"
    dir_penalty = direction_penalty.get(normalized_dir, 0.0)
    effective_fg_confidence = fg_min_confidence + dir_penalty
    details["fg_direction_penalty"] = dir_penalty
    details["fg_effective_min_confidence"] = effective_fg_confidence

    if confidence < effective_fg_confidence:
        reasons.append(
            f"fg_confidence_gate ({confidence:.2f} < {effective_fg_confidence:.2f}, "
            f"zone={fg_zone_early}, dir={normalized_dir})"
        )
        return EdgeDecision(
            take=False, edge_score=conf_score * 0.3,
            size_multiplier=0.0, reasons=reasons, details=details,
        )

    # ── 1c. F&G-aware position limit check ────────────────────────────
    max_positions = FEAR_GREED_MAX_POSITIONS.get(fg_zone_early, 8)
    details["fg_max_positions"] = max_positions
    details["open_position_count"] = open_position_count

    if open_position_count >= max_positions:
        reasons.append(
            f"fg_position_limit ({open_position_count} >= {max_positions}, "
            f"zone={fg_zone_early})"
        )
        return EdgeDecision(
            take=False, edge_score=conf_score * 0.5,
            size_multiplier=0.0, reasons=reasons, details=details,
            max_concurrent_positions=max_positions,
        )

    # ── 2. Regime fit score (0-1) ─────────────────────────────────────
    regime_fit = 0.0
    if regime.regime in ("trending_up", "trending_down"):
        # Check alignment: buy in uptrend = good, buy in downtrend = bad
        if direction in ("buy", "strong_buy") and regime.regime == "trending_up":
            regime_fit = regime.trend_strength
            reasons.append("regime_aligned_bullish")
        elif direction in ("sell", "strong_sell") and regime.regime == "trending_down":
            regime_fit = regime.trend_strength
            reasons.append("regime_aligned_bearish")
        elif direction in ("buy", "strong_buy") and regime.regime == "trending_down":
            regime_fit = 0.0
            reasons.append("regime_opposed_buying_in_downtrend")
        elif direction in ("sell", "strong_sell") and regime.regime == "trending_up":
            regime_fit = 0.0
            reasons.append("regime_opposed_selling_in_uptrend")
        else:
            regime_fit = 0.3  # hold signal in trend — meh
    elif regime.regime == "choppy":
        regime_fit = max(0.0, 0.4 - regime.choppiness * 0.5)
        reasons.append(f"choppy_regime (chop={regime.choppiness:.2f})")
    elif regime.regime == "high_vol":
        regime_fit = 0.3  # can still trade but cautiously
        reasons.append("high_vol_regime")
    else:
        regime_fit = 0.5  # unknown/neutral

    details["regime_fit"] = round(regime_fit, 3)

    # ── 3. Data quality score (0-1) ───────────────────────────────────
    sentiment_avail = float(breakdown.get("sentiment_available", 0))
    onchain_avail = float(breakdown.get("onchain_available", 0))
    # Feature-store features available?
    has_features = 1.0 if features.get("rsi_14", 0) != 0 else 0.0

    data_quality = (sentiment_avail * 0.3 + onchain_avail * 0.3 + has_features * 0.4)
    details["data_quality"] = round(data_quality, 3)
    details["sentiment_available"] = sentiment_avail
    details["onchain_available"] = onchain_avail

    if data_quality < 0.3:
        reasons.append("poor_data_quality")

    # ── 4. Spread/cost score (0-1) ────────────────────────────────────
    spread_pct = features.get("spread_pct", 0.0)
    details["max_spread_pct_used"] = round(active_max_spread, 4)
    if spread_pct > active_max_spread:
        spread_score = 0.0
        reasons.append(f"spread_too_wide ({spread_pct:.3f}% > {active_max_spread:.3f}%)")
    elif spread_pct > 0:
        spread_score = max(0.0, 1.0 - spread_pct / active_max_spread)
    else:
        spread_score = 0.8  # no spread data — assume OK but not perfect

    details["spread_score"] = round(spread_score, 3)
    details["spread_pct"] = round(spread_pct, 4)

    # ── 5. Model agreement score (0-1) ────────────────────────────────
    agreement = float(breakdown.get("agreement_bonus", 0))
    agreement_score = 1.0 if agreement > 0 else 0.4
    details["model_agreement"] = round(agreement_score, 3)

    if agreement > 0:
        reasons.append("models_agree")

    # ── 6. Fear & Greed contrarian score (0-1) ──────────────────────
    fear_greed_value = features.get("fear_greed_index", 50.0)
    details["fear_greed_value"] = round(fear_greed_value, 1)

    # Classify into zone
    fg_zone = "neutral"
    for zone_name, (low, high) in FEAR_GREED_ZONES.items():
        if low <= fear_greed_value < high:
            fg_zone = zone_name
            break
    if fear_greed_value >= 100:
        fg_zone = "extreme_greed"
    details["fear_greed_zone"] = fg_zone

    # Contrarian score: high fear = high score (good for buying)
    # Maps F&G 0→1.0 (extreme fear=great), 50→0.5 (neutral), 100→0.0 (extreme greed=bad)
    if direction in ("buy", "strong_buy"):
        fg_score = max(0.0, min(1.0, 1.0 - fear_greed_value / 100.0))
    else:
        # For sells: greed is good (confirming exit), fear is bad
        fg_score = max(0.0, min(1.0, fear_greed_value / 100.0))
    details["fear_greed_score"] = round(fg_score, 3)

    fg_edge_bonus = FEAR_GREED_EDGE_BONUS.get(fg_zone, 0.0) if direction in ("buy", "strong_buy") else 0.0
    fg_threshold_adj = FEAR_GREED_THRESHOLD_ADJUSTMENTS.get(fg_zone, 0.0) if direction in ("buy", "strong_buy") else 0.0
    details["fear_greed_edge_bonus"] = round(fg_edge_bonus, 3)
    details["fear_greed_threshold_adj"] = round(fg_threshold_adj, 3)

    if fg_zone in ("extreme_fear", "fear") and direction in ("buy", "strong_buy"):
        reasons.append(f"contrarian_fear_buy (F&G={fear_greed_value:.0f}, zone={fg_zone})")
    elif fg_zone in ("extreme_greed", "greed") and direction in ("buy", "strong_buy"):
        reasons.append(f"greed_caution (F&G={fear_greed_value:.0f}, zone={fg_zone})")

    # ── Composite edge score ──────────────────────────────────────────
    edge_score = (
        WEIGHT_CONFIDENCE * conf_score +
        WEIGHT_REGIME_FIT * regime_fit +
        WEIGHT_DATA_QUALITY * data_quality +
        WEIGHT_SPREAD * spread_score +
        WEIGHT_AGREEMENT * agreement_score +
        WEIGHT_FEAR_GREED * fg_score
    )

    # Apply Fear & Greed edge bonus (contrarian boost/penalty)
    edge_score += fg_edge_bonus
    edge_score = max(0.0, min(1.0, edge_score))  # Clamp to [0, 1]

    # Apply regime penalty + Fear & Greed threshold adjustment
    penalty = REGIME_EDGE_PENALTIES.get(regime.regime, 0.0)
    effective_threshold = EDGE_THRESHOLD + penalty + fg_threshold_adj

    # Fast mover: lower the edge threshold to capture the move
    if is_fast_mover:
        effective_threshold -= FAST_MOVER_EDGE_REDUCTION
        reasons.append(f"fast_mover_threshold_reduction (-{FAST_MOVER_EDGE_REDUCTION:.0%})")

    effective_threshold = max(0.20, effective_threshold)  # Floor: never go below 0.20
    details["edge_score_raw"] = round(edge_score, 4)
    details["regime_penalty"] = round(penalty, 3)
    details["effective_threshold"] = round(effective_threshold, 4)

    # ── Decision ──────────────────────────────────────────────────────
    take = edge_score >= effective_threshold

    # Size multiplier: scale position by how much edge exceeds threshold
    if take:
        excess = edge_score - effective_threshold
        # Map excess 0..0.3 → size_mult 0.5..1.0
        size_mult = min(1.0, 0.5 + excess / 0.3 * 0.5)
        reasons.append(f"edge_sufficient ({edge_score:.3f} >= {effective_threshold:.3f})")
    else:
        size_mult = 0.0
        reasons.append(f"edge_insufficient ({edge_score:.3f} < {effective_threshold:.3f})")

    return EdgeDecision(
        take=take,
        edge_score=round(edge_score, 4),
        size_multiplier=round(size_mult, 4),
        reasons=reasons,
        details=details,
        max_concurrent_positions=max_positions,
    )
