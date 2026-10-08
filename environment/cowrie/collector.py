from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


SOURCE_PATH = Path(os.environ["COWRIE_JSON_LOG_PATH"])
LOG_DIR = Path(os.environ["LOG_DIR"])
EVENT_LOG_PATH = LOG_DIR / "events.jsonl"
CURSOR_PATH = LOG_DIR / "cowrie-collector-state.json"
INGEST_URL = os.environ["EVENT_INGEST_URL"]
POLL_INTERVAL = float(os.environ["COLLECTOR_POLL_INTERVAL"])
MAX_LINE_BYTES = int(os.environ["COLLECTOR_MAX_LINE_BYTES"])
MAX_MAPPINGS = int(os.environ["COLLECTOR_MAX_MAPPINGS"])
EVENT_TIMEOUT = float(os.environ["EVENT_INGEST_TIMEOUT"])
HEARTBEAT_PATH = LOG_DIR / "cowrie-collector-heartbeat"

EVENT_TYPE_MAP = {
    "cowrie.session.connect": "CONNECT",
    "cowrie.login.failed": "LOGIN_ATTEMPT",
    "cowrie.login.success": "LOGIN_SUCCESS",
    "cowrie.command.input": "COMMAND",
    "cowrie.command.failed": "COMMAND",
    "cowrie.session.file_download": "FILE_ACCESS",
    "cowrie.session.file_upload": "FILE_ACCESS",
    "cowrie.session.closed": "LOGOUT",
}
SENSITIVE_DETAIL_KEYS = {"password"}


def _load_state() -> tuple[int | None, int, OrderedDict[str, str]]:
    try:
        state = json.loads(CURSOR_PATH.read_text(encoding="utf-8"))
        mappings = OrderedDict(state.get("session_mappings", []))
        return state.get("inode"), int(state.get("offset", 0)), mappings
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, 0, OrderedDict()


def _save_state(inode: int, offset: int, mappings: OrderedDict[str, str]) -> None:
    temporary = CURSOR_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "inode": inode,
                "offset": offset,
                "session_mappings": list(mappings.items()),
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(CURSOR_PATH)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_DETAIL_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:256]]
    if isinstance(value, str):
        return value[:4096]
    return value


def normalize_event(source: dict[str, Any], mappings: OrderedDict[str, str]) -> dict[str, Any] | None:
    event_id = str(source.get("eventid", ""))
    native_session_id = str(source.get("session", ""))
    if not event_id or not native_session_id:
        return None

    detail = {
        key: _sanitize(value)
        for key, value in source.items()
        if key not in {"eventid", "session", "src_ip", "timestamp", "time", "message", "format"}
    }
    environment_session_id = detail.get("environment_session_id")
    if environment_session_id:
        mappings[native_session_id] = str(environment_session_id)
        mappings.move_to_end(native_session_id)
        while len(mappings) > MAX_MAPPINGS:
            mappings.popitem(last=False)
    session_id = (
        native_session_id
        if environment_session_id
        else mappings.get(native_session_id, native_session_id)
    )

    try:
        timestamp = datetime.fromtimestamp(float(source["time"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OSError):
        try:
            timestamp = datetime.fromisoformat(str(source["timestamp"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            timestamp = datetime.now(timezone.utc)

    event_type = EVENT_TYPE_MAP.get(event_id)
    if event_type is None:
        if event_id == "cowrie.session.params":
            event_type = "CONNECT"
        elif event_id.startswith("cowrie.command."):
            event_type = "COMMAND"
        elif event_id.startswith("cowrie.session.file_"):
            event_type = "FILE_ACCESS"
        elif event_id.startswith("cowrie.session."):
            event_type = "CONNECT"
        else:
            event_type = "COMMAND"

    command = str(detail.get("input") or detail.get("username") or event_id)[:4096]
    return {
        "ts": timestamp.isoformat(),
        "session_id": session_id,
        "src_ip": source.get("src_ip"),
        "service": "cowrie",
        "event_type": event_type,
        "command": command,
        "detail": detail,
    }


def _deliver(payload: dict[str, Any], client: httpx.Client) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    response = client.post(INGEST_URL, json=payload)
    response.raise_for_status()


def run() -> None:
    os.umask(0o002)
    logging.basicConfig(level=logging.INFO)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    inode, offset, mappings = _load_state()
    with httpx.Client(timeout=EVENT_TIMEOUT) as client:
        while True:
            HEARTBEAT_PATH.write_text(str(time.time()), encoding="utf-8")
            try:
                stat_result = SOURCE_PATH.stat()
                if inode != stat_result.st_ino or stat_result.st_size < offset:
                    inode, offset = stat_result.st_ino, 0
                with SOURCE_PATH.open("rb") as source:
                    source.seek(offset)
                    while True:
                        line = source.readline(MAX_LINE_BYTES + 1)
                        if not line or not line.endswith(b"\n"):
                            break
                        next_offset = source.tell()
                        if len(line) > MAX_LINE_BYTES:
                            offset = next_offset
                            continue
                        try:
                            raw_event = json.loads(line)
                            payload = normalize_event(raw_event, mappings)
                            if payload is not None:
                                _deliver(payload, client)
                            offset = next_offset
                            _save_state(inode, offset, mappings)
                        except (json.JSONDecodeError, httpx.HTTPError, OSError, ValueError):
                            logging.warning("Cowrie event delivery failed; will retry", exc_info=True)
                            break
            except FileNotFoundError:
                pass
            except OSError:
                logging.warning("Unable to read Cowrie event log", exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()