from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mysql_mimic import IdentityProvider, MysqlServer, NativePasswordAuthPlugin, Session, User
from sqlglot.executor import execute
import httpx


SESSION_ROOT = Path(os.environ["FAKE_DB_SESSION_ROOT"])
LOG_PATH = Path(os.environ["LOG_DIR"]) / "events.jsonl"
MAX_SESSIONS = int(os.environ["FAKE_DB_MAX_SESSIONS"])
SERVER_BIND_ADDRESS = os.environ["FAKE_DB_BIND_ADDRESS"]
SERVER_PORT = int(os.environ["FAKE_DB_PORT"])
EVENT_INGEST_URL = os.environ["EVENT_INGEST_URL"]
EVENT_INGEST_TIMEOUT = float(os.environ["EVENT_INGEST_TIMEOUT"])


class SessionPasswordPlugin(NativePasswordAuthPlugin):
    def __init__(self, registry: SessionRegistry) -> None:
        self.registry = registry

    def password_matches(self, user: User, scramble: bytes, nonce: bytes) -> bool:
        accepted = super().password_matches(user, scramble, nonce)
        record = self.registry.record_for(user.name)
        write_event(
            record[0] if record else None,
            None,
            "LOGIN_ATTEMPT",
            user.name,
            {"auth_plugin": self.name, "accepted": accepted},
        )
        return accepted


class SessionRegistry(IdentityProvider):
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, dict[str, Any]]] = {}
        self.password_plugin = SessionPasswordPlugin(self)

    def get_plugins(self) -> list[NativePasswordAuthPlugin]:
        return [self.password_plugin]

    def _find_record(self, username: str) -> tuple[str, dict[str, Any]] | None:
        try:
            entries = SESSION_ROOT.iterdir()
        except OSError:
            return None

        checked = 0
        for session_dir in entries:
            if checked >= MAX_SESSIONS:
                break
            checked += 1
            if not session_dir.is_dir():
                continue
            metadata_path = session_dir / "session.json"
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                environment = metadata["environment"]
                database = environment["database"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
            if database.get("user") == username:
                return session_dir.name, environment
        return None

    async def get_user(self, username: str) -> User | None:
        record = self._find_record(username)
        if record is None:
            write_event(None, None, "LOGIN_ATTEMPT", username, {"accepted": False})
            return None
        session_id, environment = record
        self.records[username] = record
        password = environment["database"]["password"]
        return User(
            name=username,
            auth_string=NativePasswordAuthPlugin.create_auth_string(password),
            auth_plugin=NativePasswordAuthPlugin.name,
        )

    def record_for(self, username: str | None) -> tuple[str, dict[str, Any]] | None:
        if not username:
            return None
        return self.records.get(username)


def write_event(
    session_id: str | None,
    src_ip: str | None,
    event_type: str,
    command: str,
    detail: dict[str, Any],
) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "src_ip": src_ip,
        "service": "db",
        "event_type": event_type,
        "command": command[:1024],
        "detail": detail,
    }
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        logging.exception("Unable to persist database event")
    try:
        response = httpx.post(EVENT_INGEST_URL, json=payload, timeout=EVENT_INGEST_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError:
        logging.warning("Unable to ingest database event", exc_info=True)


class SyntheticSession(Session):
    def __init__(self, registry: SessionRegistry) -> None:
        super().__init__()
        self.registry = registry

    def _src_ip(self) -> str | None:
        try:
            peer = self.connection.stream.writer.get_extra_info("peername")
            return str(peer[0]) if peer else None
        except (AttributeError, IndexError):
            return None

    def _record(self) -> tuple[str, dict[str, Any]] | None:
        return self.registry.record_for(self.username)

    async def init(self, connection) -> None:
        await super().init(connection)
        if not self.username:
            return
        record = self._record()
        write_event(record[0] if record else None, self._src_ip(), "LOGIN_SUCCESS", self.username or "", {})
        write_event(record[0] if record else None, self._src_ip(), "CONNECT", "connect", {})

    async def close(self) -> None:
        record = self._record()
        write_event(record[0] if record else None, self._src_ip(), "LOGOUT", "disconnect", {})
        await super().close()

    async def query(self, expression, sql: str, attrs: dict[str, str]):
        record = self._record()
        if record is None:
            return [], []
        session_id, environment = record
        database = environment["database"]
        tables = {"users": database["users"], "orders": database["orders"]}
        result = execute(expression, tables=tables)
        write_event(
            session_id,
            self._src_ip(),
            "DB_QUERY",
            sql,
            {"database": database["name"], "query": sql[:2048]},
        )
        return result.rows, result.columns

    async def schema(self) -> dict[str, dict[str, dict[str, str]]]:
        record = self._record()
        if record is None:
            return {}
        database = record[1]["database"]
        return {
            database["name"]: {
                "users": {"id": "INT", "username": "TEXT", "email": "TEXT", "role": "TEXT"},
                "orders": {"id": "INT", "user_id": "INT", "product": "TEXT", "status": "TEXT", "total": "DOUBLE"},
            }
        }


async def serve() -> None:
    os.umask(0o002)
    registry = SessionRegistry()
    server = MysqlServer(session_factory=lambda: SyntheticSession(registry), identity_provider=registry)
    await server.serve_forever(host=SERVER_BIND_ADDRESS, port=SERVER_PORT)


if __name__ == "__main__":
    asyncio.run(serve())