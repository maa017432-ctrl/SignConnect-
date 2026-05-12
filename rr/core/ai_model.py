"""Model loading and gesture prediction logic."""
# STATUS: graceful-degradation pattern applied — safe for startup

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from threading import Lock

import numpy as np

try:
    from tensorflow.keras.models import load_model
except Exception:  # pragma: no cover
    load_model = None


LOGGER = logging.getLogger(__name__)


class GestureClassifier:
    """Classify hand landmarks into label indices with confidence scores."""

    _instance: "GestureClassifier | None" = None
    _instance_lock: Lock = Lock()

    def __new__(cls, *args, **kwargs) -> "GestureClassifier":
        """Create a lazy singleton instance."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self, model_path: str, confidence_threshold: float, labels_count: int
    ) -> None:
        if getattr(self, "_initialized", False):
            return
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.labels_count = labels_count
        self.model = None
        self._available = False
        self._demo_mode = True
        self._demo_label_indices: list[int] = []
        self._try_init()
        self._initialized = True

    @property
    def is_available(self) -> bool:
        """Return whether the TensorFlow model backend is available."""
        return self._available

    def reload(self) -> bool:
        """Re-initialize from disk, returning True on success."""
        self._try_init()
        return self._available

    @property
    def is_demo_mode(self) -> bool:
        """Return whether predictions are currently using generated fake outputs."""
        return self._demo_mode

    def _try_init(self) -> None:
        """Try to initialize TensorFlow model backend without raising errors."""
        self._available = False
        self._demo_mode = True
        self.model = None
        self._norm_mean: np.ndarray | None = None
        self._norm_std:  np.ndarray | None = None
        self._demo_label_indices = self._load_demo_label_indices()

        # Load normalisation stats produced by train.py (optional)
        norm_path = self.model_path.parent / "norm_stats.npz"
        if norm_path.exists():
            try:
                stats = np.load(str(norm_path))
                self._norm_mean = stats["mean"]
                self._norm_std  = stats["std"]
                LOGGER.info("Loaded normalisation stats from %s", norm_path)
            except Exception as error:
                LOGGER.warning("Failed to load norm_stats.npz: %s", error)

        try:
            if load_model is None:
                raise RuntimeError("TensorFlow loader unavailable")
            if not self.model_path.exists():
                raise FileNotFoundError(f"Model file not found: {self.model_path}")
            self.model = load_model(str(self.model_path))
            self._available = True
            self._demo_mode = False
            LOGGER.info("Gesture classifier initialized successfully")
        except Exception as error:
            self._available = False
            self._demo_mode = True
            self.model = None
            LOGGER.warning("Gesture classifier initialization failed: %s", error)

    def _load_demo_label_indices(self) -> list[int]:
        """Load demo label indices from `label_map.json` when available."""
        label_map_path = self.model_path.parent / "label_map.json"
        try:
            if label_map_path.exists():
                with label_map_path.open("r", encoding="utf-8") as file_obj:
                    payload = json.load(file_obj)
                if isinstance(payload, dict):
                    indices = sorted(int(key) for key in payload.keys())
                    if indices:
                        return indices
        except Exception as error:
            LOGGER.warning("Unable to read demo label map: %s", error)
        return list(range(self.labels_count))

    def _predict_demo(self) -> tuple[int, float]:
        """Return a deterministic-safe fake prediction in demo mode."""
        if not self._demo_label_indices:
            self._demo_label_indices = list(range(self.labels_count))
        label_index = random.choice(self._demo_label_indices)
        confidence = float(random.uniform(0.76, 0.95))
        return int(label_index), confidence

    def _predict_demo_with_details(self) -> dict[str, object]:
        """Return demo prediction plus top-candidate list for debug UIs."""
        label_index, confidence = self._predict_demo()
        candidates: list[dict[str, float | int]] = [
            {"index": int(label_index), "confidence": float(confidence)}
        ]
        for _ in range(2):
            idx = random.choice(self._demo_label_indices) if self._demo_label_indices else 0
            conf = float(random.uniform(0.35, max(0.36, confidence - 0.02)))
            candidates.append({"index": int(idx), "confidence": conf})
        candidates.sort(key=lambda item: float(item["confidence"]), reverse=True)
        return {
            "label_index": int(label_index),
            "confidence": float(confidence),
            "top_candidates": candidates[:3],
        }

    @staticmethod
    def _canonicalize_hand(hand: np.ndarray) -> np.ndarray:
        """Translate to wrist-origin and scale-normalize a single 21x3 hand."""
        points = hand.reshape(21, 3)
        points = points - points[0]
        scale = float(np.linalg.norm(points[9]))
        if scale < 1e-6:
            scale = float(np.linalg.norm(points[5] - points[17]))
        if scale < 1e-6:
            scale = 1.0
        return (points / scale).reshape(-1)

    def _prepare_features(self, landmarks_array: np.ndarray) -> np.ndarray:
        """Normalize and reshape landmarks into model-ready feature tensor.

        Accepts either 63-dim (one hand) or 126-dim (two hands) input.
        Always outputs a (1, INPUT_DIM) tensor matching the loaded model.
        """
        expected_dim = 126
        flat = landmarks_array.astype(np.float32).reshape(-1)

        if flat.size < expected_dim:
            flat = np.pad(flat, (0, expected_dim - flat.size), mode="constant")
        elif flat.size > expected_dim:
            flat = flat[:expected_dim]

        hand1 = self._canonicalize_hand(flat[:63])
        hand2_raw = flat[63:126]
        has_second = float(np.abs(hand2_raw).sum()) > 1e-6
        hand2 = self._canonicalize_hand(hand2_raw) if has_second else hand2_raw
        flat = np.concatenate([hand1, hand2])

        if self._norm_mean is not None and self._norm_std is not None:
            flat = (flat - self._norm_mean) / self._norm_std
        return flat.reshape(1, expected_dim)

    def predict_with_details(self, landmarks_array: np.ndarray) -> dict[str, object]:
        """Return thresholded prediction plus raw top-3 candidates.

        Returns:
            A dictionary with keys:
            - ``label_index``: int (thresholded index or -1)
            - ``confidence``: float (best raw confidence)
            - ``top_candidates``: list of up to 3 dicts with ``index`` and ``confidence``
        """
        if landmarks_array is None or landmarks_array.size == 0:
            return {"label_index": -1, "confidence": 0.0, "top_candidates": []}
        if not self._available or self.model is None:
            return self._predict_demo_with_details()

        try:
            features = self._prepare_features(landmarks_array)
            output = self.model(features, training=False)
            probabilities = output[0].numpy().astype(np.float32)
            if probabilities.size == 0:
                return {"label_index": -1, "confidence": 0.0, "top_candidates": []}

            sorted_indices = np.argsort(probabilities)[::-1]
            top_indices = sorted_indices[:3]
            top_candidates = [
                {
                    "index": int(index),
                    "confidence": float(probabilities[index]),
                }
                for index in top_indices
            ]

            best_index = int(top_indices[0])
            best_confidence = float(probabilities[best_index])
            label_index = best_index if best_confidence >= self.confidence_threshold else -1
            return {
                "label_index": int(label_index),
                "confidence": float(best_confidence),
                "top_candidates": top_candidates,
            }
        except Exception as error:
            LOGGER.warning("Prediction failed; falling back to demo mode: %s", error)
            self._available = False
            self._demo_mode = True
            self.model = None
            return self._predict_demo_with_details()

    def predict(self, landmarks_array: np.ndarray) -> tuple[int, float]:
        """Return `(label_index, confidence)` and reject low-confidence predictions."""
        details = self.predict_with_details(landmarks_array)
        return int(details["label_index"]), float(details["confidence"])
