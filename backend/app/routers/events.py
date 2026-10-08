from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import EventRecord
from app.session_tracking import ensure_session_record


router = APIRouter(tags=["events"])
EventType = Literal[
    "CONNECT",
    "LOGIN_ATTEMPT",
    "LOGIN_SUCCESS",
    "COMMAND",
    "FILE_ACCESS",
    "DB_QUERY",
    "HTTP_REQUEST",
    "LOGOUT",
]


class EventPayload(BaseModel):
    ts: datetime
    session_id: str | None = Field(default=None, max_length=128)
    src_ip: str | None = Field(default=None, max_length=45)
    service: str = Field(min_length=1, max_length=64)
    event_type: EventType
    command: str = Field(default="", max_length=4096)
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_detail_size(self) -> EventPayload:
        if len(json.dumps(self.detail, ensure_ascii=True).encode("utf-8")) > 65536:
            raise ValueError("detail must be 64 KiB or less")
        return self


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/events", status_code=202)
def ingest_event(payload: EventPayload, db: Session = Depends(get_db)) -> dict[str, bool]:
    tracked_session = None
    if payload.session_id is not None:
        tracked_session = ensure_session_record(db, payload.session_id, payload.src_ip)
        environment_session_id = payload.detail.get("environment_session_id")
        if isinstance(environment_session_id, str) and environment_session_id != payload.session_id:
            mapped_session = ensure_session_record(db, environment_session_id, payload.src_ip)
            if mapped_session.id != tracked_session.id:
                db.query(EventRecord).filter(EventRecord.session_id == tracked_session.id).update(
                    {EventRecord.session_id: mapped_session.id}, synchronize_session=False
                )
                mapped_session.src_ip = payload.src_ip or tracked_session.src_ip or mapped_session.src_ip
                if tracked_session.started_at < mapped_session.started_at:
                    mapped_session.started_at = tracked_session.started_at
                db.delete(tracked_session)
                tracked_session = mapped_session

        if payload.event_type == "CONNECT":
            tracked_session.status = "active"
            tracked_session.ended_at = None
        elif payload.event_type == "LOGOUT":
            tracked_session.status = "closed"
            tracked_session.ended_at = payload.ts

    event = EventRecord(
        session_id=tracked_session.id if tracked_session else None,
        ts=payload.ts,
        event_type=payload.event_type,
        service=payload.service,
        command=payload.command,
        detail_json=json.dumps(payload.detail, sort_keys=True),
    )
    db.add(event)
    db.commit()
    return {"accepted": True}