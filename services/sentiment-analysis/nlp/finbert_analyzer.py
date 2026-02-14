"""
FinBERT sentiment analyzer - uses ProsusAI/finbert for financial text analysis.
"""
from typing import List, Optional

import structlog
import torch
from pydantic import BaseModel

logger = structlog.get_logger()

MODEL_NAME = "ProsusAI/finbert"
BATCH_SIZE = 32


class SentimentResult(BaseModel):
    label: str  # 'positive', 'negative', 'neutral'
    score: float  # confidence score 0.0 to 1.0


class FinBERTAnalyzer:
    """Loads FinBERT model once and provides batch inference."""

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._device: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    async def load(self):
        """Load the FinBERT model and tokenizer. Call once at startup."""
        if self._model is not None:
            return

        logger.info("finbert_loading", model=MODEL_NAME)
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            self._model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)

            # Auto-detect GPU/CPU
            if torch.cuda.is_available():
                self._device = "cuda"
                self._model = self._model.to("cuda")
                logger.info("finbert_loaded", device="cuda")
            else:
                self._device = "cpu"
                logger.info("finbert_loaded", device="cpu")

            self._model.eval()
        except Exception as e:
            logger.error("finbert_load_error", error=str(e))
            raise

    def _label_from_index(self, idx: int) -> str:
        """Map model output index to label. FinBERT: 0=positive, 1=negative, 2=neutral."""
        labels = ["positive", "negative", "neutral"]
        return labels[idx] if idx < len(labels) else "neutral"

    async def analyze(self, texts: List[str]) -> List[SentimentResult]:
        """Run batch inference on a list of cleaned text strings.

        Args:
            texts: List of preprocessed text strings.

        Returns:
            List of SentimentResult with label and confidence score.
        """
        if not self.is_loaded:
            await self.load()

        if not texts:
            return []

        results: List[SentimentResult] = []

        # Process in batches
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            try:
                inputs = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                if self._device == "cuda":
                    inputs = {k: v.to("cuda") for k, v in inputs.items()}

                with torch.no_grad():
                    outputs = self._model(**inputs)

                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
                predictions = torch.argmax(probs, dim=-1)

                for j in range(len(batch)):
                    label_idx = predictions[j].item()
                    confidence = probs[j][label_idx].item()
                    results.append(
                        SentimentResult(
                            label=self._label_from_index(label_idx),
                            score=round(confidence, 4),
                        )
                    )

            except Exception as e:
                logger.error("finbert_batch_error", batch_start=i, error=str(e))
                # Fill with neutral for failed batch
                for _ in batch:
                    results.append(SentimentResult(label="neutral", score=0.0))

        logger.info("finbert_analyzed", count=len(results))
        return results

    async def analyze_single(self, text: str) -> SentimentResult:
        """Analyze a single text string."""
        results = await self.analyze([text])
        return results[0] if results else SentimentResult(label="neutral", score=0.0)
