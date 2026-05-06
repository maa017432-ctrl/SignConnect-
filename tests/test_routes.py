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


def test_api_routes(client) -> None:
    """Ensure API routes return expected statuses."""
    status_response = client.get("/api/status")
    assert status_response.status_code == 200
    payload = status_response.get_json()
    assert payload is not None
    assert payload.get("camera_frame_route") is True
    assert client.get("/api/history").status_code == 200
    assert client.delete("/api/history").status_code == 200


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


def test_camera_frame_jpeg(client) -> None:
    for path in ("/camera_frame", "/api/camera_frame"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content_type.startswith("image/jpeg"), path
