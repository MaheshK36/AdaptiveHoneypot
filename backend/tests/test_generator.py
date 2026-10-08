from pathlib import Path
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
import pytest

from app.synthetic import build_session_files, generate_environment


def test_seeded_environment_is_deterministic() -> None:
    first = generate_environment(seed="demo")
    second = generate_environment(seed="demo")

    assert first == second
    assert first["database"]["user"] == second["database"]["user"]


def test_seeded_environment_changes_with_seed() -> None:
    first = generate_environment(seed="alpha")
    second = generate_environment(seed="beta")

    assert first != second
    assert first["hostname"] != second["hostname"] or first["database"]["password"] != second["database"]["password"]


def test_session_file_generator_writes_expected_entries() -> None:
    files = build_session_files(session_id="42", seed="demo", trail="db_trail")

    assert str(files)
    assert any("etc/passwd" in item for item in files)
    assert any(".env" in item for item in files)

    passwd_path = next(Path(path) for path in files if path.endswith("/etc/passwd"))
    session_root = passwd_path.parents[1]
    entries = [line.split(":") for line in passwd_path.read_text(encoding="utf-8").splitlines()]
    assert all(len(entry) == 7 for entry in entries)
    assert any(entry[0] == "root" and entry[2] == "0" for entry in entries)
    assert any(entry[0] != "root" and entry[2] != "0" for entry in entries)
    assert all((session_root / entry[5].lstrip("/")).is_dir() for entry in entries)


def test_session_id_cannot_escape_session_root() -> None:
    with pytest.raises(ValueError, match="session_id"):
        build_session_files(session_id="../outside", seed="demo")


def test_admin_trail_keypair_is_seeded_and_private_key_is_restricted() -> None:
    session_id = f"key-check-{secrets.token_hex(6)}"
    files = build_session_files(session_id=session_id, seed="key-seed", trail="admin_trail")
    private_path = next(Path(path) for path in files if path.endswith("/.ssh/id_ed25519"))
    public_path = next(Path(path) for path in files if path.endswith("/.ssh/id_ed25519.pub"))
    private_key = load_pem_private_key(private_path.read_bytes(), password=None)
    derived_public_key = private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("ascii")

    assert derived_public_key == public_path.read_text(encoding="utf-8").strip()
    assert private_path.stat().st_mode & 0o777 == 0o600
    session_root = private_path.parents[3]
    assert (session_root / "web/admin.html").is_file()
    backup = (session_root / "web/backup.sql").read_text(encoding="utf-8")
    assert f"{generate_environment('key-seed')['database']['user']}" not in backup
    assert all(user["username"] in backup for user in generate_environment("key-seed")["database"]["users"])
