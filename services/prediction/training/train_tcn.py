"""
Training script for the Temporal Convolutional Network (TCN).

Usage
-----
    python train_tcn.py --symbol BTC/USDT --epochs 50 --lr 0.001

Walk-forward training: train on 30 days, validate on 7 days, slide window.
Saves the best model to ``shared/models/tcn_{version}.pt``.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import structlog
import torch
import torch.nn as nn
from torch.utils.data import DataLoader as TorchDataLoader, TensorDataset

# Allow running from the training/ directory or the service root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from features.technical import compute_technical_features
from models.tcn_model import TCNModel, TCNNetwork
from models.model_registry import ModelRegistry
from training.data_loader import DataLoader
from training.walk_forward import WalkForwardValidator

logger = structlog.get_logger()

SEQUENCE_LENGTH = 60
MODEL_DIR = os.getenv("MODEL_DIR", "/app/shared/models")


def _build_sequences(
    feature_df: pd.DataFrame,
    targets: np.ndarray,
    seq_len: int = SEQUENCE_LENGTH,
):
    """Slide a window of *seq_len* over feature_df and return (X, y) arrays."""
    feature_cols = [c for c in feature_df.columns if c not in ("timestamp", "target")]
    values = feature_df[feature_cols].values.astype(np.float32)
    X, y = [], []
    for i in range(seq_len, len(values)):
        X.append(values[i - seq_len : i])
        y.append(targets[i])
    return np.array(X), np.array(y)


def _map_5class_to_3class(target: int) -> int:
    """Map 5-class (0-4) to 3-class: 0,1 -> down(1), 2 -> neutral(2), 3,4 -> up(0)."""
    if target <= 1:
        return 1  # down
    if target >= 3:
        return 0  # up
    return 2  # neutral


async def train(args):
    loader = DataLoader()
    await loader.connect()

    logger.info("Loading candle data", symbol=args.symbol, days=args.days)
    candles = await loader.load_candles(args.symbol, days=args.days)
    if candles.empty:
        logger.error("No candle data available")
        return

    # Generate labels
    candles = DataLoader.generate_labels(candles)

    # Compute features for every row (rolling window)
    feature_rows = []
    for end_idx in range(60, len(candles)):
        window = candles.iloc[end_idx - 60 : end_idx]
        feats = compute_technical_features(window)
        feature_rows.append(feats)

    feature_df = pd.DataFrame(feature_rows)
    # Align with candles (first 60 rows dropped because of windowing)
    aligned_candles = candles.iloc[60:].reset_index(drop=True)
    feature_df["timestamp"] = aligned_candles["timestamp"].values
    feature_df["target"] = aligned_candles["target"].values

    # Map to 3-class for TCN
    targets_3class = feature_df["target"].apply(_map_5class_to_3class).values

    # Walk-forward splits
    wf = WalkForwardValidator(train_days=30, val_days=7, step_days=7)
    splits = wf.generate_splits(feature_df, time_col="timestamp")

    if not splits:
        logger.error("Not enough data for walk-forward splits")
        return

    n_features = len([c for c in feature_df.columns if c not in ("timestamp", "target")])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    best_val_acc = 0.0
    best_state = None

    for split_idx, (train_df, val_df) in enumerate(splits):
        logger.info(f"Walk-forward split {split_idx + 1}/{len(splits)}")

        train_targets = train_df["target"].apply(_map_5class_to_3class).values
        val_targets = val_df["target"].apply(_map_5class_to_3class).values

        X_train, y_train = _build_sequences(train_df, train_targets)
        X_val, y_val = _build_sequences(val_df, val_targets)

        if len(X_train) == 0 or len(X_val) == 0:
            continue

        network = TCNNetwork(n_features=n_features, hidden_channels=64, n_classes=3).to(device)
        optimizer = torch.optim.Adam(network.parameters(), lr=args.lr)
        criterion = nn.CrossEntropyLoss()

        train_ds = TensorDataset(
            torch.tensor(X_train, dtype=torch.float32),
            torch.tensor(y_train, dtype=torch.long),
        )
        train_loader = TorchDataLoader(train_ds, batch_size=args.batch_size, shuffle=True)

        # Training loop
        for epoch in range(args.epochs):
            network.train()
            total_loss = 0.0
            for xb, yb in train_loader:
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad()
                logits = network(xb)
                loss = criterion(logits, yb)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

            if (epoch + 1) % 10 == 0:
                logger.info(f"  Epoch {epoch + 1}/{args.epochs}, loss={total_loss / len(train_loader):.4f}")

        # Validation
        network.eval()
        X_val_t = torch.tensor(X_val, dtype=torch.float32).to(device)
        with torch.no_grad():
            val_logits = network(X_val_t)
            val_preds = val_logits.argmax(dim=1).cpu().numpy()

        from sklearn.metrics import accuracy_score
        val_acc = accuracy_score(y_val, val_preds)
        logger.info(f"  Split {split_idx + 1} val accuracy: {val_acc:.4f}")

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = network.state_dict()

    if best_state is None:
        logger.error("No successful training splits")
        return

    # Save best model
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(MODEL_DIR, f"tcn_{version}.pt")
    os.makedirs(MODEL_DIR, exist_ok=True)

    model = TCNModel(n_features=n_features)
    model._ensure_network()
    model.network.load_state_dict(best_state)
    model.save(save_path)

    # Register
    registry = ModelRegistry(registry_dir=MODEL_DIR)
    registry.register(
        model_name="tcn",
        version=version,
        metrics={"accuracy": round(best_val_acc, 4)},
        path=save_path,
    )

    logger.info(f"Training complete. Best val accuracy: {best_val_acc:.4f}", path=save_path)
    await loader.close()


def main():
    parser = argparse.ArgumentParser(description="Train TCN model")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    asyncio.run(train(args))


if __name__ == "__main__":
    main()
