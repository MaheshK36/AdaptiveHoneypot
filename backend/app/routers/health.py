from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal

router = APIRouter(prefix="/api", tags=["system"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/health")
def healthcheck(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "up"
        detail = "Database connection successful."
    except Exception as exc:  # pragma: no cover - defensive fallback
        db_status = "down"
        detail = f"Database unreachable: {exc.__class__.__name__}"

    return {
        "status": "ok",
        "service": "adaptive-honeypot-backend",
        "environment": settings.app_env,
        "database": db_status,
        "details": detail,
    }
