"""
Sentiment Analysis Service - Scrapes crypto news and social media,
processes through FinBERT NLP pipeline, and publishes sentiment scores.
"""
import asyncio
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest

from scrapers import CryptoPanicScraper, RedditScraper, FearGreedScraper, NewsItem, SocialPost
from nlp import FinBERTAnalyzer, TextPreprocessor
from db import SentimentDB

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

CRYPTOPANIC_INTERVAL = int(os.getenv("CRYPTOPANIC_INTERVAL", 300))  # 5 minutes
REDDIT_INTERVAL = int(os.getenv("REDDIT_INTERVAL", 600))  # 10 minutes
FEAR_GREED_INTERVAL = int(os.getenv("FEAR_GREED_INTERVAL", 3600))  # 1 hour
SENTIMENT_WINDOW_HOURS = int(os.getenv("SENTIMENT_WINDOW_HOURS", 24))

logger = structlog.get_logger()

# Prometheus metrics
SCRAPE_COUNT = Counter("sentiment_scrapes_total", "Total scrape runs", ["source"])
SCRAPE_ITEMS = Counter("sentiment_items_total", "Total items scraped", ["source"])
SCRAPE_ERRORS = Counter("sentiment_scrape_errors_total", "Scrape errors", ["source"])
NLP_PROCESSED = Counter("sentiment_nlp_processed_total", "Total texts analyzed by NLP")
SENTIMENT_SCORE = Gauge("sentiment_score", "Current sentiment score", ["symbol"])
FEAR_GREED_GAUGE = Gauge("sentiment_fear_greed", "Fear & Greed Index value")
PROCESSING_TIME = Histogram("sentiment_processing_seconds", "Processing time per cycle", ["source"])

# In-memory store of recent items for time-weighted aggregation
recent_items: Dict[str, List[dict]] = defaultdict(list)
recent_news: List[dict] = []
MAX_NEWS_ITEMS = 200


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:16]


# --- Components ---
crypto_scraper = CryptoPanicScraper()
reddit_scraper = RedditScraper()
fear_greed_scraper = FearGreedScraper()
nlp_analyzer = FinBERTAnalyzer()
preprocessor = TextPreprocessor()
db = SentimentDB()
redis_client: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
        )
    return redis_client


async def _process_items(items: List[dict], source: str):
    """Process scraped items through NLP and store results."""
    global recent_news

    if not items:
        return

    texts = [item["text"] for item in items]
    cleaned = preprocessor.process_batch(texts)

    if not cleaned:
        return

    results = await nlp_analyzer.analyze(cleaned)
    NLP_PROCESSED.inc(len(results))

    now = datetime.now(timezone.utc)
    db_records = []

    for i, result in enumerate(results):
        # Map cleaned text back to original item (best effort by index)
        item = items[min(i, len(items) - 1)]
        symbol = item.get("symbol", "UNKNOWN")

        record = {
            "symbol": symbol,
            "label": result.label,
            "score": result.score if result.label == "positive" else -result.score if result.label == "negative" else 0.0,
            "source": item.get("source", source),
            "timestamp": item.get("timestamp", now.isoformat()),
            "text_preview": item["text"][:100],
        }

        recent_items[symbol].append(record)

        # Store for news feed
        news_entry = {
            "text": item["text"][:300],
            "symbol": symbol,
            "source": item.get("source", source),
            "sentiment": result.label,
            "confidence": result.score,
            "timestamp": item.get("timestamp", now.isoformat()),
        }
        recent_news.append(news_entry)

        ts = item.get("timestamp", now)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                ts = now

        db_records.append((
            ts,
            symbol,
            result.label,
            result.score,
            item.get("source", source),
            _text_hash(item["text"]),
        ))

    # Trim news list
    if len(recent_news) > MAX_NEWS_ITEMS:
        recent_news = recent_news[-MAX_NEWS_ITEMS:]

    # Write to DB
    await db.batch_insert(db_records)

    # Update aggregated sentiment per symbol
    await _update_sentiment_aggregates()


async def _update_sentiment_aggregates():
    """Compute time-weighted average sentiment per symbol and publish."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=SENTIMENT_WINDOW_HOURS)
    r = await _get_redis()

    for symbol, items in recent_items.items():
        # Filter to window
        valid = []
        for item in items:
            ts = item.get("timestamp", now)
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    ts = now
            if ts >= cutoff:
                valid.append((item, ts))

        recent_items[symbol] = [item for item, _ in valid]

        if not valid:
            continue

        # Time-weighted average: more recent items get higher weight
        total_weight = 0.0
        weighted_score = 0.0
        for item, ts in valid:
            # Weight: hours remaining in window (more recent = higher)
            age_hours = (now - ts).total_seconds() / 3600.0
            weight = max(0.1, SENTIMENT_WINDOW_HOURS - age_hours)
            score = item.get("score", 0.0)
            weighted_score += score * weight
            total_weight += weight

        avg_score = weighted_score / total_weight if total_weight > 0 else 0.0
        avg_score = round(avg_score, 4)

        sentiment_data = {
            "symbol": symbol,
            "score": avg_score,
            "sample_count": len(valid),
            "updated_at": now.isoformat(),
        }

        await r.set(f"sentiment:{symbol}", json.dumps(sentiment_data), ex=86400)
        SENTIMENT_SCORE.labels(symbol=symbol).set(avg_score)

    # Publish update
    try:
        await r.publish("sentiment_update", json.dumps({
            "type": "sentiment_update",
            "timestamp": now.isoformat(),
            "symbols": list(recent_items.keys()),
        }))
    except Exception as e:
        logger.error("redis_publish_error", error=str(e))


async def _scrape_cryptopanic():
    """Periodic CryptoPanic scrape task."""
    while True:
        try:
            SCRAPE_COUNT.labels(source="cryptopanic").inc()
            with PROCESSING_TIME.labels(source="cryptopanic").time():
                items = await crypto_scraper.fetch()
                SCRAPE_ITEMS.labels(source="cryptopanic").inc(len(items))
                item_dicts = [item.model_dump() for item in items]
                for d in item_dicts:
                    if isinstance(d.get("timestamp"), datetime):
                        d["timestamp"] = d["timestamp"].isoformat()
                await _process_items(item_dicts, "cryptopanic")
        except Exception as e:
            SCRAPE_ERRORS.labels(source="cryptopanic").inc()
            logger.error("cryptopanic_task_error", error=str(e))
        await asyncio.sleep(CRYPTOPANIC_INTERVAL)


async def _scrape_reddit():
    """Periodic Reddit scrape task."""
    while True:
        try:
            SCRAPE_COUNT.labels(source="reddit").inc()
            with PROCESSING_TIME.labels(source="reddit").time():
                items = await reddit_scraper.fetch()
                SCRAPE_ITEMS.labels(source="reddit").inc(len(items))
                item_dicts = [item.model_dump() for item in items]
                for d in item_dicts:
                    if isinstance(d.get("timestamp"), datetime):
                        d["timestamp"] = d["timestamp"].isoformat()
                await _process_items(item_dicts, "reddit")
        except Exception as e:
            SCRAPE_ERRORS.labels(source="reddit").inc()
            logger.error("reddit_task_error", error=str(e))
        await asyncio.sleep(REDDIT_INTERVAL)


async def _scrape_fear_greed():
    """Periodic Fear & Greed Index fetch task."""
    while True:
        try:
            SCRAPE_COUNT.labels(source="fear_greed").inc()
            data = await fear_greed_scraper.fetch()
            if data:
                r = await _get_redis()
                fg_data = {
                    "value": data.value,
                    "classification": data.classification,
                    "normalized_score": data.normalized_score,
                    "timestamp": data.timestamp.isoformat(),
                }
                await r.set("fear_greed_index", json.dumps(fg_data), ex=7200)
                FEAR_GREED_GAUGE.set(data.value)
                logger.info("fear_greed_stored", value=data.value, classification=data.classification)
        except Exception as e:
            SCRAPE_ERRORS.labels(source="fear_greed").inc()
            logger.error("fear_greed_task_error", error=str(e))
        await asyncio.sleep(FEAR_GREED_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("sentiment_service_starting")

    # Load NLP model
    await nlp_analyzer.load()

    # Connect to DB
    await db.connect()

    # Start background tasks
    tasks = [
        asyncio.create_task(_scrape_cryptopanic()),
        asyncio.create_task(_scrape_reddit()),
        asyncio.create_task(_scrape_fear_greed()),
    ]
    logger.info("sentiment_service_started")

    yield

    # Shutdown
    logger.info("sentiment_service_stopping")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await crypto_scraper.close()
    await reddit_scraper.close()
    await fear_greed_scraper.close()
    await db.close()

    global redis_client
    if redis_client:
        await redis_client.aclose()
    logger.info("sentiment_service_stopped")


app = FastAPI(title="Sentiment Analysis Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "sentiment-analysis",
        "nlp_loaded": nlp_analyzer.is_loaded,
    }


@app.get("/sentiment/{symbol}")
async def get_sentiment(symbol: str):
    """Get aggregated sentiment for a specific symbol."""
    r = await _get_redis()
    # Try exact match first, then with /USDT suffix
    data = await r.get(f"sentiment:{symbol}")
    if not data and "/" not in symbol:
        data = await r.get(f"sentiment:{symbol}/USDT")
    if data:
        return json.loads(data)
    return {"symbol": symbol, "score": 0.0, "sample_count": 0, "message": "no data"}


@app.get("/sentiment")
async def get_all_sentiment():
    """Get aggregated sentiment for all tracked symbols."""
    r = await _get_redis()
    results = {}
    # Scan for sentiment keys
    async for key in r.scan_iter(match="sentiment:*"):
        data = await r.get(key)
        if data:
            parsed = json.loads(data)
            symbol = parsed.get("symbol", key.replace("sentiment:", ""))
            results[symbol] = parsed
    return results


@app.get("/news")
async def get_news(limit: int = 50):
    """Get recent news items with sentiment labels."""
    items = recent_news[-limit:] if recent_news else []
    return {"items": list(reversed(items)), "count": len(items)}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type="text/plain; charset=utf-8")
