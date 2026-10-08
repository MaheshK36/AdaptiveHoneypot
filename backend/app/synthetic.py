from __future__ import annotations

import hashlib
import json
import random
import re
import os
import shutil
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import yaml

from app.config import settings


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
POOLS_DIR = DATA_DIR / "pools"


def stable_seed(seed: str | int | None) -> int:
    digest = hashlib.sha256(str(seed or "default").encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _load_pool(pool_name: str) -> list[str]:
    data = _load_yaml(POOLS_DIR / f"{pool_name}.yaml")
    if isinstance(data, dict):
        values = data.get("items", [])
        if isinstance(values, list):
            return [str(item) for item in values]
    if isinstance(data, list):
        return [str(item) for item in data]
    return []


def _load_template(template_name: str) -> dict[str, Any]:
    template = _load_yaml(TEMPLATES_DIR / f"{template_name}.yaml")
    return template if isinstance(template, dict) else {}


def generate_environment(
    seed: str | int | None = None,
    requested_username: str | None = None,
) -> dict[str, Any]:
    rng = random.Random(stable_seed(seed))
    first_names = _load_pool("first_names")
    last_names = _load_pool("last_names")
    services = _load_pool("services")
    commands = _load_pool("commands")
    db_roles = _load_pool("db_roles")
    email_domains = _load_pool("email_domains")
    roles = _load_pool("roles")
    products = _load_pool("products")
    order_statuses = _load_pool("order_statuses")
    history_commands = _load_pool("history_commands")
    required_pools = {
        "first_names": first_names,
        "last_names": last_names,
        "services": services,
        "commands": commands,
        "db_roles": db_roles,
        "email_domains": email_domains,
        "roles": roles,
        "products": products,
        "order_statuses": order_statuses,
        "history_commands": history_commands,
    }
    missing_pools = [pool_name for pool_name, values in required_pools.items() if not values]
    if missing_pools:
        raise ValueError(f"Required synthetic data pools are empty: {', '.join(missing_pools)}")

    users: list[dict[str, str]] = []
    for idx in range(3):
        first = rng.choice(first_names)
        last = rng.choice(last_names)
        username = f"{first}.{last}" if idx % 2 == 0 else f"{first}{rng.randint(10, 99)}"
        users.append(
            {
                "username": username,
                "uid": str(1000 + idx),
                "gid": str(1000 + idx),
                "home": f"/home/{username}",
                "shell": "/bin/bash",
                "password": f"{username}!{rng.randint(1000, 9999)}",
            }
        )

    system_accounts = _load_yaml(POOLS_DIR / "system_accounts.yaml").get("items", [])
    for account in system_accounts:
        username = str(account["username"])
        users.append(
            {
                "username": username,
                "uid": str(account["uid"]),
                "gid": str(account["gid"]),
                "home": str(account["home"]),
                "shell": str(account["shell"]),
                "password": f"{username}!{rng.randint(1000, 9999)}",
            }
        )

    if requested_username and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", requested_username):
        if all(user["username"] != requested_username for user in users):
            uid = rng.randint(1500, 9999)
            while any(user["uid"] == str(uid) for user in users):
                uid = rng.randint(1500, 9999)
            users.append(
                {
                    "username": requested_username,
                    "uid": str(uid),
                    "gid": str(uid),
                    "home": f"/home/{requested_username}",
                    "shell": "/bin/bash",
                    "password": f"{requested_username}!{rng.randint(1000, 9999)}",
                }
            )

    server_profiles = _load_yaml(POOLS_DIR / "server_profiles.yaml").get("items", [])
    if not server_profiles:
        raise ValueError("server_profiles.yaml must contain at least one profile")
    server_profile = rng.choice(server_profiles)
    hostname = f"{rng.choice(server_profile['hostname_prefixes'])}-{rng.randint(100, 999)}"
    db_name = f"app_{rng.randint(20, 99)}"
    db_user = f"db_{rng.choice(db_roles)}_{rng.randint(1000, 9999)}"
    db_password = f"{db_user}!{rng.randint(1000, 9999)}"
    key_seed = hashlib.sha256(f"{seed or 'default'}:admin-ssh".encode("utf-8")).digest()
    ssh_private_key = Ed25519PrivateKey.from_private_bytes(key_seed)
    ssh_private_key_pem = ssh_private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    ssh_public_key = ssh_private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    database_users = [
        {
            "id": int(user["uid"]),
            "username": user["username"],
            "email": f"{user['username']}@{rng.choice(email_domains)}",
            "role": rng.choice(roles),
        }
        for user in users
    ]
    orders = []
    for user in database_users:
        for _ in range(rng.randint(1, 3)):
            orders.append(
                {
                    "id": len(orders) + 1,
                    "user_id": user["id"],
                    "product": rng.choice(products),
                    "status": rng.choice(order_statuses),
                    "total": float(f"{rng.randint(15, 950)}.{rng.randint(0, 99):02d}"),
                }
            )

    return {
        "seed": str(seed or "default"),
        "hostname": hostname,
        "os": server_profile["distribution"],
        "kernel": server_profile["kernel_release"],
        "users": users,
        "ssh_keys": {
            "private_key": ssh_private_key_pem,
            "public_key": ssh_public_key,
        },
        "ssh_login_username": requested_username
        if requested_username and any(user["username"] == requested_username for user in users)
        else users[0]["username"],
        "service_names": services,
        "common_commands": commands,
        "database": {
            "name": db_name,
            "user": db_user,
            "password": db_password,
            "host": os.environ.get("FAKE_DB_HOST", "fake-db"),
            "port": int(os.environ.get("FAKE_DB_PORT", "3306")),
            "tables": ["users", "orders"],
            "users": database_users,
            "orders": orders,
        },
        "server": {
            "distribution": server_profile["distribution"],
            "release": server_profile["release"],
            "kernel_release": server_profile["kernel_release"],
            "kernel_build_string": server_profile["kernel_build_string"],
            "hardware_platform": server_profile["hardware_platform"],
            "operating_system": server_profile["operating_system"],
            "banner": f"{hostname} ({server_profile['distribution']} Linux) {server_profile['release']}",
            "uptime": f"{rng.randint(12, 96)} days, {rng.randint(1, 23)} hours, {rng.randint(1, 59)} mins",
        },
    }


def build_session_files(
    session_id: str,
    seed: str | int | None = None,
    trail: str | None = None,
    requested_username: str | None = None,
) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session_id):
        raise ValueError("session_id must contain only letters, digits, hyphens, or underscores")

    environment = generate_environment(seed=seed or session_id, requested_username=requested_username)
    root = Path(settings.session_root) / session_id
    root.mkdir(parents=True, exist_ok=True)

    created: dict[str, str] = {}
    for user in environment["users"]:
        home = root / user["home"].lstrip("/")
        home.mkdir(parents=True, exist_ok=True)
        (home / ".bash_history").write_text("\n".join(environment["common_commands"]), encoding="utf-8")
        created[str(home / ".bash_history")] = "written"

    etc_dir = root / "etc"
    etc_dir.mkdir(parents=True, exist_ok=True)
    passwd_lines = [
        f"{u['username']}:x:{u['uid']}:{u['gid']}::{u['home']}:{u['shell']}" for u in environment["users"]
    ]
    (etc_dir / "passwd").write_text("\n".join(passwd_lines) + "\n", encoding="utf-8")
    created[str(etc_dir / "passwd")] = "written"

    (etc_dir / "hostname").write_text(f"{environment['hostname']}\n", encoding="utf-8")
    (etc_dir / "os-release").write_text(
        f"NAME=\"{environment['server']['distribution']}\"\n"
        f"VERSION=\"{environment['server']['release']}\"\n"
        f"PRETTY_NAME=\"{environment['server']['distribution']} {environment['server']['release']}\"\n"
        f"VERSION_ID=\"{environment['server']['release']}\"\n",
        encoding="utf-8",
    )
    (root / "etc" / "motd").write_text(f"Welcome to {environment['hostname']}\n", encoding="utf-8")

    config_file = root / ".env"
    config_file.write_text(
        "# synthetic values only\n"
        f"DB_NAME={environment['database']['name']}\n"
        f"DB_USER={environment['database']['user']}\n"
        f"DB_PASSWORD={environment['database']['password']}\n",
        encoding="utf-8",
    )
    created[str(config_file)] = "written"

    web_root = root / "web"
    web_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config_file, web_root / ".env")
    created[str(web_root / ".env")] = "written"

    http_admin_template = _load_template("http_admin")
    public_admin = web_root / "admin.html"
    public_admin.write_text(http_admin_template["content"].format(**environment), encoding="utf-8")
    created[str(public_admin)] = "written"

    backup_template = _load_template("backup_sql")
    backup_lines = [backup_template["header"].format(**environment).rstrip()]
    backup_lines.extend(
        backup_template["user_row"].format(**user) for user in environment["database"]["users"]
    )
    backup_lines.extend(
        backup_template["order_row"].format(**order) for order in environment["database"]["orders"]
    )
    public_backup = web_root / "backup.sql"
    public_backup.write_text("\n".join(backup_lines) + "\n", encoding="utf-8")
    shutil.copyfile(public_backup, root / "backup.sql")
    created[str(public_backup)] = "written"
    created[str(root / "backup.sql")] = "written"

    if trail:
        trail_template = _load_template(trail)
        for item in trail_template.get("files", []):
            target = root / str(item["path"]).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            rendered = item["content"].format(**environment)
            target.write_text(rendered, encoding="utf-8")
            if "mode" in item:
                target.chmod(int(str(item["mode"]), 8))
            created[str(target)] = "written"
            if item.get("http_public"):
                public_target = web_root / str(item["path"]).lstrip("/")
                public_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, public_target)
                created[str(public_target)] = "written"

    metadata = root / "session.json"
    metadata.write_text(
        json.dumps(
            {
                "seed": str(seed or session_id),
                "trail": trail,
                "requested_username": requested_username,
                "environment": environment,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    created[str(metadata)] = "written"
    return created


def get_session_state(session_id: str) -> dict[str, Any]:
    root = Path(settings.session_root) / session_id
    metadata = root / "session.json"
    if not metadata.exists():
        return {"session_id": session_id, "exists": False}
    return json.loads(metadata.read_text(encoding="utf-8"))
