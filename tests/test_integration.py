"""Real Codex protocol tests in isolated data folders; no accounts or model calls.

Set CHATSYNC_TEST_CODEX and CHATSYNC_TEST_FIXTURE (a local parent/fork regression fixture ZIP).
This intentionally does not read or mutate a production Codex database.
"""
import copy
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
import uuid
import zipfile

from chatsync.bundle import digest, read_bundle, records, write_bundle
from chatsync.bundle import encode, find_rollout
from chatsync.config import atomic_json, make_config
from chatsync.engine import (export_chats, import_bundle, inventory, ledger_path, load_ledger,
                             rollback)
from chatsync.rpc import Codex

EXE = os.environ.get("CHATSYNC_TEST_CODEX")
FIXTURE = os.environ.get("CHATSYNC_TEST_FIXTURE")


@unittest.skipUnless(EXE and FIXTURE, "Set real Codex executable and discovery fixture")
class CodexIntegration(unittest.TestCase):
    def test_multi_chat_dependency_reidentification_restart_and_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="chat-sync-integration-") as temporary:
            root = Path(temporary)
            source_home = root / "source-home"
            dest_home = root / "dest-home"
            source_home.mkdir()
            dest_home.mkdir()
            workspace = root / "workspace folder café"
            workspace.mkdir()
            source = make_config(source_home, EXE, root / "exchange", root / "source-state")
            dest = make_config(dest_home, EXE, root / "exchange", root / "dest-state")
            with zipfile.ZipFile(FIXTURE) as archive:
                rollouts = [(name, archive.read(name)) for name in archive.namelist() if name.endswith(".jsonl")]
            rollouts.sort(key=lambda item: records(item[1])[0].get("ordinal", 0))
            source_ids = []
            source_cwds = []
            ancestor_sizes = {}
            with Codex(EXE, source_home) as rpc:
                for name, data in rollouts:
                    raw_records = records(data)
                    meta = raw_records[0]["payload"]
                    meta["cwd"] = str(workspace)
                    meta["runtime_workspace_roots"] = [str(workspace)]
                    if meta.get("history_base"):
                        meta["history_base"]["end_byte_offset"] = ancestor_sizes[meta["history_base"]["thread_id"]]
                    data = b"".join(json.dumps(r,ensure_ascii=False,separators=(',',':')).encode('utf-8') + b'\n' for r in raw_records)
                    ancestor_sizes[meta["id"]] = len(data)
                    path = source_home / "sessions" / "2026" / "10" / "13" / Path(name).name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    rpc.call("thread/resume", {"threadId": meta["id"], "path": str(path),
                                               "cwd": str(workspace), "excludeTurns": True})
                    source_ids.append(meta["id"])
                    source_cwds.append(str(workspace))
                    rpc.call("thread/name/set", {"threadId": meta["id"], "name": "Integration " + str(len(source_ids))})
                project = rpc.call("project/import", {"idempotencyKey": "integration", "name": "Example",
                                                       "roots": [{"path": str(workspace)}]})
                project_id = project["project"]["id"]
                rpc.call("thread/metadata/update", {"threadId": source_ids[0], "projectId": project_id})
            print("EXPORT two source chats")
            bundle = export_chats(source, source_ids)
            manifest, members = read_bundle(bundle)
            self.assertEqual(len(manifest["chats"]), 2)
            self.assertGreaterEqual(len(manifest["nodes"]), 3)
            print("TERMINAL setup, inspect, project selection and dry-run")
            profile = root / "terminal-config.json"
            program = Path(__file__).resolve().parents[1] / "chat_sync.py"
            def command(*argv):
                result = subprocess.run([sys.executable, str(program), "--config", str(profile), *map(str, argv)],
                                        capture_output=True, text=True, encoding="utf-8", timeout=60,
                                        env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            command("setup", "--codex-home", dest_home, "--codex-executable", EXE,
                    "--exchange-dir", root / "exchange", "--state-dir", root / "terminal-state")
            self.assertIn("Verified bundle", command("inspect", bundle))
            self.assertIn("new", command("import", bundle, "--dry-run", "--yes", "--map", str(workspace) + "=" + str(workspace)))
            print("IMPORT complete ancestry")
            plans = import_bundle(dest, bundle, {str(workspace): str(workspace)})
            self.assertEqual([p["action"] for p in plans], ["new", "new"])
            with Codex(EXE, dest_home) as rpc:
                for plan in plans:
                    self.assertNotIn(plan["thread_id"], source_ids)
                    turns = rpc.turns(plan["thread_id"])
                    self.assertIn(len(turns), (9, 10))
                visible = rpc.pages("thread/list")
                self.assertEqual(len(visible), 2)
            print("REIMPORT no-op")
            again = import_bundle(dest, bundle, {str(workspace): str(workspace)})
            self.assertEqual([p["action"] for p in again], ["same", "same"])
            print("RETURN export from destination and import into source")
            returned = export_chats(dest, [p["thread_id"] for p in plans])
            return_plans = import_bundle(source, returned, {str(workspace): str(workspace)})
            self.assertEqual([p["action"] for p in return_plans], ["same", "same"])
            # A real 9-turn checkpoint and its 10-turn descendant share a logical identity.
            original, child = sorted(manifest["chats"], key=lambda c: len(c["turns"]))
            stale_manifest = copy.deepcopy(manifest)
            stale_manifest["chats"] = [dict(original, logical_id=child["logical_id"])]
            def prune(m):
                needed = set()
                def walk(k):
                    if k not in needed:
                        needed.add(k)
                        if m["nodes"][k].get("parent"):
                            walk(m["nodes"][k]["parent"])
                for chat in m["chats"]:
                    walk(chat["node"])
                m["nodes"] = {k:v for k,v in m["nodes"].items() if k in needed}
                return {n["member"]: members[n["member"]] for n in m["nodes"].values()}
            stale_file = root / "stale.zip"
            write_bundle(stale_file, stale_manifest, prune(stale_manifest))
            self.assertEqual(import_bundle(dest, stale_file, {str(workspace): str(workspace)})[0]["action"], "stale")
            print("UPDATE 9 turns to 10 turns in another destination")
            third_home = root / "third-home"
            third_home.mkdir()
            third = make_config(third_home, EXE, root / "exchange", root / "third-state")
            import_bundle(third, stale_file, {str(workspace): str(workspace)})
            only_child = copy.deepcopy(manifest)
            only_child["chats"] = [child]
            child_file = root / "child.zip"
            write_bundle(child_file, only_child, prune(only_child))
            self.assertEqual(import_bundle(third, child_file, {str(workspace): str(workspace)})[0]["action"], "update")
            print("DIVERGENT real persisted turn history preserves both branches")
            child_source_id = child["source_thread_id"]
            new_id, new_turn = str(uuid.uuid4()), str(uuid.uuid4())
            image = root / "local image.png"
            image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1cAAAAASUVORK5CYII="))
            rs = records(find_rollout(source_home, child_source_id).read_bytes())
            old_turn = child["turns"][-1]["id"]
            def change(value, key=None):
                if isinstance(value, dict):
                    return {k: change(v, k) for k, v in value.items()}
                if isinstance(value, list):
                    return [change(v, key) for v in value]
                if value == child_source_id:
                    return new_id
                if value == old_turn:
                    return new_turn
                return value
            rs = change(rs)
            for r in rs:
                if r["type"] == "response_item" and r["payload"].get("type") == "message" and r["payload"].get("role") == "user":
                    r["payload"]["content"].append({"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode('ascii')})
                    for content in r["payload"].get("content", []):
                        if "text" in content:
                            content["text"] += " Alternative branch test."
                if r["type"] == "event_msg" and r["payload"].get("type") == "item_completed" and r["payload"].get("item", {}).get("type") == "UserMessage":
                    r["payload"]["item"]["content"].append({"type": "localImage", "path": str(image)})
                    for content in r["payload"]["item"].get("content", []):
                        if "text" in content:
                            content["text"] += " Alternative branch test."
            path = source_home / "sessions" / "2026" / "10" / "13" / ("rollout-2026-10-13T00-00-00-" + new_id + ".jsonl")
            path.write_bytes(b"".join(encode(r) + b"\n" for r in rs))
            with Codex(EXE, source_home) as rpc:
                rpc.call("thread/resume", {"threadId": new_id, "path": str(path), "cwd": str(workspace), "excludeTurns": True})
                rpc.call("thread/name/set", {"threadId": new_id, "name": "Divergent fixture"})
            ledger = load_ledger(source)
            ledger["physical"][new_id] = {"logical_id": child["logical_id"], "role": "source"}
            atomic_json(ledger_path(source), ledger)
            branch_bundle = export_chats(source, [new_id])
            self.assertTrue(any(a["source"] == str(image) for a in read_bundle(branch_bundle)[0]["assets"]))
            branch = import_bundle(dest, branch_bundle, {str(workspace): str(workspace)})
            self.assertEqual(branch[0]["action"], "branch")
            self.assertEqual(len(inventory(dest)[0]), 3)
            print("MULTI-BRANCH selection, distinct folder mappings and explicit assets")
            asset = root / "example document.txt"
            asset.write_text("Portable attachment fixture", encoding="utf-8")
            two_branches = export_chats(source, [child_source_id, new_id], attachments=[asset])
            two_manifest, two_members = read_bundle(two_branches)
            second_source = str(root / "different-source-folder")
            two_manifest["chats"][1]["cwd"] = second_source
            multi_mapped = root / "multi-mapped.zip"
            write_bundle(multi_mapped, two_manifest, two_members)
            fourth_home = root / "fourth-home"
            fourth_home.mkdir()
            fourth = make_config(fourth_home, EXE, root / "exchange", root / "fourth-state")
            target_a, target_b = root / "target-a", root / "target-b"
            target_a.mkdir()
            target_b.mkdir()
            maps = {str(workspace): str(target_a), second_source: str(target_b)}
            multiple = import_bundle(fourth, multi_mapped, maps)
            self.assertEqual([p["action"] for p in multiple], ["new", "branch"])
            with Codex(EXE, fourth_home) as rpc:
                for plan in multiple:
                    thread = rpc.call("thread/read", {"threadId": plan["thread_id"], "includeTurns": False})["thread"]
                    self.assertEqual(thread["cwd"], plan["destination"])
            self.assertEqual([p["action"] for p in import_bundle(fourth, multi_mapped, maps)], ["same", "same"])
            self.assertEqual(len(list((Path(fourth["state_dir"]) / "assets").rglob("example document.txt"))), 1)
            moved = root / "relocated-project"
            moved.mkdir()
            self.assertEqual(import_bundle(fourth, multi_mapped, {str(workspace): str(moved), second_source: str(target_b)},
                                          selected=[two_manifest["chats"][0]["logical_id"]])[0]["action"], "relocate")
            print("EXACT selected branch and progress reporting")
            fifth_home = root / "fifth-home"
            fifth_home.mkdir()
            fifth = make_config(fifth_home, EXE, root / "exchange", root / "fifth-state")
            progress_messages = []
            chosen_node = two_manifest["chats"][1]["node"]
            one_branch = import_bundle(fifth, multi_mapped, maps, selected_nodes=[chosen_node],
                                       progress=progress_messages.append)
            self.assertEqual(len(one_branch), 1)
            self.assertEqual(len(inventory(fifth)[0]), 1)
            self.assertIn("Import complete", progress_messages)
            self.assertEqual(one_branch[0]["title"], two_manifest["chats"][1]["title"])
            print("NESTED metadata-only fork dependencies")
            with Codex(EXE, dest_home) as rpc:
                nested = rpc.call("thread/fork", {"threadId": branch[0]["thread_id"], "excludeTurns": True,
                                                "lastTurnId": new_turn, "cwd": str(workspace), "deferGoalContinuation": True})["thread"]["id"]
            nested_bundle = export_chats(dest, [nested])
            nested_plans = import_bundle(third, nested_bundle, {str(workspace): str(workspace)})
            self.assertEqual(nested_plans[0]["action"], "new")
            print("ROLLBACK archives imported copies")
            entry = load_ledger(dest)["imports"][-1]
            rollback(dest, entry["operation"])
            self.assertEqual(len(inventory(dest)[0]), 2)
            rollback(dest, load_ledger(dest)["imports"][0]["operation"])
            self.assertEqual(len(inventory(dest)[0]), 0)
            with Codex(EXE, dest_home) as rpc:
                self.assertEqual(len(rpc.turns(nested)), 10)  # Native fork is never removed by rollback


if __name__ == "__main__":
    unittest.main()
