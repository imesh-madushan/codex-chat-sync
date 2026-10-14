import json
from pathlib import Path
import tempfile
import unittest
import uuid
import zipfile

from chatsync.core.bundle import digest, encode, read_bundle, relation, write_bundle
from chatsync.core.config import SyncError, make_config, state_lock, relocate_state


def sample():
    thread = str(uuid.uuid4())
    logical = str(uuid.uuid4())
    data = encode({"type": "session_meta", "ordinal": 0, "payload": {"id": thread, "cwd": "/tmp"}}) + b"\n"
    sha = digest(data)
    name = "rollouts/" + sha + ".jsonl"
    manifest = {"nodes": {sha: {"member": name, "parent": None, "thread_id": thread, "size": len(data), "sha256": sha}},
                "chats": [{"logical_id": logical, "source_thread_id": thread, "node": sha, "turns": [{"id": "turn", "sha256": "0" * 64}]}]}
    return manifest, {name: data}


class BundleTests(unittest.TestCase):
    def test_roundtrip_and_immutable_publish(self):
        manifest, members = sample()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.zip"
            write_bundle(path, manifest, members)
            self.assertEqual(read_bundle(path)[1], members)
            with self.assertRaises(SyncError):
                write_bundle(path, manifest, members)

    def test_checksum_tampering(self):
        manifest, members = sample()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.zip"
            write_bundle(path, manifest, members)
            with zipfile.ZipFile(path) as z:
                contents = {n: z.read(n) for n in z.namelist()}
            contents[next(n for n in contents if n.endswith(".jsonl"))] += b" \n"
            with zipfile.ZipFile(path, "w") as z:
                for name, data in contents.items():
                    z.writestr(name, data)
            with self.assertRaisesRegex(SyncError, "mismatch"):
                read_bundle(path)

    def test_unsafe_names_and_duplicate_members(self):
        for name in ("../outside", "/absolute", "C:/absolute", "a\\b", "a/../b", "a//b"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.zip"
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr(name, b"x")
                with self.assertRaises(SyncError):
                    read_bundle(path)

    def test_missing_ancestor_and_cycle(self):
        manifest, members = sample()
        key = next(iter(manifest["nodes"]))
        manifest["nodes"][key]["parent"] = "missing"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SyncError):
                write_bundle(Path(directory) / "bad.zip", manifest, members)

    def test_history_conflict_classification(self):
        a, b, c = [{"id": v, "sha256": v} for v in "abc"]
        self.assertEqual(relation([a], [a]), "same")
        self.assertEqual(relation([a], [a, b]), "update")
        self.assertEqual(relation([a, b], [a]), "stale")
        self.assertEqual(relation([a, b], [a, c]), "branch")
        self.assertEqual(relation([a], [dict(a, sha256="different")]), "branch")

    def test_exclusive_local_state_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"state_dir": directory}
            with state_lock(config):
                with self.assertRaises(SyncError):
                    with state_lock(config):
                        pass

    def test_state_relocation_retains_receipts_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "old", Path(directory) / "new"
            old.mkdir()
            new.mkdir()
            (old / "receipts-device.json").write_text("receipt", encoding="utf-8")
            (old / "unrelated.txt").write_text("do not move", encoding="utf-8")
            relocate_state({"state_dir": str(old)}, {"state_dir": str(new)})
            self.assertEqual((new / "receipts-device.json").read_text(), "receipt")
            self.assertTrue((old / "receipts-device.json").exists())
            self.assertFalse((new / "unrelated.txt").exists())
            with self.assertRaises(SyncError):
                relocate_state({"state_dir": str(old)}, {"state_dir": str(new)})


if __name__ == "__main__":
    unittest.main()
