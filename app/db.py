from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator

from flask import current_app, g

from .config import DEFAULT_SETTINGS


SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
  id           TEXT PRIMARY KEY,
  type         TEXT NOT NULL,
  mime         TEXT NOT NULL,
  size         INTEGER NOT NULL,
  filename     TEXT,
  device_label TEXT NOT NULL,
  preview      TEXT,
  created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_created ON clips(created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  username      TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  api_token     TEXT NOT NULL
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(current_app.config["CLIPSYNC_DB_PATH"])
    return g.db


def close_db(_e=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def standalone_db(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with standalone_db(db_path) as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, str(value)),
            )
        conn.commit()


# --- settings ----------------------------------------------------------------


def get_settings(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    result = {k: int(v) for k, v in DEFAULT_SETTINGS.items()}
    for row in rows:
        if row["key"] in DEFAULT_SETTINGS:
            try:
                result[row["key"]] = int(row["value"])
            except ValueError:
                pass
    return result


def update_settings(conn: sqlite3.Connection, updates: dict[str, int]) -> None:
    for key, value in updates.items():
        if key not in DEFAULT_SETTINGS:
            raise ValueError(f"unknown setting: {key}")
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
    conn.commit()


# --- clips -------------------------------------------------------------------


def insert_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    type_: str,
    mime: str,
    size: int,
    filename: str | None,
    device_label: str,
    preview: str | None,
) -> dict:
    created_at = int(time.time())
    conn.execute(
        "INSERT INTO clips(id, type, mime, size, filename, device_label, preview, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (clip_id, type_, mime, size, filename, device_label, preview, created_at),
    )
    conn.commit()
    return {
        "id": clip_id,
        "type": type_,
        "mime": mime,
        "size": size,
        "filename": filename,
        "device_label": device_label,
        "preview": preview,
        "created_at": created_at,
    }


def list_clips(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM clips ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [clip_to_dict(r) for r in rows]


def get_clip(conn: sqlite3.Connection, clip_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return clip_to_dict(row) if row else None


def get_latest_clip(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM clips ORDER BY created_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return clip_to_dict(row) if row else None


def delete_clip(conn: sqlite3.Connection, clip_id: str) -> bool:
    cur = conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    conn.commit()
    return cur.rowcount > 0


def clear_clips(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT id FROM clips").fetchall()
    ids = [r["id"] for r in rows]
    conn.execute("DELETE FROM clips")
    conn.commit()
    return ids


def evict_over_history(conn: sqlite3.Connection, history_size: int) -> list[str]:
    if history_size <= 0:
        return []
    rows = conn.execute(
        "SELECT id FROM clips WHERE id NOT IN ("
        "  SELECT id FROM clips ORDER BY created_at DESC, rowid DESC LIMIT ?"
        ")",
        (history_size,),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM clips WHERE id IN ({placeholders})", ids)
        conn.commit()
    return ids


def evict_expired(conn: sqlite3.Connection, ttl_hours: int) -> list[str]:
    if ttl_hours <= 0:
        return []
    cutoff = int(time.time()) - ttl_hours * 3600
    rows = conn.execute(
        "SELECT id FROM clips WHERE created_at < ?", (cutoff,)
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        conn.execute("DELETE FROM clips WHERE created_at < ?", (cutoff,))
        conn.commit()
    return ids


def clip_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "mime": row["mime"],
        "size": row["size"],
        "filename": row["filename"],
        "device_label": row["device_label"],
        "preview": row["preview"],
        "created_at": row["created_at"],
    }


# --- auth --------------------------------------------------------------------


def auth_row(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT username, password_hash, api_token FROM auth WHERE id = 1"
    ).fetchone()
    if not row:
        return None
    return {
        "username": row["username"],
        "password_hash": row["password_hash"],
        "api_token": row["api_token"],
    }


def auth_bootstrap(
    conn: sqlite3.Connection, username: str, password_hash: str, api_token: str
) -> None:
    conn.execute(
        "INSERT INTO auth(id, username, password_hash, api_token) VALUES (1, ?, ?, ?)",
        (username, password_hash, api_token),
    )
    conn.commit()


def auth_update_password(conn: sqlite3.Connection, password_hash: str) -> None:
    conn.execute("UPDATE auth SET password_hash = ? WHERE id = 1", (password_hash,))
    conn.commit()


def auth_update_token(conn: sqlite3.Connection, api_token: str) -> None:
    conn.execute("UPDATE auth SET api_token = ? WHERE id = 1", (api_token,))
    conn.commit()
