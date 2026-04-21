"""Flask + SocketIO entry point for the SignConnect application."""

from __future__ import annotations

import atexit
import logging
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask.wrappers import Response
from flask_cors import CORS
from flask_socketio import SocketIO

from config import Config
from core.ai_model import GestureClassifier
from core.camera import CameraManager
from core.gesture_detector import GestureDetector
from core.prediction_smoother import PredictionSmoother, SentenceBuilder
from core.translator import Translator
from core.tts_engine import TTSEngine
from database.db import init_db
from routes.api import api_bp
from routes.main import main_bp
from routes.stream import camera_frame_response, stream_bp


LOGGER = logging.getLogger(__name__)

# Module-level SocketIO instance so routes/stream.py can import it directly.
socketio = SocketIO()


def create_app() -> Flask:
    """Create and configure the Flask + SocketIO application instance."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)

    app = Flask(__name__)
    app.config.from_object(Config())

    logging.basicConfig(
        level=getattr(logging, app.config["LOG_LEVEL"], logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    CORS(app)

    # Threading async_mode + simple-websocket: real WebSockets without eventlet/gevent
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    @app.after_request
    def _no_cache_for_api_and_frames(response: Response) -> Response:
        """Prevent browsers from caching /api/* and frame endpoints."""
        path = request.path
        if path.startswith("/api") or path in ("/camera_frame",):
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    init_db(app.config["DATABASE_PATH"], app.config["SCHEMA_PATH"])

    camera_manager = CameraManager(camera_index=app.config["CAMERA_INDEX"])
    gesture_detector = GestureDetector(
        min_detection_confidence=app.config["MP_MIN_DETECTION_CONFIDENCE"],
        min_tracking_confidence=app.config["MP_MIN_TRACKING_CONFIDENCE"],
    )
    translator = Translator(label_map_path=app.config["LABEL_MAP_PATH"])
    labels_count = len(translator.get_all_labels()) or app.config["LABELS_COUNT"]
    classifier = GestureClassifier(
        model_path=app.config["MODEL_PATH"],
        confidence_threshold=app.config["PREDICTION_CONFIDENCE_THRESHOLD"],
        labels_count=labels_count,
    )
    tts_engine = TTSEngine(
        audio_dir=app.config["AUDIO_CACHE_DIR"],
        cache_ttl_seconds=app.config["AUDIO_CACHE_TTL_SECONDS"],
    )
    smoother = PredictionSmoother(
        window=app.config.get("SMOOTHER_WINDOW", 10),
        min_fraction=app.config.get("SMOOTHER_MIN_FRACTION", 0.6),
    )
    sentence_builder = SentenceBuilder(
        stable_frames=app.config.get("SENTENCE_STABLE_FRAMES", 15),
        cooldown_frames=app.config.get("SENTENCE_COOLDOWN_FRAMES", 20),
    )

    app.extensions["camera_manager"]      = camera_manager
    app.extensions["gesture_detector"]    = gesture_detector
    app.extensions["classifier"]          = classifier
    app.extensions["translator"]          = translator
    app.extensions["tts_engine"]          = tts_engine
    app.extensions["prediction_smoother"] = smoother
    app.extensions["sentence_builder"]    = sentence_builder
    app.extensions["socketio"]            = socketio
    app.extensions["latest_prediction"]   = {
        "label": None,
        "confidence": 0.0,
        "smoothed_label": None,
        "top_candidates": [],
    }

    app.register_blueprint(main_bp)
    app.register_blueprint(stream_bp)
    app.register_blueprint(api_bp)

    app.add_url_rule(
        "/camera_frame",
        "camera_frame",
        camera_frame_response,
        methods=["GET"],
    )

    LOGGER.info("SignConnect started — JPEG preview: /camera_frame, /api/camera_frame")

    @app.errorhandler(404)
    def not_found(_: Exception) -> tuple[Response, int]:
        return jsonify({"error": "Resource not found", "code": 404}), 404

    @app.errorhandler(500)
    def server_error(_: Exception) -> tuple[Response, int]:
        return jsonify({"error": "Internal server error", "code": 500}), 500

    def _stop_camera_on_exit() -> None:
        try:
            camera_manager.stop()
        except Exception:
            LOGGER.exception("Failed to stop camera manager on exit")

    atexit.register(_stop_camera_on_exit)

    return app


if __name__ == "__main__":
    flask_app = create_app()
    # socketio.run() supports real WebSockets (via simple-websocket) in threading mode.
    # Use run_production.ps1 / run_production.bat for a multi-threaded HTTP server.
    socketio.run(
        flask_app,
        host=flask_app.config["HOST"],
        port=flask_app.config["PORT"],
        debug=flask_app.config["DEBUG"],
        allow_unsafe_werkzeug=True,
    )
