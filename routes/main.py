"""Primary view routes for page rendering."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template, send_from_directory, session
from flask.wrappers import Response

from database.db import get_connection


main_bp = Blueprint("main", __name__)


def _user_ctx() -> dict:
    """Return common user context for templates."""
    return {
        "current_user": {
            "id": session.get("user_id"),
            "email": session.get("user_email", ""),
            "name": session.get("user_name", ""),
            "is_authenticated": bool(session.get("user_id")),
        }
    }


@main_bp.get("/")
def index() -> str:
    """Render project landing page."""
    return render_template("index.html", **_user_ctx())


@main_bp.get("/translator")
def translator() -> str:
    """Render live translation interface."""
    classifier = current_app.extensions.get("classifier")
    demo_mode = classifier.is_demo_mode if classifier else True
    return render_template("translator.html", demo_mode=demo_mode, **_user_ctx())


@main_bp.get("/sw.js")
def service_worker() -> Response:
    """Serve the PWA service worker from root scope with correct headers."""
    response = send_from_directory(
        current_app.static_folder,  # type: ignore[arg-type]
        "sw.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@main_bp.get("/history")
def history() -> str:
    """Render latest translation history from SQLite."""
    user_id = session.get("user_id")
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        rows = connection.execute(
            """
            SELECT gesture_label, confidence, audio_file, created_at
            FROM translations
            WHERE user_id IS ?
            ORDER BY id DESC
            LIMIT 50
            """,
            (user_id,),
        ).fetchall()
    return render_template("history.html", rows=rows, **_user_ctx())


@main_bp.get("/dictionary")
def dictionary() -> str:
    """Render the gesture dictionary page."""
    translator_ext = current_app.extensions["translator"]
    labels = translator_ext.get_all_labels()
    return render_template("dictionary.html", labels=labels, **_user_ctx())


@main_bp.get("/settings")
def settings() -> str:
    """Render the settings page."""
    classifier = current_app.extensions.get("classifier")
    return render_template(
        "settings.html",
        confidence_threshold=classifier.confidence_threshold if classifier else 0.7,
        **_user_ctx(),
    )
