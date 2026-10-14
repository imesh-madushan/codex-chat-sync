"""Launch a prepared interface using the project-local Python environment."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from setup import interfaces, local_path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Launch Codex Chat Sync", add_help=False)
    parser.add_argument("--interface", help="Interface name; defaults to GUI when available, otherwise CLI")
    if ("--help" in argv or "-h" in argv) and "--interface" not in argv:
        parser.print_help()
        return 0
    args, forwarded = parser.parse_known_args(argv)
    try:
        available = interfaces()
        chosen = args.interface or ("gui" if "gui" in available else "cli")
        if chosen not in available:
            raise ValueError("Available interfaces: " + ", ".join(available))
        spec = available[chosen]
        directory = Path(__file__).resolve().parent / ".venv"
        windowed = os.name == "nt" and spec.get("windowed", False)
        python = directory / ("Scripts/pythonw.exe" if windowed else
                              "Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            raise ValueError("Run python setup.py first to prepare the application.")
        command = [str(python), "-X", "utf8", str(local_path(spec["entry"])), *forwarded]
        if windowed:
            subprocess.Popen(command, cwd=directory.parent, creationflags=subprocess.CREATE_NO_WINDOW,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        return subprocess.call(command, cwd=directory.parent)
    except (OSError, ValueError) as exc:
        print("Cannot launch: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
