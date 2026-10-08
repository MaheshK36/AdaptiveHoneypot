from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import SessionRecord


SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
MAX_SESSION_PK = 2_147_483_647


def ensure_session_record(db: Session, external_id: str, src_ip: str | None) -> SessionRecord:
    if not SESSION_ID_PATTERN.fullmatch(external_id):
        raise HTTPException(status_code=400, detail="invalid session_id")

    session = db.query(SessionRecord).filter(SessionRecord.external_id == external_id).first()
    numeric_id = int(external_id) if external_id.isdecimal() else None
    if numeric_id is not None:
        if numeric_id <= 0 or numeric_id > MAX_SESSION_PK:
            raise HTTPException(status_code=400, detail="numeric session_id is out of range")
        session = session or db.get(SessionRecord, numeric_id)

    if session is None:
        session = SessionRecord(
            id=numeric_id,
            external_id=external_id,
            src_ip=src_ip,
            status="active",
            current_stage="reconnaissance",
            deception_profile="default",
        )
        db.add(session)
        db.flush()
    else:
        if session.external_id is None:
            session.external_id = external_id
        if session.src_ip is None and src_ip is not None:
            session.src_ip = src_ip
    return session