from __future__ import annotations

from flask import Blueprint, jsonify, request

from . import db
from .auth import requires_auth
from .config import DEFAULT_SETTINGS


bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@bp.get("")
@requires_auth
def get_settings():
    return jsonify(db.get_settings(db.get_db()))


@bp.post("")
@requires_auth
def update_settings():
    data = request.get_json(silent=True) or {}
    updates: dict[str, int] = {}
    for key, value in data.items():
        if key not in DEFAULT_SETTINGS:
            return jsonify({"error": f"unknown setting: {key}"}), 400
        try:
            updates[key] = int(value)
        except (TypeError, ValueError):
            return jsonify({"error": f"{key} must be an integer"}), 400
        if updates[key] < 0:
            return jsonify({"error": f"{key} must be non-negative"}), 400
    conn = db.get_db()
    try:
        db.update_settings(conn, updates)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(db.get_settings(conn))
