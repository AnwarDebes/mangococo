"""
Model Training Orchestrator - Trains/retrains ML models for MangoCoco.
Runs daily via cron or manually. Downloads latest data from TimescaleDB,
trains TCN and XGBoost models, evaluates via walk-forward validation,
and saves to shared/models/ for the prediction service to load.

Usage:
    python scripts/train_models.py --days 90 --symbols BTC/USDT,ETH/USDT,SOL/USDT
    python scripts/train_models.py --retrain-all
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

# Config
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "mangococo")
POSTGRES_USER = os.getenv("POSTGRES_USER", "mangococo")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

MODELS_DIR = Path(os.getenv("MODELS_DIR", "shared/models"))
DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
                   "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT"]


async def load_training_data(pool, symbols: list, days: int) -> pd.DataFrame:
    """Load candle data from TimescaleDB."""
    start_time = datetime.utcnow() - timedelta(days=days)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT time, symbol, open, high, low, close, volume
               FROM candles
               WHERE symbol = ANY($1::text[]) AND time >= $2
               ORDER BY symbol, time ASC""",
            symbols, start_time,
        )

    if not rows:
        # Fallback to tick-derived data
        logger.warning("No candles found, trying to aggregate from ticks")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT
                    time_bucket('1 minute', time) AS time,
                    symbol,
                    first(price, time) AS open,
                    max(price) AS high,
                    min(price) AS low,
                    last(price, time) AS close,
                    sum(volume) AS volume
                   FROM ticks
                   WHERE symbol = ANY($1::text[]) AND time >= $2
                   GROUP BY time_bucket('1 minute', time), symbol
                   ORDER BY symbol, time ASC""",
                symbols, start_time,
            )

    if not rows:
        logger.error("No training data available")
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    logger.info(f"Loaded {len(df)} candle records for {df['symbol'].nunique()} symbols")
    return df


async def load_sentiment_data(pool, symbols: list, days: int) -> pd.DataFrame:
    """Load sentiment data for feature enrichment."""
    start_time = datetime.utcnow() - timedelta(days=days)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT time, symbol, source, score, volume AS mention_count
               FROM sentiment_scores
               WHERE symbol = ANY($1::text[]) AND time >= $2
               ORDER BY symbol, time ASC""",
            symbols, start_time,
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([dict(r) for r in rows])


def compute_features(candles_df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical features for each symbol."""
    features_list = []

    for symbol in candles_df["symbol"].unique():
        df = candles_df[candles_df["symbol"] == symbol].copy().sort_values("time")
        if len(df) < 60:
            continue

        close = df["close"].values.astype(float)
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        volume = df["volume"].values.astype(float)

        # RSI
        delta = np.diff(close, prepend=close[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).rolling(14).mean().values
        avg_loss = pd.Series(loss).rolling(14).mean().values
        rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
        rsi = 100 - (100 / (1 + rs))

        # MACD
        ema12 = pd.Series(close).ewm(span=12).mean().values
        ema26 = pd.Series(close).ewm(span=26).mean().values
        macd = ema12 - ema26
        macd_signal = pd.Series(macd).ewm(span=9).mean().values
        macd_hist = macd - macd_signal

        # Bollinger Bands
        sma20 = pd.Series(close).rolling(20).mean().values
        std20 = pd.Series(close).rolling(20).std().values
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_width = np.divide(bb_upper - bb_lower, sma20, out=np.zeros_like(sma20), where=sma20 != 0)
        bb_position = np.divide(close - bb_lower, bb_upper - bb_lower,
                                out=np.zeros_like(close), where=(bb_upper - bb_lower) != 0)

        # ATR
        tr = np.maximum(high - low,
                        np.maximum(np.abs(high - np.roll(close, 1)),
                                   np.abs(low - np.roll(close, 1))))
        atr = pd.Series(tr).rolling(14).mean().values

        # Volume features
        vol_sma = pd.Series(volume).rolling(20).mean().values
        vol_ratio = np.divide(volume, vol_sma, out=np.ones_like(volume), where=vol_sma != 0)

        # Momentum
        returns_1 = np.diff(close, prepend=close[0]) / np.maximum(np.roll(close, 1), 1e-10)
        returns_5 = (close - np.roll(close, 5)) / np.maximum(np.roll(close, 5), 1e-10)
        returns_15 = (close - np.roll(close, 15)) / np.maximum(np.roll(close, 15), 1e-10)

        # Target: price direction in next 5 candles
        future_return = (np.roll(close, -5) - close) / np.maximum(close, 1e-10)
        target = np.where(future_return > 0.001, 1, np.where(future_return < -0.001, -1, 0))

        feat_df = pd.DataFrame({
            "time": df["time"].values,
            "symbol": symbol,
            "close": close,
            "rsi": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "bb_width": bb_width,
            "bb_position": bb_position,
            "atr": atr,
            "vol_ratio": vol_ratio,
            "return_1": returns_1,
            "return_5": returns_5,
            "return_15": returns_15,
            "target": target,
        })

        # Drop rows with NaN from rolling calculations
        feat_df = feat_df.iloc[30:].reset_index(drop=True)
        # Remove last 5 rows where target looks ahead
        feat_df = feat_df.iloc[:-5]
        features_list.append(feat_df)

    if not features_list:
        return pd.DataFrame()

    return pd.concat(features_list, ignore_index=True)


def train_xgboost(features_df: pd.DataFrame, output_path: Path) -> dict:
    """Train XGBoost model with walk-forward validation."""
    try:
        import xgboost as xgb
    except ImportError:
        logger.error("XGBoost not installed, skipping")
        return {"status": "skipped", "reason": "xgboost not installed"}

    feature_cols = ["rsi", "macd", "macd_signal", "macd_hist", "bb_width",
                    "bb_position", "atr", "vol_ratio", "return_1", "return_5", "return_15"]

    X = features_df[feature_cols].fillna(0).values
    y = features_df["target"].values

    # Walk-forward: train on first 80%, test on last 20%
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    # Map targets: -1 -> 0, 0 -> 1, 1 -> 2 (for multi:softprob)
    y_train_mapped = y_train + 1
    y_test_mapped = y_test + 1

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        use_label_encoder=False,
        tree_method="hist",
    )

    model.fit(
        X_train, y_train_mapped,
        eval_set=[(X_test, y_test_mapped)],
        verbose=False,
    )

    # Evaluate
    preds = model.predict(X_test)
    accuracy = np.mean(preds == y_test_mapped)

    # Directional accuracy (ignore neutral)
    directional_mask = y_test != 0
    if directional_mask.sum() > 0:
        dir_accuracy = np.mean(preds[directional_mask] == y_test_mapped[directional_mask])
    else:
        dir_accuracy = 0

    # Save model
    model_path = output_path / "xgboost_latest.json"
    model.save_model(str(model_path))

    # Save metadata
    metadata = {
        "model_type": "xgboost",
        "trained_at": datetime.utcnow().isoformat(),
        "samples_train": len(X_train),
        "samples_test": len(X_test),
        "accuracy": round(float(accuracy), 4),
        "directional_accuracy": round(float(dir_accuracy), 4),
        "features": feature_cols,
        "version": datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
    }

    with open(output_path / "xgboost_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("XGBoost trained", accuracy=accuracy, directional_accuracy=dir_accuracy,
                train_samples=len(X_train), test_samples=len(X_test))
    return metadata


def train_tcn(features_df: pd.DataFrame, output_path: Path) -> dict:
    """Train TCN model with walk-forward validation."""
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        logger.error("PyTorch not installed, skipping TCN training")
        return {"status": "skipped", "reason": "torch not installed"}

    feature_cols = ["close", "rsi", "macd", "macd_hist", "bb_width",
                    "bb_position", "atr", "vol_ratio", "return_1", "return_5", "return_15"]

    seq_length = 60  # 60 candle lookback

    # Prepare sequences per symbol
    all_X, all_y = [], []
    for symbol in features_df["symbol"].unique():
        sym_df = features_df[features_df["symbol"] == symbol].sort_values("time")
        data = sym_df[feature_cols].fillna(0).values
        targets = sym_df["target"].values

        for i in range(seq_length, len(data)):
            all_X.append(data[i - seq_length:i])
            all_y.append(targets[i] + 1)  # Map -1,0,1 -> 0,1,2

    if len(all_X) < 100:
        logger.warning("Not enough sequences for TCN training")
        return {"status": "skipped", "reason": "insufficient data"}

    X = np.array(all_X, dtype=np.float32)
    y = np.array(all_y, dtype=np.int64)

    # Walk-forward split
    split_idx = int(len(X) * 0.8)
    X_train = torch.tensor(X[:split_idx]).permute(0, 2, 1)  # (batch, channels, seq_len)
    y_train = torch.tensor(y[:split_idx])
    X_test = torch.tensor(X[split_idx:]).permute(0, 2, 1)
    y_test = torch.tensor(y[split_idx:])

    # Simple TCN model
    class SimpleTCN(nn.Module):
        def __init__(self, num_inputs, num_channels, num_classes):
            super().__init__()
            layers = []
            for i, out_ch in enumerate(num_channels):
                in_ch = num_inputs if i == 0 else num_channels[i - 1]
                layers.append(nn.Conv1d(in_ch, out_ch, kernel_size=3, padding=1))
                layers.append(nn.ReLU())
                layers.append(nn.Dropout(0.2))
            self.network = nn.Sequential(*layers)
            self.fc = nn.Linear(num_channels[-1], num_classes)

        def forward(self, x):
            out = self.network(x)
            out = out[:, :, -1]  # Take last timestep
            return self.fc(out)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SimpleTCN(
        num_inputs=len(feature_cols),
        num_channels=[32, 32, 16],
        num_classes=3,
    ).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()

    # Training
    batch_size = 64
    best_acc = 0
    for epoch in range(30):
        model.train()
        indices = np.random.permutation(len(X_train))
        total_loss = 0

        for start in range(0, len(indices), batch_size):
            batch_idx = indices[start:start + batch_size]
            xb = X_train[batch_idx].to(device)
            yb = y_train[batch_idx].to(device)

            optimizer.zero_grad()
            out = model(xb)
            loss = criterion(out, yb)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        # Evaluate
        model.eval()
        with torch.no_grad():
            test_out = model(X_test.to(device))
            preds = test_out.argmax(dim=1).cpu()
            acc = (preds == y_test).float().mean().item()

        if acc > best_acc:
            best_acc = acc
            torch.save(model.state_dict(), output_path / "tcn_latest.pt")

    # Directional accuracy
    directional_mask = y_test != 1  # 1 = neutral
    if directional_mask.sum() > 0:
        dir_acc = (preds[directional_mask] == y_test[directional_mask]).float().mean().item()
    else:
        dir_acc = 0

    metadata = {
        "model_type": "tcn",
        "trained_at": datetime.utcnow().isoformat(),
        "samples_train": len(X_train),
        "samples_test": len(X_test),
        "accuracy": round(best_acc, 4),
        "directional_accuracy": round(dir_acc, 4),
        "features": feature_cols,
        "seq_length": seq_length,
        "device": str(device),
        "version": datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
    }

    with open(output_path / "tcn_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("TCN trained", accuracy=best_acc, directional_accuracy=dir_acc,
                train_samples=len(X_train), test_samples=len(X_test))
    return metadata


async def main():
    parser = argparse.ArgumentParser(description="Train MangoCoco ML models")
    parser.add_argument("--days", type=int, default=90, help="Days of historical data")
    parser.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS),
                        help="Comma-separated symbols")
    parser.add_argument("--retrain-all", action="store_true", help="Force retrain all models")
    parser.add_argument("--xgboost-only", action="store_true", help="Train only XGBoost")
    parser.add_argument("--tcn-only", action="store_true", help="Train only TCN")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Starting model training", symbols=len(symbols), days=args.days)

    pool = await asyncpg.create_pool(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        database=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, min_size=2, max_size=5,
    )

    try:
        # Load data
        candles_df = await load_training_data(pool, symbols, args.days)
        if candles_df.empty:
            logger.error("No training data available. Run backfill first: python scripts/backfill_data.py")
            return

        # Compute features
        features_df = compute_features(candles_df)
        if features_df.empty:
            logger.error("Feature computation produced no data")
            return

        logger.info(f"Computed features: {len(features_df)} samples, {features_df['symbol'].nunique()} symbols")

        results = {}

        # Train XGBoost
        if not args.tcn_only:
            logger.info("Training XGBoost model...")
            results["xgboost"] = train_xgboost(features_df, MODELS_DIR)

        # Train TCN
        if not args.xgboost_only:
            logger.info("Training TCN model...")
            results["tcn"] = train_tcn(features_df, MODELS_DIR)

        # Save training summary
        summary = {
            "trained_at": datetime.utcnow().isoformat(),
            "data_days": args.days,
            "symbols": symbols,
            "total_samples": len(features_df),
            "models": results,
        }

        with open(MODELS_DIR / "training_summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        logger.info("Training complete", results=results)

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
