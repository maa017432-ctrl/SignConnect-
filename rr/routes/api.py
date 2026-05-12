"""REST API endpoints for status, translation, and history."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request
from flask.wrappers import Response

from database.db import get_connection
from routes.stream import _prediction_lock, camera_frame_response


LOGGER = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__)


@api_bp.get("/api/status")
def status() -> tuple[dict[str, bool], int]:
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
    return jsonify({"sentence": ""}), 200


@api_bp.post("/api/translate")
def translate() -> tuple[dict[str, str | int], int]:
    """Convert input text to speech and return audio URL."""
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"error": "Missing text", "code": 400}), 400

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
                connection.execute("INSERT INTO sessions (ended_at) VALUES (NULL)")
                session_id = connection.execute(
                    "SELECT id FROM sessions ORDER BY id DESC LIMIT 1"
                ).fetchone()["id"]
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
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        connection.execute("DELETE FROM translations")
    return jsonify({"status": "cleared"}), 200


@api_bp.post("/api/model/reload")
def reload_model() -> tuple[dict[str, object], int]:
    """Hot-reload the gesture model and label map from disk."""
    classifier = current_app.extensions["classifier"]
    translator = current_app.extensions["translator"]

    translator._load_label_map()
    success = classifier.reload()

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
