"""Desktop interface (pywebview + React).

This module is an *interface*: it depends only on ``chatsync.core`` (through
``ChatSyncService``) and never on another interface, exactly like the CLI.
pywebview is imported lazily, so importing this module needs no GUI packages.

Run:   python chat_sync_gui.py            (uses web/dist built by `npm run build`)
Dev:   python chat_sync_gui.py --dev      (expects `npm run dev` on http://localhost:5173)
"""
import argparse
import functools
import json
from pathlib import Path
import sys
import threading

from ...core.config import SyncError
from ...core.service import ChatSyncService


def web_root():
    # PyInstaller unpacks data files under sys._MEIPASS.
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "chatsync" / "interfaces" / "gui" / "web"
    return Path(__file__).resolve().parent / "web"


def plain(value):
    """Make service results JSON-safe (Paths, sets, tuples)."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    return value


def reply(function):
    """Never raise into JavaScript: return {ok, data} or {ok: False, error}."""
    @functools.wraps(function)
    def wrapper(self, *args, **kwargs):
        try:
            return {"ok": True, "data": plain(function(self, *args, **kwargs))}
        except (SyncError, OSError, ValueError, KeyError) as exc:
            return {"ok": False, "error": str(exc) or type(exc).__name__}
        except Exception as exc:  # unexpected: still surface it in the window
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return wrapper


def exclusive(function):
    """One migration operation at a time, like every other interface."""
    @functools.wraps(function)
    def wrapper(self, *args, **kwargs):
        if not self._busy.acquire(blocking=False):
            raise SyncError("Wait for the current operation to finish.")
        try:
            return function(self, *args, **kwargs)
        finally:
            self._busy.release()
    return wrapper


class Api:
    """Exposed to JavaScript as window.pywebview.api.<method>.

    Names starting with an underscore stay private to Python. pywebview runs
    every call on its own thread, so a long export/import never freezes the window.
    """

    def __init__(self, settings_path=None, service=None):
        self._svc = service or ChatSyncService(settings_path)
        self._busy = threading.Lock()
        self._window = None

    # ---- private helpers ---------------------------------------------------
    def _progress(self, message):
        window = self._window
        if window is None:
            return
        try:
            window.evaluate_js("window.__chatsyncProgress && window.__chatsyncProgress(%s)" % json.dumps(message))
        except Exception:
            pass  # a display failure must never abort a migration

    def _on_closing(self):
        """Return False to cancel closing while a transaction is running."""
        if self._busy.locked():
            self._progress("An operation is running. Wait for it to finish before closing.")
            return False
        return True

    def _dialog(self, kind):
        import webview
        if self._window is None:
            return None
        dialog = getattr(webview, "FileDialog", None)
        mode = (dialog.FOLDER if kind == "folder" else dialog.OPEN) if dialog else (
            webview.FOLDER_DIALOG if kind == "folder" else webview.OPEN_DIALOG)
        types = ("Chat bundles (*.zip)",) if kind == "bundle" else ()
        chosen = self._window.create_file_dialog(mode, allow_multiple=False, file_types=types)
        return str(chosen[0]) if chosen else None

    # ---- settings ----------------------------------------------------------
    @reply
    def get_settings(self):
        svc = self._svc
        return {"configured": bool(svc.config), "settings_path": svc.settings_path,
                "values": svc.defaults(), "mappings": (svc.config or {}).get("mappings", {})}

    @reply
    @exclusive
    def save_settings(self, values):
        self._progress("Checking paths and Codex connection…")
        self._svc.save_settings(values)
        svc = self._svc
        return {"configured": True, "settings_path": svc.settings_path,
                "values": svc.defaults(), "mappings": (svc.config or {}).get("mappings", {})}

    # ---- chats -------------------------------------------------------------
    @reply
    @exclusive
    def load_snapshot(self, archived=False):
        self._progress("Loading local chats and projects…")
        threads, projects, bundles, history = self._svc.snapshot(bool(archived))
        return {"threads": threads, "projects": projects,
                "bundles": [{"path": p, "name": Path(p).name} for p in bundles],
                "history": history}

    @reply
    def preview(self, thread_id):
        return self._svc.preview(thread_id)

    @reply
    @exclusive
    def export_chats(self, thread_ids):
        return {"path": self._svc.export(list(thread_ids), self._progress)}

    # ---- import ------------------------------------------------------------
    @reply
    @exclusive
    def load_bundle(self, path):
        self._progress("Validating bundle checksums and dependencies…")
        resolved, manifest, fingerprint = self._svc.inspect(path)
        return {"path": resolved, "hash": fingerprint,
                "source_device": manifest.get("source_device", ""),
                "codex_version": manifest.get("codex_version", ""),
                "created_at": manifest.get("created_at", ""),
                "chats": [{"id": c["source_thread_id"], "title": c["title"], "cwd": c["cwd"],
                           "turns": len(c["turns"]), "project": (c.get("project") or {}).get("name")}
                          for c in manifest["chats"]]}

    @reply
    @exclusive
    def review_import(self, path, ids, destinations, projects, fingerprint):
        return self._svc.analyze(path, list(ids), destinations, projects, fingerprint, self._progress)

    @reply
    @exclusive
    def run_import(self, path, ids, destinations, projects, fingerprint):
        return self._svc.perform_import(path, list(ids), destinations, projects, fingerprint, self._progress)

    # ---- history -----------------------------------------------------------
    @reply
    @exclusive
    def load_history(self):
        return self._svc.history()

    @reply
    @exclusive
    def rollback(self, operation):
        return self._svc.rollback(operation, self._progress)

    # ---- native pickers ----------------------------------------------------
    @reply
    def pick_folder(self):
        return self._dialog("folder")

    @reply
    def pick_file(self, kind="any"):
        return self._dialog(kind)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Codex Chat Sync desktop interface")
    parser.add_argument("--config", help="Device-local settings file (also CHATSYNC_CONFIG)")
    parser.add_argument("--dev", nargs="?", const="http://localhost:5173",
                        help="Load the Vite dev server instead of the built interface")
    args = parser.parse_args(argv)
    page = web_root() / "dist" / "index.html"
    if not args.dev and not page.exists():
        print("Build the interface first:  cd chatsync/interfaces/gui/web && npm install && npm run build",
              file=sys.stderr)
        return 1
    try:
        import webview
    except ModuleNotFoundError as exc:
        print(f"Cannot import the GUI dependency (missing module: {exc.name}).\n"
              f"Python in use: {sys.executable}\n"
              "Install with:  python -m pip install -r requirements-gui.txt  (in the Python shown above)",
              file=sys.stderr)
        return 1
    try:
        api = Api(args.config)
    except (SyncError, OSError) as exc:
        print("Error:", exc, file=sys.stderr)
        return 1
    window = webview.create_window(
        "Codex Chat Sync", args.dev or str(page), js_api=api, width=1240, height=800,
        min_size=(960, 620), background_color="#0b1220")
    api._window = window
    window.events.closing += api._on_closing
    webview.start(debug=bool(args.dev))
    return 0