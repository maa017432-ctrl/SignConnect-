"""REST API endpoints for status, translation, and history."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from flask.wrappers import Response

from database.db import get_connection
from routes.stream import _prediction_lock, camera_frame_response


LOGGER = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)

_MAX_TEXT_LEN = 500


def _api_key_ok() -> bool:
    """Return True if the request carries a valid API key, or if no key is configured."""
    if current_app.config.get("DEBUG", False):
        return True
    required = current_app.config.get("API_KEY", "")
    if not required:
        return False
    return request.headers.get("X-API-Key", "") == required


@api_bp.get("/api/status")
def status() -> tuple[dict[str, object], int]:
    """Return runtime health status for core services."""
    camera_manager = current_app.extensions["camera_manager"]
    classifier = current_app.extensions["classifier"]
    tts_engine = current_app.extensions["tts_engine"]
    gesture_detector = current_app.extensions["gesture_detector"]
    camera_frame_route = any(
        rule.rule in ("/camera_frame", "/api/camera_frame")
        for rule in current_app.url_map.iter_rules()
    )
    return (
        jsonify(
            {
                "camera": camera_manager.is_available(),
                "model": classifier.is_available,
                "model_demo_mode": classifier.is_demo_mode,
                "model_type": getattr(classifier, "model_type", "unknown"),
                "model_input_dim": getattr(classifier, "model_input_dim", None),
                "sequence_length": getattr(classifier, "sequence_length", None),
                "label_count": getattr(classifier, "labels_count", None),
                "norm_stats_loaded": getattr(classifier, "has_norm_stats", False),
                "tts": tts_engine.is_available,
                "mediapipe": gesture_detector.is_available,
                "camera_frame_route": camera_frame_route,
            }
        ),
        200,
    )


@api_bp.get("/api/camera_frame")
def api_camera_frame() -> Response:
    """Same JPEG as ``/camera_frame``; use this URL if the root path is blocked or stale."""
    return camera_frame_response()


@api_bp.get("/api/prediction")
def latest_prediction() -> tuple[dict[str, object], int]:
    """Return current gesture prediction, smoothed label, and sentence state."""
    with _prediction_lock:
        payload = dict(current_app.extensions.get("latest_prediction") or {})
    builder = current_app.extensions.get("sentence_builder")
    return (
        jsonify(
            {
                "label": payload.get("label"),
                "confidence": float(payload.get("confidence") or 0.0),
                "smoothed_label": payload.get("smoothed_label"),
                "top_candidates": payload.get("top_candidates") or [],
                "model_type": payload.get("model_type"),
                "inference_ms": payload.get("inference_ms"),
                "sentence": builder.sentence if builder else "",
                "current_run": builder.current_run if builder else 0,
                "stable_frames": builder.stable_frames if builder else 15,
                "is_cooling_down": builder.is_cooling_down if builder else False,
            }
        ),
        200,
    )


@api_bp.post("/api/sentence/delete")
def sentence_delete() -> tuple[dict[str, str], int]:
    """Delete the last word from the sentence builder."""
    builder = current_app.extensions.get("sentence_builder")
    if builder:
        builder.delete_last_word()
    return jsonify({"sentence": builder.sentence if builder else ""}), 200


@api_bp.post("/api/sentence/clear")
def sentence_clear() -> tuple[dict[str, str], int]:
    """Clear the entire sentence and reset the builder state."""
    builder = current_app.extensions.get("sentence_builder")
    smoother = current_app.extensions.get("prediction_smoother")
    if builder:
        builder.clear()
    if smoother:
        smoother.reset()
    classifier = current_app.extensions.get("classifier")
    if classifier and hasattr(classifier, "reset_sequence"):
        classifier.reset_sequence()
    return jsonify({"sentence": ""}), 200


@api_bp.post("/api/translate")
def translate() -> tuple[dict[str, str | int], int]:
    """Convert input text to speech and return audio URL."""
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Missing text", "code": 400}), 400
    if len(text) > _MAX_TEXT_LEN:
        return jsonify({"error": f"Text exceeds {_MAX_TEXT_LEN} character limit", "code": 400}), 400

    lang = str(payload.get("lang", "en")).strip().lower() or "en"

    tts_engine = current_app.extensions["tts_engine"]
    try:
        filename = tts_engine.synthesize(text, lang=lang)
    except ValueError:
        return jsonify({"error": "Invalid text input", "code": 400}), 400
    except RuntimeError:
        return jsonify({"error": "TTS generation failed", "code": 503}), 503

    if filename is None:
        return jsonify({"error": "TTS unavailable or synthesis failed", "code": 503}), 503

    try:
        latest = current_app.extensions.get("latest_prediction") or {}
        confidence = float(latest.get("confidence") or 0.0) or None
        with get_connection(current_app.config["DATABASE_PATH"]) as connection:
            row = connection.execute(
                "SELECT id FROM sessions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                cursor = connection.execute("INSERT INTO sessions (ended_at) VALUES (NULL)")
                session_id = cursor.lastrowid
            else:
                session_id = row["id"]
            connection.execute(
                """
                INSERT INTO translations (session_id, gesture_label, confidence, audio_file)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, text, confidence, filename),
            )
    except Exception:
        LOGGER.exception("Failed to persist translation to database")

    return jsonify({"audio_url": f"/static/audio/{filename}"}), 200


@api_bp.get("/api/history")
def get_history() -> tuple[list[dict[str, str | float | None]], int]:
    """Return latest translation history as JSON list."""
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        rows = connection.execute(
            """
            SELECT id, gesture_label, confidence, audio_file, created_at
            FROM translations
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()

    payload = [
        {
            "id": row["id"],
            "gesture_label": row["gesture_label"],
            "confidence": row["confidence"],
            "audio_file": row["audio_file"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return jsonify(payload), 200


@api_bp.get("/api/config")
def get_config() -> tuple[dict[str, float], int]:
    """Return current runtime tunable configuration."""
    classifier = current_app.extensions["classifier"]
    return jsonify({"confidence_threshold": classifier.confidence_threshold}), 200


@api_bp.post("/api/config")
def update_config() -> tuple[dict[str, float | str], int]:
    """Update runtime configuration values without restarting the server."""
    if not _api_key_ok():
        return jsonify({"error": "Unauthorized", "code": 401}), 401
    payload = request.get_json(silent=True) or {}
    classifier = current_app.extensions["classifier"]

    if "confidence_threshold" in payload:
        try:
            threshold = float(payload["confidence_threshold"])
        except (TypeError, ValueError):
            return jsonify({"error": "confidence_threshold must be a number", "code": 400}), 400
        classifier.confidence_threshold = max(0.1, min(1.0, threshold))
        LOGGER.info("Confidence threshold updated to %.2f", classifier.confidence_threshold)

    return jsonify({"confidence_threshold": classifier.confidence_threshold}), 200


@api_bp.delete("/api/history")
def clear_history() -> tuple[dict[str, str], int]:
    """Delete all translation rows from the database."""
    if not _api_key_ok():
        return jsonify({"error": "Unauthorized", "code": 401}), 401
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        connection.execute("DELETE FROM translations")
    return jsonify({"status": "cleared"}), 200


@api_bp.post("/api/model/reload")
def reload_model() -> tuple[dict[str, object], int]:
    """Hot-reload the gesture model and label map from disk."""
    if not _api_key_ok():
        return jsonify({"error": "Unauthorized", "code": 401}), 401

    classifier = current_app.extensions["classifier"]
    translator = current_app.extensions["translator"]

    translator.reload()
    success = classifier.reload()
    if hasattr(classifier, "reset_sequence"):
        classifier.reset_sequence()

    labels = translator.get_all_labels()
    return jsonify({
        "status": "ok" if success else "failed",
        "model_available": classifier.is_available,
        "demo_mode": classifier.is_demo_mode,
        "label_count": len(labels),
    }), 200 if success else 503


@api_bp.get("/api/labels")
def get_labels() -> tuple[dict[str, object], int]:
    """Return all known gesture labels."""
    translator = current_app.extensions["translator"]
    labels = translator.get_all_labels()
    return jsonify({"labels": labels, "count": len(labels)}), 200


@api_bp.get("/api/translations/<lang>")
def get_translations(lang: str) -> tuple[dict[str, object], int]:
    """Return translations for the specified language."""
    lang = lang.lower().strip()
    if lang not in ("en", "ar", "fr", "es", "de", "zh", "ja", "ko"):
        lang = "en"

    translations_file = Path(current_app.static_folder) / "data" / "translations.json"
    try:
        with translations_file.open("r", encoding="utf-8") as file_obj:
            all_translations = json.load(file_obj)

        if lang in all_translations:
            return jsonify({"lang": lang, "translations": all_translations[lang]}), 200
        return jsonify({"lang": "en", "translations": all_translations.get("en", {})}), 200
    except FileNotFoundError:
        LOGGER.warning("Translations file missing: %s", translations_file)
        return jsonify({"error": "Translations file not found", "code": 404}), 404
    except json.JSONDecodeError:
        LOGGER.exception("Invalid translations JSON: %s", translations_file)
        return jsonify({"error": "Invalid translations file", "code": 500}), 500
    except OSError as error:
        LOGGER.error("Failed to load translations: %s", error)
        return jsonify({"error": "Failed to load translations", "code": 500}), 500
