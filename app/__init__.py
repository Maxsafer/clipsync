from __future__ import annotations

import os
import threading
import time
from datetime import timedelta

from flask import Flask, send_from_directory

from . import auth, clips, db, settings, storage
from .config import Config, load_config
from .events import Broker


def create_app(config: Config | None = None, *, start_background: bool = True) -> Flask:
    cfg = config or load_config()
    os.makedirs(cfg.data_dir, exist_ok=True)
    os.makedirs(cfg.blobs_dir, exist_ok=True)
    db.init_db(cfg.db_path)
    auth.bootstrap_auth(cfg.db_path, cfg.bootstrap_username, cfg.bootstrap_password)

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=cfg.secret_key,
        CLIPSYNC_DB_PATH=cfg.db_path,
        CLIPSYNC_BLOBS_DIR=cfg.blobs_dir,
        CLIPSYNC_BROKER=Broker(),
        CLIPSYNC_STATIC_DIR=static_dir,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=None,
    )

    app.teardown_appcontext(db.close_db)

    app.register_blueprint(auth.bp)
    app.register_blueprint(clips.bp)
    app.register_blueprint(settings.bp)

    @app.get("/")
    def root():
        return send_from_directory(static_dir, "index.html")

    @app.get("/<path:path>")
    def static_files(path: str):
        full = os.path.join(static_dir, path)
        if os.path.isfile(full):
            return send_from_directory(static_dir, path)
        # SPA fallback for unknown paths
        return send_from_directory(static_dir, "index.html")

    if start_background:
        _start_ttl_thread(app)

    return app


def _start_ttl_thread(app: Flask) -> None:
    cfg_db_path = app.config["CLIPSYNC_DB_PATH"]
    blobs_dir = app.config["CLIPSYNC_BLOBS_DIR"]
    broker: Broker = app.config["CLIPSYNC_BROKER"]
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                with db.standalone_db(cfg_db_path) as conn:
                    s = db.get_settings(conn)
                    expired = db.evict_expired(conn, s["item_ttl_hours"])
                if expired:
                    storage.delete_blobs(blobs_dir, expired)
                    for cid in expired:
                        broker.publish("clip.deleted", {"id": cid})
            except Exception:  # noqa: BLE001 — background loop, must not die
                pass
            stop.wait(60)

    t = threading.Thread(target=loop, name="clipsync-ttl", daemon=True)
    t.start()
    app.config["CLIPSYNC_TTL_STOP"] = stop
