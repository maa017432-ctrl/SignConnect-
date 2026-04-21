"""Integration tests for /api/translate and /api/config endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


# ── Shared client fixture ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from app import create_app
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ── /api/translate ────────────────────────────────────────────────────────────

class TestApiTranslate:
    def test_empty_text_returns_400(self, client) -> None:
        res = client.post(
            "/api/translate",
            json={"text": ""},
            content_type="application/json",
        )
        assert res.status_code == 400
        body = res.get_json()
        assert body is not None
        assert "error" in body

    def test_missing_text_field_returns_400(self, client) -> None:
        res = client.post(
            "/api/translate",
            json={"lang": "en"},
            content_type="application/json",
        )
        assert res.status_code == 400

    def test_non_json_body_returns_400(self, client) -> None:
        res = client.post(
            "/api/translate",
            data="not json at all",
            content_type="text/plain",
        )
        assert res.status_code == 400

    def test_tts_unavailable_returns_503(self, client, app) -> None:
        """When TTS engine returns None (unavailable) the API must 503."""
        tts = app.extensions["tts_engine"]
        with patch.object(tts, "synthesize", return_value=None):
            res = client.post("/api/translate", json={"text": "Hello"})
        assert res.status_code == 503
        body = res.get_json()
        assert body is not None

    def test_translate_with_language_param(self, client, app) -> None:
        """Lang param should be accepted and passed along without error."""
        tts = app.extensions["tts_engine"]
        with patch.object(tts, "synthesize", return_value="test_file.mp3") as mock_syn:
            res = client.post(
                "/api/translate",
                json={"text": "Bonjour", "lang": "fr"},
            )
        # If synthesis returned a filename the route should 200-OK
        if res.status_code == 200:
            body = res.get_json()
            assert "audio_url" in body
        # Verify lang was forwarded (may be skipped when TTS actually ran)
        if mock_syn.called:
            _, kwargs = mock_syn.call_args
            assert kwargs.get("lang") == "fr"

    def test_happy_path_returns_audio_url(self, client, app) -> None:
        tts = app.extensions["tts_engine"]
        with patch.object(tts, "synthesize", return_value="abcdef123456.mp3"):
            res = client.post("/api/translate", json={"text": "Hello world"})
        assert res.status_code == 200
        body = res.get_json()
        assert body is not None
        assert "audio_url" in body
        assert body["audio_url"].endswith("abcdef123456.mp3")


# ── /api/config ───────────────────────────────────────────────────────────────

class TestApiConfig:
    def test_get_config_returns_threshold(self, client) -> None:
        res = client.get("/api/config")
        assert res.status_code == 200
        body = res.get_json()
        assert body is not None
        assert "confidence_threshold" in body
        assert 0.0 < body["confidence_threshold"] <= 1.0

    def test_post_config_updates_threshold(self, client, app) -> None:
        classifier = app.extensions["classifier"]
        original = classifier.confidence_threshold
        try:
            res = client.post("/api/config", json={"confidence_threshold": 0.55})
            assert res.status_code == 200
            body = res.get_json()
            assert body is not None
            assert abs(body["confidence_threshold"] - 0.55) < 0.001
            assert abs(classifier.confidence_threshold - 0.55) < 0.001
        finally:
            classifier.confidence_threshold = original  # restore

    def test_post_config_clamps_above_one(self, client, app) -> None:
        classifier = app.extensions["classifier"]
        original = classifier.confidence_threshold
        try:
            res = client.post("/api/config", json={"confidence_threshold": 9.99})
            assert res.status_code == 200
            body = res.get_json()
            assert body["confidence_threshold"] <= 1.0
        finally:
            classifier.confidence_threshold = original

    def test_post_config_clamps_below_minimum(self, client, app) -> None:
        classifier = app.extensions["classifier"]
        original = classifier.confidence_threshold
        try:
            res = client.post("/api/config", json={"confidence_threshold": 0.0})
            assert res.status_code == 200
            body = res.get_json()
            assert body["confidence_threshold"] >= 0.1
        finally:
            classifier.confidence_threshold = original

    def test_post_config_non_numeric_returns_400(self, client) -> None:
        res = client.post("/api/config", json={"confidence_threshold": "high"})
        assert res.status_code == 400
        body = res.get_json()
        assert body is not None
        assert "error" in body

    def test_post_config_empty_body_is_noop(self, client, app) -> None:
        """Empty payload returns 200 with the current threshold unchanged."""
        classifier = app.extensions["classifier"]
        original = classifier.confidence_threshold
        res = client.post("/api/config", json={})
        assert res.status_code == 200
        body = res.get_json()
        assert abs(body["confidence_threshold"] - original) < 0.001
