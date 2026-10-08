from __future__ import annotations

from datetime import datetime, timezone
import secrets

from fastapi.testclient import TestClient
from sqlalchemy import func

from app.db import SessionLocal
from app.main import app
from app.models import EventRecord, SessionRecord


def test_event_ingestion_tracks_and_closes_external_session() -> None:
    session_id = f"cowrie-{secrets.token_hex(8)}"
    client = TestClient(app)
    connected_at = datetime.now(timezone.utc)
    for event_type, command in (("CONNECT", "connect"), ("COMMAND", "id"), ("LOGOUT", "disconnect")):
        response = client.post(
            "/events",
            json={
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "src_ip": None,
                "service": "cowrie",
                "event_type": event_type,
                "command": command,
                "detail": {},
            },
        )
        assert response.status_code == 202

    with SessionLocal() as db:
        session = db.query(SessionRecord).filter(SessionRecord.external_id == session_id).one()
        event_count = db.query(func.count(EventRecord.id)).filter(EventRecord.session_id == session.id).scalar()

    assert session.status == "closed"
    assert session.ended_at is not None
    assert event_count == 3
    assert connected_at <= session.ended_at


def test_event_without_session_is_stored_without_fake_session_row() -> None:
    response = TestClient(app).post(
        "/events",
        json={
            "ts": datetime.now(timezone.utc).isoformat(),
            "service": "http",
            "event_type": "HTTP_REQUEST",
            "command": "GET",
            "detail": {"path": "/"},
        },
    )
    assert response.status_code == 202


def test_cowrie_session_alias_merges_pre_auth_events() -> None:
    native_session_id = f"cowrie-{secrets.token_hex(8)}"
    environment_session_id = f"cw-{secrets.token_hex(16)}"
    client = TestClient(app)
    events = [
        (native_session_id, "CONNECT", {}),
        (
            native_session_id,
            "CONNECT",
            {"environment_session_id": environment_session_id},
        ),
        (environment_session_id, "LOGOUT", {}),
    ]
    for session_id, event_type, detail in events:
        response = client.post(
            "/events",
            json={
                "ts": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "service": "cowrie",
                "event_type": event_type,
                "command": event_type.lower(),
                "detail": detail,
            },
        )
        assert response.status_code == 202

    with SessionLocal() as db:
        session = db.query(SessionRecord).filter(SessionRecord.external_id == environment_session_id).one()
        duplicate = db.query(SessionRecord).filter(SessionRecord.external_id == native_session_id).first()
        event_count = db.query(func.count(EventRecord.id)).filter(EventRecord.session_id == session.id).scalar()

    assert session.status == "closed"
    assert duplicate is None
    assert event_count == 3