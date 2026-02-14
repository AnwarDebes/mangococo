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
    3-block TCN with global average pooling and a 2-layer classification head.

    Parameters
    ----------
    n_features : int
        Number of input features per timestep.
    hidden_channels : int
        Channel width of every TCN block (default 64).
    n_classes : int
        Number of output classes (default 3: up, down, neutral).
    kernel_size : int
        Convolution kernel size (default 3).
    dropout : float
        Dropout rate inside TCN blocks (default 0.2).
    """

    def __init__(
        self,
        n_features: int,
        hidden_channels: int = 64,
        n_classes: int = 3,
        kernel_size: int = 3,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.blocks = nn.Sequential(
            TCNBlock(n_features, hidden_channels, kernel_size, dilation=1, dropout=dropout),
            TCNBlock(hidden_channels, hidden_channels, kernel_size, dilation=2, dropout=dropout),
            TCNBlock(hidden_channels, hidden_channels, kernel_size, dilation=4, dropout=dropout),
        )
        self.fc1 = nn.Linear(hidden_channels, hidden_channels)
        self.fc2 = nn.Linear(hidden_channels, n_classes)
        self.dropout = nn.Dropout(dropout)

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
        # Global average pooling over time dimension
        x = x.mean(dim=2)
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        return self.fc2(x)


# ---------------------------------------------------------------------------
# High-level wrapper used by the prediction service
# ---------------------------------------------------------------------------

DIRECTION_MAP = {0: "up", 1: "down", 2: "neutral"}


class TCNModel:
    """High-level wrapper around :class:`TCNNetwork` for inference and persistence."""

    def __init__(self, n_features: int = 20, hidden_channels: int = 64, n_classes: int = 3):
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

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str) -> None:
        """Load model weights from a ``.pt`` file."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"TCN weights not found: {path}")

        net = self._ensure_network()
        state = torch.load(path, map_location=self.device, weights_only=True)

        # Support both raw state_dict and wrapped checkpoint dicts
        if "model_state_dict" in state:
            net.load_state_dict(state["model_state_dict"])
        else:
            net.load_state_dict(state)

        self._loaded = True
        logger.info("TCN model loaded", path=path, device=str(self.device))

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
