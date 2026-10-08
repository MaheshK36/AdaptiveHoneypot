from __future__ import annotations

import json
import importlib
import os
import posixpath
import secrets
import stat
import types
import urllib.error
import urllib.request
from pathlib import Path


def _post_session_start(session_id: str, requested_username: str) -> dict:
    api_root = os.environ["COWRIE_SESSION_API_URL"].rstrip("/")
    payload = json.dumps({"requested_username": requested_username}).encode("utf-8")
    request = urllib.request.Request(
        f"{api_root}/env/{session_id}/start",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=float(os.environ["EVENT_INGEST_TIMEOUT"])) as response:
        return json.loads(response.read(65536))


def _owner_for_path(virtual_path: str, environment: dict) -> tuple[int, int]:
    parts = Path(virtual_path.lstrip("/")).parts
    if len(parts) > 1 and parts[0] == "home":
        for user in environment["users"]:
            if user["username"] == parts[1]:
                return int(user["uid"]), int(user["gid"])
    return 0, 0


def _ensure_virtual_directory(filesystem, virtual_path: str, environment: dict) -> None:
    from cowrie.shell.fs import A_TYPE, T_DIR

    normalized = "/" + virtual_path.strip("/")
    if normalized == "/":
        return
    node = filesystem.getfile(normalized, follow_symlinks=False)
    if node is not None and node[A_TYPE] == T_DIR:
        return
    parent = str(Path(normalized).parent)
    _ensure_virtual_directory(filesystem, parent, environment)
    if node is None:
        uid, gid = _owner_for_path(normalized, environment)
        filesystem.mkdir(normalized, uid, gid, 4096, stat.S_IFDIR | 0o755)


def _install_session_files(server, session_root: Path) -> None:
    from cowrie.shell.fs import A_TYPE, T_DIR, T_FILE

    metadata = json.loads((session_root / "session.json").read_text(encoding="utf-8"))
    environment = metadata["environment"]
    filesystem = server.fs
    filesystem.init_honeyfs(str(session_root))

    for base, directories, filenames in os.walk(session_root, followlinks=False):
        directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()]
        for name in directories:
            physical_path = Path(base) / name
            virtual_path = "/" + physical_path.relative_to(session_root).as_posix()
            if virtual_path == "/":
                continue
            uid, gid = _owner_for_path(virtual_path, environment)
            node = filesystem.getfile(virtual_path, follow_symlinks=False)
            if node is None:
                _ensure_virtual_directory(filesystem, virtual_path, environment)
            elif node[A_TYPE] != T_DIR:
                continue

        for name in filenames:
            physical_path = Path(base) / name
            if name == "session.json" or physical_path.is_symlink() or not physical_path.is_file():
                continue
            virtual_path = "/" + physical_path.relative_to(session_root).as_posix()
            parent = str(Path(virtual_path).parent)
            _ensure_virtual_directory(filesystem, parent, environment)
            node = filesystem.getfile(virtual_path, follow_symlinks=False)
            details = physical_path.stat()
            uid, gid = _owner_for_path(virtual_path, environment)
            if node is None or node[A_TYPE] != T_FILE:
                if not filesystem.mkfile(
                    virtual_path,
                    uid,
                    gid,
                    details.st_size,
                    stat.S_IFREG | stat.S_IMODE(details.st_mode),
                    details.st_mtime,
                ):
                    continue
                node = filesystem.getfile(virtual_path, follow_symlinks=False)
            filesystem.update_realfile(node, str(physical_path))

    original_getfile = filesystem.getfile
    sync_state = {"active": False}
    session_root = session_root.resolve()

    def ensure_virtual_directory(virtual_path: str) -> None:
        normalized = "/" + virtual_path.strip("/")
        if normalized == "/":
            return
        node = original_getfile(normalized, follow_symlinks=False)
        if node is not None:
            return
        parent = posixpath.dirname(normalized)
        ensure_virtual_directory(parent)
        uid, gid = _owner_for_path(normalized, environment)
        filesystem.mkdir(normalized, uid, gid, 4096, stat.S_IFDIR | 0o755)

    def sync_virtual_path(virtual_path: str) -> None:
        normalized = posixpath.normpath("/" + virtual_path.lstrip("/"))
        if ".." in Path(normalized).parts:
            return
        candidate = (session_root / normalized.lstrip("/")).resolve()
        if candidate != session_root and session_root not in candidate.parents:
            return
        if candidate == session_root:
            directory = candidate
        elif candidate.is_dir():
            directory = candidate
        else:
            directory = candidate.parent

        if not directory.is_dir():
            return
        for child in sorted(directory.iterdir())[:4096]:
            if child.is_symlink() or child.name == "session.json":
                continue
            child_virtual = "/" + child.relative_to(session_root).as_posix()
            uid, gid = _owner_for_path(child_virtual, environment)
            if child.is_dir():
                ensure_virtual_directory(child_virtual)
                continue
            if not child.is_file():
                continue
            node = original_getfile(child_virtual, follow_symlinks=False)
            if node is None:
                ensure_virtual_directory(str(Path(child_virtual).parent))
                details = child.stat()
                if not filesystem.mkfile(
                    child_virtual,
                    uid,
                    gid,
                    details.st_size,
                    stat.S_IFREG | stat.S_IMODE(details.st_mode),
                    details.st_mtime,
                ):
                    continue
                node = original_getfile(child_virtual, follow_symlinks=False)
            if node is not None and node[A_TYPE] == T_FILE:
                filesystem.update_realfile(node, str(child))

    def getfile_with_session_overlay(filesystem_instance, path: str, follow_symlinks: bool = True):
        if not sync_state["active"]:
            sync_state["active"] = True
            try:
                sync_virtual_path(path)
            finally:
                sync_state["active"] = False
        return original_getfile(path, follow_symlinks=follow_symlinks)

    filesystem.getfile = types.MethodType(getfile_with_session_overlay, filesystem)


def _install_hooks() -> None:
    from twisted.conch.interfaces import IConchUser

    from cowrie.shell.protocol import HoneyPotBaseProtocol
    from cowrie.shell.realm import HoneyPotRealm
    from cowrie.shell.server import CowrieServer

    original_avatar = HoneyPotRealm.requestAvatar
    original_filesystem = CowrieServer.initFileSystem
    original_connection_made = HoneyPotBaseProtocol.connectionMade
    uname_module = importlib.import_module("cowrie.commands.uname")
    original_uname_call = uname_module.Command_uname.call

    def request_avatar(realm, avatar_id, mind, *interfaces):
        if IConchUser not in interfaces:
            return original_avatar(realm, avatar_id, mind, *interfaces)

        session_id = f"cw-{secrets.token_hex(16)}"
        requested_username = avatar_id.decode("utf-8", errors="replace")
        start = _post_session_start(session_id, requested_username)
        result = original_avatar(realm, avatar_id, mind, *interfaces)
        user = result[1]
        server = user.server
        session_root = Path(os.environ["COWRIE_SESSION_DATA_ROOT"]) / session_id
        metadata = json.loads((session_root / "session.json").read_text(encoding="utf-8"))
        environment = metadata["environment"]
        login_username = start["login_username"]
        account = next(user_record for user_record in environment["users"] if user_record["username"] == login_username)

        server.session_id = session_id
        server.environment = environment
        server.hostname = start["hostname"]
        user.username = login_username
        user.uid = int(account["uid"])
        user.gid = int(account["gid"])
        user.home = account["home"]
        user.temporary = False
        return result

    def init_filesystem(server, home: str) -> None:
        original_filesystem(server, home)
        session_id = getattr(server, "session_id", None)
        if not session_id:
            raise RuntimeError("Cowrie avatar has no generated session identifier")
        session_root = Path(os.environ["COWRIE_SESSION_DATA_ROOT"]) / session_id
        _install_session_files(server, session_root)

    def connection_made(protocol) -> None:
        original_connection_made(protocol)
        session_id = getattr(protocol.user.server, "session_id", None)
        if session_id:
            protocol.events.dispatch(
                "cowrie.session.params",
                "",
                environment_session_id=session_id,
            )

    def uname_call(command) -> None:
        server_info = command.protocol.user.server.environment["server"]
        replacements = {
            "kernel_name": server_info["distribution"],
            "kernel_version": server_info["kernel_release"],
            "kernel_build_string": server_info["kernel_build_string"],
            "hardware_platform": server_info["hardware_platform"],
            "operating_system": server_info["operating_system"],
        }
        previous = {name: getattr(uname_module, name) for name in replacements}
        try:
            for name, value in replacements.items():
                setattr(uname_module, name, lambda value=value: value)
            original_uname_call(command)
        finally:
            for name, function in previous.items():
                setattr(uname_module, name, function)

    HoneyPotRealm.requestAvatar = request_avatar
    CowrieServer.initFileSystem = init_filesystem
    HoneyPotBaseProtocol.connectionMade = connection_made
    uname_module.Command_uname.call = uname_call


if os.environ.get("COWRIE_SESSION_FS_HOOK") == "enabled":
    _install_hooks()