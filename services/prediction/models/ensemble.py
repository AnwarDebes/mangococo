"""
Ensemble combiner that merges predictions from multiple model sources.

Weights:
  TCN        : 0.35
  XGBoost    : 0.40
  Sentiment  : 0.15
  On-chain   : 0.10

Agreement bonus: when TCN and XGBoost agree on direction -> +15 % confidence.

Internally maps the 5-class labels to a directional score in [-1, 1]:
  strong_sell = -1.0,  sell = -0.5,  hold = 0.0,  buy = 0.5,  strong_buy = 1.0
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

CLASS_TO_SCORE: Dict[str, float] = {
    "strong_sell": -1.0,
    "sell": -0.5,
    "hold": 0.0,
    "buy": 0.5,
    "strong_buy": 1.0,
    # 3-class labels used by TCN
    "down": -0.75,
    "neutral": 0.0,
    "up": 0.75,
}

SCORE_TO_CLASS = [
    (-1.0, "strong_sell"),
    (-0.4, "sell"),
    (0.0, "hold"),
    (0.4, "buy"),
    (1.0, "strong_buy"),
]


def _score_to_direction(score: float) -> str:
    """Map a continuous score to a discrete 5-class label.

    Narrow hold zone: temperature-scaled models produce lower scores,
    so the hold dead-zone must be tight to avoid suppressing all signals.
    """
    if score <= -0.5:
        return "strong_sell"
    if score <= -0.05:
        return "sell"
    if score <= 0.05:
        return "hold"
    if score <= 0.5:
        return "buy"
    return "strong_buy"


def _direction_sign(direction: str) -> int:
    """Return +1 for bullish, -1 for bearish, 0 for neutral."""
    score = CLASS_TO_SCORE.get(direction, 0.0)
    if score > 0.1:
        return 1
    if score < -0.1:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ModelPrediction:
    """Prediction from a single model source."""
    direction: str
    confidence: float
    probabilities: Optional[Dict[str, float]] = None


@dataclass
class EnsemblePrediction:
    """Combined prediction from the ensemble."""
    direction: str
    confidence: float
    score: float
    breakdown: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Combiner
# ---------------------------------------------------------------------------

class EnsembleCombiner:
    """Weighted ensemble combiner with multi-TCN support."""

    WEIGHT_TCN = 0.35
    WEIGHT_XGB = 0.40
    WEIGHT_SENTIMENT = 0.15
    WEIGHT_ONCHAIN = 0.10
    AGREEMENT_BONUS = 0.25

    # Per-variant weights within the TCN allocation (sum to 1.0)
    TCN_VARIANT_WEIGHTS = {
        "tcn_micro":  0.10,
        "tcn_short":  0.20,
        "tcn_medium": 0.40,  # Primary model gets highest weight
        "tcn_long":   0.30,
    }

    def combine(
        self,
        tcn_pred: Optional[ModelPrediction] = None,
        xgb_pred: Optional[ModelPrediction] = None,
        sentiment_score: float = 0.0,
        onchain_score: float = 0.0,
        sentiment_available: bool = True,
        onchain_available: bool = True,
        multi_tcn_preds: Optional[list] = None,
    ) -> EnsemblePrediction:
        """
        Combine predictions from all sources into a single ensemble prediction.

        Parameters
        ----------
        tcn_pred : ModelPrediction or None
            TCN model output.
        xgb_pred : ModelPrediction or None
            XGBoost model output.
        sentiment_score : float
            Normalised sentiment score in [-1, 1].
        onchain_score : float
            Normalised on-chain score in [-1, 1].
        sentiment_available : bool
            Whether sentiment data came from a real source (not defaults).
        onchain_available : bool
            Whether on-chain data came from a real source (not defaults).

        Returns
        -------
        EnsemblePrediction
        """
        total_weight = 0.0
        weighted_score = 0.0
        breakdown: Dict[str, float] = {}

        # TCN contribution — supports multi-variant ensemble
        # multi_tcn_preds: list of (variant_name, direction, confidence)
        if multi_tcn_preds and len(multi_tcn_preds) > 0:
            # Weighted combination of all TCN variants
            variant_total_weight = 0.0
            variant_weighted_score = 0.0
            for variant_name, direction, confidence in multi_tcn_preds:
                v_weight = self.TCN_VARIANT_WEIGHTS.get(variant_name, 0.15)
                v_score = CLASS_TO_SCORE.get(direction, 0.0) * confidence
                variant_weighted_score += v_weight * v_score
                variant_total_weight += v_weight
                breakdown[f"tcn_{variant_name}"] = round(v_score, 4)

            if variant_total_weight > 0:
                tcn_score = variant_weighted_score / variant_total_weight
            else:
                tcn_score = 0.0
            weighted_score += self.WEIGHT_TCN * tcn_score
            total_weight += self.WEIGHT_TCN
            breakdown["tcn"] = round(tcn_score, 4)
            breakdown["tcn_variants_used"] = len(multi_tcn_preds)

            # Synthesize a single tcn_pred for agreement check below
            if tcn_pred is None:
                combined_dir = "up" if tcn_score > 0.1 else ("down" if tcn_score < -0.1 else "neutral")
                tcn_pred = ModelPrediction(direction=combined_dir, confidence=abs(tcn_score))

        elif tcn_pred is not None:
            # Fallback: single TCN model (backwards compatible)
            tcn_score = CLASS_TO_SCORE.get(tcn_pred.direction, 0.0) * tcn_pred.confidence
            weighted_score += self.WEIGHT_TCN * tcn_score
            total_weight += self.WEIGHT_TCN
            breakdown["tcn"] = tcn_score

        # XGBoost contribution
        if xgb_pred is not None:
            xgb_score = CLASS_TO_SCORE.get(xgb_pred.direction, 0.0) * xgb_pred.confidence
            weighted_score += self.WEIGHT_XGB * xgb_score
            total_weight += self.WEIGHT_XGB
            breakdown["xgboost"] = xgb_score

        # Sentiment contribution — skip if using default zeros
        if sentiment_available:
            clamped_sentiment = max(-1.0, min(1.0, sentiment_score))
            weighted_score += self.WEIGHT_SENTIMENT * clamped_sentiment
            total_weight += self.WEIGHT_SENTIMENT
            breakdown["sentiment"] = clamped_sentiment
        else:
            breakdown["sentiment"] = 0.0

        # On-chain contribution — skip if using default zeros
        if onchain_available:
            clamped_onchain = max(-1.0, min(1.0, onchain_score))
            weighted_score += self.WEIGHT_ONCHAIN * clamped_onchain
            total_weight += self.WEIGHT_ONCHAIN
            breakdown["onchain"] = clamped_onchain
        else:
            breakdown["onchain"] = 0.0

        breakdown["sentiment_available"] = 1.0 if sentiment_available else 0.0
        breakdown["onchain_available"] = 1.0 if onchain_available else 0.0

        # Normalise
        if total_weight > 0:
            final_score = weighted_score / total_weight
        else:
            final_score = 0.0

        # Agreement bonus
        agreement = False
        if tcn_pred is not None and xgb_pred is not None:
            tcn_sign = _direction_sign(tcn_pred.direction)
            xgb_sign = _direction_sign(xgb_pred.direction)
            if tcn_sign != 0 and tcn_sign == xgb_sign:
                agreement = True
                # Amplify in the agreed direction
                final_score += self.AGREEMENT_BONUS * tcn_sign
                final_score = max(-1.0, min(1.0, final_score))

        breakdown["agreement_bonus"] = self.AGREEMENT_BONUS if agreement else 0.0

        direction = _score_to_direction(final_score)

        # Confidence: use the stronger of abs(score) or max individual model
        # confidence (when directional). Ensemble averaging dilutes confidence,
        # but if a model is confident and directional, that should carry through.
        score_confidence = min(1.0, abs(final_score))
        model_confidences = []
        if tcn_pred and _direction_sign(tcn_pred.direction) != 0:
            model_confidences.append(tcn_pred.confidence)
        if xgb_pred and _direction_sign(xgb_pred.direction) != 0:
            model_confidences.append(xgb_pred.confidence)
        max_model_conf = max(model_confidences) if model_confidences else 0.0
        # Blend: 60% score-based, 40% best-model-based (prevents pure score dilution)
        confidence = 0.6 * score_confidence + 0.4 * max_model_conf

        return EnsemblePrediction(
            direction=direction,
            confidence=round(confidence, 4),
            score=round(final_score, 4),
            breakdown=breakdown,
        )
