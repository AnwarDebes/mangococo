"""
Reddit scraper - monitors crypto subreddits for sentiment data.
"""
import os
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "mangococo-sentiment/1.0")

MONITORED_SUBREDDITS = [
    "cryptocurrency",
    "bitcoin",
    "ethereum",
    "solana",
    "altcoins",
]

# Coin name/symbol patterns for mention detection
COIN_PATTERNS = {
    "BTC/USDT": [r"\bbitcoin\b", r"\bbtc\b"],
    "ETH/USDT": [r"\bethereum\b", r"\beth\b"],
    "SOL/USDT": [r"\bsolana\b", r"\bsol\b"],
    "BNB/USDT": [r"\bbnb\b", r"\bbinance\s+coin\b"],
    "XRP/USDT": [r"\bxrp\b", r"\bripple\b"],
    "ADA/USDT": [r"\bcardano\b", r"\bada\b"],
    "DOGE/USDT": [r"\bdogecoin\b", r"\bdoge\b"],
    "AVAX/USDT": [r"\bavalanche\b", r"\bavax\b"],
    "DOT/USDT": [r"\bpolkadot\b", r"\bdot\b"],
    "MATIC/USDT": [r"\bpolygon\b", r"\bmatic\b"],
    "LINK/USDT": [r"\bchainlink\b", r"\blink\b"],
    "ARB/USDT": [r"\barbitrum\b", r"\barb\b"],
    "OP/USDT": [r"\boptimism\b"],
    "NEAR/USDT": [r"\bnear\s+protocol\b", r"\bnear\b"],
    "SUI/USDT": [r"\bsui\b"],
    "APT/USDT": [r"\baptos\b", r"\bapt\b"],
}


class SocialPost(BaseModel):
    text: str
    symbol: str
    source: str
    timestamp: datetime
    score: int = 0


def _detect_symbols(text: str) -> List[str]:
    """Detect coin mentions in text, return list of trading pair symbols."""
    text_lower = text.lower()
    found = []
    for pair, patterns in COIN_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                found.append(pair)
                break
    return found


class RedditScraper:
    """Monitors crypto subreddits using asyncpraw."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self.client_id = client_id or REDDIT_CLIENT_ID
        self.client_secret = client_secret or REDDIT_CLIENT_SECRET
        self.user_agent = user_agent or REDDIT_USER_AGENT
        self._reddit = None

    async def _get_reddit(self):
        if self._reddit is None:
            try:
                import asyncpraw

                self._reddit = asyncpraw.Reddit(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    user_agent=self.user_agent,
                )
            except ImportError:
                logger.error("reddit_import_error", msg="asyncpraw not installed")
                return None
        return self._reddit

    async def close(self):
        if self._reddit is not None:
            await self._reddit.close()
            self._reddit = None

    async def fetch(self) -> List[SocialPost]:
        """Fetch hot posts and top comments from monitored subreddits."""
        if not self.client_id or not self.client_secret:
            logger.warning("reddit_no_credentials", msg="Reddit API credentials not set, skipping")
            return []

        reddit = await self._get_reddit()
        if reddit is None:
            return []

        posts: List[SocialPost] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        for sub_name in MONITORED_SUBREDDITS:
            try:
                subreddit = await reddit.subreddit(sub_name)
                async for submission in subreddit.hot(limit=25):
                    created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
                    if created < cutoff:
                        continue

                    full_text = f"{submission.title} {submission.selftext or ''}"
                    symbols = _detect_symbols(full_text)

                    for symbol in symbols:
                        posts.append(
                            SocialPost(
                                text=full_text[:2000],
                                symbol=symbol,
                                source=f"reddit/r/{sub_name}",
                                timestamp=created,
                                score=submission.score,
                            )
                        )

                    # Fetch top comments
                    submission.comment_sort = "top"
                    await submission.load()
                    comments = submission.comments[:10]
                    for comment in comments:
                        if not hasattr(comment, "body"):
                            continue
                        comment_symbols = _detect_symbols(comment.body)
                        comment_created = datetime.fromtimestamp(
                            comment.created_utc, tz=timezone.utc
                        )
                        for symbol in comment_symbols:
                            posts.append(
                                SocialPost(
                                    text=comment.body[:2000],
                                    symbol=symbol,
                                    source=f"reddit/r/{sub_name}/comment",
                                    timestamp=comment_created,
                                    score=comment.score,
                                )
                            )

                logger.info("reddit_subreddit_fetched", subreddit=sub_name, posts=len(posts))
            except Exception as e:
                logger.error("reddit_subreddit_error", subreddit=sub_name, error=str(e))

        logger.info("reddit_total_fetched", count=len(posts))
        return posts
