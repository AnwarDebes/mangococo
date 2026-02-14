"""
Simple file-based model registry backed by a JSON manifest.

Manifest path: ``shared/models/registry.json``

Each entry stores: model_name, version, creation_date, metrics dict, file path.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger()

DEFAULT_REGISTRY_DIR = os.getenv("MODEL_REGISTRY_DIR", "/app/shared/models")
MANIFEST_FILENAME = "registry.json"


@dataclass
class ModelInfo:
    model_name: str
    version: str
    creation_date: str
    metrics: Dict[str, float] = field(default_factory=dict)
    path: str = ""


class ModelRegistry:
    """Manages model versions stored on disk with a JSON manifest."""

    def __init__(self, registry_dir: Optional[str] = None):
        self.registry_dir = registry_dir or DEFAULT_REGISTRY_DIR
        self.manifest_path = os.path.join(self.registry_dir, MANIFEST_FILENAME)
        self._entries: List[ModelInfo] = []
        self._load_manifest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        model_name: str,
        version: str,
        metrics: Dict[str, float],
        path: str,
    ) -> ModelInfo:
        """Register a new model version."""
        info = ModelInfo(
            model_name=model_name,
            version=version,
            creation_date=datetime.now(timezone.utc).isoformat(),
            metrics=metrics,
            path=path,
        )
        self._entries.append(info)
        self._save_manifest()
        logger.info("Model registered", model_name=model_name, version=version, path=path)
        return info

    def get_latest(self, model_name: str) -> Optional[ModelInfo]:
        """Return the most recently registered version for *model_name*."""
        candidates = [e for e in self._entries if e.model_name == model_name]
        if not candidates:
            return None
        # Sort by creation_date descending
        candidates.sort(key=lambda e: e.creation_date, reverse=True)
        return candidates[0]

    def list_versions(self, model_name: str) -> List[ModelInfo]:
        """List all registered versions for *model_name*, newest first."""
        candidates = [e for e in self._entries if e.model_name == model_name]
        candidates.sort(key=lambda e: e.creation_date, reverse=True)
        return candidates

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_manifest(self) -> None:
        if not os.path.isfile(self.manifest_path):
            self._entries = []
            return
        try:
            with open(self.manifest_path, "r") as fh:
                raw = json.load(fh)
            self._entries = [ModelInfo(**item) for item in raw]
        except Exception as exc:
            logger.warning("Failed to load model registry manifest", error=str(exc))
            self._entries = []

    def _save_manifest(self) -> None:
        os.makedirs(self.registry_dir, exist_ok=True)
        with open(self.manifest_path, "w") as fh:
            json.dump([asdict(e) for e in self._entries], fh, indent=2)
