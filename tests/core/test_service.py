from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from chatsync.core.config import SyncError
from chatsync.core.service import ChatSyncService, file_fingerprint


class ServiceTests(unittest.TestCase):
    def test_selecting_one_of_two_branches_routes_only_its_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "fixture.zip"
            bundle.write_bytes(b"immutable fixture")
            target = root / "workspace"
            target.mkdir()
            service = ChatSyncService(root / "config.json")
            service.config = {"mappings": {}}
            manifest = {"chats": [{"source_thread_id": "one", "node": "snapshot-one", "cwd": "source"},
                                   {"source_thread_id": "two", "node": "snapshot-two", "cwd": "source"}]}
            fingerprint = file_fingerprint(bundle)
            with patch("chatsync.core.service.read_bundle", return_value=(manifest, {})), \
                    patch("chatsync.core.service.import_bundle", return_value=[]) as migration:
                service.analyze(bundle, ["two"], {"source": str(target)}, {}, fingerprint, lambda text: None)
                self.assertEqual(migration.call_args.kwargs["selected_nodes"], ["snapshot-two"])
                service.perform_import(bundle, ["two"], {"source": str(target)}, {}, fingerprint, lambda text: None)
                self.assertEqual(migration.call_args.kwargs["selected_nodes"], ["snapshot-two"])
                self.assertTrue(service.settings_path.exists())
                bundle.write_bytes(b"modified fixture")
                with self.assertRaisesRegex(SyncError, "changed"):
                    service.perform_import(bundle, ["two"], {"source": str(target)}, {}, fingerprint, lambda text: None)
                self.assertEqual(migration.call_count, 2)

    def test_include_archived_retains_active_chats(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ChatSyncService(Path(directory) / "settings.json")
            service.config = {"device_name": "Device A"}
            active, archived = {"id": "active"}, {"id": "archived"}
            with patch("chatsync.core.service.inventory", side_effect=[([active], []), ([archived], [])]), \
                    patch.object(service, "bundles", return_value=[]), patch.object(service, "history", return_value=[]):
                threads, _, _, _ = service.snapshot(archived=True)
                self.assertEqual({t["id"] for t in threads}, {"active", "archived"})

    def test_missing_destination_stops_before_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "fixture.zip"
            bundle.write_bytes(b"fixture")
            service = ChatSyncService(root / "settings.json")
            service.config = {"mappings": {}}
            manifest = {"chats": [{"source_thread_id": "one", "node": "node", "cwd": "source"}]}
            with patch("chatsync.core.service.read_bundle", return_value=(manifest, {})), \
                    patch("chatsync.core.service.import_bundle") as migration:
                with self.assertRaisesRegex(SyncError, "destination"):
                    service.analyze(bundle, ["one"], {"source": ""}, {}, file_fingerprint(bundle), lambda text: None)
                migration.assert_not_called()
