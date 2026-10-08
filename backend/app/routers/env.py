from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import EventRecord, SessionRecord
from app.session_tracking import ensure_session_record
from app.synthetic import build_session_files, get_session_state

router = APIRouter(tags=["environment"])


class TrailRequest(BaseModel):
    trail: str


class SessionStartRequest(BaseModel):
    requested_username: str | None = Field(default=None, max_length=128)


class SessionState(BaseModel):
    session_id: str
    status: str
    trail: str | None = None
    data_dir: str | None = None


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _log_event(db: Session, session_id: str, service: str, event_type: str, command: str, detail: dict) -> None:
    session = db.query(SessionRecord).filter(SessionRecord.external_id == session_id).first()
    if session is None and session_id.isdecimal():
        session = db.get(SessionRecord, int(session_id))
    if not session:
        return

    event = EventRecord(
        session_id=session.id,
        event_type=event_type,
        service=service,
        command=command,
        detail_json=json.dumps(detail),
    )
    db.add(event)
    db.commit()

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "src_ip": session.src_ip,
        "service": service,
        "event_type": event_type,
        "command": command,
        "detail": detail,
    }
    log_path = log_dir / "events.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _ensure_session(db: Session, session_id: str, src_ip: str | None) -> SessionRecord:
    session = ensure_session_record(db, session_id, src_ip)
    db.commit()
    db.refresh(session)
    return session


@router.post("/env/{session_id}/add-trail")
def add_trail(session_id: str, payload: TrailRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    allowed = {"db_trail", "admin_trail"}
    if payload.trail not in allowed:
        raise HTTPException(status_code=400, detail=f"trail must be one of: {sorted(allowed)}")

    session = _ensure_session(db, session_id, src_ip=request.client.host if request.client else None)
    session.deception_profile = payload.trail
    session.status = "active"
    previous = get_session_state(session_id)
    created = build_session_files(
        session_id,
        seed=session_id,
        trail=payload.trail,
        requested_username=previous.get("requested_username"),
    )
    _log_event(db, session_id, service="control_api", event_type="FILE_ACCESS", command=f"add_trail:{payload.trail}", detail={"files": sorted(created.keys()), "trail": payload.trail})
    db.commit()
    return {"session_id": session_id, "trail": payload.trail, "files": sorted(created.keys()), "status": "ok"}


@router.post("/env/{session_id}/start")
def start_session(
    session_id: str,
    payload: SessionStartRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    session = _ensure_session(db, session_id, src_ip=request.client.host if request.client else None)
    previous = get_session_state(session_id)
    if not previous.get("exists"):
        build_session_files(session_id, seed=session_id, requested_username=payload.requested_username)
        previous = get_session_state(session_id)
    session.status = "active"
    db.commit()
    _log_event(db, session_id, "control_api", "CONNECT", "start-session", {})
    return {
        "session_id": session_id,
        "status": "active",
        "data_dir": str(Path(settings.session_root) / session_id),
        "hostname": previous["environment"]["hostname"],
        "login_username": previous["environment"]["ssh_login_username"],
    }


@router.post("/env/{session_id}/reset")
def reset_session(session_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    session = _ensure_session(db, session_id, src_ip=request.client.host if request.client else None)
    previous = get_session_state(session_id)
    build_session_files(
        session_id,
        seed=session_id,
        trail=None,
        requested_username=previous.get("requested_username"),
    )
    session.status = "reset"
    session.deception_profile = "default"
    _log_event(db, session_id, service="control_api", event_type="COMMAND", command="reset", detail={"action": "reset-session"})
    db.commit()
    return {"session_id": session_id, "status": "reset", "trail": None}


@router.post("/env/{session_id}/terminate")
def terminate_session(session_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    session = _ensure_session(db, session_id, src_ip=request.client.host if request.client else None)
    session.status = "terminated"
    session.ended_at = datetime.now(timezone.utc)
    _log_event(db, session_id, service="control_api", event_type="LOGOUT", command="terminate", detail={"action": "terminate-session"})
    db.commit()

    evidence_dir = Path(settings.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    source_log = Path(settings.log_dir) / "events.jsonl"
    if source_log.exists():
        blob = source_log.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        target = evidence_dir / f"{session_id}-{digest}.jsonl"
        target.write_bytes(blob)
    return {"session_id": session_id, "status": "terminated", "evidence_sha256": hashlib.sha256((source_log.read_bytes() if source_log.exists() else b"")).hexdigest()}


@router.get("/env/{session_id}/state")
def get_state(session_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    session = _ensure_session(db, session_id, src_ip=request.client.host if request.client else None)
    return {
        "session_id": session_id,
        "status": session.status,
        "trail": session.deception_profile,
        "src_ip": session.src_ip,
        "data_dir": str(Path(settings.session_root) / session_id),
    }
