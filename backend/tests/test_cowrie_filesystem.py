from __future__ import annotations

import json
import os
from pathlib import Path
import select

import paramiko
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_ssh_shell_uses_generated_per_session_filesystem() -> None:
    cowrie_host = os.environ.get("COWRIE_TEST_HOST")
    if not cowrie_host:
        pytest.skip("COWRIE_TEST_HOST is not configured")

    session_root = Path(settings.session_root)
    cowrie_log_path = Path(os.environ["COWRIE_JSON_LOG_PATH"])
    log_offset = cowrie_log_path.stat().st_size
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=cowrie_host,
            port=int(os.environ["COWRIE_TEST_PORT"]),
            username="root",
            password="integration-probe",
            timeout=5,
            banner_timeout=5,
            auth_timeout=5,
            allow_agent=False,
            look_for_keys=False,
        )
        shell = client.invoke_shell()
        shell.settimeout(5)

        def read_until_prompt() -> str:
            output = bytearray()
            while True:
                ready, _, _ = select.select([shell], [], [], 5)
                assert ready, "Cowrie shell did not return a prompt"
                output.extend(shell.recv(8192))
                if output.rstrip().endswith((b"#", b"$")):
                    return output.decode("utf-8", errors="replace")

        read_until_prompt()
        shell.send("cat /etc/passwd\n")
        passwd_contents = read_until_prompt()
        shell.send("cat /etc/hostname\n")
        hostname_contents = read_until_prompt().strip()
        shell.send("uname -a\n")
        uname_contents = read_until_prompt()

        with cowrie_log_path.open("rb") as handle:
            handle.seek(log_offset)
            events = [json.loads(line) for line in handle if line.strip()]
        generated_ids = [
            event["environment_session_id"]
            for event in events
            if event.get("eventid") == "cowrie.session.params" and event.get("environment_session_id")
        ]
        assert generated_ids
        session_dir = session_root / generated_ids[-1]
        trail_response = TestClient(app).post(
            f"/env/{generated_ids[-1]}/add-trail",
            json={"trail": "db_trail"},
        )
        assert trail_response.status_code == 200
        shell.send("cat /etc/my.cnf\n")
        database_config = read_until_prompt()
    finally:
        client.close()

    session_data = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    environment = session_data["environment"]
    assert environment["hostname"] in hostname_contents
    assert environment["server"]["kernel_release"] in uname_contents
    assert environment["server"]["distribution"] in uname_contents
    assert any(line.startswith("root:x:0:0:") for line in passwd_contents.splitlines())
    assert all(user["username"] in passwd_contents for user in environment["users"])
    assert f"host = {environment['database']['host']}" in database_config
    assert f"password = {environment['database']['password']}" in database_config