"""
XGBoost multi-class classifier for crypto trading signals.

Input:  flat feature vector (40+ features: technical + sentiment + on-chain)
Output: 5-class classification (strong_buy, buy, hold, sell, strong_sell) with probabilities
"""

import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import structlog
import xgboost as xgb

logger = structlog.get_logger()

CLASS_LABELS: List[str] = ["strong_sell", "sell", "hold", "buy", "strong_buy"]
CLASS_TO_IDX: Dict[str, int] = {label: idx for idx, label in enumerate(CLASS_LABELS)}

# Temperature scaling for XGBoost: spreads probability distribution to reduce
# "always hold" collapse. Applied as power-scaling: probs^(1/T) then renormalize.
INFERENCE_TEMPERATURE = 2.0

# Hold penalty: reduce hold probability to force directional predictions.
# XGBoost outputs probabilities directly (multi:softprob), so we scale hold down.
HOLD_PENALTY_FACTOR = 0.03  # Multiply hold probability by this before renormalizing


def _apply_temperature(probs: np.ndarray, temperature: float = INFERENCE_TEMPERATURE) -> np.ndarray:
    """Apply temperature scaling + hold penalty to probability array."""
    # Apply hold penalty (class index 2 = "hold")
    if probs.ndim == 1:
        probs = probs.copy()
        probs[2] *= HOLD_PENALTY_FACTOR
        probs = probs / probs.sum()
    else:
        probs = probs.copy()
        probs[:, 2] *= HOLD_PENALTY_FACTOR
        probs = probs / probs.sum(axis=1, keepdims=True)

    if temperature == 1.0:
        return probs
    scaled = np.power(probs.clip(1e-10), 1.0 / temperature)
    if scaled.ndim == 1:
        return scaled / scaled.sum()
    return scaled / scaled.sum(axis=1, keepdims=True)


class XGBoostModel:
    """Wrapper around an XGBoost multi-class classifier for trading signal prediction."""

    # Default feature ordering (must match training pipeline)
    DEFAULT_FEATURE_NAMES: List[str] = [
        # Technical (20 features)
        "rsi_14", "rsi_7", "macd_histogram", "macd_signal",
        "bb_percent_b", "bb_bandwidth", "atr_pct", "obv_trend",
        "stoch_rsi_k", "stoch_rsi_d", "williams_r",
        "ema_9_21_cross", "ema_25_50_cross", "volume_ratio",
        "momentum_5m", "momentum_15m", "momentum_30m", "momentum_60m",
        "spread_pct", "vwap_deviation",
        # Sentiment (6 features)
        "sentiment_score", "sentiment_momentum_1h", "sentiment_momentum_4h",
        "sentiment_momentum_24h", "sentiment_volume", "fear_greed_index",
        # On-chain (5 features)
        "whale_activity_score", "exchange_netflow", "funding_rate",
        "google_trends_score", "social_volume_zscore",
        # Derived (9+ features for padding to 40+)
        "price_change_1m", "price_change_5m", "price_change_15m",
        "high_low_range", "close_open_ratio", "upper_shadow_pct",
        "lower_shadow_pct", "body_pct", "volume_change_pct",
    ]

    def __init__(self, feature_names: Optional[List[str]] = None):
        self.feature_names = feature_names or self.DEFAULT_FEATURE_NAMES
        self.model: Optional[xgb.Booster] = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, features: Dict[str, float]) -> Tuple[str, float, Dict[str, float]]:
        """
        Predict trading signal from a flat feature dict.

        Parameters
        ----------
        features : dict
            Mapping of feature_name -> float.  Missing features default to 0.0.

        Returns
        -------
        direction : str
            One of CLASS_LABELS.
        confidence : float
            Probability of the predicted class.
        probabilities : dict
            Mapping class_label -> probability.
        """
        if self.model is None:
            raise RuntimeError("XGBoost model not loaded. Call load() first.")

        vec = np.array(
            [features.get(f, 0.0) for f in self.feature_names],
            dtype=np.float32,
        ).reshape(1, -1)

        dmat = xgb.DMatrix(vec, feature_names=self.feature_names)
        raw_probs = self.model.predict(dmat)  # shape (1, n_classes)

        if raw_probs.ndim == 1:
            probs = raw_probs
        else:
            probs = raw_probs[0]

        probs = _apply_temperature(probs)
        predicted_idx = int(np.argmax(probs))
        direction = CLASS_LABELS[predicted_idx]
        confidence = float(probs[predicted_idx])
        probabilities = {label: float(probs[i]) for i, label in enumerate(CLASS_LABELS)}

        return direction, confidence, probabilities

    def predict_batch(self, feature_dicts: list) -> list:
        """
        Batched inference — processes all feature dicts in a single XGBoost call.

        Parameters
        ----------
        feature_dicts : list of dict
            Each dict maps feature_name -> float.

        Returns
        -------
        list of (direction, confidence, probabilities) tuples
        """
        if self.model is None:
            raise RuntimeError("XGBoost model not loaded. Call load() first.")
        if not feature_dicts:
            return []

        mat = np.array(
            [[fd.get(f, 0.0) for f in self.feature_names] for fd in feature_dicts],
            dtype=np.float32,
        )
        dmat = xgb.DMatrix(mat, feature_names=self.feature_names)
        all_probs = self.model.predict(dmat)  # (N, n_classes)

        if all_probs.ndim == 1:
            all_probs = all_probs.reshape(1, -1)

        all_probs = _apply_temperature(all_probs)
        results = []
        for probs in all_probs:
            idx = int(np.argmax(probs))
            direction = CLASS_LABELS[idx]
            confidence = float(probs[idx])
            probabilities = {label: float(probs[i]) for i, label in enumerate(CLASS_LABELS)}
            results.append((direction, confidence, probabilities))
        return results

    # ------------------------------------------------------------------
    # Feature importance
    # ------------------------------------------------------------------

    def feature_importance(self) -> Dict[str, float]:
        """Return feature importance scores (gain-based)."""
        if self.model is None:
            return {}
        scores = self.model.get_score(importance_type="gain")
        # Normalise to 0-1
        total = sum(scores.values()) or 1.0
        return {k: v / total for k, v in sorted(scores.items(), key=lambda x: -x[1])}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str) -> None:
        """Load model from a ``.json`` (or ``.ubj``) file."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"XGBoost model file not found: {path}")
        self.model = xgb.Booster()
        self.model.load_model(path)
        self._loaded = True
        logger.info("XGBoost model loaded", path=path)

    def save(self, path: str) -> None:
        """Save model to a ``.json`` file."""
        if self.model is None:
            raise RuntimeError("No model to save.")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.model.save_model(path)
        logger.info("XGBoost model saved", path=path)
