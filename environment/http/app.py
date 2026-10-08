from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
import httpx


CONTENT_ROOT = Path(os.environ["FAKE_HTTP_CONTENT_ROOT"]).resolve()
SESSION_CONTENT_ROOT = Path(os.environ["FAKE_HTTP_SESSIONS_ROOT"]).resolve()
LOG_PATH = Path(os.environ["LOG_DIR"]) / "events.jsonl"
SERVER_HEADER = os.environ["FAKE_HTTP_SERVER_HEADER"]
EVENT_INGEST_URL = os.environ["EVENT_INGEST_URL"]
EVENT_INGEST_TIMEOUT = float(os.environ["EVENT_INGEST_TIMEOUT"])
SESSION_COOKIE = "honeypot_session"
LOG_LOCK = threading.Lock()
os.umask(0o002)

app = FastAPI()


def log_event(request: Request, event_type: str, command: str, detail: dict) -> None:
    path_parts = request.url.path.split("/")
    session_id = getattr(request.state, "session_id", None)
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "src_ip": request.client.host if request.client else None,
        "service": "http",
        "event_type": event_type,
        "command": command,
        "detail": detail,
    }
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_LOCK, LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        logging.exception("Unable to persist HTTP event")
    try:
        response = httpx.post(EVENT_INGEST_URL, json=payload, timeout=EVENT_INGEST_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError:
        logging.warning("Unable to ingest HTTP event", exc_info=True)


def request_session_id(request: Request) -> tuple[str, bool]:
    path_parts = request.url.path.split("/")
    if len(path_parts) > 2 and path_parts[1] == "sessions":
        return path_parts[2], False
    existing = request.cookies.get(SESSION_COOKIE)
    if existing:
        return existing, False
    return f"http-{secrets.token_hex(16)}", True


@app.middleware("http")
async def record_http_request(request: Request, call_next) -> Response:
    session_id, is_new_session = request_session_id(request)
    request.state.session_id = session_id
    response = await call_next(request)
    response.headers["Server"] = SERVER_HEADER
    if is_new_session:
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax")
    log_event(
        request,
        event_type="HTTP_REQUEST",
        command=request.method,
        detail={"path": request.url.path, "status_code": response.status_code},
    )
    return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(CONTENT_ROOT / "index.html")


@app.get("/admin.html")
def admin() -> FileResponse:
    return FileResponse(CONTENT_ROOT / "admin.html")


@app.get("/robots.txt")
def robots() -> FileResponse:
    return FileResponse(CONTENT_ROOT / "robots.txt", media_type="text/plain")


@app.get("/backup.sql")
def backup() -> FileResponse:
    return FileResponse(CONTENT_ROOT / "backup.sql", media_type="application/sql")


@app.get("/sessions/{session_id}/{asset_path:path}")
def session_asset(session_id: str, asset_path: str) -> FileResponse:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session_id):
        raise HTTPException(status_code=404)
    parts = Path(asset_path).parts
    if not asset_path or any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=404)
    public_root = (SESSION_CONTENT_ROOT / session_id / "web").resolve()
    target = (public_root / asset_path).resolve()
    if public_root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target)


@app.post("/login")
async def login(request: Request) -> Response:
    content_type = request.headers.get("content-type", "")
    username = ""
    password_length = 0
    if content_type.startswith("application/x-www-form-urlencoded"):
        from urllib.parse import parse_qs

        fields = parse_qs((await request.body()).decode("utf-8", errors="replace"), max_num_fields=16)
        username = fields.get("username", [""])[0][:128]
        password_length = len(fields.get("password", [""])[0])

    log_event(
        request,
        event_type="LOGIN_ATTEMPT",
        command="POST /login",
        detail={"username": username, "password_length": password_length},
    )
    return FileResponse(CONTENT_ROOT / "index.html", status_code=401)


@app.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    log_event(request, event_type="LOGOUT", command="POST /logout", detail={})
    response.delete_cookie(SESSION_COOKIE)
    return response