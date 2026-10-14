"""Prepare a local Python environment and available interfaces; not setuptools."""
import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def local_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Interface paths must stay inside this project.")
    return path


def interfaces():
    result = {}
    for path in sorted((ROOT / "chatsync" / "interfaces").glob("*/setup.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        if not spec.get("id") or spec["id"] in result:
            raise ValueError("Interface identifiers must be present and unique.")
        local_path(spec["entry"])
        result[spec["id"]] = spec
    return result


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.paths.append(values["src"])
        if tag == "link" and values.get("rel") in ("stylesheet", "modulepreload"):
            self.paths.append(values.get("href", ""))


def resources_ready(directory):
    directory = Path(directory).resolve()
    index = directory / "index.html"
    if not index.is_file():
        return False
    parser = AssetLinks()
    parser.feed(index.read_text(encoding="utf-8"))
    if not parser.paths:
        return False
    for value in parser.paths:
        if not value or ":" in value or value.startswith("/"):
            return False
        path = (directory / value.split("?", 1)[0]).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            return False
    return True


def prepare_resources(spec, rebuild=False, npm=None):
    web = spec.get("web")
    if not web:
        return
    directory = local_path(web["directory"])
    output = local_path(web["output"])
    npm = npm or shutil.which("npm")
    if not rebuild and resources_ready(output):
        print("Using the included interface files; no frontend build is needed.")
        if not npm:
            print("Node.js/npm isn't installed. That's OK; the included interface is ready.")
        return
    if not npm:
        raise ValueError("The interface files are missing or incomplete. Download a complete copy "
                         "of this project, or install Node.js/npm to rebuild them.")
    print("Building interface files with Node.js/npm...")
    subprocess.run([npm, "ci"], cwd=directory, check=True)
    subprocess.run([npm, "run", "build"], cwd=directory, check=True)
    if not resources_ready(output):
        raise ValueError("The frontend build did not produce a complete interface.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set up Codex Chat Sync in a local Python environment")
    parser.add_argument("--interface", action="append", help="Prepare a specific interface; repeat for several. Default: all available")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild frontend resources; requires Node.js/npm")
    parser.add_argument("--skip-install", action="store_true", help="Developer option: retain already installed Python dependencies")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        print("Python 3.11 or newer is required.", file=sys.stderr)
        return 1
    try:
        available = interfaces()
        selected = args.interface or list(available)
        if not selected or set(selected) - available.keys():
            raise ValueError("Choose an available interface: " + ", ".join(available))
        specs = [available[key] for key in dict.fromkeys(selected)]
        for spec in specs:
            if not local_path(spec["entry"]).is_file():
                raise ValueError("Missing application entry point: " + spec["entry"])
            prepare_resources(spec, args.rebuild)
        environment = ROOT / ".venv"
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            print("Creating the project's Python environment...")
            venv.EnvBuilder(with_pip=True).create(environment)
        if not args.skip_install:
            requirements = sorted({spec["requirements"] for spec in specs if spec.get("requirements")})
            for requirement in requirements:
                print("Installing Python dependencies for " + requirement + "...")
                subprocess.run([str(python), "-m", "pip", "install", "-r", str(local_path(requirement))], check=True)
        from chatsync.core.discovery import suggest_executable
        executable = suggest_executable()
        print("Codex executable found; confirm its path in Settings." if executable else
              "Choose your installed Codex executable in Settings. If needed, install Codex before importing or exporting.")
        if os.name == "nt" and "gui" in selected:
            pythonw = python.with_name("pythonw.exe")
            if not pythonw.is_file():
                raise ValueError("This Python installation is missing pythonw.exe; use a complete Python installation.")
            shortcut = ROOT / "Codex Chat Sync.lnk"
            # Pass filesystem values via environment variables, never shell interpolation.
            environment_vars = dict(os.environ, CHATSYNC_SHORTCUT=str(shortcut),
                                    CHATSYNC_GUI_PYTHON=str(pythonw), CHATSYNC_ROOT=str(ROOT),
                                    CHATSYNC_GUI_ARGS=subprocess.list2cmdline(["-X", "utf8", str(local_path(available["gui"]["entry"]))]))
            script = ('$shell = New-Object -ComObject WScript.Shell; '
                      '$link = $shell.CreateShortcut($env:CHATSYNC_SHORTCUT); '
                      '$link.TargetPath = $env:CHATSYNC_GUI_PYTHON; '
                      '$link.Arguments = $env:CHATSYNC_GUI_ARGS; '
                      '$link.WorkingDirectory = $env:CHATSYNC_ROOT; $link.Save()')
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           env=environment_vars, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            print("Open Codex Chat Sync.lnk in this folder to launch the application.")
        print("Setup complete. Run: python launch.py")
        print("For the command-line interface: python launch.py --interface cli")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print("Setup could not finish: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
