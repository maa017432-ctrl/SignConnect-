"""Primary view routes for page rendering."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, send_from_directory
from flask.wrappers import Response

from database.db import get_connection


main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index() -> str:
    """Render project landing page."""
    return render_template("index.html")


@main_bp.get("/translator")
def translator() -> str:
    """Render live translation interface."""
    return render_template("translator.html")


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
    with get_connection(current_app.config["DATABASE_PATH"]) as connection:
        rows = connection.execute(
            """
            SELECT gesture_label, confidence, audio_file, created_at
            FROM translations
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()
    return render_template("history.html", rows=rows)


@main_bp.get("/dictionary")
def dictionary() -> str:
    """Render the gesture dictionary page."""
    translator = current_app.extensions["translator"]
    labels = translator.get_all_labels()
    return render_template("dictionary.html", labels=labels)
