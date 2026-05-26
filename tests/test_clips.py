from __future__ import annotations

import io
import json
import time


def _push_text(client, auth_headers, text="hello world", label="pytest"):
    return client.post(
        "/api/clip",
        headers={
            **auth_headers,
            "Content-Type": "text/plain; charset=utf-8",
            "X-Device-Label": label,
        },
        data=text.encode("utf-8"),
    )


def test_push_and_get_latest_text(client, auth_headers):
    r = _push_text(client, auth_headers, "hello world")
    assert r.status_code == 201
    cid = r.json["id"]
    assert r.json["type"] == "text"

    raw = client.get("/api/clip/latest", headers=auth_headers)
    assert raw.status_code == 200
    assert raw.data == b"hello world"

    txt = client.get("/api/clip/latest.txt", headers=auth_headers)
    assert txt.status_code == 200
    assert txt.headers["Content-Type"].startswith("text/plain")

    bin_ = client.get("/api/clip/latest.bin", headers=auth_headers)
    assert bin_.status_code == 200
    assert bin_.headers["Content-Type"] == "application/octet-stream"

    meta = client.get(f"/api/clip/{cid}/meta", headers=auth_headers).json
    assert meta["device_label"] == "pytest"
    assert meta["size"] == len(b"hello world")
    assert meta["preview"] == "hello world"


def test_latest_404_when_empty(client, auth_headers):
    r = client.get("/api/clip/latest", headers=auth_headers)
    assert r.status_code == 404


def test_latest_txt_rejects_non_text(client, auth_headers):
    client.post(
        "/api/clip",
        headers={**auth_headers, "Content-Type": "application/octet-stream"},
        data=b"\x00\x01\x02",
    )
    r = client.get("/api/clip/latest.txt", headers=auth_headers)
    assert r.status_code == 409


def test_push_multipart_file(client, auth_headers):
    r = client.post(
        "/api/clip",
        headers=auth_headers,
        data={"file": (io.BytesIO(b"binary contents"), "thing.dat", "application/octet-stream")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    cid = r.json["id"]
    meta = client.get(f"/api/clip/{cid}/meta", headers=auth_headers).json
    assert meta["type"] == "file"
    assert meta["filename"] == "thing.dat"

    blob = client.get(f"/api/clip/{cid}", headers=auth_headers)
    assert blob.status_code == 200
    assert blob.data == b"binary contents"


def test_push_multipart_image(client, auth_headers):
    png_stub = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    r = client.post(
        "/api/clip",
        headers=auth_headers,
        data={"file": (io.BytesIO(png_stub), "shot.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    assert r.json["type"] == "image"


def test_list_returns_metadata_only(client, auth_headers):
    _push_text(client, auth_headers, "one")
    _push_text(client, auth_headers, "two")
    rows = client.get("/api/clips", headers=auth_headers).json
    assert len(rows) == 2
    assert rows[0]["preview"] == "two"
    assert "preview" in rows[0] and "id" in rows[0]


def test_delete_clip(client, auth_headers):
    cid = _push_text(client, auth_headers).json["id"]
    r = client.delete(f"/api/clip/{cid}", headers=auth_headers)
    assert r.status_code == 200
    assert client.get(f"/api/clip/{cid}", headers=auth_headers).status_code == 404


def test_clear_all(client, auth_headers):
    _push_text(client, auth_headers, "a")
    _push_text(client, auth_headers, "b")
    r = client.delete("/api/clips", headers=auth_headers)
    assert r.status_code == 200
    assert r.json["deleted"] == 2
    assert client.get("/api/clips", headers=auth_headers).json == []


def test_size_cap_enforced_raw(client, auth_headers):
    # Cap to 1 MB to make the test fast.
    client.post("/api/settings", headers=auth_headers, json={"max_item_size_mb": 1})
    big = b"x" * (2 * 1024 * 1024)
    r = client.post(
        "/api/clip",
        headers={**auth_headers, "Content-Type": "application/octet-stream"},
        data=big,
    )
    assert r.status_code == 413


def test_size_cap_zero_means_unlimited(client, auth_headers, app):
    client.post("/api/settings", headers=auth_headers, json={"max_item_size_mb": 0})
    payload = b"y" * (256 * 1024)
    r = client.post(
        "/api/clip",
        headers={**auth_headers, "Content-Type": "application/octet-stream"},
        data=payload,
    )
    assert r.status_code == 201


def test_history_eviction(client, auth_headers, app):
    client.post("/api/settings", headers=auth_headers, json={"history_size": 3})
    ids = [_push_text(client, auth_headers, f"item-{i}").json["id"] for i in range(5)]
    rows = client.get("/api/clips", headers=auth_headers).json
    assert [r["id"] for r in rows] == list(reversed(ids[-3:]))

    import os
    from app import storage

    for cid in ids[:2]:
        path = storage.blob_path(app.config["CLIPSYNC_BLOBS_DIR"], cid)
        assert not os.path.exists(path)


def test_ttl_eviction_direct(app):
    from app import db, storage

    db_path = app.config["CLIPSYNC_DB_PATH"]
    blobs_dir = app.config["CLIPSYNC_BLOBS_DIR"]

    with db.standalone_db(db_path) as conn:
        storage.write_bytes(blobs_dir, "old1", b"x")
        conn.execute(
            "INSERT INTO clips(id, type, mime, size, filename, device_label, preview, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("old1", "text", "text/plain", 1, None, "test", "x", int(time.time()) - 3600 * 48),
        )
        conn.commit()
        evicted = db.evict_expired(conn, 24)
        assert evicted == ["old1"]


def test_sse_emits_clip_new(client, auth_headers, app):
    broker = app.config["CLIPSYNC_BROKER"]
    q = broker.subscribe()
    try:
        r = _push_text(client, auth_headers, "for-sse")
        assert r.status_code == 201
        event, data = q.get(timeout=2)
        assert event == "clip.new"
        assert data["preview"] == "for-sse"
    finally:
        broker.unsubscribe(q)


def test_latest_sets_content_disposition_with_extension(client, auth_headers):
    import re

    # Filename pattern: clip-<id8>-<timestamp>[-<original>].<ext>
    # The timestamp guarantees repeated fetches don't collide on the client.
    ts = r"\d{8}T\d{9}Z"  # YYYYMMDDTHHMMSSmmmZ

    # Text push: no original filename — server synthesizes clip-<id8>-<ts>.txt
    cid = _push_text(client, auth_headers, "hi").json["id"]
    r = client.get("/api/clip/latest", headers=auth_headers)
    cd = r.headers["Content-Disposition"]
    assert re.search(rf"clip-{cid[:8]}-{ts}\.txt", cd), cd

    # Image upload with original filename — preserved, prefixed, timestamped.
    png_stub = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    img_cid = client.post(
        "/api/clip",
        headers=auth_headers,
        data={"file": (io.BytesIO(png_stub), "shot.png", "image/png")},
        content_type="multipart/form-data",
    ).json["id"]
    r = client.get("/api/clip/latest", headers=auth_headers)
    cd = r.headers["Content-Disposition"]
    assert re.search(rf"clip-{img_cid[:8]}-{ts}-shot\.png", cd), cd

    # Image upload with no original filename — clip-<id8>-<ts>.png.
    cid2 = client.post(
        "/api/clip",
        headers={**auth_headers, "Content-Type": "image/png"},
        data=png_stub,
    ).json["id"]
    r = client.get("/api/clip/latest", headers=auth_headers)
    cd = r.headers["Content-Disposition"]
    assert re.search(rf"clip-{cid2[:8]}-{ts}\.png", cd), cd

    # Two fetches of the same clip must yield distinct download filenames
    # (otherwise `curl -OJ` would refuse to overwrite the first download).
    time.sleep(0.005)
    r2 = client.get("/api/clip/latest", headers=auth_headers)
    assert r.headers["Content-Disposition"] != r2.headers["Content-Disposition"]


def test_device_label_falls_back(client, auth_headers):
    r = client.post(
        "/api/clip",
        headers={**auth_headers, "Content-Type": "text/plain"},
        data=b"no label",
    )
    assert r.status_code == 201
    cid = r.json["id"]
    meta = client.get(f"/api/clip/{cid}/meta", headers=auth_headers).json
    assert meta["device_label"] != ""
    assert meta["device_label"] != "pytest"
