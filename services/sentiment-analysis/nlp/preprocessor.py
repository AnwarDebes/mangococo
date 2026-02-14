"""
Text preprocessor for NLP pipeline - cleans and deduplicates text inputs.
"""
import re
from difflib import SequenceMatcher
from typing import List, Tuple

import structlog

logger = structlog.get_logger()

# Regex patterns for cleaning
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")
MENTION_PATTERN = re.compile(r"@\w+")
HASHTAG_PATTERN = re.compile(r"#\w+")
EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    r"\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251"
    r"\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
    r"\U00002600-\U000026FF\U00002700-\U000027BF]+",
    flags=re.UNICODE,
)
WHITESPACE_PATTERN = re.compile(r"\s+")

# FinBERT max token limit
MAX_TOKENS = 512
# Approximate chars per token for English text
CHARS_PER_TOKEN = 4
MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

# Deduplication threshold (0.0 to 1.0)
SIMILARITY_THRESHOLD = 0.85


class TextPreprocessor:
    """Cleans, normalizes, and deduplicates text for FinBERT analysis."""

    def clean(self, text: str) -> str:
        """Clean a single text string for NLP processing."""
        # Remove URLs
        text = URL_PATTERN.sub("", text)
        # Remove mentions
        text = MENTION_PATTERN.sub("", text)
        # Remove hashtags (keep the word without #)
        text = HASHTAG_PATTERN.sub(lambda m: m.group(0)[1:], text)
        # Remove emojis
        text = EMOJI_PATTERN.sub("", text)
        # Normalize whitespace
        text = WHITESPACE_PATTERN.sub(" ", text).strip()
        # Truncate to approximate FinBERT token limit
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
        return text

    def deduplicate(self, texts: List[str]) -> List[str]:
        """Remove near-duplicate texts using fuzzy matching."""
        if not texts:
            return []

        unique: List[str] = []
        for text in texts:
            is_dup = False
            for existing in unique:
                similarity = SequenceMatcher(None, text[:200], existing[:200]).ratio()
                if similarity >= SIMILARITY_THRESHOLD:
                    is_dup = True
                    break
            if not is_dup:
                unique.append(text)

        removed = len(texts) - len(unique)
        if removed > 0:
            logger.info("text_dedup", original=len(texts), unique=len(unique), removed=removed)
        return unique

    def process_batch(self, texts: List[str]) -> List[str]:
        """Clean and deduplicate a batch of texts."""
        cleaned = [self.clean(t) for t in texts if t.strip()]
        # Filter empty strings after cleaning
        cleaned = [t for t in cleaned if len(t) >= 10]
        return self.deduplicate(cleaned)

    def process_with_indices(self, texts: List[str]) -> Tuple[List[str], List[int]]:
        """Clean and deduplicate, returning cleaned texts and their original indices.

        Useful for mapping sentiment results back to original items.
        """
        cleaned_with_idx = []
        for i, text in enumerate(texts):
            c = self.clean(text)
            if len(c) >= 10:
                cleaned_with_idx.append((c, i))

        if not cleaned_with_idx:
            return [], []

        # Deduplicate while tracking indices
        unique_texts: List[str] = []
        unique_indices: List[int] = []
        for text, idx in cleaned_with_idx:
            is_dup = False
            for existing in unique_texts:
                similarity = SequenceMatcher(None, text[:200], existing[:200]).ratio()
                if similarity >= SIMILARITY_THRESHOLD:
                    is_dup = True
                    break
            if not is_dup:
                unique_texts.append(text)
                unique_indices.append(idx)

        return unique_texts, unique_indices
