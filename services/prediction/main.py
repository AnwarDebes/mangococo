"""
ML-Powered Ensemble Prediction Service.

FastAPI service (port 8002) that runs real-time inference using a TCN +
XGBoost ensemble, with sentiment and on-chain signal inputs.

On startup the service loads trained models from the shared/models/
directory.  If models are not yet available it falls back to a legacy
rule-based TA strategy (degraded mode).

A background task runs every 5 seconds, performing batch inference for
all active symbols and publishing predictions to Redis pubsub.
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

from features.technical import compute_technical_features
from features.sentiment import fetch_sentiment_features
from features.onchain import fetch_onchain_features
from models.tcn_model import TCNModel
from models.xgboost_model import XGBoostModel
from models.ensemble import EnsembleCombiner, EnsemblePrediction, ModelPrediction
from models.model_registry import ModelRegistry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
MODEL_DIR = os.getenv("MODEL_DIR", "/app/shared/models")
FEATURE_STORE_URL = os.getenv("FEATURE_STORE_URL", "http://feature-store:8003")
INFERENCE_INTERVAL = float(os.getenv("INFERENCE_INTERVAL", 5.0))
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

PREDICTIONS_TOTAL = Counter(
    "prediction_total", "Total predictions made", ["symbol", "direction"],
)
PREDICTION_LATENCY = Histogram(
    "prediction_latency_seconds", "End-to-end prediction latency",
)
MODEL_CONFIDENCE = Gauge(
    "model_confidence", "Latest ensemble confidence", ["symbol"],
)
ENSEMBLE_AGREEMENT = Gauge(
    "ensemble_agreement", "Whether TCN and XGBoost agree (1/0)", ["symbol"],
)

# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class PredictionResponse(BaseModel):
    symbol: str
    timestamp: str
    direction: str
    confidence: float
    score: float
    mode: str  # "ml" or "legacy"
    breakdown: Dict[str, float] = {}
    tcn_direction: Optional[str] = None
    tcn_confidence: Optional[float] = None
    xgb_direction: Optional[str] = None
    xgb_confidence: Optional[float] = None


class ModelStatusResponse(BaseModel):
    tcn_loaded: bool
    xgb_loaded: bool
    mode: str
    tcn_version: Optional[str] = None
    xgb_version: Optional[str] = None
    registry_dir: str = MODEL_DIR


class HealthResponse(BaseModel):
    status: str
    mode: str
    symbols_active: int
    device: str


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

redis_client: Optional[aioredis.Redis] = None
tcn_model: Optional[TCNModel] = None
xgb_model: Optional[XGBoostModel] = None
ensemble = EnsembleCombiner()
registry: Optional[ModelRegistry] = None
price_history: Dict[str, List[dict]] = {}
latest_predictions: Dict[str, PredictionResponse] = {}


def _ml_mode_available() -> bool:
    return (tcn_model is not None and tcn_model.is_loaded) or (
        xgb_model is not None and xgb_model.is_loaded
    )


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_models() -> None:
    """Attempt to load latest TCN and XGBoost models from the registry."""
    global tcn_model, xgb_model, registry

    registry = ModelRegistry(registry_dir=MODEL_DIR)

    # TCN
    tcn_info = registry.get_latest("tcn")
    if tcn_info and os.path.isfile(tcn_info.path):
        try:
            tcn_model = TCNModel()
            tcn_model.load(tcn_info.path)
            logger.info("TCN model loaded from registry", version=tcn_info.version)
        except Exception as exc:
            logger.warning("Failed to load TCN model", error=str(exc))
            tcn_model = None
    else:
        logger.info("No TCN model in registry, ML-TCN will be unavailable")

    # XGBoost
    xgb_info = registry.get_latest("xgboost")
    if xgb_info and os.path.isfile(xgb_info.path):
        try:
            xgb_model = XGBoostModel()
            xgb_model.load(xgb_info.path)
            logger.info("XGBoost model loaded from registry", version=xgb_info.version)
        except Exception as exc:
            logger.warning("Failed to load XGBoost model", error=str(exc))
            xgb_model = None
    else:
        logger.info("No XGBoost model in registry, ML-XGB will be unavailable")


# ---------------------------------------------------------------------------
# Legacy TA fallback (degraded mode)
# ---------------------------------------------------------------------------

def _legacy_predict(ticks: List[dict]) -> Optional[PredictionResponse]:
    """Simple momentum + RSI strategy used when ML models are unavailable."""
    if len(ticks) < 20:
        return None

    prices = [t.get("close", t.get("price", 0)) for t in ticks[-50:]]
    volumes = [t.get("volume", 1) for t in ticks[-50:]]

    if not prices or prices[-1] <= 0:
        return None

    symbol = ticks[-1].get("symbol", "UNKNOWN")

    # RSI
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    period = min(14, len(gains))
    avg_gain = np.mean(gains[-period:]) if period > 0 else 0
    avg_loss = np.mean(losses[-period:]) if period > 0 else 0
    rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
    rsi = 100 - (100 / (1 + rs))

    # Momentum
    lookback = min(5, len(prices) - 1)
    momentum = (prices[-1] - prices[-1 - lookback]) / prices[-1 - lookback] * 100

    # Volume ratio
    vol_avg = np.mean(volumes[-10:]) if len(volumes) >= 10 else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0

    direction = "hold"
    confidence = 0.5

    buy_signals = 0
    sell_signals = 0

    if rsi < 30:
        buy_signals += 1
    elif rsi > 70:
        sell_signals += 1

    if momentum > 0.15:
        buy_signals += 1
    elif momentum < -0.15:
        sell_signals += 1

    if vol_ratio > 1.2 and momentum > 0:
        buy_signals += 1
    elif vol_ratio > 1.2 and momentum < 0:
        sell_signals += 1

    if buy_signals >= 2:
        direction = "buy"
        confidence = min(0.85, 0.6 + buy_signals * 0.08)
    elif sell_signals >= 2:
        direction = "sell"
        confidence = min(0.85, 0.6 + sell_signals * 0.08)

    return PredictionResponse(
        symbol=symbol,
        timestamp=datetime.now(timezone.utc).isoformat(),
        direction=direction,
        confidence=round(confidence, 4),
        score=round({"buy": 0.5, "sell": -0.5, "hold": 0.0}.get(direction, 0.0), 4),
        mode="legacy",
        breakdown={"rsi": rsi, "momentum": momentum, "volume_ratio": vol_ratio},
    )


# ---------------------------------------------------------------------------
# ML inference
# ---------------------------------------------------------------------------

async def _ml_predict(symbol: str, ticks: List[dict]) -> Optional[PredictionResponse]:
    """Run the full ML ensemble pipeline for a single symbol."""
    if len(ticks) < 60:
        return None

    start = time.monotonic()

    # Build candle DataFrame
    df = pd.DataFrame(ticks[-120:])
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = df.get("price", 0)

    # Compute technical features
    tech_features = compute_technical_features(df)

    # Fetch sentiment and on-chain
    sentiment_feats = await fetch_sentiment_features(
        symbol, redis_client=redis_client, feature_store_url=FEATURE_STORE_URL,
    )
    onchain_feats = await fetch_onchain_features(
        symbol, redis_client=redis_client, feature_store_url=FEATURE_STORE_URL,
    )

    tcn_pred: Optional[ModelPrediction] = None
    xgb_pred: Optional[ModelPrediction] = None

    # TCN inference (needs sequence)
    if tcn_model is not None and tcn_model.is_loaded:
        try:
            # Build sequence: last 60 rows of technical features
            seq_rows = []
            start_idx = max(0, len(df) - 60)
            for i in range(start_idx, len(df)):
                window = df.iloc[max(0, i - 59) : i + 1]
                row_feats = compute_technical_features(window)
                seq_rows.append([row_feats.get(k, 0.0) for k in sorted(row_feats.keys())])

            if len(seq_rows) >= 60:
                sequence = np.array(seq_rows[-60:], dtype=np.float32)
                direction, confidence = tcn_model.predict(sequence)
                tcn_pred = ModelPrediction(direction=direction, confidence=confidence)
        except Exception as exc:
            logger.warning("TCN inference failed", symbol=symbol, error=str(exc))

    # XGBoost inference (flat feature vector)
    if xgb_model is not None and xgb_model.is_loaded:
        try:
            all_features = {**tech_features, **sentiment_feats, **onchain_feats}
            direction, confidence, probs = xgb_model.predict(all_features)
            xgb_pred = ModelPrediction(direction=direction, confidence=confidence, probabilities=probs)
        except Exception as exc:
            logger.warning("XGBoost inference failed", symbol=symbol, error=str(exc))

    # Sentiment aggregate score
    sentiment_score = sentiment_feats.get("sentiment_score", 0.0)

    # On-chain aggregate score (average of normalised metrics)
    onchain_vals = [v for v in onchain_feats.values() if isinstance(v, (int, float))]
    onchain_score = float(np.mean(onchain_vals)) if onchain_vals else 0.0

    # Ensemble
    result: EnsemblePrediction = ensemble.combine(
        tcn_pred=tcn_pred,
        xgb_pred=xgb_pred,
        sentiment_score=sentiment_score,
        onchain_score=onchain_score,
    )

    elapsed = time.monotonic() - start
    PREDICTION_LATENCY.observe(elapsed)
    PREDICTIONS_TOTAL.labels(symbol=symbol, direction=result.direction).inc()
    MODEL_CONFIDENCE.labels(symbol=symbol).set(result.confidence)

    agreement = 0
    if tcn_pred and xgb_pred:
        from models.ensemble import _direction_sign
        agreement = 1 if _direction_sign(tcn_pred.direction) == _direction_sign(xgb_pred.direction) else 0
    ENSEMBLE_AGREEMENT.labels(symbol=symbol).set(agreement)

    return PredictionResponse(
        symbol=symbol,
        timestamp=datetime.now(timezone.utc).isoformat(),
        direction=result.direction,
        confidence=result.confidence,
        score=result.score,
        mode="ml",
        breakdown=result.breakdown,
        tcn_direction=tcn_pred.direction if tcn_pred else None,
        tcn_confidence=round(tcn_pred.confidence, 4) if tcn_pred else None,
        xgb_direction=xgb_pred.direction if xgb_pred else None,
        xgb_confidence=round(xgb_pred.confidence, 4) if xgb_pred else None,
    )


async def make_prediction(symbol: str) -> Optional[PredictionResponse]:
    """Generate a prediction for *symbol*, using ML or falling back to legacy."""
    ticks = price_history.get(symbol)
    if not ticks or len(ticks) < 20:
        return None

    if _ml_mode_available():
        pred = await _ml_predict(symbol, ticks)
        if pred is not None:
            return pred

    # Fallback: legacy TA
    for t in ticks:
        t["symbol"] = symbol
    return _legacy_predict(ticks)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def collect_market_data():
    """Subscribe to Redis tick channels and accumulate price history."""
    global price_history
    pubsub = redis_client.pubsub()
    channels = [f"ticks:{s.strip().replace('/', '_')}" for s in TRADING_PAIRS]
    logger.info("Subscribing to tick channels", count=len(channels))
    await pubsub.subscribe(*channels)

    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                tick = json.loads(message["data"])
                symbol = tick["symbol"]
                data_point = {
                    "timestamp": tick.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    "open": tick.get("price", 0),
                    "high": tick.get("price", 0),
                    "low": tick.get("price", 0),
                    "close": tick.get("price", 0),
                    "volume": tick.get("volume", 0),
                }
                if symbol not in price_history:
                    price_history[symbol] = []
                price_history[symbol].append(data_point)
                # Keep last 200 ticks
                if len(price_history[symbol]) > 200:
                    price_history[symbol] = price_history[symbol][-200:]
            except Exception as exc:
                logger.debug("Tick parse error", error=str(exc))


async def prediction_loop():
    """Batch inference every INFERENCE_INTERVAL seconds."""
    while True:
        await asyncio.sleep(INFERENCE_INTERVAL)

        symbols = list(TRADING_PAIRS)
        batch_size = 50

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            tasks = [make_prediction(s.strip()) for s in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for symbol, result in zip(batch, results):
                sym = symbol.strip()
                if isinstance(result, Exception):
                    logger.error("Prediction failed", symbol=sym, error=str(result))
                elif result is not None:
                    latest_predictions[sym] = result
                    # Publish to Redis
                    try:
                        await redis_client.publish(
                            f"predictions:{sym.replace('/', '_')}",
                            result.model_dump_json(),
                        )
                    except Exception:
                        pass

            await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Symbol loading helper
# ---------------------------------------------------------------------------

def load_symbols_from_file(filepath: str, wait_seconds: int = 60) -> List[str]:
    """Load symbols from file, waiting up to *wait_seconds* for it to appear."""
    import time as _time
    deadline = _time.monotonic() + wait_seconds
    while _time.monotonic() < deadline:
        try:
            if os.path.isfile(filepath):
                with open(filepath, "r") as fh:
                    lines = [l.strip() for l in fh if l.strip() and not l.strip().startswith("#")]
                if lines:
                    return lines
        except Exception:
            pass
        _time.sleep(2)
    return []


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, TRADING_PAIRS

    logger.info("Starting ML Prediction Service")

    # Connect to Redis
    redis_client = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True,
    )
    await redis_client.ping()
    logger.info("Redis connected")

    # Load models
    load_models()
    mode = "ml" if _ml_mode_available() else "legacy"
    logger.info("Prediction mode", mode=mode)

    # Load trading pairs
    if TRADING_PAIRS_FILE:
        pairs = await asyncio.to_thread(load_symbols_from_file, TRADING_PAIRS_FILE)
        if pairs:
            TRADING_PAIRS = pairs
            logger.info("Loaded symbols from file", count=len(TRADING_PAIRS))
    else:
        TRADING_PAIRS = [s.strip() for s in os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",") if s.strip()]

    # Start background tasks
    data_task = asyncio.create_task(collect_market_data())
    pred_task = asyncio.create_task(prediction_loop())

    yield

    data_task.cancel()
    pred_task.cancel()
    if redis_client:
        await redis_client.close()


# ---------------------------------------------------------------------------
# FastAPI app + routes
# ---------------------------------------------------------------------------

app = FastAPI(title="ML Prediction Service", version="2.0.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health():
    import torch
    return HealthResponse(
        status="healthy",
        mode="ml" if _ml_mode_available() else "legacy",
        symbols_active=len(price_history),
        device="cuda" if torch.cuda.is_available() else "cpu",
    )


@app.get("/predict/{symbol}", response_model=PredictionResponse)
async def predict(symbol: str):
    symbol = symbol.replace("_", "/").upper()
    result = await make_prediction(symbol)
    if result is None:
        raise HTTPException(status_code=400, detail="Insufficient data for prediction")
    return result


@app.get("/model-status", response_model=ModelStatusResponse)
async def model_status():
    tcn_ver = None
    xgb_ver = None
    if registry:
        tcn_info = registry.get_latest("tcn")
        xgb_info = registry.get_latest("xgboost")
        tcn_ver = tcn_info.version if tcn_info else None
        xgb_ver = xgb_info.version if xgb_info else None

    return ModelStatusResponse(
        tcn_loaded=tcn_model is not None and tcn_model.is_loaded,
        xgb_loaded=xgb_model is not None and xgb_model.is_loaded,
        mode="ml" if _ml_mode_available() else "legacy",
        tcn_version=tcn_ver,
        xgb_version=xgb_ver,
        registry_dir=MODEL_DIR,
    )


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()


@app.get("/predictions")
async def get_all_predictions():
    """Return the latest cached prediction for every active symbol."""
    return {sym: pred.model_dump() for sym, pred in latest_predictions.items()}
