"""UI operations without a dependency on Textual or terminal input."""
import copy
import hashlib
from pathlib import Path
import socket

from .bundle import read_bundle
from .config import (SyncError, atomic_json, config_path, load_config, make_config,
                     relocate_state)
from .engine import export_chats, import_bundle, inventory, load_ledger, rollback
from .rpc import Codex, executable_version


def file_fingerprint(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class UIService:
    def __init__(self, settings_path=None):
        self.settings_path = Path(settings_path or config_path()).expanduser().resolve()
        self.config = load_config(self.settings_path) if self.settings_path.exists() else None

    def require_config(self):
        if not self.config:
            raise SyncError("Save device settings before loading or migrating chats.")
        return self.config

    def defaults(self):
        from .cli import suggest_executable
        values = {"codex_home": str(Path.home() / ".codex"),
                  "codex_executable": suggest_executable(), "exchange_dir": "",
                  "state_dir": str(self.settings_path.parent / "state"),
                  "device_name": socket.gethostname()}
        values.update(self.config or {})
        return values

    def snapshot(self, archived=False):
        config = self.require_config()
        threads, projects = inventory(config)
        if archived:
            archived_threads, _ = inventory(config, True)
            threads = list({t["id"]: t for t in threads + archived_threads}.values())
        return threads, projects, self.bundles(), self.history()

    def preview(self, thread_id):
        config = self.require_config()
        with Codex(config["codex_executable"], config["codex_home"]) as rpc:
            turns = rpc.pages("thread/turns/list", {"threadId": thread_id,
                              "itemsView": "notLoaded", "sortDirection": "desc"})
            page = rpc.call("thread/turns/list", {"threadId": thread_id, "limit": 1,
                            "itemsView": "full", "sortDirection": "desc"})
        messages = []
        if page["data"]:
            for item in page["data"][0].get("items", []):
                if item.get("type") == "agentMessage" and item.get("text"):
                    messages.append(item["text"])
        return {"turn_count": len(turns), "completed": sum(t.get("status") == "completed" for t in turns),
                "last_message": messages[-1][:1800] if messages else "No persisted assistant message."}

    def bundles(self):
        config = self.require_config()
        return sorted(Path(config["exchange_dir"]).glob("*.chatbundle.zip"),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    def inspect(self, path):
        path = Path(path).expanduser().resolve()
        manifest, _ = read_bundle(path)
        return path, manifest, file_fingerprint(path)

    def export(self, physical_ids, progress):
        return export_chats(self.require_config(), physical_ids, progress=progress)

    def _import_options(self, path, physical_ids, destinations, projects, expected_hash):
        path = Path(path).expanduser().resolve()
        if file_fingerprint(path) != expected_hash:
            raise SyncError("The bundle changed after it was loaded. Load it again before importing.")
        manifest, _ = read_bundle(path)
        chosen = set(physical_ids)
        chats = [c for c in manifest["chats"] if c["source_thread_id"] in chosen]
        if not chosen or chosen != {c["source_thread_id"] for c in chats}:
            raise SyncError("Choose valid chats from the loaded bundle.")
        sources = {c["cwd"] for c in chats}
        mapped = {}
        for source in sources:
            value = destinations.get(source, "").strip().strip(chr(34))
            if not value:
                raise SyncError("Choose a destination folder for: " + source)
            target = Path(value).expanduser().resolve()
            if not target.is_dir():
                raise SyncError("Destination folder does not exist: " + str(target))
            mapped[source] = str(target)
        return path, mapped, {s: projects.get(s) for s in sources}, [c["node"] for c in chats]

    def analyze(self, path, physical_ids, destinations, projects, expected_hash, progress):
        options = self._import_options(path, physical_ids, destinations, projects, expected_hash)
        path, mapped, projects, nodes = options
        plans = import_bundle(self.require_config(), path, mapped, projects,
                              dry_run=True, selected_nodes=nodes, progress=progress)
        return plans

    def perform_import(self, path, physical_ids, destinations, projects, expected_hash, progress):
        options = self._import_options(path, physical_ids, destinations, projects, expected_hash)
        path, mapped, projects, nodes = options
        plans = import_bundle(self.require_config(), path, mapped, projects,
                              selected_nodes=nodes, progress=progress)
        updated = copy.deepcopy(self.config)
        for source, destination in mapped.items():
            updated.setdefault("mappings", {})[source] = {"destination": destination,
                                                          "project_id": projects.get(source)}
        try:
            atomic_json(self.settings_path, updated)
        except OSError as exc:
            raise SyncError("Chats were imported, but folder mappings could not be saved: " + str(exc)) from exc
        self.config = updated
        return plans

    def save_settings(self, values):
        previous = self.config or {}
        for name in ("codex_home", "codex_executable", "exchange_dir", "state_dir"):
            if not values.get(name, "").strip():
                raise SyncError("All four device paths are required.")
        updated = make_config(values["codex_home"], values["codex_executable"],
                              values["exchange_dir"], values["state_dir"], previous)
        updated["device_name"] = values.get("device_name", "").strip() or socket.gethostname()
        executable_version(updated["codex_executable"])
        with Codex(updated["codex_executable"], updated["codex_home"]) as rpc:
            rpc.pages("project/list")
            rpc.pages("thread/list", {"useStateDbOnly": True})
        relocate_state(previous, updated)
        atomic_json(self.settings_path, updated)
        self.config = updated
        return updated

    def save_mapping(self, source, destination, project_id):
        updated = copy.deepcopy(self.require_config())
        if not destination.strip() or not Path(destination).expanduser().is_dir():
            raise SyncError("The destination must be an existing folder.")
        updated.setdefault("mappings", {})[source] = {
            "destination": str(Path(destination).expanduser().resolve()), "project_id": project_id}
        atomic_json(self.settings_path, updated)
        self.config = updated

    def history(self):
        config = self.require_config()
        receipts = {e["operation"]: e for e in load_ledger(config)["imports"]}
        rows = []
        for path in (Path(config["state_dir"]) / "operations").glob("*.json"):
            import json
            record = json.loads(path.read_text(encoding="utf-8"))
            receipt = receipts.get(record["operation"], {})
            rows.append({"operation": record["operation"], "status": record["status"],
                         "created_at": record.get("created_at", ""),
                         "title": ", ".join(p["title"] for p in receipt.get("plans", [])) or Path(record.get("bundle", "")).name})
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    def rollback(self, operation, progress):
        progress("Archiving imported copies; retaining their messages and original chats")
        rollback(self.require_config(), operation)
        return self.history()
