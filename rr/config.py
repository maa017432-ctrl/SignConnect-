"""Application configuration values for SignConnect."""

from __future__ import annotations

import os
from pathlib import Path


class Config:
    """Centralized configuration loaded from environment variables."""

    def __init__(self) -> None:
        root_dir = Path(__file__).resolve().parent
        self.SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
        self.DEBUG = os.getenv("DEBUG", "false").lower() == "true"
        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "5000"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

        self.CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
        self.MODEL_INPUT_SIZE = int(os.getenv("MODEL_INPUT_SIZE", "64"))
        self.PREDICTION_CONFIDENCE_THRESHOLD = float(
            os.getenv("PREDICTION_CONFIDENCE_THRESHOLD", "0.75")
        )
        self.MP_MIN_DETECTION_CONFIDENCE = float(
            os.getenv("MP_MIN_DETECTION_CONFIDENCE", "0.5")
        )
        self.MP_MIN_TRACKING_CONFIDENCE = float(
            os.getenv("MP_MIN_TRACKING_CONFIDENCE", "0.5")
        )
        self.LABELS_COUNT = int(os.getenv("LABELS_COUNT", "31"))

        self.DATABASE_PATH = str(root_dir / "database" / "signconnect.db")
        self.SCHEMA_PATH = str(root_dir / "database" / "schema.sql")
        self.MODEL_PATH = str(root_dir / "models" / "gesture_model.h5")
        self.LABEL_MAP_PATH = str(root_dir / "models" / "label_map.json")
        self.AUDIO_CACHE_DIR = str(root_dir / "static" / "audio")
        self.AUDIO_CACHE_TTL_SECONDS = int(os.getenv("AUDIO_CACHE_TTL_SECONDS", "60"))

        # Prediction smoother
        self.SMOOTHER_WINDOW = int(os.getenv("SMOOTHER_WINDOW", "10"))
        self.SMOOTHER_MIN_FRACTION = float(os.getenv("SMOOTHER_MIN_FRACTION", "0.6"))

        # Sentence builder
        self.SENTENCE_STABLE_FRAMES = int(os.getenv("SENTENCE_STABLE_FRAMES", "15"))
        self.SENTENCE_COOLDOWN_FRAMES = int(os.getenv("SENTENCE_COOLDOWN_FRAMES", "20"))

