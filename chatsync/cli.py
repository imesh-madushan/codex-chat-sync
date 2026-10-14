import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .bundle import normalized_path, read_bundle
from .config import SyncError, atomic_json, config_path, load_config, make_config, relocate_state
from .engine import export_chats, import_bundle, inventory, load_ledger, rollback
from .rpc import Codex, executable_version


def choose(rows, label):
    if not rows:
        raise SyncError("No " + label + " available.")
    for index, row in enumerate(rows, 1):
        print(f"{index:4}. {row}")
    while True:
        answer = input(f"Select {label}: numbers/ranges (1,3-5), all, or cancel: ").strip().lower()
        if answer == "cancel":
            return []
        if answer == "all":
            return list(range(len(rows)))
        try:
            indices = set()
            for part in answer.split(","):
                bounds = [int(x.strip()) for x in part.split("-")]
                if len(bounds) == 1:
                    indices.add(bounds[0] - 1)
                elif len(bounds) == 2 and bounds[0] <= bounds[1]:
                    if bounds[1] - bounds[0] > len(rows):
                        raise ValueError()
                    indices.update(range(bounds[0] - 1, bounds[1]))
                else:
                    raise ValueError()
            if indices and min(indices) >= 0 and max(indices) < len(rows):
                return sorted(indices)
        except ValueError:
            pass
        print("Enter valid selection numbers, ranges, all, or cancel.")


def ask_path(label, previous=""):
    prompt = f"{label}" + (f" [{previous}]" if previous else "") + ": "
    value = input(prompt).strip().strip('"') or previous
    if not value:
        raise SyncError(label + " is required.")
    return value


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


def setup(args):
    target = Path(args.config or config_path())
    previous = load_config(target) if target.exists() else {}
    home = args.codex_home or ask_path("Codex data folder", previous.get("codex_home", str(Path.home() / ".codex")))
    exe = args.codex_executable or ask_path("Codex executable", previous.get("codex_executable", suggest_executable()))
    exchange = args.exchange_dir or ask_path("Bundle exchange folder (your synced folder)", previous.get("exchange_dir", ""))
    state = args.state_dir or ask_path("Local state folder (outside synced folders)", previous.get("state_dir", str(target.parent / "state")))
    config = make_config(home, exe, exchange, state, previous)
    if args.device_name:
        config["device_name"] = args.device_name
    print("Checking", executable_version(config["codex_executable"]))
    with Codex(config["codex_executable"], config["codex_home"]) as rpc:
        rpc.pages("project/list")
        rpc.pages("thread/list", {"useStateDbOnly": True})
    relocate_state(previous, config)
    atomic_json(target, config)
    print("Saved device settings:", target)


def select_export(config, args):
    threads, projects = inventory(config, args.archived)
    chosen = set(args.thread or [])
    projects_by_id = {p["id"]: p for p in projects}
    scope = set(args.project or [])
    roots = {normalized_path(p) for p in args.cwd or []}
    if scope - projects_by_id.keys():
        raise SyncError("Unknown project ID. Use list to inspect local projects.")
    if scope or roots:
        chosen.update(t["id"] for t in threads if t.get("projectId") in scope or normalized_path(t["cwd"]) in roots)
        if not chosen:
            raise SyncError("No chats matched the selected projects/folders.")
    if chosen:
        return sorted(chosen)
    mode = input("Export: [1] select chats across projects [2] select whole projects [3] select folders [cancel]: ").strip()
    if mode == "cancel":
        return []
    if mode == "2":
        picks = choose([p.get("name", p["id"]) + " | " + ", ".join(r["path"] for r in p.get("roots", [])) for p in projects], "projects")
        scope = {projects[i]["id"] for i in picks}
        return [t["id"] for t in threads if t.get("projectId") in scope]
    if mode == "3":
        folders = sorted({t["cwd"] for t in threads})
        picks = choose(folders, "folders")
        roots = {normalized_path(folders[i]) for i in picks}
        threads = [t for t in threads if normalized_path(t["cwd"]) in roots]
        if not picks:
            return []
    elif mode != "1":
        raise SyncError("Choose 1, 2, 3, or cancel.")
    query = input("Optional title filter (Enter for all): ").strip().casefold()
    if query:
        threads = [t for t in threads if query in (t.get("name") or t.get("preview", "")).casefold()]
    labels = []
    for t in threads:
        project = projects_by_id.get(t.get("projectId"), {}).get("name", "unassigned")
        labels.append(f"{t.get('name') or t.get('preview', '')[:90] or t['id']} | {project} | {t['cwd']}")
    return [threads[i]["id"] for i in choose(labels, "chats")]


def parse_pairs(values):
    result = {}
    for value in values or []:
        if "=" not in value:
            raise SyncError("Mapping must be SOURCE=DESTINATION.")
        source, target = value.split("=", 1)
        if not source or not target:
            raise SyncError("Mapping needs both a source and destination.")
        result[source] = target
    return result


def do_import(config, args):
    manifest, _ = read_bundle(args.bundle)
    chats = manifest["chats"]
    if args.chat:
        selected = args.chat
        if set(selected) - {c["logical_id"] for c in chats}:
            raise SyncError("Selected logical chat ID is not in this bundle.")
        chats = [c for c in chats if c["logical_id"] in selected]
    elif not args.yes:
        picks = choose([c["title"] + " | " + c["cwd"] for c in chats], "bundled chats")
        chats = [chats[i] for i in picks]
        selected = [c["logical_id"] for c in chats]
        if not selected:
            return
    else:
        selected = [c["logical_id"] for c in chats]
    supplied = parse_pairs(args.map)
    project_ids = parse_pairs(args.project_map)
    destinations = {}
    _, projects = inventory(config)
    valid_projects = {p["id"] for p in projects}
    for source in dict.fromkeys(c["cwd"] for c in chats):
        saved = config["mappings"].get(source, {})
        destination = supplied.get(source) or saved.get("destination")
        if not destination:
            if args.yes:
                raise SyncError("No saved mapping for " + source + "; supply --map SOURCE=DESTINATION.")
            print("Source folder:", source)
            destination = ask_path("Destination folder")
        destination = str(Path(destination).expanduser().resolve())
        if not Path(destination).is_dir():
            raise SyncError("Destination folder does not exist: " + destination)
        destinations[source] = destination
        if source not in project_ids:
            project_ids[source] = saved.get("project_id")
            if not args.yes:
                print("Assign chats to an existing Codex project, or Enter to use bundle project / leave ordinary chats unassigned.")
                for i, project in enumerate(projects, 1):
                    print(f"{i}. {project.get('name', project['id'])}")
                choice = input("Project number (Enter for saved/default): ").strip()
                if choice:
                    try:
                        project_ids[source] = projects[int(choice) - 1]["id"] if 1 <= int(choice) <= len(projects) else "invalid"
                    except ValueError as exc:
                        raise SyncError("Invalid project number.") from exc
        if project_ids.get(source) and project_ids[source] not in valid_projects:
            raise SyncError("Saved/entered project is unavailable. Edit the mapping in Settings.")
    plans = import_bundle(config, args.bundle, destinations, project_ids, selected, dry_run=True)
    for plan in plans:
        print(f"{plan['action']:8} {plan['title']} -> {plan['destination']}")
    if args.dry_run:
        return
    if not args.yes and input("Import these chats? [y/N]: ").strip().lower() != "y":
        return
    results = import_bundle(config, args.bundle, destinations, project_ids, selected)
    for source, destination in destinations.items():
        config["mappings"][source] = {"destination": destination, "project_id": project_ids.get(source)}
    atomic_json(args.config or config_path(), config)
    for result in results:
        if result.get("thread_id"):
            print(result["action"], result["title"], "\n  Resume ID:", result["thread_id"])
            print("  Codex CLI: codex resume", result["thread_id"])
    print("Done. Existing conversations were retained. If desktop visibility is delayed, reopen Codex and open the imported chat.")


def menu(config, args):
    while True:
        print("\nCodex Chat Sync —", config["device_name"])
        print("1 Export chats/projects\n2 Import bundle\n3 List chats/projects\n4 Settings\n5 Import history / rollback\n0 Exit")
        choice = input("> ").strip()
        try:
            if choice == "0":
                return
            if choice == "1":
                options = argparse.Namespace(thread=[], project=[], cwd=[], archived=False)
                selected = select_export(config, options)
                if selected:
                    print("Exported:", export_chats(config, selected))
            elif choice == "2":
                files = sorted(Path(config["exchange_dir"]).glob("*.chatbundle.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
                print("Choose a bundle, or cancel and enter its path with the import command.")
                selected = choose([p.name for p in files], "one bundle")
                if len(selected) > 1:
                    raise SyncError("Choose one bundle; each bundle can contain many chats.")
                if selected:
                    do_import(config, argparse.Namespace(bundle=str(files[selected[0]]), chat=[], map=[], project_map=[],
                                                         yes=False, dry_run=False, config=args.config))
            elif choice == "3":
                print_inventory(config)
            elif choice == "4":
                print(json.dumps(config, indent=2))
                action = input("[1] Edit device paths [2] Edit folder mapping [Enter] Back: ").strip()
                if action == "1":
                    setup(argparse.Namespace(config=args.config, codex_home=None, codex_executable=None,
                                             exchange_dir=None, state_dir=None, device_name=None))
                    config = load_config(args.config)
                elif action == "2":
                    sources = list(config["mappings"])
                    picks = choose([s + " -> " + config["mappings"][s]["destination"] for s in sources], "mappings")
                    for i in picks:
                        source = sources[i]
                        entry = config["mappings"][source]
                        entry["destination"] = ask_path("New destination", entry["destination"])
                        entry["project_id"] = input("Project ID (Enter clears assignment): ").strip() or None
                    atomic_json(args.config or config_path(), config)
            elif choice == "5":
                entries = load_ledger(config)["imports"]
                for entry in entries:
                    print(entry["operation"], ", ".join(p["title"] for p in entry["plans"]))
                operation = input("Operation ID to roll back (Enter returns): ").strip()
                if operation and input("Archive imported copies? Original chats remain available. [y/N]: ").lower() == "y":
                    rollback(config, operation)
                    print("Imported copies archived; they can be restored in Codex.")
        except SyncError as exc:
            print("Error:", exc)


def print_inventory(config, archived=False):
    threads, projects = inventory(config, archived)
    print("Projects:")
    for p in projects:
        print(p["id"], p.get("name", ""), ", ".join(r["path"] for r in p.get("roots", [])))
    print("Chats:")
    for t in threads:
        print(t["id"], t.get("name") or t.get("preview", "")[:90], "|", t.get("projectId") or "unassigned", "|", t["cwd"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Portable Codex chat export/import. Python 3.11+; no third-party packages.")
    parser.add_argument("--config", help="Device-local settings file (also CHATSYNC_CONFIG)")
    sub = parser.add_subparsers(dest="command")
    settings = sub.add_parser("setup", help="Enter or edit saved device paths")
    for name in ("codex-home", "codex-executable", "exchange-dir", "state-dir", "device-name"):
        settings.add_argument("--" + name)
    listing = sub.add_parser("list", help="Show local chats and projects")
    listing.add_argument("--archived", action="store_true")
    export = sub.add_parser("export", help="Select many chats, projects or folders into one file")
    for name in ("thread", "project", "cwd", "asset"):
        export.add_argument("--" + name, action="append", help="Repeat for multiple selections")
    export.add_argument("--output")
    export.add_argument("--archived", action="store_true")
    importing = sub.add_parser("import", help="Validate and import selected bundled chats")
    importing.add_argument("bundle")
    importing.add_argument("--chat", action="append", help="Logical chat ID; repeat to select multiple")
    importing.add_argument("--map", action="append", help="SOURCE=DESTINATION folder; repeat")
    importing.add_argument("--project-map", action="append", help="SOURCE=LOCAL_PROJECT_ID; repeat")
    importing.add_argument("--dry-run", action="store_true")
    importing.add_argument("--yes", action="store_true", help="Import without terminal prompts; requires saved/explicit mappings")
    inspection = sub.add_parser("inspect", help="Validate bundle and show its inventory")
    inspection.add_argument("bundle")
    reverting = sub.add_parser("rollback", help="Archive an operation's imported copies")
    reverting.add_argument("operation")
    sub.add_parser("doctor", help="Check executable/protocol and local paths")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            setup(args)
            return 0
        if args.command == "inspect":
            manifest, _ = read_bundle(args.bundle)
            print("Verified bundle from", manifest["source_device"], manifest["codex_version"])
            for chat in manifest["chats"]:
                print(chat["logical_id"], chat["title"], len(chat["turns"]), "completed turns |", chat["cwd"])
            return 0
        config = load_config(args.config)
        if args.command == "list":
            print_inventory(config, args.archived)
        elif args.command == "export":
            selected = select_export(config, args)
            if selected:
                print("Exported:", export_chats(config, selected, args.output, args.asset or []))
        elif args.command == "import":
            do_import(config, args)
        elif args.command == "rollback":
            rollback(config, args.operation)
            print("Imported copies archived. Original histories retained.")
        elif args.command == "doctor":
            print(executable_version(config["codex_executable"]))
            threads, projects = inventory(config)
            print(f"Protocol OK: {len(threads)} chats, {len(projects)} projects")
            print("Settings:", args.config or config_path())
            print("Exchange:", config["exchange_dir"])
            print("Local state:", config["state_dir"])
        else:
            menu(config, args)
        return 0
    except (SyncError, OSError) as exc:
        print("Error:", exc, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 130
