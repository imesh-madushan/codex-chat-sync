"""Immutable, checked ZIP bundles and complete fork dependency snapshots."""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
import zipfile

from .config import SyncError

FORMAT = "codex-chat-sync"
MAX_MEMBER = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_MEMBERS = 10000
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def records(data):
    try:
        result = [json.loads(line) for line in data.splitlines() if line.strip()]
        if not result or result[0]["type"] != "session_meta":
            raise ValueError("Missing session metadata")
        ordinals = [r.get("ordinal") for r in result]
        if any(o is not None for o in ordinals):
            if not all(isinstance(o, int) and o >= 0 for o in ordinals):
                raise ValueError("Mixed or invalid ordinals")
            if any(b <= a for a, b in zip(ordinals, ordinals[1:])):
                raise ValueError("Rollout ordinals are not increasing")
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise SyncError(f"Invalid rollout: {exc}") from exc


def normalized_path(value):
    value = str(value)
    if value.startswith("file://"):
        from urllib.parse import unquote, urlparse
        parsed = urlparse(value)
        value = unquote(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            value = "//" + parsed.netloc + value
        if re.match(r"^/[A-Za-z]:", value):
            value = value[1:]
    if value.startswith("\\\\?\\"):
        value = value[4:]
    value = value.replace("\\", "/").rstrip("/")
    return value.casefold() if re.match(r"^[A-Za-z]:/", value) else value


def turn_signatures(turns, assets=()):
    """Content and stable turn IDs, independent of physical thread IDs/local images."""
    asset_map = {normalized_path(a["source"]): "asset:" + a["sha256"] for a in assets}

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if k not in ("threadId", "thread_id", "sessionId", "session_id", "startedAt", "completedAt")}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, str):
            return asset_map.get(normalized_path(value), value)
        return value

    return [{"id": turn["id"], "sha256": digest(encode(clean(turn)))} for turn in turns]


def relation(local, incoming):
    if local == incoming:
        return "same"
    if local == incoming[:len(local)]:
        return "update"
    if incoming == local[:len(incoming)]:
        return "stale"
    return "branch"


def find_rollout(home, thread_id):
    if not UUID.fullmatch(thread_id):
        raise SyncError("Invalid physical chat ID: " + thread_id)
    paths = []
    for folder in ("sessions", "archived_sessions"):
        base = Path(home) / folder
        if base.exists():
            paths.extend(base.rglob("*" + thread_id + ".jsonl"))
    if len(paths) != 1:
        raise SyncError(f"Expected one raw rollout for {thread_id}; found {len(paths)}. Refresh Codex inventory first.")
    return paths[0]


def stable_bytes(path, length=None):
    with Path(path).open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        length = size if length is None else length
        if not isinstance(length, int) or length <= 0 or length > size or length > MAX_MEMBER:
            raise SyncError("Invalid or oversized history byte boundary.")
        data = stream.read(length)
        stream.seek(0)
        if stream.read(length) != data:
            raise SyncError("Conversation changed while being exported. Retry once its turn has completed.")
    if not data.endswith(b"\n"):
        raise SyncError("Rollout ends in a partial record. Wait for Codex to finish writing.")
    return data


class Snapshot:
    def __init__(self, home):
        self.home = home
        self.nodes = {}
        self.members = {}
        self.active = set()

    def capture(self, thread_id, length=None, ordinal_limit=None, checkpoint=None):
        if thread_id in self.active:
            raise SyncError("Cyclic fork ancestry.")
        self.active.add(thread_id)
        try:
            data = stable_bytes(find_rollout(self.home, thread_id), length)
            if checkpoint:
                offset = 0
                boundary = None
                for line in data.splitlines(keepends=True):
                    offset += len(line)
                    record = json.loads(line)
                    payload = record.get("payload", {})
                    if record["type"] == "event_msg" and payload.get("type") == "task_complete" and payload.get("turn_id") == checkpoint:
                        boundary = offset
                if boundary is None:
                    rs = records(data)
                    if not rs[0]["payload"].get("history_base") or any(
                            r["type"] == "event_msg" and r.get("payload", {}).get("type") == "task_started" for r in rs):
                        raise SyncError("Completed checkpoint is not present in the raw rollout.")
                    # A newly created fork may contain metadata only; all turns are inherited.
                else:
                    data = data[:boundary]
            rs = records(data)
            if ordinal_limit is not None:
                if rs[-1].get("ordinal", -1) + 1 != ordinal_limit:
                    raise SyncError("Ancestor ordinal and byte boundaries do not agree.")
            meta = rs[0]["payload"]
            if meta.get("id") != thread_id:
                raise SyncError("Rollout identity does not match filename.")
            key = digest(data)
            if key in self.nodes:
                return key
            parent = None
            base = meta.get("history_base")
            if base:
                parent = self.capture(base["thread_id"], length=base["end_byte_offset"],
                                      ordinal_limit=base["end_ordinal_exclusive"])
            elif meta.get("forked_from_id"):
                raise SyncError("Fork has no explicit history byte boundary; this storage version is unsupported.")
            member = "rollouts/" + key + ".jsonl"
            self.nodes[key] = {"member": member, "thread_id": thread_id, "parent": parent,
                               "size": len(data), "sha256": key}
            self.members[member] = data
            return key
        finally:
            self.active.remove(thread_id)


def image_paths(value):
    """Structured media/file inputs only; never scrape arbitrary tool output."""
    result = set()
    if isinstance(value, dict):
        if str(value.get("type", "")).lower() in ("localimage", "local_image", "localaudio", "local_audio", "mention"):
            if value.get("path"):
                path = value["path"]
                if Path(path).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", path):
                    result.add(path)
        for key in ("image_url", "url"):
            url = value.get(key)
            if isinstance(url, str) and url.startswith("file://"):
                from urllib.parse import unquote, urlparse
                p = unquote(urlparse(url).path)
                if re.match(r"^/[A-Za-z]:", p):
                    p = p[1:]
                result.add(p)
        for item in value.values():
            result.update(image_paths(item))
    elif isinstance(value, list):
        for item in value:
            result.update(image_paths(item))
    return result


def write_bundle(path, manifest, members):
    if sum(len(v) for v in members.values()) > MAX_TOTAL:
        raise SyncError("Bundle exceeds the 1 GiB uncompressed limit.")
    manifest = copy.deepcopy(manifest)
    manifest.update(format=FORMAT, version=1)
    manifest["members"] = {name: {"size": len(data), "sha256": digest(data)} for name, data in members.items()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SyncError("Export target already exists; choose a new filename.")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", encode(manifest))
            for name, data in members.items():
                archive.writestr(name, data)
        read_bundle(temporary)
        # Hard link publication is atomic and refuses a concurrent existing target.
        os.link(temporary, path)
    except OSError as exc:
        raise SyncError(f"Cannot publish export atomically: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def safe_member(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and str(p) == name and all(
        part not in (".", "..", "") for part in p.parts) and not any(c in name for c in ("\\", ":", "\x00"))


def read_bundle(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [e.filename for e in entries]
            if len(names) > MAX_MEMBERS or len(set(names)) != len(names):
                raise SyncError("Too many members or duplicate ZIP names.")
            if sum(e.file_size for e in entries) > MAX_TOTAL:
                raise SyncError("Bundle exceeds size limit.")
            for entry in entries:
                if not safe_member(entry.filename) or entry.file_size > MAX_MEMBER or entry.is_dir():
                    raise SyncError("Unsafe or oversized ZIP member.")
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise SyncError("Symlinks and encrypted ZIPs are unsupported.")
            if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > 8 * 1024 * 1024:
                raise SyncError("Missing or oversized manifest.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != FORMAT or manifest.get("version") != 1:
                raise SyncError("Unsupported chat bundle format/version.")
            specs = manifest["members"]
            if set(names) != set(specs) | {"manifest.json"}:
                raise SyncError("ZIP members differ from manifest.")
            members = {}
            for name, spec in specs.items():
                data = archive.read(name)
                if len(data) != spec["size"] or digest(data) != spec["sha256"]:
                    raise SyncError("Checksum/size mismatch: " + name)
                members[name] = data
            validate_manifest(manifest, members)
            return manifest, members
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SyncError(f"Cannot validate bundle: {exc}") from exc


def validate_manifest(manifest, members):
    nodes = manifest["nodes"]
    if not isinstance(nodes, dict) or not nodes or not manifest["chats"]:
        raise SyncError("Bundle contains no conversations.")
    checked = set()

    def visit(key, active):
        if key in active or key not in nodes:
            raise SyncError("Invalid/cyclic ancestor closure.")
        if key in checked:
            return
        node = nodes[key]
        data = members[node["member"]]
        rs = records(data)
        meta = rs[0]["payload"]
        if digest(data) != node["sha256"] or len(data) != node["size"] or meta["id"] != node["thread_id"] or not UUID.fullmatch(meta["id"]):
            raise SyncError("Invalid node identity/checksum.")
        parent = node.get("parent")
        base = meta.get("history_base")
        if bool(parent) != bool(base):
            raise SyncError("Missing or unexpected history dependency.")
        if parent:
            visit(parent, active | {key})
            pn = nodes[parent]
            prs = records(members[pn["member"]])
            if base["thread_id"] != pn["thread_id"] or base["end_byte_offset"] != pn["size"] or base["end_ordinal_exclusive"] != prs[-1]["ordinal"] + 1:
                raise SyncError("Invalid ancestor boundaries.")
        elif meta.get("forked_from_id"):
            raise SyncError("Unresolved fork ancestry.")
        checked.add(key)

    physical = set()
    for chat in manifest["chats"]:
        if chat["source_thread_id"] in physical or not UUID.fullmatch(chat["logical_id"]):
            raise SyncError("Duplicate physical chat or invalid logical identity.")
        physical.add(chat["source_thread_id"])
        if chat["source_thread_id"] != nodes[chat["node"]]["thread_id"]:
            raise SyncError("Selected chat does not match its rollout node.")
        visit(chat["node"], set())
        expected = chat["turns"]
        if not expected or len({t["id"] for t in expected}) != len(expected):
            raise SyncError("Empty or duplicate completed turn checkpoints.")
        if any(not re.fullmatch(r"[0-9a-f]{64}", t["sha256"]) for t in expected):
            raise SyncError("Invalid turn checksum.")
    if checked != set(nodes):
        raise SyncError("Bundle includes unreferenced rollouts.")
    for asset in manifest.get("assets", []):
        if digest(members[asset["member"]]) != asset["sha256"]:
            raise SyncError("Invalid attachment checksum.")
