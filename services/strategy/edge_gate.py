"""
Layer B — Edge Gate (Meta-labeling style)

Decides whether to TAKE or SKIP a trade based on contextual quality:
- Model confidence and agreement
- Feature data quality (sentiment/onchain availability)
- Regime alignment with signal direction
- Spread/volatility conditions (don't trade in wide-spread or extreme vol)
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

from .regime import RegimeState


@dataclass
class EdgeDecision:
    """Output of the edge gate: take/skip + sizing hint."""
    take: bool
    edge_score: float          # 0.0 to 1.0
    size_multiplier: float     # 0.0 to 1.0 (applied on top of vol sizing)
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, float] = field(default_factory=dict)


# ── Configuration ─────────────────────────────────────────────────────

EDGE_THRESHOLD = 0.40          # minimum edge score to take trade
MIN_CONFIDENCE = 0.35          # model must be at least 35% confident
MAX_SPREAD_PCT = 0.5           # skip if spread > 0.5% (too expensive)
AGREEMENT_BONUS = 0.15         # bonus when TCN + XGBoost agree

# Regime-based adjustments
REGIME_EDGE_PENALTIES = {
    "choppy": 0.25,            # need 25% more edge in chop
    "high_vol": 0.15,          # need 15% more edge in high vol
    "trending_up": 0.0,        # no penalty in trends
    "trending_down": 0.0,
}

# Feature quality weights
WEIGHT_CONFIDENCE = 0.35
WEIGHT_REGIME_FIT = 0.25
WEIGHT_DATA_QUALITY = 0.15
WEIGHT_SPREAD = 0.10
WEIGHT_AGREEMENT = 0.15


def evaluate_edge(
    prediction: dict,
    regime: RegimeState,
    features: Dict[str, float],
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
    if spread_pct > MAX_SPREAD_PCT:
        spread_score = 0.0
        reasons.append(f"spread_too_wide ({spread_pct:.3f}%)")
    elif spread_pct > 0:
        spread_score = max(0.0, 1.0 - spread_pct / MAX_SPREAD_PCT)
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

    # ── Composite edge score ──────────────────────────────────────────
    edge_score = (
        WEIGHT_CONFIDENCE * conf_score +
        WEIGHT_REGIME_FIT * regime_fit +
        WEIGHT_DATA_QUALITY * data_quality +
        WEIGHT_SPREAD * spread_score +
        WEIGHT_AGREEMENT * agreement_score
    )

    # Apply regime penalty
    penalty = REGIME_EDGE_PENALTIES.get(regime.regime, 0.0)
    effective_threshold = EDGE_THRESHOLD + penalty
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
    )
