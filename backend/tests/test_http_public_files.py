from __future__ import annotations

import os
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_http_publishes_fake_files_without_exposing_session_metadata() -> None:
    http_host = os.environ.get("FAKE_HTTP_TEST_HOST")
    if not http_host:
        pytest.skip("FAKE_HTTP_TEST_HOST is not configured")

    session_id = str(secrets.randbelow(1_000_000_000) + 1_000_000_000)
    response = TestClient(app).post(f"/env/{session_id}/add-trail", json={"trail": "admin_trail"})
    assert response.status_code == 200

    base_url = f"http://{http_host}:{os.environ['FAKE_HTTP_PORT']}"
    public_config = httpx.get(f"{base_url}/sessions/{session_id}/.env", timeout=5)
    internal_metadata = httpx.get(f"{base_url}/sessions/{session_id}/session.json", timeout=5)
    private_key = httpx.get(
        f"{base_url}/sessions/{session_id}/home/root/.ssh/id_ed25519",
        timeout=5,
    )

    assert public_config.status_code == 200
    assert internal_metadata.status_code == 404
    assert private_key.status_code == 404