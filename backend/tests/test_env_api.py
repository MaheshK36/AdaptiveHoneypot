import json
import os
import secrets
from pathlib import Path

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_env_api.db")
os.environ.setdefault("SESSION_ROOT", "/tmp/honeypot_sessions_test")
os.environ.setdefault("LOG_DIR", "/tmp/honeypot_logs_test")
os.environ.setdefault("EVIDENCE_DIR", "/tmp/honeypot_evidence_test")

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_add_trail_and_state() -> None:
    response = client.post("/env/101/add-trail", json={"trail": "db_trail"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["trail"] == "db_trail"

    session_dir = Path(settings.session_root) / "101"
    generated_config = (session_dir / "opt/app/.env").read_text(encoding="utf-8")
    environment = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))["environment"]
    assert f"DB_PASSWORD={environment['database']['password']}" in generated_config

    state = client.get("/env/101/state")
    assert state.status_code == 200
    assert state.json()["status"] in {"active", "reset"}


def test_reset_and_terminate_endpoints() -> None:
    reset = client.post("/env/101/reset")
    assert reset.status_code == 200

    terminate = client.post("/env/101/terminate")
    assert terminate.status_code == 200
    assert terminate.json()["status"] == "terminated"


def test_start_session_creates_requested_user_idempotently() -> None:
    session_id = f"cowrie-{secrets.token_hex(6)}"
    payload = {"requested_username": "fieldtech"}
    first = client.post(f"/env/{session_id}/start", json=payload)
    second = client.post(f"/env/{session_id}/start", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["hostname"] == second.json()["hostname"]
    assert first.json()["login_username"] == second.json()["login_username"] == "fieldtech"

    session_dir = Path(settings.session_root) / session_id
    passwd = (session_dir / "etc/passwd").read_text(encoding="utf-8")
    assert any(line.startswith("fieldtech:x:") for line in passwd.splitlines())
    assert (session_dir / "home/fieldtech").is_dir()
