import os

from fastapi import FastAPI

from app.config import settings
from app.db import Base, engine
from app.routers.events import router as events_router
from app.routers.env import router as env_router
from app.routers.health import router as health_router
from app.schema_migrations import ensure_database_schema

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Environment-layer control API for the Adaptive Honeypot MVP.",
)

app.include_router(health_router)
app.include_router(env_router)
app.include_router(events_router)


@app.on_event("startup")
def startup() -> None:
    os.umask(0o002)
    ensure_database_schema(engine)


@app.get("/")
def read_root() -> dict:
    return {
        "message": "Adaptive Honeypot API",
        "version": "0.1.0",
        "environment": settings.app_env,
    }
