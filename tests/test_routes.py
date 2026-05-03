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


def test_camera_frame_jpeg(client) -> None:
    """Translator preview polls these URLs; must be JPEG, not JSON 404."""
    for path in ("/camera_frame", "/api/camera_frame"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content_type.startswith("image/jpeg"), path


def test_api_status_includes_model_metadata(client) -> None:
    """/api/status must include model type, class count, and sequence length."""
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert "model_type" in payload
    assert "label_count" in payload
    assert "sequence_length" in payload
    assert "norm_stats_loaded" in payload


def test_sentence_clear_resets_temporal_state(client) -> None:
    """POST /api/sentence/clear must clear the classifier's temporal buffer."""
    from app import create_app
    from core.ai_model import GestureClassifier

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as test_client:
        classifier = app.extensions.get("classifier")
        if classifier is not None:
            import numpy as np
            # Manually stuff a frame into the buffer to simulate buffered state
            frame = np.random.rand(126).astype(np.float32)
            if hasattr(classifier, "_sequence_buffer"):
                classifier._sequence_buffer.append(frame)
                assert len(classifier._sequence_buffer) >= 1

        response = test_client.post("/api/sentence/clear")
        assert response.status_code == 200

        if classifier is not None and hasattr(classifier, "_sequence_buffer"):
            assert len(classifier._sequence_buffer) == 0, (
                "sentence/clear must reset the temporal sequence buffer"
            )

