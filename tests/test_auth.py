"""Auth route tests: sign-in, sign-up, sign-out, and CSRF protection."""

from __future__ import annotations

import pytest

pytest.importorskip("flask")


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _register(client, email="test@example.com", password="password123", first="Test", last="User"):
    """POST /signup with the given credentials."""
    return client.post(
        "/signup",
        data={"first_name": first, "last_name": last, "email": email, "password": password},
        follow_redirects=True,
    )


def _login(client, email="test@example.com", password="password123"):
    """POST /signin with the given credentials."""
    return client.post(
        "/signin",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


# ── Sign-up tests ─────────────────────────────────────────────────────────────

class TestSignup:
    def test_get_renders_form(self, client) -> None:
        res = client.get("/signup")
        assert res.status_code == 200
        assert b"Create" in res.data or b"sign" in res.data.lower()

    def test_valid_registration_redirects_home(self, client) -> None:
        res = _register(client, email="newuser@example.com")
        assert res.status_code == 200

    def test_duplicate_email_returns_error(self, client) -> None:
        _register(client, email="dup@example.com")
        res = _register(client, email="dup@example.com")
        assert b"already exists" in res.data

    def test_too_short_password_returns_error(self, client) -> None:
        res = _register(client, email="short@example.com", password="abc")
        assert b"8 character" in res.data

    def test_malformed_email_returns_error(self, client) -> None:
        res = _register(client, email="not-an-email", password="validpass")
        assert b"valid email" in res.data

    def test_missing_first_name_returns_error(self, client) -> None:
        res = _register(client, email="nofirst@example.com", first="")
        assert b"required" in res.data

    def test_password_with_leading_space_is_accepted(self, client) -> None:
        """Passwords with leading/trailing spaces must NOT be silently stripped."""
        res = _register(client, email="spacepw@example.com", password="  spaced  ")
        # Should succeed (password is ≥ 8 chars after counting spaces)
        assert b"already exists" not in res.data
        assert b"8 character" not in res.data


# ── Sign-in tests ─────────────────────────────────────────────────────────────

class TestSignin:
    def setup_method(self):
        """Pre-register a user for sign-in tests."""
        self._email = "signintest@example.com"
        self._password = "correcthorse"

    def _ensure_registered(self, client):
        _register(client, email=self._email, password=self._password)

    def test_get_renders_form(self, client) -> None:
        res = client.get("/signin")
        assert res.status_code == 200

    def test_valid_credentials_set_session(self, client) -> None:
        self._ensure_registered(client)
        with client.session_transaction() as sess:
            sess.clear()
        res = _login(client, email=self._email, password=self._password)
        assert res.status_code == 200
        with client.session_transaction() as sess:
            assert "user_id" in sess

    def test_wrong_password_returns_error(self, client) -> None:
        self._ensure_registered(client)
        res = _login(client, email=self._email, password="wrongpassword")
        assert b"Invalid" in res.data

    def test_unknown_email_returns_error(self, client) -> None:
        res = _login(client, email="nobody@example.com", password="doesnotmatter")
        assert b"Invalid" in res.data

    def test_empty_fields_returns_error(self, client) -> None:
        res = client.post(
            "/signin",
            data={"email": "", "password": ""},
            follow_redirects=True,
        )
        assert b"required" in res.data

    def test_password_not_stripped(self, client) -> None:
        """Correct password with leading space must match exactly."""
        spaced_pw = "  spacedpw  "
        _register(client, email="striptest@example.com", password=spaced_pw)
        # Using the exact password should succeed
        res = _login(client, email="striptest@example.com", password=spaced_pw)
        with client.session_transaction() as sess:
            assert "user_id" in sess, "Login with exact spaced password should succeed"
        # Using the stripped password must NOT succeed
        with client.session_transaction() as sess:
            sess.clear()
        res2 = _login(client, email="striptest@example.com", password=spaced_pw.strip())
        with client.session_transaction() as sess:
            assert "user_id" not in sess, "Stripped password must not grant access"


# ── Sign-out tests ─────────────────────────────────────────────────────────────

class TestSignout:
    def test_signout_clears_session(self, client) -> None:
        _register(client, email="logouttest@example.com", password="testpass1")
        _login(client, email="logouttest@example.com", password="testpass1")
        with client.session_transaction() as sess:
            assert "user_id" in sess

        client.get("/signout", follow_redirects=True)
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_signout_via_post(self, client) -> None:
        _register(client, email="postlogout@example.com", password="testpass2")
        _login(client, email="postlogout@example.com", password="testpass2")
        client.post("/signout", follow_redirects=True)
        with client.session_transaction() as sess:
            assert "user_id" not in sess


# ── API key enforcement ────────────────────────────────────────────────────────

class TestApiKeyEnforcement:
    def test_delete_history_requires_key_when_configured(self, client, app) -> None:
        original_key = app.config["API_KEY"]
        try:
            app.config["API_KEY"] = "test-key-xyz"
            no_key = client.delete("/api/history")
            wrong_key = client.delete("/api/history", headers={"X-API-Key": "wrong"})
            good_key = client.delete("/api/history", headers={"X-API-Key": "test-key-xyz"})
            assert no_key.status_code == 401
            assert wrong_key.status_code == 401
            assert good_key.status_code == 200
        finally:
            app.config["API_KEY"] = original_key

    def test_delete_history_allowed_when_no_key_configured(self, client, app) -> None:
        original_key = app.config["API_KEY"]
        try:
            app.config["API_KEY"] = ""
            res = client.delete("/api/history")
            assert res.status_code == 200
        finally:
            app.config["API_KEY"] = original_key
