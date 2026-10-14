"""Headless terminal interaction tests using neutral, synthetic conversations."""
import asyncio
import copy
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    import textual
except ModuleNotFoundError:
    textual = None

if textual is not None:
    from textual.widgets import Button, Input, SelectionList, Select, Static, TabbedContent
    from chatsync.tui import ChatSyncApp, ConfirmScreen

from chatsync.config import SyncError
from chatsync.ui_service import UIService, file_fingerprint


class FakeBackend:
    """No accounts, filesystem migrations or subprocesses are used by UI tests."""
    def __init__(self, root, configured=True):
        self.settings_path = root / "config.json"
        self.config = {"device_name": "Device A", "exchange_dir": str(root / "exchange"), "mappings": {}}
        self.values = dict(self.config, codex_home=str(root / "codex-data"), codex_executable=str(root / "codex.exe"),
                           state_dir=str(root / "state"))
        if not configured:
            self.config = None
        self.threads = [{"id": "chat-1", "name": "Plan database schema", "cwd": "D:/Projects/sample-app",
                         "projectId": "project-1", "updatedAt": 0},
                        {"id": "chat-2", "name": "Review API endpoints", "cwd": "D:/Projects/sample-app",
                         "projectId": "project-1", "updatedAt": 0},
                        {"id": "chat-3", "name": "Discuss database indexing", "cwd": "D:/Projects/notes",
                         "projectId": None, "updatedAt": 0}]
        self.projects = [{"id": "project-1", "name": "sample-app", "roots": [{"path": "D:/Projects/sample-app"}]}]
        self.bundle_path = root / "example.chatbundle.zip"
        self.manifest = {"chats": [{"source_thread_id": "branch-1", "logical_id": "family-1", "node": "node-1",
                                    "title": "Plan database schema", "cwd": "D:/Projects/sample-app", "turns": [1] * 12},
                                   {"source_thread_id": "branch-2", "logical_id": "family-1", "node": "node-2",
                                    "title": "Plan database schema — branch", "cwd": "D:/Projects/notes", "turns": [1] * 13}]}
        self.exported = []
        self.imported = []
        self.saved = []
        self.hold_export = None
        self.import_calls = 0
        self.mappings_saved = []
        self.rolled_back = []

    def defaults(self):
        return self.values

    def snapshot(self, archived=False):
        return self.threads, self.projects, [self.bundle_path], self.history()

    def preview(self, thread_id):
        return {"turn_count": 12, "completed": 12, "last_message": "Add an index for the lookup field."}

    def inspect(self, path):
        return Path(path), self.manifest, "checksum"

    def export(self, ids, progress):
        if self.hold_export:
            self.hold_export.wait(timeout=5)
        self.exported.append(ids)
        progress("Export complete")
        return self.bundle_path

    def analyze(self, path, ids, destinations, projects, fingerprint, progress):
        progress("Import review is ready")
        self.last_analyzed = list(ids)
        return [{"title": "Plan database schema", "action": "branch", "destination": next(iter(destinations.values()))}]

    def perform_import(self, path, ids, destinations, projects, fingerprint, progress):
        self.import_calls += 1
        self.imported = list(ids)
        progress("Completed histories verified")
        return [{"title": "Plan database schema", "action": "branch", "thread_id": "imported-chat"}]

    def save_settings(self, values):
        self.saved.append(dict(values))
        self.config = dict(values, mappings={})
        return self.config

    def save_mapping(self, source, destination, project):
        self.mappings_saved.append((source, destination, project))
        self.config["mappings"][source] = {"destination": destination, "project_id": project}

    def rollback(self, operation, progress):
        self.rolled_back.append(operation)
        progress("Imported copies archived")
        return []

    def history(self):
        return []


async def idle(app, pilot):
    for _ in range(150):
        await pilot.pause(0.02)
        if not app.busy:
            await pilot.pause(0.05)
            if not app.busy:
                return
    raise AssertionError("UI operation did not finish")


@unittest.skipUnless(textual is not None, "Install requirements-tui.txt for UI tests")
class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyboard_selection_survives_search_and_exports_all_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend(Path(directory))
            app = ChatSyncApp(backend=backend)
            async with app.run_test(size=(130, 45)) as pilot:
                await idle(app, pilot)
                listing = app.query_one("#chat-list", SelectionList)
                listing.focus()
                listing.highlighted = 0
                await pilot.press("space", "down", "space")
                self.assertEqual(app.selected_chats, {"chat-1", "chat-2"})
                app.query_one("#chat-search", Input).value = "indexing"
                await pilot.pause()
                self.assertEqual(listing.option_count, 1)
                self.assertEqual(app.selected_chats, {"chat-1", "chat-2"})
                await pilot.click("#select-visible")
                self.assertEqual(app.selected_chats, {"chat-1", "chat-2", "chat-3"})
                await pilot.click("#export-chats")
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm-no")
                self.assertEqual(backend.exported, [])
                await pilot.click("#export-chats")
                await pilot.click("#confirm-yes")
                await idle(app, pilot)
                self.assertEqual(backend.exported, [["chat-1", "chat-2", "chat-3"]])

    async def test_import_review_confirm_and_exact_branch_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend(Path(directory))
            app = ChatSyncApp(backend=backend)
            async with app.run_test(size=(135, 50)) as pilot:
                await idle(app, pilot)
                app.query_one("#tabs", TabbedContent).active = "imports"
                app.query_one("#import-path", Input).value = str(backend.bundle_path)
                await pilot.pause()
                await pilot.click("#load-bundle")
                await idle(app, pilot)
                await pilot.pause(0.1)
                listing = app.query_one("#import-list", SelectionList)
                listing.select("branch-2")
                app.query_one("#destination-1", Input).value = directory
                await pilot.pause()
                self.assertTrue(app.query_one("#import-chats", Button).disabled)
                await pilot.click("#review-import")
                await idle(app, pilot)
                self.assertEqual(backend.last_analyzed, ["branch-2"])
                self.assertFalse(app.query_one("#import-chats", Button).disabled)
                app.query_one("#destination-1", Input).value = directory + "/changed"
                await pilot.pause()
                self.assertTrue(app.query_one("#import-chats", Button).disabled)
                await pilot.click("#review-import")
                await idle(app, pilot)
                await pilot.click("#import-chats")
                await pilot.click("#confirm-no")
                self.assertEqual(backend.import_calls, 0)
                await pilot.click("#import-chats")
                await pilot.click("#confirm-yes")
                await idle(app, pilot)
                self.assertEqual(backend.imported, ["branch-2"])

    async def test_first_launch_settings_and_compact_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend(Path(directory), configured=False)
            app = ChatSyncApp(backend=backend)
            async with app.run_test(size=(80, 35)) as pilot:
                await pilot.pause()
                self.assertEqual(app.query_one("#tabs", TabbedContent).active, "settings")
                app.query_one("#setting-exchange-dir", Input).value = str(Path(directory) / "bundles")
                await pilot.click("#save-settings")
                await idle(app, pilot)
                self.assertEqual(backend.saved[0]["exchange_dir"], str(Path(directory) / "bundles"))
                self.assertTrue(app.screen.has_class("compact"))
                app.query_one("#tabs", TabbedContent).active = "chats"
                await pilot.pause()
                self.assertGreater(app.query_one("#chat-list", SelectionList).size.height, 0)

    async def test_busy_operation_prevents_quit_and_double_export(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend(Path(directory))
            backend.hold_export = threading.Event()
            app = ChatSyncApp(backend=backend)
            try:
                async with app.run_test(size=(130, 45)) as pilot:
                    await idle(app, pilot)
                    app.query_one("#chat-list", SelectionList).select("chat-1")
                    await pilot.pause()
                    await pilot.click("#export-chats")
                    await pilot.click("#confirm-yes")
                    await pilot.pause()
                    self.assertTrue(app.busy)
                    self.assertTrue(app.query_one("#export-chats", Button).disabled)
                    app.action_quit()
                    self.assertTrue(app.is_running)
                    backend.hold_export.set()
                    await idle(app, pilot)
                    self.assertEqual(len(backend.exported), 1)
            finally:
                backend.hold_export.set()


    async def test_saved_mapping_edits_and_rollback_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = FakeBackend(Path(directory))
            backend.config["mappings"]["source-folder"] = {"destination": "old-folder", "project_id": "project-1"}
            backend.history = lambda: [{"operation": "operation-1", "status": "committed",
                                       "title": "Plan database schema", "created_at": "2026-01-01T09:00:00"}]
            app = ChatSyncApp(backend=backend)
            async with app.run_test(size=(135, 50)) as pilot:
                await idle(app, pilot)
                app.query_one("#tabs", TabbedContent).active = "settings"
                app.query_one("#saved-mapping", Select).value = "source-folder"
                await pilot.pause()
                self.assertEqual(app.query_one("#saved-destination", Input).value, "old-folder")
                app.query_one("#saved-destination", Input).value = directory
                app.query_one("#saved-project", Select).value = "auto"
                button = app.query_one("#save-mapping", Button)
                button.scroll_visible()
                await pilot.pause()
                await pilot.click("#save-mapping")
                await idle(app, pilot)
                self.assertEqual(backend.mappings_saved, [("source-folder", directory, None)])
                app.query_one("#tabs", TabbedContent).active = "history"
                await pilot.pause()
                await pilot.click("#rollback-operation")
                await pilot.click("#confirm-no")
                self.assertEqual(backend.rolled_back, [])
                await pilot.click("#rollback-operation")
                await pilot.click("#confirm-yes")
                await idle(app, pilot)
                self.assertEqual(backend.rolled_back, ["operation-1"])

    async def test_preview_is_available_in_small_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            app = ChatSyncApp(backend=FakeBackend(Path(directory)))
            async with app.run_test(size=(80, 24)) as pilot:
                await idle(app, pilot)
                listing = app.query_one("#chat-list", SelectionList)
                listing.highlighted = 0
                listing.focus()
                await pilot.pause(0.3)
                await pilot.press("f3")
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertLessEqual(app.screen.query_one("#confirm-yes", Button).region.bottom, app.size.height)
                await pilot.press("escape")
                self.assertNotIsInstance(app.screen, ConfirmScreen)


class ServiceTests(unittest.TestCase):
    def test_selecting_one_of_two_branches_routes_only_its_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "fixture.zip"
            bundle.write_bytes(b"immutable fixture")
            target = root / "workspace"
            target.mkdir()
            service = UIService(root / "config.json")
            service.config = {"mappings": {}}
            manifest = {"chats": [{"source_thread_id": "one", "node": "snapshot-one", "cwd": "source"},
                                   {"source_thread_id": "two", "node": "snapshot-two", "cwd": "source"}]}
            fingerprint = file_fingerprint(bundle)
            with patch("chatsync.ui_service.read_bundle", return_value=(manifest, {})), \
                    patch("chatsync.ui_service.import_bundle", return_value=[]) as migration:
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
            service = UIService(Path(directory) / "settings.json")
            service.config = {"device_name": "Device A"}
            active, archived = {"id": "active"}, {"id": "archived"}
            with patch("chatsync.ui_service.inventory", side_effect=[([active], []), ([archived], [])]), \
                    patch.object(service, "bundles", return_value=[]), patch.object(service, "history", return_value=[]):
                threads, _, _, _ = service.snapshot(archived=True)
                self.assertEqual({t["id"] for t in threads}, {"active", "archived"})

    def test_missing_destination_stops_before_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "fixture.zip"
            bundle.write_bytes(b"fixture")
            service = UIService(root / "settings.json")
            service.config = {"mappings": {}}
            manifest = {"chats": [{"source_thread_id": "one", "node": "node", "cwd": "source"}]}
            with patch("chatsync.ui_service.read_bundle", return_value=(manifest, {})), \
                    patch("chatsync.ui_service.import_bundle") as migration:
                with self.assertRaisesRegex(SyncError, "destination"):
                    service.analyze(bundle, ["one"], {"source": ""}, {}, file_fingerprint(bundle), lambda text: None)
                migration.assert_not_called()

    @unittest.skipUnless(textual is not None, "Install requirements-tui.txt for routing tests")
    def test_tui_and_legacy_export_routes_remain_separate(self):
        from chatsync.cli import main
        with patch("chatsync.tui.run_tui", return_value=0) as launch:
            self.assertEqual(main(["tui"]), 0)
            launch.assert_called_once_with(None)
        with patch("chatsync.cli.load_config", return_value={}), \
                patch("chatsync.cli.select_export", return_value=["chat"]), \
                patch("chatsync.cli.export_chats", return_value=Path("bundle.zip")) as export, \
                patch("chatsync.tui.run_tui") as launch, patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(main(["export", "--thread", "chat"]), 0)
            export.assert_called_once()
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
