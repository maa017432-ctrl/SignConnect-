"""Authentication routes: sign-in, sign-up, sign-out."""

from __future__ import annotations

import logging
import re

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.wrappers import Response
from werkzeug.security import check_password_hash, generate_password_hash

from core.csrf import generate_csrf_token, validate_csrf_token
from database.db import get_connection
from flask import current_app

LOGGER = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_user_by_email(db_path: str, email: str) -> dict | None:
    """Return a user row dict or None."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, full_name FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
    return dict(row) if row else None


def _create_user(db_path: str, email: str, password: str, full_name: str) -> int:
    """Insert a new user and return their id.

    Uses ``lastrowid`` instead of a follow-up SELECT to avoid a TOCTOU race
    when multiple threads insert the same e-mail concurrently.
    """
    pw_hash = generate_password_hash(password)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)",
            (email.lower().strip(), pw_hash, full_name.strip()),
        )
        return cursor.lastrowid


# ── routes ────────────────────────────────────────────────────────────────────

@auth_bp.get("/signin")
def signin_get() -> str | Response:
    """Render sign-in page. Redirect to home if already logged in."""
    if session.get("user_id"):
        return redirect(url_for("main.index"))
    return render_template("signin.html", error=None, csrf_token=generate_csrf_token())


@auth_bp.post("/signin")
def signin_post() -> str | Response:
    """Handle sign-in form submission."""
    if not validate_csrf_token():
        return render_template("signin.html", error="Invalid form submission. Please try again.", csrf_token=generate_csrf_token())

    email = request.form.get("email", "").strip()
    # Do NOT strip the password — leading/trailing spaces are intentional.
    password = request.form.get("password", "")

    if not email or not password:
        return render_template("signin.html", error="Email and password are required.", csrf_token=generate_csrf_token())

    db_path = current_app.config["DATABASE_PATH"]
    user = _get_user_by_email(db_path, email)

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("signin.html", error="Invalid email or password.", csrf_token=generate_csrf_token())

    session.clear()
    session["user_id"] = user["id"]
    session["user_email"] = user["email"]
    session["user_name"] = user["full_name"] or user["email"].split("@")[0]
    session.permanent = True

    LOGGER.info("User %s signed in", user["email"])
    return redirect(url_for("main.index"))


@auth_bp.get("/signup")
def signup_get() -> str | Response:
    """Render sign-up page. Redirect to home if already logged in."""
    if session.get("user_id"):
        return redirect(url_for("main.index"))
    return render_template("signup.html", error=None, csrf_token=generate_csrf_token())


@auth_bp.post("/signup")
def signup_post() -> str | Response:
    """Handle sign-up form submission."""
    if not validate_csrf_token():
        return render_template("signup.html", error="Invalid form submission. Please try again.", csrf_token=generate_csrf_token())

    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip()
    # Do NOT strip the password — leading/trailing spaces are intentional.
    password = request.form.get("password", "")

    # Validation
    if not email or not password or not first:
        return render_template("signup.html", error="All fields are required.", csrf_token=generate_csrf_token())
    if not _EMAIL_RE.match(email):
        return render_template("signup.html", error="Please enter a valid email address.", csrf_token=generate_csrf_token())
    if len(password) < 8:
        return render_template("signup.html", error="Password must be at least 8 characters.", csrf_token=generate_csrf_token())

    db_path = current_app.config["DATABASE_PATH"]

    if _get_user_by_email(db_path, email):
        return render_template("signup.html", error="An account with that email already exists.", csrf_token=generate_csrf_token())

    try:
        full_name = f"{first} {last}".strip()
        user_id = _create_user(db_path, email, password, full_name)
    except Exception:
        LOGGER.exception("Failed to create user account")
        return render_template("signup.html", error="Account creation failed. Please try again.", csrf_token=generate_csrf_token())

    session.clear()
    session["user_id"] = user_id
    session["user_email"] = email.lower()
    session["user_name"] = full_name or email.split("@")[0]
    session.permanent = True

    LOGGER.info("New user registered: %s", email)
    return redirect(url_for("main.index"))


@auth_bp.get("/signout")
@auth_bp.post("/signout")
def signout() -> Response:
    """Clear session and redirect to home."""
    session.clear()
    return redirect(url_for("main.index"))
