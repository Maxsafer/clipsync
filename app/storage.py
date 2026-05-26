from __future__ import annotations

import os
from typing import BinaryIO


CHUNK = 64 * 1024


class SizeExceeded(Exception):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"upload exceeds limit of {limit} bytes")


def blob_path(blobs_dir: str, clip_id: str) -> str:
    return os.path.join(blobs_dir, clip_id)


def write_stream(blobs_dir: str, clip_id: str, src: BinaryIO, max_bytes: int) -> int:
    """Stream src into blobs_dir/clip_id. Returns bytes written.

    max_bytes == 0 means unlimited. Raises SizeExceeded if cap is crossed and
    cleans up the partial file.
    """
    os.makedirs(blobs_dir, exist_ok=True)
    path = blob_path(blobs_dir, clip_id)
    written = 0
    try:
        with open(path, "wb") as out:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if max_bytes and written > max_bytes:
                    raise SizeExceeded(max_bytes)
                out.write(chunk)
    except BaseException:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise
    return written


def write_bytes(blobs_dir: str, clip_id: str, data: bytes) -> int:
    os.makedirs(blobs_dir, exist_ok=True)
    path = blob_path(blobs_dir, clip_id)
    with open(path, "wb") as out:
        out.write(data)
    return len(data)


def read_bytes(blobs_dir: str, clip_id: str) -> bytes:
    with open(blob_path(blobs_dir, clip_id), "rb") as f:
        return f.read()


def delete_blob(blobs_dir: str, clip_id: str) -> None:
    try:
        os.unlink(blob_path(blobs_dir, clip_id))
    except FileNotFoundError:
        pass


def delete_blobs(blobs_dir: str, clip_ids: list[str]) -> None:
    for cid in clip_ids:
        delete_blob(blobs_dir, cid)
