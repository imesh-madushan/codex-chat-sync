"""Locate installed executables without importing an interface."""
from pathlib import Path
import shutil


def suggest_executable():
    executable = shutil.which("codex")
    if executable and Path(executable).suffix.lower() not in (".ps1", ".cmd", ".bat"):
        return executable
    if executable:
        base = Path(executable).parent / "node_modules" / "@openai" / "codex" / "node_modules"
        matches = list(base.glob("@openai/codex-*/vendor/*/bin/codex.exe"))
        if matches:
            return str(matches[0])
    return ""
