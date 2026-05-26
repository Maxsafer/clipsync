from __future__ import annotations

import functools
import secrets
from datetime import timedelta
from typing import Callable

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def bootstrap_auth(db_path: str, username: str | None, password: str | None) -> None:
    """If the auth table is empty, seed it from env-provided credentials.
    On subsequent runs (auth row exists), env values are ignored."""
    with db.standalone_db(db_path) as conn:
        if db.auth_row(conn) is not None:
            return
        if not username or not password:
            raise RuntimeError(
                "First-run bootstrap requires CLIPSYNC_USERNAME and CLIPSYNC_PASSWORD"
            )
        db.auth_bootstrap(
            conn,
            username=username,
            password_hash=generate_password_hash(password),
            api_token=secrets.token_urlsafe(32),
        )


def _extract_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :].strip()
    qs = request.args.get("token")
    if qs:
        return qs.strip()
    return None


def _token_matches(provided: str) -> bool:
    conn = db.get_db()
    row = db.auth_row(conn)
    if not row:
        return False
    return secrets.compare_digest(provided, row["api_token"])


def is_authed() -> bool:
    if session.get("uid") == 1:
        return True
    token = _extract_token()
    if token and _token_matches(token):
        return True
    return False


def requires_auth(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    remember = bool(data.get("remember"))
    conn = db.get_db()
    row = db.auth_row(conn)
    if not row or username != row["username"] or not check_password_hash(
        row["password_hash"], password
    ):
        return jsonify({"error": "invalid credentials"}), 401
    session.clear()
    session["uid"] = 1
    session.permanent = remember
    current_app.permanent_session_lifetime = timedelta(days=30)
    return jsonify({"ok": True, "username": row["username"]})


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    if not is_authed():
        return jsonify({"authed": False}), 401
    conn = db.get_db()
    row = db.auth_row(conn)
    return jsonify({"authed": True, "username": row["username"] if row else None})


@bp.post("/rotate-token")
@requires_auth
def rotate_token():
    conn = db.get_db()
    new_token = secrets.token_urlsafe(32)
    db.auth_update_token(conn, new_token)
    return jsonify({"api_token": new_token})


@bp.post("/change-password")
@requires_auth
def change_password():
    data = request.get_json(silent=True) or {}
    current = data.get("current") or ""
    new = data.get("new") or ""
    if len(new) < 8:
        return jsonify({"error": "new password must be at least 8 characters"}), 400
    conn = db.get_db()
    row = db.auth_row(conn)
    if not row or not check_password_hash(row["password_hash"], current):
        return jsonify({"error": "current password is incorrect"}), 401
    db.auth_update_password(conn, generate_password_hash(new))
    return jsonify({"ok": True})


@bp.get("/token")
@requires_auth
def show_token():
    conn = db.get_db()
    row = db.auth_row(conn)
    return jsonify({"api_token": row["api_token"] if row else None})
