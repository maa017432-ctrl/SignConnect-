"""Lightweight double-submit CSRF protection for form-based routes."""

from __future__ import annotations

import secrets

from flask import current_app, session


_SESSION_KEY = "_csrf_token"
_FORM_FIELD = "csrf_token"


def generate_csrf_token() -> str:
    """Return the session CSRF token, creating one if absent."""
    if _SESSION_KEY not in session:
        session[_SESSION_KEY] = secrets.token_hex(32)
    return session[_SESSION_KEY]


def validate_csrf_token() -> bool:
    """Return True if the submitted form token matches the session token.

    Always returns True in TESTING mode so test clients do not need to set up
    CSRF tokens.
    """
    if current_app.config.get("TESTING", False):
        return True
    expected = session.get(_SESSION_KEY, "")
    if not expected:
        return False
    submitted = _get_submitted_token()
    return secrets.compare_digest(expected, submitted)


def _get_submitted_token() -> str:
    """Return the submitted CSRF token from the form or JSON body."""
    from flask import request

    # Form submission
    token = request.form.get(_FORM_FIELD, "")
    if token:
        return token
    # JSON body (future-proofing)
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        return str(payload.get(_FORM_FIELD, ""))
    return ""
