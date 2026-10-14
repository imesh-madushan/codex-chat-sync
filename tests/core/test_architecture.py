"""Enforce the framework-free core dependency boundary."""
import ast
from pathlib import Path
import unittest
from chatsync.core.engine import _report


class ArchitectureTests(unittest.TestCase):
    def test_core_does_not_import_interfaces_or_external_ui_packages(self):
        directory = Path(__file__).resolve().parents[2] / "chatsync" / "core"
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    self.assertLessEqual(node.level, 1, str(path))
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    self.assertFalse(name.startswith(("chatsync.interfaces", "textual", "rich")), str(path))

    def test_progress_observer_failure_does_not_interrupt_transaction(self):
        def broken_observer(message):
            raise RuntimeError("Display failed")
        _report(broken_observer, "Migration continues")
