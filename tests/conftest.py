from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app
from app.config import Config


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        data_dir=str(tmp_path),
        secret_key="test-secret",
        bootstrap_username="alice",
        bootstrap_password="hunter2hunter",
        port=0,
    )


@pytest.fixture
def app(cfg):
    application = create_app(cfg, start_background=False)
    application.config["TESTING"] = True
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def token(app):
    from app import db

    with db.standalone_db(app.config["CLIPSYNC_DB_PATH"]) as conn:
        return db.auth_row(conn)["api_token"]


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}
