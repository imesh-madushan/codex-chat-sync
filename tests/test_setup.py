"""Setup resource fallback and interface launch checks, with no live migrations."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import launch
import setup


class SetupTests(unittest.TestCase):
    def resource_tree(self, root):
        directory = root / "web" / "dist"
        directory.mkdir(parents=True)
        (directory / "app.js").write_text("// neutral fixture", encoding="utf-8")
        (directory / "index.html").write_text('<script src="./app.js"></script>', encoding="utf-8")
        return directory

    def test_complete_resources_work_without_npm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.resource_tree(root)
            spec = {"web": {"directory": "web", "output": "web/dist"}}
            output = io.StringIO()
            with patch.object(setup, "ROOT", root), patch("setup.shutil.which", return_value=None), \
                    patch("setup.subprocess.run") as run, contextlib.redirect_stdout(output):
                setup.prepare_resources(spec)
                run.assert_not_called()
            self.assertIn("no frontend build", output.getvalue())
            self.assertIn("Node.js/npm isn't installed", output.getvalue())

    def test_missing_asset_is_rejected_without_npm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = self.resource_tree(root)
            (directory / "app.js").unlink()
            self.assertFalse(setup.resources_ready(directory))
            with patch.object(setup, "ROOT", root), patch("setup.shutil.which", return_value=None):
                with self.assertRaisesRegex(ValueError, "missing or incomplete"):
                    setup.prepare_resources({"web": {"directory": "web", "output": "web/dist"}})

    def test_frontend_build_must_produce_complete_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "web").mkdir()
            with patch.object(setup, "ROOT", root), patch("setup.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "complete interface"):
                    setup.prepare_resources({"web": {"directory": "web", "output": "web/dist"}}, npm="npm")
                self.assertEqual([call.args[0] for call in run.call_args_list], [["npm", "ci"], ["npm", "run", "build"]])

    def test_resource_references_cannot_escape_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = self.resource_tree(root)
            (root / "outside.js").write_text("// fixture", encoding="utf-8")
            (directory / "index.html").write_text('<script src="../../outside.js"></script>', encoding="utf-8")
            self.assertFalse(setup.resources_ready(directory))

    def test_interface_paths_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(setup, "ROOT", Path(temporary)):
            with self.assertRaisesRegex(ValueError, "inside this project"):
                setup.local_path("../outside.py")

    def test_cli_launch_preserves_arguments_and_exit_code(self):
        with patch("launch.interfaces", return_value={"cli": {"entry": "chat_sync.py"}}), \
                patch("launch.Path.is_file", return_value=True), patch("launch.subprocess.call", return_value=7) as call:
            self.assertEqual(launch.main(["--interface", "cli", "--config", "settings.json", "list"]), 7)
            self.assertEqual(call.call_args.args[0][-3:], ["--config", "settings.json", "list"])

    @unittest.skipUnless(os.name == "nt", "Windowless dispatch is Windows-specific")
    def test_gui_launch_detaches_without_console(self):
        with patch("launch.interfaces", return_value={"gui": {"entry": "chat_sync_gui.py", "windowed": True}}), \
                patch("launch.Path.is_file", return_value=True), patch("launch.subprocess.Popen") as process:
            self.assertEqual(launch.main(["--config", "settings.json"]), 0)
            self.assertTrue(process.call_args.args[0][0].endswith("pythonw.exe"))
            self.assertEqual(process.call_args.kwargs["creationflags"], launch.subprocess.CREATE_NO_WINDOW)
            self.assertEqual(process.call_args.args[0][-2:], ["--config", "settings.json"])
