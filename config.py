"""Application configuration values for SignConnect."""

from __future__ import annotations

import os
from pathlib import Path

from model_contract import (
    DEFAULT_MODEL_TYPE,
    MODEL_INPUT_DIM,
    SEQUENCE_LENGTH,
    SUPPORTED_MODEL_TYPES,
)

_DEFAULT_SECRET = "change-me-in-production"


class Config:
    """Centralized configuration loaded from environment variables."""

    def __init__(self) -> None:
        root_dir = Path(__file__).resolve().parent
        self.SECRET_KEY = os.getenv("SECRET_KEY", _DEFAULT_SECRET)
        self.DEBUG = os.getenv("DEBUG", "false").lower() == "true"
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        self.SESSION_COOKIE_SECURE = not self.DEBUG

        # ── Security: fail hard if running in production with the default key ──
        if not self.DEBUG and self.SECRET_KEY == _DEFAULT_SECRET:
            raise RuntimeError(
                "\n[FATAL] SECRET_KEY is set to the insecure default value.\n"
                "Set a strong SECRET_KEY in your .env file before running in production.\n"
            )

        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "5000"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

        # ── CORS: restrict to specific origins (comma-separated in ALLOWED_ORIGINS) ──
        origins_env = os.getenv("ALLOWED_ORIGINS", "")
        if origins_env:
            self.ALLOWED_ORIGINS: list[str] | str = [
                o.strip() for o in origins_env.split(",") if o.strip()
            ]
        else:
            # Safe default: only allow local dev origins
            self.ALLOWED_ORIGINS = [
                "http://localhost:5000",
                "http://127.0.0.1:5000",
            ]

        # ── API key for admin-level endpoints (delete history, update config) ──
        # Leave blank in dev to skip the check; set in production .env
        self.API_KEY = os.getenv("API_KEY", "")
        if not self.DEBUG and not self.API_KEY:
            raise RuntimeError(
                "\n[FATAL] API_KEY is required for production admin endpoints.\n"
                "Set API_KEY in your .env file before running in production.\n"
            )

        self.CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
        self.MODEL_INPUT_DIM = int(os.getenv("MODEL_INPUT_DIM", str(MODEL_INPUT_DIM)))
        if self.MODEL_INPUT_DIM != MODEL_INPUT_DIM:
            raise RuntimeError(
                f"\n[FATAL] MODEL_INPUT_DIM must be {MODEL_INPUT_DIM} for the "
                "current MediaPipe landmark pipeline.\n"
            )
        self.MODEL_TYPE = os.getenv("MODEL_TYPE", DEFAULT_MODEL_TYPE).strip().lower()
        if self.MODEL_TYPE not in SUPPORTED_MODEL_TYPES:
            raise RuntimeError(
                f"\n[FATAL] MODEL_TYPE must be one of {SUPPORTED_MODEL_TYPES}.\n"
            )
        self.SEQUENCE_LENGTH = int(os.getenv("SEQUENCE_LENGTH", str(SEQUENCE_LENGTH)))
        if self.SEQUENCE_LENGTH <= 0:
            raise RuntimeError(
                "\n[FATAL] SEQUENCE_LENGTH must be a positive integer.\n"
            )
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
