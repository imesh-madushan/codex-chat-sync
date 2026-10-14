"""Dispatch optional terminal UI commands while retaining the shared CLI."""
import argparse
import sys
from ..cli.app import main as cli_main
from ...core.config import SyncError


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print("Optional terminal interface: tui (or no command); plain CLI menu: menu\n")
        return cli_main(argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config")
    options, remaining = parser.parse_known_args(argv)
    command = remaining[0] if remaining else None
    if command == "menu":
        return cli_main((["--config", options.config] if options.config else []) + remaining[1:])
    if command not in (None, "tui"):
        return cli_main(argv)
    if remaining[1:]:
        parser.error("tui does not accept additional arguments")
    try:
        from .app import run_tui
    except ModuleNotFoundError as exc:
        if exc.name not in ("textual", "rich") and not str(exc.name).startswith(("textual.", "rich.")):
            raise
        guidance = "Install the interface dependency: python -m pip install -r requirements-tui.txt"
        if command == "tui":
            print("Error:", guidance, file=sys.stderr)
            return 1
        print("Optional interface not installed; using the text menu. " + guidance)
        return cli_main(argv)
    try:
        return run_tui(options.config)
    except (SyncError, OSError) as exc:
        print("Error:", exc, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 130
