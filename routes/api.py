"""REST API endpoints for status, translation, and history."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, session
from flask.wrappers import Response

from core.logging_config import get_uptime_seconds
from database.db import get_connection
from routes.stream import _prediction_lock, camera_frame_response

try:
    import psutil as _psutil
except ImportError:  # pragma: no cover
    _psutil = None  # type: ignore[assignment]


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
    """Return runtime health status for core services.
    ---
    tags:
      - Runtime
    summary: Inspect core runtime dependencies
    description: Reports whether the camera, model, TTS engine, and MediaPipe pipeline are currently available.
    responses:
      200:
        description: Current runtime status snapshot.
        schema:
          type: object
          properties:
            camera:
              type: boolean
            model:
              type: boolean
            model_demo_mode:
              type: boolean
            model_type:
              type: string
            model_input_dim:
              type: integer
            sequence_length:
              type: integer
            label_count:
              type: integer
            norm_stats_loaded:
              type: boolean
            tts:
              type: boolean
            mediapipe:
              type: boolean
            camera_frame_route:
              type: boolean
    """
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


@api_bp.get("/api/health")
def health() -> tuple[Response, int]:
    """Deep health check suitable for load-balancer and orchestrator probes.

    Returns HTTP 200 with a JSON body while all critical components are
    operational, or HTTP 503 when the model is unavailable.  Memory metrics
    are included when ``psutil`` is installed; if it is absent the ``memory``
    key is omitted rather than causing a hard error.
    ---
    tags:
      - Runtime
    summary: Health probe for operations and deployment
    responses:
      200:
        description: Application is healthy.
        schema:
          type: object
          properties:
            status:
              type: string
              example: ok
            uptime_seconds:
              type: number
            model_loaded:
              type: boolean
      503:
        description: Application is running in degraded mode because the model is unavailable.
    """
    classifier = current_app.extensions.get("classifier")
    model_loaded: bool = bool(classifier and classifier.is_available)

    payload: dict[str, object] = {
        "status": "ok" if model_loaded else "degraded",
        "uptime_seconds": round(get_uptime_seconds(), 3),
        "model_loaded": model_loaded,
    }

    if _psutil is not None:
        try:
            proc = _psutil.Process()
            mem = proc.memory_info()
            payload["memory"] = {
                "rss_mb": round(mem.rss / (1024 * 1024), 2),
                "vms_mb": round(mem.vms / (1024 * 1024), 2),
            }
            payload["threads"] = proc.num_threads()
            # num_fds() is Unix-only; not available on Windows.
            if hasattr(proc, "num_fds"):
                payload["open_fds"] = proc.num_fds()
        except Exception:
            LOGGER.debug("psutil memory query failed", exc_info=True)

    http_status = 200 if model_loaded else 503
    return jsonify(payload), http_status

@api_bp.get("/api/camera_frame")
def api_camera_frame() -> Response:
    """Return a single annotated JPEG camera frame.
    ---
    tags:
      - Streaming
    summary: Fetch one JPEG frame snapshot
    produces:
      - image/jpeg
    responses:
      200:
        description: JPEG snapshot for polling-based preview clients.
        schema:
          type: string
          format: binary
    """
    return camera_frame_response()


@api_bp.get("/api/prediction")
def latest_prediction() -> tuple[dict[str, object], int]:
    """Return current gesture prediction, smoothed label, and sentence state.
    ---
    tags:
      - Runtime
    summary: Read the latest prediction payload
    responses:
      200:
        description: Current prediction and sentence-builder state.
        schema:
          type: object
          properties:
            label:
              type: string
              nullable: true
            confidence:
              type: number
            smoothed_label:
              type: string
              nullable: true
            top_candidates:
              type: array
              items:
                type: object
            sentence:
              type: string
            current_run:
              type: integer
            stable_frames:
              type: integer
            is_cooling_down:
              type: boolean
            model_type:
              type: string
            inference_ms:
              type: number
              nullable: true
    """
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


@api_bp.post("/api/tts")
def tts() -> tuple[dict[str, str | int], int]:
    """Synthesise speech and return an audio URL without writing to history.

    This lightweight endpoint is used by the auto-speak feature to speak each
    committed word without polluting the translation history.  Use
    ``POST /api/translate`` instead when a history entry is also desired.
    ---
    tags:
      - Speech
    summary: Generate speech audio without saving history
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - text
          properties:
            text:
              type: string
              example: Hello world
            lang:
              type: string
              example: en
    responses:
      200:
        description: Audio was generated successfully.
        schema:
          type: object
          properties:
            audio_url:
              type: string
      400:
        description: Invalid or missing request body.
      503:
        description: Speech synthesis backend is unavailable.
    """
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

    return jsonify({"audio_url": f"/static/audio/{filename}"}), 200


@api_bp.post("/api/translate")
def translate() -> tuple[dict[str, str | int], int]:
    """Convert input text to speech, save history, and return an audio URL.
    ---
    tags:
      - Speech
    summary: Generate speech audio and persist a translation history row
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - text
          properties:
            text:
              type: string
              example: Thank you
            lang:
              type: string
              example: en
    responses:
      200:
        description: Audio URL returned successfully.
        schema:
          type: object
          properties:
            audio_url:
              type: string
      400:
        description: Invalid or missing request body.
      503:
        description: Speech synthesis backend is unavailable.
    """
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
        confidence = float(latest.get("confidence") or 0.0)
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
                INSERT INTO translations (session_id, user_id, gesture_label, confidence, audio_file)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, session.get("user_id"), text, confidence, filename),
            )
    except Exception:
        LOGGER.exception("Failed to persist translation to database")

    return jsonify({"audio_url": f"/static/audio/{filename}"}), 200


@api_bp.get("/api/history")
def get_history() -> tuple[list[dict[str, str | float | None]], int]:
    """Return latest translation history as JSON list."""
    user_id = session.get("user_id")
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        rows = connection.execute(
            """
            SELECT id, gesture_label, confidence, audio_file, created_at
            FROM translations
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 50
            """,
            (user_id,),
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
    """Delete all translation rows belonging to the current user."""
    if not _api_key_ok():
        return jsonify({"error": "Unauthorized", "code": 401}), 401
    user_id = session.get("user_id")
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        connection.execute("DELETE FROM translations WHERE user_id = ?", (user_id,))
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
