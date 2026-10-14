"""Desktop interface: bridge behaviour, service contract and dependency boundary."""
import ast
import inspect
from pathlib import Path
import threading
import time
import unittest

from chatsync.core.config import SyncError
from chatsync.core.service import ChatSyncService
from chatsync.interfaces.gui.app import Api

GUI = Path(__file__).resolve().parents[2] / "chatsync" / "interfaces" / "gui"


class FakeService:
    config = {"mappings": {"a": {"destination": "/x", "project_id": None}}}
    settings_path = Path("/tmp/settings.json")

    def defaults(self):
        return {"device_name": "device"}

    def snapshot(self, archived):
        return [{"id": "t"}], [{"id": "p"}], [Path("/ex/a.chatbundle.zip")], []

    def inspect(self, path):
        manifest = {"source_device": "office", "codex_version": "1", "created_at": "", "chats": [
            {"source_thread_id": "t", "title": "T", "cwd": "/c", "turns": [1, 2], "project": None}]}
        return Path(path), manifest, "fingerprint"

    def export(self, ids, progress):
        progress("working")
        time.sleep(0.3)
        return Path("/ex/new.zip")

    def analyze(self, *arguments):
        raise SyncError("bundle changed")

    def preview(self, thread_id):
        return {"turn_count": 1}

    def history(self):
        return []


class Window:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, script):
        self.calls.append(script)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.api = Api(service=FakeService())
        self.window = Window()
        self.api._window = self.window

    def test_results_are_json_safe_and_errors_never_raise(self):
        settings = self.api.get_settings()
        self.assertEqual(settings["data"]["settings_path"], "/tmp/settings.json")
        snapshot = self.api.load_snapshot(False)
        self.assertEqual(snapshot["data"]["bundles"], [{"path": "/ex/a.chatbundle.zip", "name": "a.chatbundle.zip"}])
        bundle = self.api.load_bundle("/ex/a.chatbundle.zip")
        self.assertEqual((bundle["data"]["chats"][0]["turns"], bundle["data"]["hash"]), (2, "fingerprint"))
        self.assertEqual(self.api.review_import("p", ["t"], {}, {}, "x"), {"ok": False, "error": "bundle changed"})

    def test_one_operation_at_a_time_and_closing_is_blocked_meanwhile(self):
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.update(self.api.export_chats(["t"])))
        worker.start()
        time.sleep(0.1)
        self.assertFalse(self.api._on_closing())
        refused = self.api.load_history()
        self.assertFalse(refused["ok"])
        self.assertIn("Wait", refused["error"])
        self.assertTrue(self.api.preview("t")["ok"])  # read-only preview is not exclusive
        worker.join()
        self.assertEqual(outcome, {"ok": True, "data": {"path": "/ex/new.zip"}})
        self.assertTrue(self.api._on_closing())
        self.assertTrue(any("working" in call for call in self.window.calls))

    def test_display_failure_cannot_abort_an_operation(self):
        class Broken:
            def evaluate_js(self, script):
                raise RuntimeError("window closed")
        self.api._window = Broken()
        self.assertTrue(self.api.export_chats(["t"])["ok"])


class ContractTests(unittest.TestCase):
    """Fails loudly if core's service drifts away from what the desktop interface calls."""

    CALLS = {
        "defaults": (), "snapshot": (False,), "preview": ("id",), "export": (["id"], print),
        "inspect": ("path",), "analyze": ("path", ["id"], {}, {}, "hash", print),
        "perform_import": ("path", ["id"], {}, {}, "hash", print), "history": (),
        "rollback": ("operation", print), "save_settings": ({},),
    }

    def test_service_exposes_every_method_the_interface_uses(self):
        for name, arguments in self.CALLS.items():
            method = getattr(ChatSyncService, name, None)
            self.assertIsNotNone(method, name)
            inspect.signature(method).bind(None, *arguments)  # raises TypeError on a mismatch


class BoundaryTests(unittest.TestCase):
    def test_interface_depends_on_core_only(self):
        for path in GUI.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level >= 2:
                    self.assertTrue((node.module or "").startswith("core"), f"{path.name}: {node.module}")
                elif isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("chatsync.interfaces"), path.name)
                elif isinstance(node, ast.Import):
                    for item in node.names:
                        self.assertFalse(item.name.startswith(("chatsync.interfaces", "textual", "rich")), path.name)

    def test_importing_the_interface_needs_no_gui_packages(self):
        source = (GUI / "app.py").read_text(encoding="utf-8")
        top_level = [n for n in ast.parse(source).body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any(getattr(n, "module", None) == "webview" or
                             any(a.name == "webview" for a in getattr(n, "names", [])) for n in top_level))


if __name__ == "__main__":
    unittest.main()
