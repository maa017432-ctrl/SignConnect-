"""Route tests for expected status codes."""

from __future__ import annotations

import pytest

pytest.importorskip("flask")


@pytest.fixture()
def client():
    """Create Flask test client."""
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_main_routes(client) -> None:
    """Ensure page routes render correctly."""
    assert client.get("/").status_code == 200
    assert client.get("/translator").status_code == 200
    assert client.get("/history").status_code == 200
    assert client.get("/dictionary").status_code == 200


def test_dictionary_page_renders_searchable_supported_signs(client) -> None:
    """Dictionary page should show educational searchable glossary UI."""
    response = client.get("/dictionary")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Supported Signs Dictionary" in body
    assert 'id="dict-search"' in body
    assert "Showing " in body


def test_dictionary_uses_config_fallback_when_label_map_is_empty(client) -> None:
    """When no labels exist in the map, dictionary should fall back to configured classes."""
    translator = client.application.extensions["translator"]
    classifier = client.application.extensions["classifier"]
    original_label_map = dict(translator.label_map)
    original_labels_count = classifier.labels_count
    try:
        translator.label_map = {}
        classifier.labels_count = 3
        response = client.get("/dictionary")
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Class 1" in body
        assert "Class 3" in body
        assert "config fallback" in body
    finally:
        translator.label_map = original_label_map
        classifier.labels_count = original_labels_count


def test_admin_route_requires_authentication(client) -> None:
    """Admin dashboard should redirect guests to sign-in."""
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/signin")


def test_admin_dashboard_renders_for_signed_in_user(client) -> None:
    """Signed-in users should see dashboard metrics and charts."""
    from database.db import get_connection

    db_path = client.application.config["DATABASE_PATH"]
    email = "admin-dashboard@example.com"
    with get_connection(db_path) as connection:
        connection.execute("DELETE FROM translations WHERE user_id IN (SELECT id FROM users WHERE email = ?)", (email,))
        connection.execute("DELETE FROM users WHERE email = ?", (email,))
        cursor = connection.execute(
            "INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)",
            (email, "hash", "Admin User"),
        )
        user_id = cursor.lastrowid
        session_id = connection.execute(
            "INSERT INTO sessions (ended_at) VALUES (NULL)"
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO translations (session_id, user_id, gesture_label, confidence, audio_file)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (session_id, user_id, "Hello", 0.92, "hello.mp3"),
                (session_id, user_id, "Thank You", 0.88, "thanks.mp3"),
                (session_id, user_id, "Hello", 0.95, "hello2.mp3"),
            ],
        )

    with client.session_transaction() as flask_session:
        flask_session["user_id"] = user_id
        flask_session["user_name"] = "Admin User"
        flask_session["user_email"] = email

    response = client.get("/admin")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Admin Dashboard" in body
    assert "Total Translations" in body
    assert "Most Common Gestures" in body
    assert "Hello" in body


def test_api_routes(client) -> None:
    """Ensure API routes return expected statuses."""
    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    payload = status_response.get_json()
    assert payload is not None
    assert payload.get("camera_frame_route") is True
    assert client.get("/api/history").status_code == 200
    assert client.delete("/api/history").status_code == 200


def test_api_docs_routes(client) -> None:
    """Swagger UI and OpenAPI spec should be exposed for presentation/demo use."""
    docs_response = client.get("/api/docs")
    assert docs_response.status_code == 200
    assert "SignConnect API Docs" in docs_response.get_data(as_text=True)

    spec_response = client.get("/api/docs/openapi.json")
    assert spec_response.status_code == 200
    spec = spec_response.get_json()
    assert spec is not None
    assert spec["info"]["title"] == "SignConnect API"
    assert "/api/status" in spec["paths"]
    assert "/api/camera_frame" in spec["paths"]
    assert "/video_feed" in spec["paths"]


def test_health_endpoint(client) -> None:
    """Health endpoint should return JSON with required fields."""
    response = client.get("/api/health")
    # Status is either 200 (model loaded) or 503 (demo/no model) — both valid
    assert response.status_code in (200, 503)
    payload = response.get_json()
    assert payload is not None
    assert "status" in payload
    assert payload["status"] in ("ok", "degraded")
    assert "uptime_seconds" in payload
    assert isinstance(payload["uptime_seconds"], (int, float))
    assert payload["uptime_seconds"] >= 0
    assert "model_loaded" in payload
    assert isinstance(payload["model_loaded"], bool)
    # threads is included when psutil is available (best-effort check)
    if "threads" in payload:
        assert isinstance(payload["threads"], int)
        assert payload["threads"] >= 1


def test_camera_frame_jpeg(client) -> None:
    """Translator preview polls these URLs; must be JPEG, not JSON 404."""
    for path in ("/camera_frame", "/api/camera_frame"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content_type.startswith("image/jpeg"), path
