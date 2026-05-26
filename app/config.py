from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    data_dir: str
    secret_key: str
    bootstrap_username: str | None
    bootstrap_password: str | None
    port: int

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "clipsync.db")

    @property
    def blobs_dir(self) -> str:
        return os.path.join(self.data_dir, "blobs")


def load_config() -> Config:
    data_dir = os.environ.get("CLIPSYNC_DATA_DIR", "/data")
    secret_key = os.environ.get("CLIPSYNC_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("CLIPSYNC_SECRET_KEY is required")
    return Config(
        data_dir=data_dir,
        secret_key=secret_key,
        bootstrap_username=os.environ.get("CLIPSYNC_USERNAME"),
        bootstrap_password=os.environ.get("CLIPSYNC_PASSWORD"),
        port=int(os.environ.get("CLIPSYNC_PORT", "8080")),
    )


DEFAULT_SETTINGS: dict[str, int] = {
    "history_size": 50,
    "item_ttl_hours": 24,
    "max_item_size_mb": 100,
}
