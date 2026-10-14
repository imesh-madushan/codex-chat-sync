import contextlib
import json
import os
from pathlib import Path
import socket
import shutil
import uuid


class SyncError(Exception):
    """An actionable error safe to show in the terminal."""


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def config_path():
    override = os.environ.get("CHATSYNC_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "CodexChatSync" / "config.json"


def load_config(path=None):
    path = Path(path or config_path())
    if not path.exists():
        raise SyncError("Run setup first: python chat_sync.py setup")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        for key in ("codex_home", "codex_executable", "exchange_dir", "state_dir", "device_id"):
            if not config.get(key):
                raise ValueError("Missing " + key)
        if config.get("version") != 1:
            raise ValueError("Unsupported settings version")
        return config
    except (ValueError, OSError) as exc:
        raise SyncError(f"Cannot read settings at {path}: {exc}") from exc


def make_config(codex_home, codex_executable, exchange_dir, state_dir, previous=None):
    previous = previous or {}
    result = dict(previous)
    for key, value in (("codex_home", codex_home), ("codex_executable", codex_executable),
                       ("exchange_dir", exchange_dir), ("state_dir", state_dir)):
        result[key] = str(Path(value).expanduser().resolve())
    if not Path(result["codex_home"]).is_dir():
        raise SyncError("Codex data folder must already exist.")
    executable = Path(result["codex_executable"])
    if not executable.is_file() or executable.suffix.lower() in (".ps1", ".cmd", ".bat"):
        raise SyncError("Choose the real Codex executable (codex.exe on Windows), not a shell wrapper.")
    state = Path(result["state_dir"])
    exchange = Path(result["exchange_dir"])
    codex_home_path = Path(result["codex_home"])
    if codex_home_path == state or codex_home_path.is_relative_to(state):
        raise SyncError("Use a dedicated state folder, not the Codex data folder or one of its parents.")
    if state == exchange or state.is_relative_to(exchange) or exchange.is_relative_to(state):
        raise SyncError("Local state and the bundle folder must be separate; keep state on this device.")
    if previous.get("codex_home") and previous["codex_home"] != result["codex_home"]:
        result["device_id"] = str(uuid.uuid4())
    result.update(version=1, device_id=result.get("device_id") or str(uuid.uuid4()),
                  device_name=result.get("device_name") or socket.gethostname(),
                  mappings=result.get("mappings", {}))
    exchange.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    return result


def relocate_state(previous, current):
    old = previous.get("state_dir")
    if not old or normalized_local(old) == normalized_local(current["state_dir"]):
        return
    old_path, new_path = Path(old), Path(current["state_dir"])
    if old_path.is_relative_to(new_path) or new_path.is_relative_to(old_path):
        raise SyncError("New state folder cannot be inside the old state folder (or vice versa).")
    if any(new_path.iterdir()):
        raise SyncError("Choose an empty new state folder so existing receipts/assets cannot be overwritten.")
    if old_path.exists():
        with state_lock(previous):
            for filename in old_path.glob("receipts-*.json"):
                shutil.copy2(filename, new_path / filename.name)
            for name in ("assets", "operations", "backups"):
                managed = old_path / name
                if managed.is_dir():
                    shutil.copytree(managed, new_path / name)
    # Old receipts are retained as a backup; managed image paths must remain available there.


def normalized_local(value):
    return os.path.normcase(str(Path(value).expanduser().resolve()))


@contextlib.contextmanager
def state_lock(config):
    """OS releases the lock if the process crashes; no stale PID guessing."""
    path = Path(config["state_dir"]) / "operation.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SyncError("Another chat-sync operation is using this local state folder.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
