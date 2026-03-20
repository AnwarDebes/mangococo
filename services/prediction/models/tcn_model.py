"""
Temporal Convolutional Network (TCN) for time-series price prediction.

Architecture:
  Input -> [TCNBlock(dilation=1)] -> [TCNBlock(dilation=2)] -> [TCNBlock(dilation=4)]
        -> GlobalAvgPool -> FC(64) -> FC(3)

Each TCNBlock: dilated causal conv -> batch norm -> ReLU -> dropout -> residual add
Output: 3-class (up / down / neutral) with softmax probabilities.
"""

import os
from typing import Tuple, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

class CausalConv1d(nn.Module):
    """1-D causal convolution with left-padding so output length == input length."""

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, dilation: int):
        super().__init__()
        self.padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels, out_channels,
            kernel_size=kernel_size,
            dilation=dilation,
            padding=0,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Left-pad for causal behaviour
        x = F.pad(x, (self.padding, 0))
        return self.conv(x)


class TCNBlock(nn.Module):
    """Single TCN residual block: causal conv -> BN -> ReLU -> dropout."""

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, dilation: int, dropout: float = 0.2):
        super().__init__()
        self.causal_conv = CausalConv1d(in_channels, out_channels, kernel_size, dilation)
        self.batch_norm = nn.BatchNorm1d(out_channels)
        self.dropout = nn.Dropout(dropout)

        # 1x1 conv for residual if channel dimensions differ
        self.residual_conv = (
            nn.Conv1d(in_channels, out_channels, kernel_size=1)
            if in_channels != out_channels
            else nn.Identity()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = self.residual_conv(x)
        out = self.causal_conv(x)
        out = self.batch_norm(out)
        out = F.relu(out)
        out = self.dropout(out)
        return F.relu(out + residual)


class TCNNetwork(nn.Module):
    """
    Deep TCN with multi-scale dilations, attention pooling, and 3-layer classification head.

    Scaled for V100 GPU with 32GB VRAM. Uses 6 TCN blocks with dilations
    up to 32 (receptive field = 189 timesteps at kernel_size=3).

    Parameters
    ----------
    n_features : int
        Number of input features per timestep.
    hidden_channels : int
        Channel width of every TCN block (default 256 for V100).
    n_classes : int
        Number of output classes (default 3: up, down, neutral).
    kernel_size : int
        Convolution kernel size (default 3).
    dropout : float
        Dropout rate inside TCN blocks (default 0.15).
    """

    def __init__(
        self,
        n_features: int,
        hidden_channels: int = 256,
        n_classes: int = 3,
        kernel_size: int = 3,
        dropout: float = 0.15,
    ):
        super().__init__()
        # 6-block architecture: dilations 1,2,4,8,16,32 for massive receptive field
        self.blocks = nn.Sequential(
            TCNBlock(n_features, hidden_channels, kernel_size, dilation=1, dropout=dropout),
            TCNBlock(hidden_channels, hidden_channels, kernel_size, dilation=2, dropout=dropout),
            TCNBlock(hidden_channels, hidden_channels, kernel_size, dilation=4, dropout=dropout),
            TCNBlock(hidden_channels, hidden_channels, kernel_size, dilation=8, dropout=dropout),
            TCNBlock(hidden_channels, hidden_channels, kernel_size, dilation=16, dropout=dropout),
            TCNBlock(hidden_channels, hidden_channels, kernel_size, dilation=32, dropout=dropout),
        )
        # Attention-weighted pooling instead of simple average
        self.attn = nn.Linear(hidden_channels, 1)
        # Deeper classification head
        self.fc1 = nn.Linear(hidden_channels, hidden_channels)
        self.fc2 = nn.Linear(hidden_channels, hidden_channels // 2)
        self.fc3 = nn.Linear(hidden_channels // 2, n_classes)
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(hidden_channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Parameters
        ----------
        x : Tensor of shape (batch, timesteps, features)

        Returns
        -------
        logits : Tensor of shape (batch, n_classes)
        """
        # Conv1d expects (batch, channels, length)
        x = x.transpose(1, 2)
        x = self.blocks(x)
        # Attention-weighted pooling: learn which timesteps matter most
        x = x.transpose(1, 2)  # (batch, length, channels)
        attn_weights = torch.softmax(self.attn(x), dim=1)  # (batch, length, 1)
        x = (x * attn_weights).sum(dim=1)  # (batch, channels)
        x = self.layer_norm(x)
        x = F.gelu(self.fc1(x))
        x = self.dropout(x)
        x = F.gelu(self.fc2(x))
        x = self.dropout(x)
        return self.fc3(x)


# ---------------------------------------------------------------------------
# High-level wrapper used by the prediction service
# ---------------------------------------------------------------------------

DIRECTION_MAP = {0: "up", 1: "down", 2: "neutral"}

# ---------------------------------------------------------------------------
# Multi-timeframe TCN configuration
# ---------------------------------------------------------------------------

TCN_VARIANTS = [
    {"name": "tcn_micro",  "seq_length": 15,  "hidden_channels": 128, "description": "Sub-minute momentum"},
    {"name": "tcn_short",  "seq_length": 30,  "hidden_channels": 192, "description": "2-5 min scalping"},
    {"name": "tcn_medium", "seq_length": 60,  "hidden_channels": 256, "description": "5-15 min swing (primary)"},
    {"name": "tcn_long",   "seq_length": 120, "hidden_channels": 256, "description": "15-60 min trend following"},
]


class TCNModel:
    """High-level wrapper around :class:`TCNNetwork` for inference and persistence."""

    def __init__(self, n_features: int = 20, hidden_channels: int = 256, n_classes: int = 3):
        self.n_features = n_features
        self.hidden_channels = hidden_channels
        self.n_classes = n_classes
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.network: Optional[TCNNetwork] = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def _ensure_network(self) -> TCNNetwork:
        if self.network is None:
            self.network = TCNNetwork(
                n_features=self.n_features,
                hidden_channels=self.hidden_channels,
                n_classes=self.n_classes,
            ).to(self.device)
        return self.network

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, feature_sequence: np.ndarray) -> Tuple[str, float]:
        """
        Run inference on a feature sequence.

        Parameters
        ----------
        feature_sequence : ndarray of shape (timesteps, n_features)
            Typically 60 timesteps x N features.

        Returns
        -------
        direction : str
            One of ``"up"``, ``"down"``, ``"neutral"``.
        confidence : float
            Softmax probability of the winning class (0-1).
        """
        net = self._ensure_network()
        net.eval()

        tensor = torch.tensor(feature_sequence, dtype=torch.float32).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = net(tensor)
            probs = F.softmax(logits, dim=1).squeeze(0).cpu().numpy()

        predicted_class = int(np.argmax(probs))
        confidence = float(probs[predicted_class])
        direction = DIRECTION_MAP.get(predicted_class, "neutral")

        return direction, confidence

    def predict_batch(self, sequences: list) -> list:
        """
        Batched GPU inference — processes all sequences in a single forward pass.

        Parameters
        ----------
        sequences : list of ndarray, each of shape (timesteps, n_features)

        Returns
        -------
        list of (direction, confidence) tuples
        """
        if not sequences:
            return []

        net = self._ensure_network()
        net.eval()

        stacked = np.stack(sequences, axis=0)  # (N, timesteps, features)
        tensor = torch.tensor(stacked, dtype=torch.float32).to(self.device)

        with torch.no_grad():
            logits = net(tensor)
            probs = F.softmax(logits, dim=1).cpu().numpy()  # (N, n_classes)

        classes = np.argmax(probs, axis=1)
        results = []
        for i in range(len(classes)):
            cls = int(classes[i])
            conf = float(probs[i, cls])
            direction = DIRECTION_MAP.get(cls, "neutral")
            results.append((direction, conf))
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str) -> None:
        """Load model weights from a ``.pt`` file."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"TCN weights not found: {path}")

        state = torch.load(path, map_location=self.device, weights_only=True)

        # Adapt to model architecture stored in checkpoint (supports dynamic hidden_channels)
        if "hidden_channels" in state and state["hidden_channels"] != self.hidden_channels:
            self.hidden_channels = state["hidden_channels"]
            self.network = None  # Force re-creation with new dimensions
        if "n_features" in state and state["n_features"] != self.n_features:
            self.n_features = state["n_features"]
            self.network = None

        net = self._ensure_network()

        # Support both raw state_dict and wrapped checkpoint dicts
        if "model_state_dict" in state:
            net.load_state_dict(state["model_state_dict"])
        else:
            net.load_state_dict(state)

        self._loaded = True
        logger.info("TCN model loaded", path=path, device=str(self.device),
                     hidden_channels=self.hidden_channels)

    def save(self, path: str) -> None:
        """Save model weights to a ``.pt`` file."""
        net = self._ensure_network()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save(
            {
                "model_state_dict": net.state_dict(),
                "n_features": self.n_features,
                "hidden_channels": self.hidden_channels,
                "n_classes": self.n_classes,
            },
            path,
        )
        logger.info("TCN model saved", path=path)


# ---------------------------------------------------------------------------
# Multi-Timeframe TCN Ensemble
# ---------------------------------------------------------------------------

class MultiTCNEnsemble:
    """Manages multiple TCN models with different sequence lengths and architectures.

    Each variant captures patterns at a different time horizon. The ensemble
    combines their predictions with configurable weights for richer signals.
    """

    def __init__(self):
        self.models: dict[str, TCNModel] = {}
        self.variant_configs: dict[str, dict] = {}
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return any(m.is_loaded for m in self.models.values())

    def initialize_variants(self, model_dir: str) -> None:
        """Create and load TCN variants from the model directory.

        For each variant, tries to load a variant-specific checkpoint
        (e.g., tcn_short_latest.pt). Falls back to loading the primary
        model (tcn_latest.pt) into all variants — the different sequence
        lengths still provide diversity even with shared weights.
        """
        primary_path = os.path.join(model_dir, "tcn_latest.pt")

        for variant in TCN_VARIANTS:
            name = variant["name"]
            hc = variant["hidden_channels"]
            self.variant_configs[name] = variant

            model = TCNModel(n_features=20, hidden_channels=hc)

            # Try variant-specific checkpoint first
            variant_path = os.path.join(model_dir, f"{name}_latest.pt")
            if os.path.isfile(variant_path):
                try:
                    model.load(variant_path)
                    logger.info("Multi-TCN variant loaded", variant=name, path=variant_path)
                    self.models[name] = model
                    continue
                except Exception as e:
                    logger.warning("Failed to load variant checkpoint", variant=name, error=str(e))

            # Fall back to primary model (with matching hidden_channels)
            if os.path.isfile(primary_path):
                try:
                    model.load(primary_path)
                    logger.info("Multi-TCN variant loaded from primary", variant=name,
                                hidden_channels=hc)
                    self.models[name] = model
                except Exception as e:
                    logger.warning("Failed to load primary model for variant",
                                    variant=name, error=str(e))
            else:
                logger.info("No model file for variant", variant=name)

        loaded = [n for n, m in self.models.items() if m.is_loaded]
        logger.info("Multi-TCN ensemble initialized",
                     total_variants=len(TCN_VARIANTS),
                     loaded=len(loaded),
                     variants=loaded)

    def predict_all(self, feature_matrix: np.ndarray) -> list[tuple[str, str, float]]:
        """Run inference across all loaded variants for a single symbol.

        Parameters
        ----------
        feature_matrix : ndarray of shape (N, n_features)
            Full feature matrix from which each variant slices its sequence.

        Returns
        -------
        list of (variant_name, direction, confidence) tuples
        """
        results = []
        for name, model in self.models.items():
            if not model.is_loaded:
                continue
            seq_len = self.variant_configs[name]["seq_length"]
            if len(feature_matrix) < seq_len:
                continue
            sequence = feature_matrix[-seq_len:]
            try:
                direction, confidence = model.predict(sequence)
                results.append((name, direction, confidence))
            except Exception as e:
                logger.debug("Variant prediction failed", variant=name, error=str(e))
        return results

    def predict_batch_all(self, feature_matrices: dict[str, np.ndarray]) -> dict[str, list[tuple[str, str, float]]]:
        """Batched inference across all variants for multiple symbols.

        Parameters
        ----------
        feature_matrices : dict mapping symbol -> feature_matrix (N, n_features)

        Returns
        -------
        dict mapping symbol -> list of (variant_name, direction, confidence)
        """
        all_results: dict[str, list[tuple[str, str, float]]] = {sym: [] for sym in feature_matrices}

        for name, model in self.models.items():
            if not model.is_loaded:
                continue
            seq_len = self.variant_configs[name]["seq_length"]

            # Collect sequences for this variant
            batch_syms = []
            batch_seqs = []
            for sym, feat_mat in feature_matrices.items():
                if len(feat_mat) >= seq_len:
                    batch_syms.append(sym)
                    batch_seqs.append(feat_mat[-seq_len:])

            if not batch_seqs:
                continue

            try:
                batch_preds = model.predict_batch(batch_seqs)
                for sym, (direction, confidence) in zip(batch_syms, batch_preds):
                    all_results[sym].append((name, direction, confidence))
            except Exception as e:
                logger.warning("Variant batch prediction failed", variant=name, error=str(e))

        return all_results

    def reload(self, model_dir: str) -> None:
        """Reload all variant models (called on hot-reload signal)."""
        self.models.clear()
        self.variant_configs.clear()
        self.initialize_variants(model_dir)
