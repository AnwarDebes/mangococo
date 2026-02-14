"""
Data loader for the Backtesting service.
Reads historical candles, sentiment scores, and feature vectors
from TimescaleDB and merges them into a unified DataFrame.
"""
from datetime import datetime
from typing import Optional

import asyncpg
import pandas as pd
import structlog

logger = structlog.get_logger()


async def load_candles(
    pool: asyncpg.Pool,
    symbols: list[str],
    start: datetime,
    end: datetime,
    timeframe: str = "1m",
) -> pd.DataFrame:
    """
    Load OHLCV candles from the ``candles`` hypertable.

    Returns a DataFrame with columns:
        time, symbol, open, high, low, close, volume
    sorted by (symbol, time).
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, symbol, open, high, low, close, volume
            FROM candles
            WHERE symbol = ANY($1)
              AND timeframe = $2
              AND time >= $3
              AND time <= $4
            ORDER BY symbol, time ASC
            """,
            symbols,
            timeframe,
            start,
            end,
        )

    if not rows:
        logger.warning("No candles found", symbols=symbols, start=start, end=end)
        return pd.DataFrame(columns=["time", "symbol", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame([dict(r) for r in rows])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("Candles loaded", rows=len(df), symbols=df["symbol"].nunique())
    return df


async def load_sentiment(
    pool: asyncpg.Pool,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """
    Load sentiment scores from the ``sentiment_scores`` table.

    Returns a DataFrame with columns:
        time, symbol, source, score, mentions
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, symbol, source, score, mentions
                FROM sentiment_scores
                WHERE symbol = ANY($1)
                  AND time >= $2
                  AND time <= $3
                ORDER BY symbol, time ASC
                """,
                symbols,
                start,
                end,
            )
    except asyncpg.UndefinedTableError:
        logger.info("sentiment_scores table does not exist yet")
        return pd.DataFrame(columns=["time", "symbol", "score"])

    if not rows:
        return pd.DataFrame(columns=["time", "symbol", "score"])

    df = pd.DataFrame([dict(r) for r in rows])
    df["time"] = pd.to_datetime(df["time"], utc=True)

    # Aggregate multiple sources into a single score per (symbol, time bucket)
    # Use 5-minute buckets so sentiment aligns reasonably with 1m candles
    df = df.set_index("time")
    agg = (
        df.groupby([pd.Grouper(freq="5min"), "symbol"])
        .agg(sentiment_score=("score", "mean"), mentions=("mentions", "sum"))
        .reset_index()
    )
    agg.rename(columns={"time": "time"}, inplace=True)

    logger.info("Sentiment loaded", rows=len(agg))
    return agg


async def load_features(
    pool: asyncpg.Pool,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """
    Load pre-computed feature vectors from the ``feature_vectors`` table.

    Returns a DataFrame where each JSONB feature dict is expanded into columns.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, symbol, features
                FROM feature_vectors
                WHERE symbol = ANY($1)
                  AND time >= $2
                  AND time <= $3
                ORDER BY symbol, time ASC
                """,
                symbols,
                start,
                end,
            )
    except asyncpg.UndefinedTableError:
        logger.info("feature_vectors table does not exist yet")
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    import json

    records = []
    for r in rows:
        rec = {"time": r["time"], "symbol": r["symbol"]}
        feats = r["features"]
        if isinstance(feats, str):
            feats = json.loads(feats)
        rec.update(feats)
        records.append(rec)

    df = pd.DataFrame(records)
    df["time"] = pd.to_datetime(df["time"], utc=True)

    logger.info("Features loaded", rows=len(df))
    return df


async def build_backtest_dataframe(
    pool: asyncpg.Pool,
    symbols: list[str],
    start: datetime,
    end: datetime,
    timeframe: str = "1m",
) -> pd.DataFrame:
    """
    Load candles, sentiment, and features then merge into a single
    DataFrame suitable for the backtesting engine.

    The resulting DataFrame has one row per (symbol, time) with columns:
        time, symbol, open, high, low, close, volume,
        sentiment_score (forward-filled), plus any feature columns.
    """
    candles = await load_candles(pool, symbols, start, end, timeframe)
    if candles.empty:
        return candles

    sentiment = await load_sentiment(pool, symbols, start, end)
    features = await load_features(pool, symbols, start, end)

    df = candles.copy()

    # Merge sentiment (asof join on nearest previous sentiment timestamp)
    if not sentiment.empty:
        for sym in df["symbol"].unique():
            sym_candles = df[df["symbol"] == sym].copy()
            sym_sent = sentiment[sentiment["symbol"] == sym].copy()

            if sym_sent.empty:
                df.loc[df["symbol"] == sym, "sentiment_score"] = 0.0
                continue

            merged = pd.merge_asof(
                sym_candles.sort_values("time"),
                sym_sent[["time", "sentiment_score"]].sort_values("time"),
                on="time",
                direction="backward",
            )
            df.loc[df["symbol"] == sym, "sentiment_score"] = merged["sentiment_score"].values
    else:
        df["sentiment_score"] = 0.0

    # Merge features (asof join)
    if not features.empty:
        feature_cols = [c for c in features.columns if c not in ("time", "symbol")]
        for sym in df["symbol"].unique():
            sym_candles = df[df["symbol"] == sym].copy()
            sym_feats = features[features["symbol"] == sym].copy()

            if sym_feats.empty:
                for col in feature_cols:
                    df.loc[df["symbol"] == sym, col] = 0.0
                continue

            merged = pd.merge_asof(
                sym_candles.sort_values("time"),
                sym_feats[["time"] + feature_cols].sort_values("time"),
                on="time",
                direction="backward",
            )
            for col in feature_cols:
                df.loc[df["symbol"] == sym, col] = merged[col].values

    df["sentiment_score"] = df.get("sentiment_score", pd.Series(0.0)).fillna(0.0)
    df = df.sort_values(["symbol", "time"]).reset_index(drop=True)

    logger.info(
        "Backtest DataFrame built",
        rows=len(df),
        columns=list(df.columns),
        symbols=df["symbol"].nunique(),
    )
    return df
