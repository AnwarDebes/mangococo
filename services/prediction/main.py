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

from features.technical import compute_technical_features, compute_features_matrix
from features.sentiment import fetch_sentiment_features
from features.onchain import fetch_onchain_features
from models.tcn_model import TCNModel, MultiTCNEnsemble
from models.xgboost_model import XGBoostModel
from models.ensemble import EnsembleCombiner, EnsemblePrediction, ModelPrediction
from models.model_registry import ModelRegistry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
MODEL_DIR = os.getenv("MODEL_DIR", "/app/shared/models")
FEATURE_STORE_URL = os.getenv("FEATURE_STORE_URL", "http://localhost:8007")
INFERENCE_INTERVAL = float(os.getenv("INFERENCE_INTERVAL", 5.0))
TRADING_PAIRS_FILE = os.getenv("TRADING_PAIRS_FILE", "")
TRADING_PAIRS = os.getenv("TRADING_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")
MAX_ACTIVE_PAIRS = int(os.getenv("MAX_ACTIVE_PAIRS", 50))

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
    current_price: float
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
    tcn_accuracy: Optional[float] = None
    xgb_accuracy: Optional[float] = None
    last_train_time: Optional[str] = None
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
multi_tcn: Optional[MultiTCNEnsemble] = None
ensemble = EnsembleCombiner()
registry: Optional[ModelRegistry] = None
price_history: Dict[str, List[dict]] = {}
latest_predictions: Dict[str, PredictionResponse] = {}


def _ml_mode_available() -> bool:
    return (
        (tcn_model is not None and tcn_model.is_loaded)
        or (multi_tcn is not None and multi_tcn.is_loaded)
        or (xgb_model is not None and xgb_model.is_loaded)
    )


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_models() -> None:
    """Attempt to load latest TCN and XGBoost models from the registry."""
    global tcn_model, xgb_model, multi_tcn, registry

    registry = ModelRegistry(registry_dir=MODEL_DIR)

    # TCN (primary — kept for backwards compatibility)
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

    # Multi-timeframe TCN ensemble (loads variant-specific or falls back to primary)
    multi_tcn = MultiTCNEnsemble()
    multi_tcn.initialize_variants(MODEL_DIR)
    if multi_tcn.is_loaded:
        logger.info("Multi-TCN ensemble ready",
                     variants_loaded=sum(1 for m in multi_tcn.models.values() if m.is_loaded))
    else:
        logger.info("Multi-TCN ensemble has no loaded models, will use single TCN fallback")

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
        current_price=float(prices[-1]),
        mode="legacy",
        breakdown={"rsi": rsi, "momentum": momentum, "volume_ratio": vol_ratio},
    )


# ---------------------------------------------------------------------------
# ML inference
# ---------------------------------------------------------------------------

def _safe_float(v, default=0.0):
    """Clamp NaN/Inf to default."""
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return default
    return float(v)


def _prepare_symbol_features(symbol: str, ticks_snapshot: List[dict]) -> Optional[dict]:
    """CPU-bound: build DataFrame, compute technical features and full feature matrix.

    Runs in thread pool. Returns prepared data for batched GPU inference.
    Uses vectorized feature computation — one pass over the DataFrame.
    The full feature matrix is kept so multi-TCN variants can slice their
    own sequence lengths (15, 30, 60, 120 timesteps).
    """
    # Use more history to support long-horizon TCN variants (120+ timesteps)
    df = pd.DataFrame(ticks_snapshot[-250:])
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = df.get("price", 0)

    tech_features = compute_technical_features(df)

    # Build full feature matrix — each TCN variant slices what it needs
    feat_matrix = None
    tcn_sequence = None
    if len(df) >= 15:  # Minimum for smallest variant (tcn_micro)
        try:
            feat_matrix = compute_features_matrix(df)  # (N, 20)
            if len(feat_matrix) >= 60:
                tcn_sequence = feat_matrix[-60:]  # Primary TCN sequence for backwards compat
        except Exception:
            pass

    return {
        "symbol": symbol,
        "df": df,
        "tech_features": tech_features,
        "tcn_sequence": tcn_sequence,
        "feat_matrix": feat_matrix,
    }


async def make_prediction(symbol: str) -> Optional[PredictionResponse]:
    """Generate a prediction for *symbol* (single-symbol fallback path)."""
    ticks = price_history.get(symbol)
    if not ticks or len(ticks) < 20:
        return None
    for t in ticks:
        t["symbol"] = symbol
    return _legacy_predict(ticks)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def seed_price_history_from_db():
    """Seed price_history from TimescaleDB so ML mode is available immediately after restart."""
    global price_history
    import asyncpg

    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = int(os.getenv("POSTGRES_PORT", 5432))
    pg_db = os.getenv("POSTGRES_DB", "goblin")
    pg_user = os.getenv("POSTGRES_USER", "goblin")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "goblin_pg_pass")

    try:
        conn = await asyncpg.connect(
            host=pg_host, port=pg_port, database=pg_db,
            user=pg_user, password=pg_pass, timeout=10,
        )

        seeded = 0

        # Strategy 1: Seed from ticks table (most granular, real-time data)
        ticks_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='ticks')"
        )
        if ticks_exists:
            # Get symbols that have enough tick data
            symbols_with_data = await conn.fetch(
                """SELECT symbol, count(*) as cnt FROM ticks
                   GROUP BY symbol HAVING count(*) >= 60
                   ORDER BY count(*) DESC"""
            )
            for row in symbols_with_data:
                symbol = row["symbol"]
                if symbol not in [s.strip() for s in TRADING_PAIRS]:
                    continue
                try:
                    tick_rows = await conn.fetch(
                        """SELECT time, price, volume FROM ticks
                           WHERE symbol = $1 ORDER BY time DESC LIMIT 500""",
                        symbol
                    )
                    if tick_rows and len(tick_rows) >= 60:
                        ticks = []
                        for tr in reversed(tick_rows):
                            p = float(tr["price"] or 0)
                            v = float(tr["volume"] or 0)
                            ticks.append({
                                "timestamp": tr["time"].isoformat() if tr["time"] else "",
                                "open": p, "high": p, "low": p, "close": p,
                                "volume": v,
                            })
                        price_history[symbol] = ticks
                        seeded += 1
                except Exception:
                    pass

        # Strategy 2: Fill remaining symbols from 5m candles
        candles_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='candles')"
        )
        if candles_exists:
            for i in range(0, len(TRADING_PAIRS), 200):
                batch = [s.strip() for s in TRADING_PAIRS[i:i+200]]
                for symbol in batch:
                    if symbol in price_history and len(price_history[symbol]) >= 60:
                        continue  # Already seeded from ticks
                    try:
                        rows = await conn.fetch(
                            """SELECT time, open, high, low, close, volume
                               FROM candles WHERE symbol = $1 AND timeframe = '5m'
                               ORDER BY time DESC LIMIT 500""",
                            symbol
                        )
                        if rows and len(rows) >= 20:
                            ticks = []
                            for row in reversed(rows):
                                ticks.append({
                                    "timestamp": row["time"].isoformat() if row["time"] else "",
                                    "open": float(row["open"] or 0),
                                    "high": float(row["high"] or 0),
                                    "low": float(row["low"] or 0),
                                    "close": float(row["close"] or 0),
                                    "volume": float(row["volume"] or 0),
                                })
                            price_history[symbol] = ticks
                            seeded += 1
                    except Exception:
                        pass

        await conn.close()
        ml_ready = sum(1 for v in price_history.values() if len(v) >= 60)
        logger.info(f"Seeded price history from DB: {seeded} symbols total, {ml_ready} ML-ready (60+ ticks)")

    except Exception as e:
        logger.warning(f"Could not seed price history from DB: {e}")


_last_tick_time: float = 0.0  # monotonic timestamp of last received tick


async def collect_market_data():
    """Subscribe to Redis tick channels and accumulate price history.

    Automatically reconnects on Redis pubsub failures with exponential backoff.
    Includes staleness detection: if no tick arrives within STALENESS_TIMEOUT
    seconds the connection is assumed half-open and forcibly recycled.
    """
    global price_history, _last_tick_time
    backoff = 1
    max_backoff = 30
    STALENESS_TIMEOUT = 60  # seconds — force reconnect if no ticks for this long

    while True:
        pubsub = None
        try:
            pubsub = redis_client.pubsub()
            channels = [f"ticks:{s.strip().replace('/', '_')}" for s in TRADING_PAIRS]
            logger.info("Subscribing to tick channels", count=len(channels))
            await pubsub.subscribe(*channels)
            backoff = 1  # reset on successful connect
            _last_tick_time = time.monotonic()

            while True:
                # Use get_message with a short timeout instead of the blocking
                # async-for iterator so we can detect stale connections.
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                if message is not None and message["type"] == "message":
                    _last_tick_time = time.monotonic()
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
                        # Keep last 10,000 ticks (RAM is plentiful — supports longer sequences)
                        if len(price_history[symbol]) > 10000:
                            price_history[symbol] = price_history[symbol][-10000:]
                    except Exception as exc:
                        logger.debug("Tick parse error", error=str(exc))
                else:
                    # No message received — check for staleness
                    silence = time.monotonic() - _last_tick_time
                    if silence > STALENESS_TIMEOUT:
                        logger.warning(
                            "No ticks received, assuming stale pubsub — forcing reconnect",
                            silence_seconds=round(silence, 1),
                        )
                        break  # exit inner loop → reconnect
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Market data pubsub disconnected, reconnecting", error=str(exc), backoff=backoff)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


async def model_reload_watcher():
    """Watch for model update signals from the continuous learner and hot-reload.

    Automatically reconnects on Redis pubsub failures with exponential backoff.
    """
    backoff = 1
    max_backoff = 30

    while True:
        pubsub = None
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("model:reload")
            logger.info("Model reload watcher started")
            backoff = 1

            async for message in pubsub.listen():
                if message["type"] == "message":
                    logger.info("Model reload signal received, reloading models...")
                    try:
                        # Run in thread to avoid blocking the event loop
                        # (torch.load / xgb.Booster.load_model are heavy I/O)
                        await asyncio.to_thread(load_models)
                        mode = "ml" if _ml_mode_available() else "legacy"
                        logger.info("Models hot-reloaded", mode=mode)
                    except Exception as exc:
                        logger.error("Model reload failed", error=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Model reload watcher disconnected, reconnecting", error=str(exc), backoff=backoff)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


async def prediction_loop():
    """Batch inference pipeline — runs every INFERENCE_INTERVAL seconds.

    Pipeline:
      Phase 1 (CPU, thread pool): Prepare features for all symbols in parallel.
      Phase 2 (GPU, single call): Batched TCN + XGBoost inference.
      Phase 3 (CPU):              Ensemble combination per symbol.
      Phase 4 (Redis):            Publish all predictions.
    """
    from models.ensemble import _direction_sign

    while True:
        await asyncio.sleep(INFERENCE_INTERVAL)

        try:
            cycle_start = time.monotonic()
            symbols = [s.strip() for s in TRADING_PAIRS]

            # Filter to symbols with enough data, rank by data availability
            candidates = []
            for sym in symbols:
                ticks = price_history.get(sym)
                if ticks and len(ticks) >= 20:
                    candidates.append((sym, len(ticks)))

            # Sort by tick count descending — prioritize pairs with most data
            candidates.sort(key=lambda x: x[1], reverse=True)

            # Cap to MAX_ACTIVE_PAIRS
            eligible = [sym for sym, _ in candidates[:MAX_ACTIVE_PAIRS]]

            if not eligible:
                logger.debug("No eligible symbols for prediction", total=len(symbols), with_data=len(price_history))
                continue

            ml_mode = _ml_mode_available()

            # ── Phase 1: Parallel CPU feature preparation ─────────────
            if ml_mode:
                logger.debug("Phase 1: preparing features", symbols=len(eligible))
                prep_futures = []
                for sym in eligible:
                    ticks_snapshot = list(price_history[sym])
                    prep_futures.append(
                        asyncio.to_thread(_prepare_symbol_features, sym, ticks_snapshot)
                    )
                prepared_list = await asyncio.gather(*prep_futures, return_exceptions=True)
                logger.debug("Phase 1 done", prepared=sum(1 for x in prepared_list if not isinstance(x, Exception) and x is not None))

                # Separate successes from failures
                prepared = {}
                for item in prepared_list:
                    if isinstance(item, Exception) or item is None:
                        continue
                    prepared[item["symbol"]] = item

                # Fetch sentiment/onchain features with bounded concurrency and timeout.
                # Keep the wall-clock budget short (4s) so the prediction cycle
                # never blocks the event loop long enough to miss health checks.
                sentiment_map = {}
                onchain_map = {}
                ext_sem = asyncio.Semaphore(60)

                async def _fetch_ext(sym):
                    async with ext_sem:
                        s, o = await asyncio.gather(
                            fetch_sentiment_features(sym, redis_client=redis_client, feature_store_url=FEATURE_STORE_URL),
                            fetch_onchain_features(sym, redis_client=redis_client, feature_store_url=FEATURE_STORE_URL),
                        )
                        return sym, s, o

                try:
                    ext_results = await asyncio.wait_for(
                        asyncio.gather(
                            *[_fetch_ext(sym) for sym in prepared.keys()],
                            return_exceptions=True,
                        ),
                        timeout=4.0,
                    )
                    for r in ext_results:
                        if isinstance(r, Exception):
                            continue
                        sym, s, o = r
                        sentiment_map[sym] = s
                        onchain_map[sym] = o
                except asyncio.TimeoutError:
                    logger.warning("Ext feature fetch timed out, using defaults")

                await asyncio.sleep(0)  # Yield for health checks
                logger.debug("Phase 1+ext done")

                # ── Phase 2: Batched GPU inference ────────────────────────
                # Multi-TCN ensemble batch inference
                multi_tcn_results: Dict[str, list] = {}  # symbol -> [(variant, direction, confidence)]
                tcn_results = {}

                if multi_tcn is not None and multi_tcn.is_loaded:
                    # Collect feature matrices for all prepared symbols
                    feat_matrices = {}
                    for sym, prep in prepared.items():
                        if prep.get("feat_matrix") is not None:
                            feat_matrices[sym] = prep["feat_matrix"]

                    if feat_matrices:
                        try:
                            multi_tcn_results = await asyncio.wait_for(
                                asyncio.to_thread(multi_tcn.predict_batch_all, feat_matrices),
                                timeout=15.0,
                            )
                            # Also populate tcn_results from primary variant for backwards compat
                            for sym, variant_preds in multi_tcn_results.items():
                                medium_preds = [p for p in variant_preds if p[0] == "tcn_medium"]
                                if medium_preds:
                                    _, direction, confidence = medium_preds[0]
                                    tcn_results[sym] = ModelPrediction(direction=direction, confidence=confidence)
                                elif variant_preds:
                                    # Use first available variant
                                    _, direction, confidence = variant_preds[0]
                                    tcn_results[sym] = ModelPrediction(direction=direction, confidence=confidence)
                        except asyncio.TimeoutError:
                            logger.warning("Multi-TCN batch inference timed out", symbols=len(feat_matrices))
                        except Exception as exc:
                            logger.warning("Multi-TCN batch inference failed", error=str(exc))

                # Fallback to single TCN if multi-TCN didn't produce results
                if not tcn_results and tcn_model is not None and tcn_model.is_loaded:
                    tcn_syms = []
                    tcn_seqs = []
                    for sym, prep in prepared.items():
                        if prep["tcn_sequence"] is not None:
                            tcn_syms.append(sym)
                            tcn_seqs.append(prep["tcn_sequence"])

                    if tcn_seqs:
                        try:
                            batch_preds = await asyncio.wait_for(
                                asyncio.to_thread(tcn_model.predict_batch, tcn_seqs),
                                timeout=10.0,
                            )
                            for sym, (direction, confidence) in zip(tcn_syms, batch_preds):
                                tcn_results[sym] = ModelPrediction(direction=direction, confidence=confidence)
                        except asyncio.TimeoutError:
                            logger.warning("TCN batch inference timed out", symbols=len(tcn_syms))
                        except Exception as exc:
                            logger.warning("TCN batch inference failed", error=str(exc))

                # XGBoost batch
                xgb_results = {}
                if xgb_model is not None and xgb_model.is_loaded:
                    xgb_syms = []
                    xgb_feat_dicts = []
                    for sym, prep in prepared.items():
                        sf = sentiment_map.get(sym, {})
                        of = onchain_map.get(sym, {})
                        xgb_feat_dicts.append({**prep["tech_features"], **sf, **of})
                        xgb_syms.append(sym)

                    if xgb_feat_dicts:
                        try:
                            batch_preds = await asyncio.wait_for(
                                asyncio.to_thread(xgb_model.predict_batch, xgb_feat_dicts),
                                timeout=10.0,
                            )
                            for sym, (direction, confidence, probs) in zip(xgb_syms, batch_preds):
                                xgb_results[sym] = ModelPrediction(direction=direction, confidence=confidence, probabilities=probs)
                        except asyncio.TimeoutError:
                            logger.warning("XGBoost batch inference timed out", symbols=len(xgb_syms))
                        except Exception as exc:
                            logger.warning("XGBoost batch inference failed", error=str(exc))

                await asyncio.sleep(0)

                # ── Phase 3: Ensemble combination ─────────────────────────
                now_ts = datetime.now(timezone.utc).isoformat()
                for sym, prep in prepared.items():
                    tcn_pred = tcn_results.get(sym)
                    xgb_pred = xgb_results.get(sym)
                    sf = sentiment_map.get(sym, {})
                    of = onchain_map.get(sym, {})

                    sentiment_score = _safe_float(sf.get("sentiment_score", 0.0))
                    onchain_vals = [v for k, v in of.items() if isinstance(v, (int, float)) and k != "_source"]
                    onchain_score = float(np.mean(onchain_vals)) if onchain_vals else 0.0

                    # Check if features came from real sources or fell back to defaults
                    sentiment_avail = sf.get("_source", "default") != "default"
                    onchain_avail = of.get("_source", "default") != "default"

                    # Multi-TCN variant predictions for this symbol
                    sym_multi_tcn = multi_tcn_results.get(sym)

                    result = ensemble.combine(
                        tcn_pred=tcn_pred, xgb_pred=xgb_pred,
                        sentiment_score=sentiment_score, onchain_score=onchain_score,
                        sentiment_available=sentiment_avail, onchain_available=onchain_avail,
                        multi_tcn_preds=sym_multi_tcn if sym_multi_tcn else None,
                    )

                    PREDICTIONS_TOTAL.labels(symbol=sym, direction=result.direction).inc()
                    MODEL_CONFIDENCE.labels(symbol=sym).set(result.confidence)

                    agreement = 0
                    if tcn_pred and xgb_pred:
                        agreement = 1 if _direction_sign(tcn_pred.direction) == _direction_sign(xgb_pred.direction) else 0
                    ENSEMBLE_AGREEMENT.labels(symbol=sym).set(agreement)

                    latest_predictions[sym] = PredictionResponse(
                        symbol=sym,
                        timestamp=now_ts,
                        direction=result.direction,
                        confidence=_safe_float(result.confidence, 0.5),
                        score=_safe_float(result.score, 0.0),
                        current_price=_safe_float(prep["df"]["close"].iloc[-1], 0.0),
                        mode="ml",
                        breakdown={k: _safe_float(v) for k, v in result.breakdown.items()},
                        tcn_direction=tcn_pred.direction if tcn_pred else None,
                        tcn_confidence=round(_safe_float(tcn_pred.confidence, 0.5), 4) if tcn_pred else None,
                        xgb_direction=xgb_pred.direction if xgb_pred else None,
                        xgb_confidence=round(_safe_float(xgb_pred.confidence, 0.5), 4) if xgb_pred else None,
                    )

            else:
                # Legacy fallback for all symbols
                for sym in eligible:
                    ticks = list(price_history[sym])
                    for t in ticks:
                        t["symbol"] = sym
                    pred = _legacy_predict(ticks)
                    if pred is not None:
                        latest_predictions[sym] = pred

            await asyncio.sleep(0)

            # ── Phase 4: Publish all predictions to Redis ─────────────
            try:
                pipe = redis_client.pipeline()
                for sym, pred in latest_predictions.items():
                    pipe.publish(f"predictions:{sym.replace('/', '_')}", pred.model_dump_json())
                await pipe.execute()
            except Exception as pub_exc:
                logger.warning("Batch publish failed", error=str(pub_exc))

            elapsed = time.monotonic() - cycle_start
            PREDICTION_LATENCY.observe(elapsed)
            logger.info("Prediction cycle complete",
                         symbols=len(eligible), duration_s=round(elapsed, 2),
                         mode="ml" if ml_mode else "legacy")

        except Exception as loop_exc:
            logger.error("Prediction loop iteration failed", error=str(loop_exc), error_type=type(loop_exc).__name__)


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

    # Expand default thread pool for parallel CPU feature preparation
    from concurrent.futures import ThreadPoolExecutor
    _workers = int(os.getenv("INFERENCE_WORKERS", "32"))
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=_workers))
    logger.info("Thread pool configured", workers=_workers)

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

    # Seed price history from DB for immediate ML mode
    await seed_price_history_from_db()

    # Start background tasks with monitoring
    bg_tasks: Dict[str, asyncio.Task] = {}

    def _start_task(name: str, coro_fn):
        task = asyncio.create_task(coro_fn(), name=name)
        bg_tasks[name] = task
        return task

    _start_task("collect_market_data", collect_market_data)
    _start_task("prediction_loop", prediction_loop)
    _start_task("model_reload_watcher", model_reload_watcher)

    # Monitor tasks: restart any that crash unexpectedly
    async def _task_monitor():
        while True:
            await asyncio.sleep(5)
            for name, task in list(bg_tasks.items()):
                if task.done():
                    exc = task.exception() if not task.cancelled() else None
                    logger.error("Background task died, restarting", task=name, error=str(exc))
                    coro_map = {
                        "collect_market_data": collect_market_data,
                        "prediction_loop": prediction_loop,
                        "model_reload_watcher": model_reload_watcher,
                    }
                    if name in coro_map:
                        _start_task(name, coro_map[name])

    monitor_task = asyncio.create_task(_task_monitor(), name="task_monitor")

    yield

    monitor_task.cancel()
    for task in bg_tasks.values():
        task.cancel()
    if redis_client:
        await redis_client.close()


# ---------------------------------------------------------------------------
# FastAPI app + routes
# ---------------------------------------------------------------------------

app = FastAPI(title="ML Prediction Service", version="2.0.0", lifespan=lifespan)


_cached_device: Optional[str] = None


def _get_device() -> str:
    """Cache the device string once — torch.cuda.is_available() is expensive."""
    global _cached_device
    if _cached_device is None:
        try:
            import torch
            _cached_device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            _cached_device = "cpu"
    return _cached_device


@app.get("/health", response_model=HealthResponse)
async def health():
    symbols_with_data = sum(1 for v in price_history.values() if len(v) >= 20)
    has_recent_predictions = len(latest_predictions) > 0

    # A service that has produced predictions is fundamentally working —
    # only report "degraded" if we've never generated any predictions AND
    # have no data at all.  Transient tick gaps should not flip status.
    if symbols_with_data == 0 and not has_recent_predictions:
        status = "degraded"
    else:
        status = "healthy"

    return HealthResponse(
        status=status,
        mode="ml" if _ml_mode_available() else "legacy",
        symbols_active=symbols_with_data,
        device=_get_device(),
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
    tcn_acc = None
    xgb_acc = None
    last_train = None

    if registry:
        tcn_info = registry.get_latest("tcn")
        xgb_info = registry.get_latest("xgboost")
        if tcn_info:
            tcn_ver = tcn_info.version
            tcn_acc = tcn_info.metrics.get("accuracy")
            last_train = tcn_info.creation_date
        if xgb_info:
            xgb_ver = xgb_info.version
            xgb_acc = xgb_info.metrics.get("accuracy")
            if xgb_info.creation_date and (not last_train or xgb_info.creation_date > last_train):
                last_train = xgb_info.creation_date

    return ModelStatusResponse(
        tcn_loaded=tcn_model is not None and tcn_model.is_loaded,
        xgb_loaded=xgb_model is not None and xgb_model.is_loaded,
        mode="ml" if _ml_mode_available() else "legacy",
        tcn_version=tcn_ver,
        xgb_version=xgb_ver,
        tcn_accuracy=tcn_acc,
        xgb_accuracy=xgb_acc,
        last_train_time=last_train,
        registry_dir=MODEL_DIR,
    )


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()


def _sanitize_floats(obj):
    """Replace NaN/Inf with None so JSON serialization doesn't fail."""
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


@app.get("/predictions")
async def get_all_predictions():
    """Return the latest cached prediction for every active symbol."""
    return {sym: _sanitize_floats(pred.model_dump()) for sym, pred in latest_predictions.items()}
