"""
Training script for the XGBoost multi-class classifier.

Usage
-----
    python train_xgboost.py --days 90

Cross-validation with walk-forward splits.
Saves the best model to ``shared/models/xgboost_{version}.json``.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import structlog
import xgboost as xgb
from sklearn.metrics import accuracy_score, classification_report

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from features.technical import compute_technical_features
from models.xgboost_model import XGBoostModel, CLASS_LABELS
from models.model_registry import ModelRegistry
from training.data_loader import DataLoader
from training.walk_forward import WalkForwardValidator

logger = structlog.get_logger()

MODEL_DIR = os.getenv("MODEL_DIR", "/app/shared/models")
FEATURE_COLS = XGBoostModel.DEFAULT_FEATURE_NAMES


def _prepare_features(candles: pd.DataFrame) -> pd.DataFrame:
    """Compute feature rows for every candle (using 60-row trailing window)."""
    rows = []
    for end_idx in range(60, len(candles)):
        window = candles.iloc[end_idx - 60 : end_idx]
        feats = compute_technical_features(window)
        # Pad missing features with 0
        for col in FEATURE_COLS:
            if col not in feats:
                feats[col] = 0.0
        rows.append(feats)

    feature_df = pd.DataFrame(rows)
    # Ensure column ordering matches model expectations
    for col in FEATURE_COLS:
        if col not in feature_df.columns:
            feature_df[col] = 0.0
    return feature_df[FEATURE_COLS]


async def train(args):
    loader = DataLoader()
    await loader.connect()

    symbols = [s.strip() for s in args.symbols.split(",")]
    all_features = []
    all_targets = []

    for symbol in symbols:
        logger.info("Loading data", symbol=symbol, days=args.days)
        candles = await loader.load_candles(symbol, days=args.days)
        if candles.empty or len(candles) < 100:
            logger.warning("Insufficient data, skipping", symbol=symbol)
            continue

        candles = DataLoader.generate_labels(candles)
        feature_df = _prepare_features(candles)

        # Align targets
        aligned = candles.iloc[60:].reset_index(drop=True)
        targets = aligned["target"].values[: len(feature_df)]
        feature_df = feature_df.iloc[: len(targets)]

        all_features.append(feature_df)
        all_targets.append(targets)

    if not all_features:
        logger.error("No training data collected")
        return

    X = pd.concat(all_features, ignore_index=True)
    y = np.concatenate(all_targets)

    logger.info(f"Total samples: {len(X)}, features: {X.shape[1]}")

    # Walk-forward validation on combined data (using index as pseudo-time)
    X["_index"] = range(len(X))
    # Use simple split ratios for XGBoost (no sequence dependency)
    n = len(X)
    train_end = int(n * 0.7)
    val_end = int(n * 0.85)

    X_train = X.iloc[:train_end][FEATURE_COLS].values
    y_train = y[:train_end]
    X_val = X.iloc[train_end:val_end][FEATURE_COLS].values
    y_val = y[train_end:val_end]
    X_test = X.iloc[val_end:][FEATURE_COLS].values
    y_test = y[val_end:]

    logger.info(f"Split sizes: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}")

    # XGBoost training
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLS)

    params = {
        "objective": "multi:softprob",
        "num_class": 5,
        "eval_metric": "mlogloss",
        "max_depth": args.max_depth,
        "learning_rate": args.lr,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "gamma": 0.1,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "tree_method": "hist",
        "verbosity": 1,
    }

    evals = [(dtrain, "train"), (dval, "val")]
    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=args.rounds,
        evals=evals,
        early_stopping_rounds=20,
        verbose_eval=50,
    )

    # Evaluate on test set
    dtest = xgb.DMatrix(X_test, feature_names=FEATURE_COLS)
    test_probs = booster.predict(dtest)
    test_preds = np.argmax(test_probs, axis=1)
    test_acc = accuracy_score(y_test, test_preds)

    logger.info(f"Test accuracy: {test_acc:.4f}")
    print("\nClassification Report (Test Set):")
    print(classification_report(y_test, test_preds, target_names=CLASS_LABELS, zero_division=0))

    # Feature importance
    importance = booster.get_score(importance_type="gain")
    sorted_imp = sorted(importance.items(), key=lambda x: -x[1])
    print("\nTop 15 Feature Importance (gain):")
    for fname, score in sorted_imp[:15]:
        print(f"  {fname:30s} {score:.2f}")

    # Save model
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(MODEL_DIR, f"xgboost_{version}.json")
    os.makedirs(MODEL_DIR, exist_ok=True)
    booster.save_model(save_path)

    # Register
    registry = ModelRegistry(registry_dir=MODEL_DIR)
    registry.register(
        model_name="xgboost",
        version=version,
        metrics={"accuracy": round(test_acc, 4)},
        path=save_path,
    )

    logger.info("Training complete", path=save_path, accuracy=f"{test_acc:.4f}")
    await loader.close()


def main():
    parser = argparse.ArgumentParser(description="Train XGBoost model")
    parser.add_argument("--symbols", type=str, default="BTC/USDT,ETH/USDT,SOL/USDT")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--rounds", type=int, default=500)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--max-depth", type=int, default=6)
    args = parser.parse_args()
    asyncio.run(train(args))


if __name__ == "__main__":
    main()
