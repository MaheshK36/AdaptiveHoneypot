from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db import Base


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(128), nullable=True, unique=True, index=True)
    src_ip = Column(String(45), nullable=True)
    status = Column(String(32), nullable=False, default="new")
    risk_score = Column(Float, nullable=False, default=0.0)
    awareness_score = Column(Float, nullable=False, default=0.0)
    current_stage = Column(String(64), nullable=True)
    deception_profile = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)


class EventRecord(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True, index=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    event_type = Column(String(32), nullable=False)
    service = Column(String(64), nullable=True)
    command = Column(Text, nullable=True)
    detail_json = Column(Text, nullable=True)
