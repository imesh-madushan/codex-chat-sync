import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid

from .bundle import (Snapshot, digest, encode, find_rollout, image_paths, normalized_path,
                     read_bundle, records, relation, stable_bytes, turn_signatures, write_bundle)
from .config import SyncError, atomic_json, state_lock
from .rpc import Codex, executable_version


def _report(progress, message):
    if progress is not None:
        try:
            progress(message)
        except Exception:
            # A display callback must not abort a migration transaction.
            pass


IDENTITY_NAMESPACE = uuid.UUID("a31b0d74-9852-4980-807b-7e11465354ba")


def ledger_path(config):
    return Path(config["state_dir"]) / ("receipts-" + config["device_id"] + ".json")


def load_ledger(config):
    path = ledger_path(config)
    if not path.exists():
        return {"version": 1, "physical": {}, "imports": []}
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["version"] != 1:
            raise ValueError("Unsupported receipt version")
        return result
    except (ValueError, KeyError, OSError) as exc:
        raise SyncError("Cannot read local migration receipts; restore their backup before importing.") from exc


def logical_id(ledger, thread_id):
    return ledger["physical"].get(thread_id, {}).get("logical_id") or str(uuid.uuid5(IDENTITY_NAMESPACE, thread_id))


def inventory(config, archived=False):
    with Codex(config["codex_executable"], config["codex_home"]) as rpc:
        threads = list_threads(rpc, archived)
        projects = rpc.pages("project/list")
    return threads, projects


def list_threads(rpc, archived=False):
    # Raw scanning can omit otherwise valid indexed forks on some Codex builds.
    scanned = rpc.pages("thread/list", {"archived": archived})
    indexed = rpc.pages("thread/list", {"archived": archived, "useStateDbOnly": True})
    return list({t["id"]: t for t in indexed + scanned}.values())


def completed_turns(rpc, thread_id):
    turns = rpc.turns(thread_id)
    if not turns:
        raise SyncError("Chat has no persisted completed turns: " + thread_id)
    if any(t.get("status") != "completed" for t in turns):
        raise SyncError("Chat contains an unfinished/interrupted turn. Finish it in Codex before exporting: " + thread_id)
    return turns


def export_chats(config, thread_ids, output=None, attachments=(), progress=None):
    _report(progress, "Reading selected conversations")
    thread_ids = list(dict.fromkeys(thread_ids))
    if not thread_ids:
        raise SyncError("Select at least one chat.")
    with state_lock(config):
        ledger = load_ledger(config)
        snapshot = Snapshot(config["codex_home"])
        chats, turns_by_id = [], {}
        asset_paths = set(str(Path(p).expanduser().resolve()) for p in attachments)
        with Codex(config["codex_executable"], config["codex_home"]) as rpc:
            projects = {p["id"]: p for p in rpc.pages("project/list")}
            for index, thread_id in enumerate(thread_ids, 1):
                _report(progress, f"Snapshotting conversation {index} of {len(thread_ids)}")
                thread = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
                turns = completed_turns(rpc, thread_id)
                node = snapshot.capture(thread_id, checkpoint=turns[-1]["id"])
                turns_by_id[thread_id] = turns
                asset_paths.update(image_paths(turns))
                project = projects.get(thread.get("projectId"))
                chats.append({"logical_id": logical_id(ledger, thread_id), "source_thread_id": thread_id,
                              "title": thread.get("name") or thread.get("preview", "")[:100] or thread_id,
                              "cwd": thread["cwd"], "project": project,
                              "archived": thread.get("archived", False), "node": node})
                if completed_turns(rpc, thread_id) != turns:
                    raise SyncError("History changed while exporting. Retry when all selected chats are idle.")
        _report(progress, "Collecting conversation attachments")
        assets = []
        for node in snapshot.nodes.values():
            for record in records(snapshot.members[node["member"]]):
                payload = record.get("payload", {})
                if (record["type"] == "response_item" and payload.get("type") == "message") or (
                    record["type"] == "event_msg" and payload.get("type") == "item_completed" and
                    payload.get("item", {}).get("type") == "UserMessage"):
                    asset_paths.update(image_paths(payload))
        for source in sorted(asset_paths):
            path = Path(source)
            if not path.is_file():
                raise SyncError("Referenced attachment is missing: " + source)
            if path.stat().st_size > 256 * 1024 * 1024:
                raise SyncError("Attachment exceeds size limit: " + source)
            data = path.read_bytes()
            sha = digest(data)
            member = "assets/" + sha
            snapshot.members[member] = data
            assets.append({"source": source, "member": member, "sha256": sha, "name": path.name})
        for chat in chats:
            chat["turns"] = turn_signatures(turns_by_id[chat["source_thread_id"]], assets)
        manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                    "source_device": config["device_name"], "source_device_id": config["device_id"],
                    "codex_version": executable_version(config["codex_executable"]),
                    "chats": chats, "nodes": snapshot.nodes, "assets": assets}
        output = Path(output) if output else Path(config["exchange_dir"]) / (
            "chats-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".chatbundle.zip")
        _report(progress, "Checking and publishing the completed bundle")
        write_bundle(output, manifest, snapshot.members)
        for chat in chats:
            ledger["physical"].setdefault(chat["source_thread_id"], {"logical_id": chat["logical_id"], "role": "source"})
        atomic_json(ledger_path(config), ledger)
        _report(progress, "Export complete")
        return output.resolve()


def render_nodes(manifest, members, destinations, assets_dir):
    """Reidentify the WHOLE dependency closure; retain original ordinals and response data."""
    nodes = manifest["nodes"]
    ids = {key: str(uuid.uuid4()) for key in nodes}
    mapped = {}
    rendered = {}
    asset_paths = {}
    normalized_assets = []
    for asset in manifest.get("assets", []):
        destination = Path(assets_dir) / asset["sha256"] / Path(asset["name"]).name
        if not destination.name or destination.name in (".", "..") or any(c in destination.name for c in (":", "\\")):
            raise SyncError("Invalid attachment basename.")
        source = normalized_path(asset["source"])
        asset_paths[source] = str(destination)
        normalized_assets.extend([asset, dict(asset, source=str(destination))])
    paths = {normalized_path(source): str(Path(target).resolve()) for source, target in destinations.items()}
    node_destinations = {c["node"]: str(Path(destinations[c["cwd"]]).resolve()) for c in manifest["chats"]}
    for chat in manifest["chats"]:
        key = chat["node"]
        destination = node_destinations[key]
        while key:
            node_destinations.setdefault(key, destination)
            key = nodes[key].get("parent")
    identity_keys = {"thread_id", "threadId", "session_id", "sessionId", "root_thread_id", "rootThreadId",
                     "origin_thread_id", "originThreadId", "forked_from_id"}

    def visit(key):
        if key in rendered:
            return
        node = nodes[key]
        local_paths = dict(paths)
        original_meta = records(members[node["member"]])[0]["payload"]
        local_paths[normalized_path(original_meta["cwd"])] = node_destinations[key]
        parent = node.get("parent")
        if parent:
            visit(parent)
        lineage = {}
        cursor = key
        while cursor:
            lineage[nodes[cursor]["thread_id"]] = ids[cursor]
            cursor = nodes[cursor].get("parent")

        def rewrite(value, field=None, response=False):
            if isinstance(value, dict):
                return {k: rewrite(v, k, response or k == "item") for k, v in value.items()}
            if isinstance(value, list):
                return [rewrite(v, field, response) for v in value]
            if isinstance(value, str):
                if field in identity_keys and value in lineage:
                    return lineage[value]
                norm = normalized_path(value)
                if field in ("path", "image_url", "url") and norm in asset_paths:
                    return Path(asset_paths[norm]).as_uri() if value.startswith("file://") else asset_paths[norm]
                if not response and norm in local_paths:
                    return local_paths[norm]
            return value

        output = []
        for record in records(members[node["member"]]):
            record = copy.deepcopy(record)
            record["payload"] = rewrite(record["payload"], response=record["type"] == "response_item")
            if record["type"] == "session_meta":
                meta = record["payload"]
                meta["id"] = ids[key]
                meta["session_id"] = ids[key]
                meta["cwd"] = node_destinations[key]
                meta["runtime_workspace_roots"] = [node_destinations[key]]
                meta.pop("creator_user_id", None)
                meta.pop("creator_account_id", None)
                # New local identities belong to this installation, not a connected remote host.
                # Preserve source provenance: it also controls display of nested tool events.
                if parent:
                    meta["forked_from_id"] = ids[parent]
                    meta["history_base"]["thread_id"] = ids[parent]
                    meta["history_base"]["end_byte_offset"] = len(rendered[parent])
            output.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        rendered[key] = b"".join(output)
        mapped[key] = records(rendered[key])[0]["payload"]["cwd"]

    for chat in manifest["chats"]:
        visit(chat["node"])
    return ids, rendered, mapped, asset_paths, normalized_assets


def install_assets(manifest, members, asset_paths):
    for asset in manifest.get("assets", []):
        target = Path(asset_paths[normalized_path(asset["source"])])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if digest(target.read_bytes()) != asset["sha256"]:
                raise SyncError("Managed attachment differs from its checksum: " + str(target))
        else:
            with target.open("xb") as stream:
                stream.write(members[asset["member"]])


def register_nodes(rpc, manifest, ids, rendered, mapped, folder):
    paths = {}
    for key, data in rendered.items():  # render_nodes insertion order is ancestor first
        path = Path(folder) / ("rollout-" + datetime.now().strftime("%Y-%m-%dT%H-%M-%S") + "-" + ids[key] + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        rpc.call("thread/resume", {"threadId": ids[key], "path": str(path), "cwd": mapped[key],
                                   "runtimeWorkspaceRoots": [mapped[key]], "excludeTurns": True})
        paths[key] = path
    return paths


def verify_chats(rpc, manifest, ids, assets):
    for chat in manifest["chats"]:
        turns = completed_turns(rpc, ids[chat["node"]])
        if turn_signatures(turns, assets) != chat["turns"]:
            actual = turn_signatures(turns, assets)
            mismatch = next((str(i) for i, (a,b) in enumerate(zip(actual, chat["turns"])) if a != b), "count")
            raise SyncError("Reconstructed history differs from the exported checkpoint: " + chat["title"] + " (turn index " + mismatch + ")")


def import_bundle(config, bundle, destinations, project_ids=None, selected=None, dry_run=False, progress=None, selected_nodes=None):
    _report(progress, "Validating bundle checksums and dependencies")
    manifest, members = read_bundle(bundle)
    if selected_nodes is not None:
        nodes = set(selected_nodes)
        available = {c["node"] for c in manifest["chats"]}
        if not nodes or not nodes.issubset(available):
            raise SyncError("Choose valid bundled conversation snapshots.")
        manifest["chats"] = [c for c in manifest["chats"] if c["node"] in nodes]
    project_ids = project_ids or {}
    if selected is not None:
        selection = set(selected)
        manifest["chats"] = [c for c in manifest["chats"] if c["logical_id"] in selection]
        if not manifest["chats"]:
            raise SyncError("Select at least one bundled chat.")
    for chat in manifest["chats"]:
        if chat["cwd"] not in destinations or not Path(destinations[chat["cwd"]]).is_dir():
            raise SyncError("Enter an existing destination folder for: " + chat["cwd"])
    with state_lock(config):
        ledger = load_ledger(config)
        plans = []
        _report(progress, "Comparing completed histories on this device")
        with Codex(config["codex_executable"], config["codex_home"]) as rpc:
            active = list_threads(rpc)
            active_ids = {t["id"] for t in active}
            current = active + list_threads(rpc, True)
            current_by_id = {t["id"]: t for t in current}
            relevant = {c["logical_id"] for c in manifest["chats"]}
            for thread_id, receipt in ledger["physical"].items():
                if receipt["logical_id"] in relevant and thread_id not in current_by_id:
                    try:
                        find_rollout(config["codex_home"], thread_id)
                    except SyncError:
                        raise SyncError("A previously tracked chat is missing/ambiguous: " + thread_id + ". Restore its files/receipts before importing.")
                    current_by_id[thread_id] = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
            for chat in manifest["chats"]:
                comparisons = []
                same_destination = False
                for thread_id, thread in current_by_id.items():
                    if logical_id(ledger, thread_id) == chat["logical_id"]:
                        if ledger["physical"].get(thread_id, {}).get("role") == "rolled_back" and thread_id not in active_ids:
                            continue
                        turns = completed_turns(rpc, thread_id)
                        # Managed asset paths also normalize to the portable hash.
                        extras = []
                        for entry in ledger["imports"]:
                            extras.extend(entry.get("assets", []))
                        comparison = relation(turn_signatures(turns, manifest.get("assets", []) + extras), chat["turns"])
                        comparisons.append(comparison)
                        if comparison == "same" and normalized_path(thread["cwd"]) == normalized_path(destinations[chat["cwd"]]) and (
                                not project_ids.get(chat["cwd"]) or thread.get("projectId") == project_ids[chat["cwd"]]):
                            same_destination = True
                classification = ("same" if "same" in comparisons else "stale" if "stale" in comparisons
                                  else "branch" if "branch" in comparisons else "update" if comparisons else "new")
                if classification == "same" and not same_destination:
                    classification = "relocate"
                for previous in manifest["chats"][:len(plans)]:
                    if previous["logical_id"] == chat["logical_id"] and relation(previous["turns"], chat["turns"]) == "branch" and classification not in ("same", "stale"):
                        classification = "branch"
                plans.append({"logical_id": chat["logical_id"], "title": chat["title"], "action": classification,
                              "destination": destinations[chat["cwd"]], "node": chat["node"]})
        if dry_run:
            _report(progress, "Import review is ready")
            return plans
        applicable = {p["node"] for p in plans if p["action"] not in ("same", "stale")}
        if not applicable:
            _report(progress, "Selected histories are already available or newer on this device")
            return plans
        manifest["chats"] = [c for c in manifest["chats"] if c["node"] in applicable]
        operation = uuid.uuid4().hex
        assets_dir = Path(config["state_dir"]) / "assets"
        ids, rendered, mapped, asset_paths, assets = render_nodes(manifest, members, destinations, assets_dir)
        _report(progress, "Preparing portable attachments")
        install_assets(manifest, members, asset_paths)
        # Validate without accounts/configuration or touching destination databases.
        _report(progress, "Reconstructing histories in an isolated data folder")
        with tempfile.TemporaryDirectory(prefix="chat-sync-verify-") as temporary:
            lab = Path(temporary)
            with Codex(config["codex_executable"], lab) as rpc:
                register_nodes(rpc, manifest, ids, rendered, mapped, lab / "sessions" / datetime.now().strftime("%Y/%m/%d"))
            with Codex(config["codex_executable"], lab) as rpc:
                for chat in manifest["chats"]:
                    rpc.call("thread/resume", {"threadId": ids[chat["node"]], "excludeTurns": True})
                verify_chats(rpc, manifest, ids, assets)
        _report(progress, "Completed histories verified after restart")
        folder = Path(config["codex_home"]) / "sessions" / datetime.now().strftime("%Y/%m/%d")
        journal_path = Path(config["state_dir"]) / "operations" / (operation + ".json")
        journal = {"operation": operation, "status": "prepared", "thread_ids": list(ids.values()),
                   "bundle": str(Path(bundle).resolve()), "created_at": datetime.now(timezone.utc).isoformat()}
        atomic_json(journal_path, journal)
        backup = Path(config["state_dir"]) / "backups" / (operation + ".json")
        atomic_json(backup, ledger)
        selected_ids = {ids[c["node"]] for c in manifest["chats"]}
        registered = []
        try:
            with Codex(config["codex_executable"], config["codex_home"]) as rpc:
                # Each file is new and exclusively created, never replacing an existing rollout.
                for index, (key, data) in enumerate(rendered.items(), 1):
                    _report(progress, f"Registering history {index} of {len(rendered)}")
                    one = {key: data}
                    register_nodes(rpc, manifest, ids, one, mapped, folder)
                    registered.append(ids[key])
                verify_chats(rpc, manifest, ids, assets)
                _report(progress, "Assigning conversation titles and destination projects")
                for chat in manifest["chats"]:
                    physical = ids[chat["node"]]
                    plan = next(p for p in plans if p["node"] == chat["node"])
                    suffix = " [branch from " + manifest["source_device"] + "]" if plan["action"] == "branch" else ""
                    rpc.call("thread/name/set", {"threadId": physical, "name": chat["title"] + suffix})
                    project_id = project_ids.get(chat["cwd"])
                    if project_id:
                        rpc.call("thread/metadata/update", {"threadId": physical, "projectId": project_id})
                    elif chat.get("project"):
                        root = str(Path(destinations[chat["cwd"]]).resolve())
                        project = rpc.call("project/import", {"idempotencyKey": "chat-sync:" + digest(root.encode()),
                                           "name": chat["project"].get("name", Path(root).name), "roots": [{"path": root}]})
                        project_id = project["project"]["id"]
                        rpc.call("thread/metadata/update", {"threadId": physical, "projectId": project_id})
                    ledger["physical"][physical] = {"logical_id": chat["logical_id"], "role": "import", "operation": operation}
                    plan["thread_id"] = physical
                    plan["project_id"] = project_id
                for thread_id in registered:
                    if thread_id not in selected_ids:
                        rpc.call("thread/archive", {"threadId": thread_id})
            # Restart against actual destination before committing receipts.
            with Codex(config["codex_executable"], config["codex_home"]) as rpc:
                for chat in manifest["chats"]:
                    thread = rpc.call("thread/resume", {"threadId": ids[chat["node"]], "excludeTurns": True})["thread"]
                    if normalized_path(thread["cwd"]) != normalized_path(destinations[chat["cwd"]]):
                        raise SyncError("Destination folder changed after restart.")
                verify_chats(rpc, manifest, ids, assets)
            _report(progress, "Verified destination histories; saving import receipts")
            ledger["imports"].append({"operation": operation, "bundle_sha256": digest(Path(bundle).read_bytes()),
                                      "thread_ids": list(selected_ids), "assets": assets, "plans": plans})
            atomic_json(ledger_path(config), ledger)
            journal["status"] = "committed"
            atomic_json(journal_path, journal)
        except Exception:
            journal["status"] = "failed"
            journal["registered"] = registered
            atomic_json(journal_path, journal)
            # Preserve evidence; hide only newly created chats after a failed transaction.
            with Codex(config["codex_executable"], config["codex_home"]) as rpc:
                for thread_id in registered:
                    try:
                        rpc.call("thread/archive", {"threadId": thread_id})
                    except SyncError:
                        pass
            raise
        _report(progress, "Import complete")
        return plans


def rollback(config, operation):
    """Archive imported copies only; never remove source chats or new user messages."""
    if not operation or any(c not in "0123456789abcdef" for c in operation):
        raise SyncError("Invalid operation ID.")
    with state_lock(config):
        path = Path(config["state_dir"]) / "operations" / (operation + ".json")
        if not path.is_file():
            raise SyncError("Operation not found.")
        journal = json.loads(path.read_text(encoding="utf-8"))
        with Codex(config["codex_executable"], config["codex_home"]) as rpc:
            available = {t["id"] for t in list_threads(rpc)}
            for thread_id in journal["thread_ids"]:
                if thread_id in available:
                    rpc.call("thread/archive", {"threadId": thread_id})
        journal["status"] = "rolled_back"
        atomic_json(path, journal)
        ledger = load_ledger(config)
        for tid in journal["thread_ids"]:
            if tid in ledger["physical"]:
                ledger["physical"][tid]["role"] = "rolled_back"
        ledger["imports"] = [e for e in ledger["imports"] if e["operation"] != operation]
        atomic_json(ledger_path(config), ledger)
