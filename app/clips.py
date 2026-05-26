from __future__ import annotations

import hashlib
import io
import mimetypes
import time
import uuid
from typing import BinaryIO

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from . import db, storage
from .auth import requires_auth
from .events import sse_stream


bp = Blueprint("clips", __name__, url_prefix="/api")


PREVIEW_CHARS = 256


def _device_label() -> str:
    label = (request.headers.get("X-Device-Label") or "").strip()
    if label:
        return label[:64]
    ua = request.headers.get("User-Agent", "")
    if ua:
        return "ua:" + hashlib.sha1(ua.encode("utf-8", "replace")).hexdigest()[:8]
    return "unknown"


def _type_for_mime(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/"):
        return "text"
    return "file"


def _max_bytes() -> int:
    settings = db.get_settings(db.get_db())
    return settings["max_item_size_mb"] * 1024 * 1024


def _ingest_stream(src: BinaryIO, mime: str, filename: str | None) -> tuple[str, int, str, str | None]:
    """Write src into a new blob, returning (clip_id, size, type, preview)."""
    clip_id = uuid.uuid4().hex
    blobs_dir = current_app.config["CLIPSYNC_BLOBS_DIR"]
    max_bytes = _max_bytes()
    size = storage.write_stream(blobs_dir, clip_id, src, max_bytes)
    type_ = _type_for_mime(mime)
    preview: str | None = None
    if type_ == "text":
        try:
            raw = storage.read_bytes(blobs_dir, clip_id)
            preview = raw.decode("utf-8", errors="replace")[:PREVIEW_CHARS]
        except OSError:
            preview = None
    elif type_ == "file" and filename:
        preview = filename
    return clip_id, size, type_, preview


def _enforce_history(conn) -> list[str]:
    settings = db.get_settings(conn)
    return db.evict_over_history(conn, settings["history_size"])


@bp.post("/clip")
@requires_auth
def push_clip():
    device = _device_label()
    conn = db.get_db()
    blobs_dir = current_app.config["CLIPSYNC_BLOBS_DIR"]

    content_type = (request.content_type or "").split(";")[0].strip().lower()

    try:
        if content_type == "multipart/form-data":
            file = request.files.get("file")
            if not file:
                return jsonify({"error": "missing 'file' field"}), 400
            mime = (file.mimetype or "application/octet-stream").lower()
            filename = file.filename or None
            clip_id, size, type_, preview = _ingest_stream(file.stream, mime, filename)
        else:
            mime = content_type or "application/octet-stream"
            filename = request.headers.get("X-Filename")
            src: BinaryIO = request.stream
            length = request.content_length
            if length is None:
                # Buffer once so we know the size when no Content-Length is given.
                src = io.BytesIO(request.get_data(cache=False))
            clip_id, size, type_, preview = _ingest_stream(src, mime, filename)
    except storage.SizeExceeded as e:
        return jsonify({"error": str(e)}), 413

    clip = db.insert_clip(
        conn,
        clip_id=clip_id,
        type_=type_,
        mime=mime,
        size=size,
        filename=filename,
        device_label=device,
        preview=preview,
    )

    evicted = _enforce_history(conn)
    if evicted:
        storage.delete_blobs(blobs_dir, evicted)

    broker = current_app.config["CLIPSYNC_BROKER"]
    broker.publish("clip.new", clip)
    for cid in evicted:
        broker.publish("clip.deleted", {"id": cid})

    return jsonify({"id": clip["id"], "type": clip["type"], "created_at": clip["created_at"]}), 201


@bp.get("/clips")
@requires_auth
def list_clips():
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    conn = db.get_db()
    cap = db.get_settings(conn)["history_size"] or 1000
    limit = max(1, min(limit, cap))
    return jsonify(db.list_clips(conn, limit))


_MIME_EXT_OVERRIDES = {
    "image/jpeg": ".jpg",
    "text/plain": ".txt",
    "application/octet-stream": ".bin",
}


def _download_name(clip: dict, mime: str) -> str:
    # Include a request-time UTC timestamp with ms precision so repeated fetches
    # of the same clip produce distinct filenames — `curl -OJ` on older curl
    # refuses to overwrite, and back-to-back calls land in the same second.
    now = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now)) + f"{int((now % 1) * 1000):03d}Z"
    if clip["filename"]:
        base = clip["filename"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if base:
            return f"clip-{clip['id'][:8]}-{stamp}-{base}"
    ext = _MIME_EXT_OVERRIDES.get(mime) or mimetypes.guess_extension(mime) or ".bin"
    return f"clip-{clip['id'][:8]}-{stamp}{ext}"


def _send_clip(clip: dict, *, force_mime: str | None = None, as_attachment: bool | None = None) -> Response:
    blobs_dir = current_app.config["CLIPSYNC_BLOBS_DIR"]
    path = storage.blob_path(blobs_dir, clip["id"])
    mime = force_mime or clip["mime"]
    if as_attachment is None:
        as_attachment = clip["type"] == "file"
    return send_file(
        path,
        mimetype=mime,
        as_attachment=as_attachment,
        download_name=_download_name(clip, mime),
        conditional=True,
    )


@bp.get("/clip/latest")
@requires_auth
def latest():
    conn = db.get_db()
    clip = db.get_latest_clip(conn)
    if not clip:
        return jsonify({"error": "no clips"}), 404
    return _send_clip(clip)


@bp.get("/clip/latest.txt")
@requires_auth
def latest_txt():
    conn = db.get_db()
    clip = db.get_latest_clip(conn)
    if not clip:
        return jsonify({"error": "no clips"}), 404
    if clip["type"] != "text":
        return jsonify({"error": "latest clip is not text", "type": clip["type"]}), 409
    return _send_clip(clip, force_mime="text/plain", as_attachment=False)


@bp.get("/clip/latest.bin")
@requires_auth
def latest_bin():
    conn = db.get_db()
    clip = db.get_latest_clip(conn)
    if not clip:
        return jsonify({"error": "no clips"}), 404
    return _send_clip(clip, force_mime="application/octet-stream", as_attachment=False)


@bp.get("/clip/<clip_id>")
@requires_auth
def get_one(clip_id: str):
    conn = db.get_db()
    clip = db.get_clip(conn, clip_id)
    if not clip:
        return jsonify({"error": "not found"}), 404
    return _send_clip(clip)


@bp.get("/clip/<clip_id>/meta")
@requires_auth
def get_meta(clip_id: str):
    conn = db.get_db()
    clip = db.get_clip(conn, clip_id)
    if not clip:
        return jsonify({"error": "not found"}), 404
    return jsonify(clip)


@bp.delete("/clip/<clip_id>")
@requires_auth
def delete_one(clip_id: str):
    conn = db.get_db()
    blobs_dir = current_app.config["CLIPSYNC_BLOBS_DIR"]
    if not db.delete_clip(conn, clip_id):
        return jsonify({"error": "not found"}), 404
    storage.delete_blob(blobs_dir, clip_id)
    current_app.config["CLIPSYNC_BROKER"].publish("clip.deleted", {"id": clip_id})
    return jsonify({"ok": True})


@bp.delete("/clips")
@requires_auth
def clear_all():
    conn = db.get_db()
    blobs_dir = current_app.config["CLIPSYNC_BLOBS_DIR"]
    ids = db.clear_clips(conn)
    storage.delete_blobs(blobs_dir, ids)
    current_app.config["CLIPSYNC_BROKER"].publish("clips.cleared", {"count": len(ids)})
    return jsonify({"ok": True, "deleted": len(ids)})


@bp.get("/events")
@requires_auth
def events():
    broker = current_app.config["CLIPSYNC_BROKER"]
    resp = Response(sse_stream(broker), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"] = "keep-alive"
    return resp
