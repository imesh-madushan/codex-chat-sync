import io
import unittest
from pathlib import Path
from unittest.mock import patch
from chatsync.interfaces.cli.app import choose, main


class CLITests(unittest.TestCase):
    def test_multi_selection_ranges_and_validation(self):
        with patch("builtins.input", side_effect=["0", "8-10", "1,3-4"]), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(choose(list("abcde"), "chats"), [0, 2, 3])

    def test_export_routes_to_core_without_ui_dependencies(self):
        with patch("chatsync.interfaces.cli.app.load_config", return_value={}), \
                patch("chatsync.interfaces.cli.app.select_export", return_value=["chat"]), \
                patch("chatsync.interfaces.cli.app.export_chats", return_value=Path("bundle.zip")) as export, \
                patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(main(["export", "--thread", "chat"]), 0)
            export.assert_called_once()

    def test_default_launch_uses_plain_menu(self):
        with patch("chatsync.interfaces.cli.app.load_config", return_value={}), \
                patch("chatsync.interfaces.cli.app.menu") as menu:
            self.assertEqual(main([]), 0)
            menu.assert_called_once()
