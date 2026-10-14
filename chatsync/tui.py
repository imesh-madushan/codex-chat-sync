"""Optional Textual interface; migration operations stay in the shared engine."""
import asyncio
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input,
                             Label, LoadingIndicator, RichLog, Select, SelectionList,
                             Static, TabbedContent, TabPane)

from .bundle import normalized_path
from .config import SyncError
from .ui_service import UIService

ACTION_LABELS = {"same": "DUPLICATE", "stale": "OLDER"}

COLORS = {"new": "cyan", "update": "green", "branch": "yellow", "same": "dim",
          "stale": "dim", "relocate": "blue"}


def title(thread):
    return thread.get("name") or thread.get("preview", "")[:100] or thread["id"]


def updated_label(value):
    try:
        date = datetime.fromtimestamp(value)
        return date.strftime("Today %H:%M") if date.date() == datetime.now().date() else date.strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError, OverflowError):
        return "Date unavailable"


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Back")]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; background: $background 70%; }
    #confirm-box { width: 76; max-width: 94%; height: 75%; min-height: 12; max-height: 90%;
        background: $surface; border: round $accent; padding: 1 2; }
    #confirm-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #confirm-summary { height: 1fr; }
    #confirm-buttons { height: 3; margin-top: 1; align-horizontal: right; }
    #confirm-buttons Button { margin-left: 1; }
    """

    def __init__(self, heading, summary, accept="Confirm"):
        super().__init__()
        self.heading, self.summary, self.accept = heading, summary, accept

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(Text(self.heading), id="confirm-title")
            with VerticalScroll(id="confirm-summary"):
                yield Static(self.summary, markup=False)
            with Horizontal(id="confirm-buttons"):
                yield Button("Back", id="confirm-no")
                yield Button(self.accept, variant="primary", id="confirm-yes")

    def on_mount(self):
        self.query_one("#confirm-no", Button).focus()

    @on(Button.Pressed, "#confirm-yes")
    def accept_pressed(self):
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-no")
    def action_cancel(self):
        self.dismiss(False)


class ChatSyncApp(App):
    TITLE = "Codex Chat Sync"
    SUB_TITLE = "Portable conversations"
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+r", "refresh", "Refresh"),
                ("ctrl+e", "export_selected", "Export"), ("f3", "show_preview", "Preview"), ("f4", "toggle_archived", "Archives"), ("/", "search", "Search")]
    CSS = """
    Screen { background: $background; }
    Header { background: $surface; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; height: 1fr; }
    .toolbar { height: 3; margin-bottom: 1; }
    .toolbar Input { width: 1fr; }
    #chat-filter { width: 36; margin-left: 1; }
    #include-archived { height: 3; width: 34; }
    .split { height: 1fr; }
    .list-box { width: 60%; height: 1fr; margin-right: 1; }
    .preview-box { width: 1fr; height: 1fr; border: round $accent;
        padding: 1 2; background: $surface; }
    .section-title { text-style: bold; color: $accent; height: 1; margin-bottom: 1; }
    SelectionList { height: 1fr; border: round $primary; }
    #chat-preview { height: auto; }
    .actions { height: 3; margin-top: 1; }
    .actions Button { margin-right: 1; }
    .counter { width: 1fr; height: 3; content-align: right middle; color: $text-muted; }
    .compact .split { layout: vertical; }
    .compact .list-box { width: 1fr; margin-right: 0; }
    .compact .preview-box { width: 1fr; height: 9; margin-top: 1; }
    #import-path { width: 1fr; }
    #bundle-select { width: 1fr; margin-right: 1; }
    #import-path-row { margin-bottom: 1; }
    #mapping-scroll { height: 1fr; }
    .mapping-row { height: auto; margin-bottom: 1; }
    .mapping-row Label { height: auto; color: $text-muted; }
    .mapping-row Input, .mapping-row Select { width: 1fr; margin-top: 1; }
    #import-analysis { height: auto; margin-top: 1; }
    #settings-scroll { height: 1fr; }
    #settings-scroll Label { margin-top: 1; }
    #settings-scroll Input, #settings-scroll Select { margin-top: 1; }
    #settings-heading { color: $accent; }
    #settings-path { color: $text-muted; height: auto; }
    #history-table { height: 1fr; }
    #history-note { color: $text-muted; height: auto; margin-bottom: 1; }
    #activity { height: 6; border-top: solid $primary; background: $surface; }
    #status-row { height: 1; }
    #activity-spinner { width: 4; height: 1; display: none; }
    #status { height: 1; width: 1fr; color: $accent; }
    #activity-log { height: 1fr; border: none; padding: 0 2; }
    .short #activity { height: 2; }
    .short .toolbar { margin-bottom: 0; }
    .short .actions { margin-top: 0; }
    .short .section-title { margin-bottom: 0; }
    .short #include-archived { display: none; }
    .short #activity-log { display: none; }
    .compact.short #chats .preview-box { display: none; }
    """

    def __init__(self, settings_path=None, backend=None):
        super().__init__()
        self.backend = backend or UIService(settings_path)
        self.register_theme(Theme(name="chat-sync", primary="#14b8a6", secondary="#334155",
                                  accent="#2dd4bf", foreground="#e2e8f0", background="#0b1220",
                                  surface="#101c2f", panel="#17263b", dark=True))
        self.theme = "chat-sync"
        self.threads, self.projects, self.bundles = [], [], []
        self.selected_chats = set()
        self.visible_chats = set()
        self.busy = False
        self.preview_serial = 0
        self.bundle_path = None
        self.bundle_hash = None
        self.manifest = None
        self.sources = []
        self.import_plans = None
        self.mapping_forms_ready = False
        self.selected_operation = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="chats", id="tabs"):
            with TabPane("Chats", id="chats"):
                with Horizontal(classes="toolbar"):
                    yield Input(placeholder="Search titles or folders…", id="chat-search")
                    yield Select([("All chats", "all"), ("Unassigned chats", "unassigned")],
                                 value="all", allow_blank=False, id="chat-filter")
                yield Checkbox("Include archived chats", id="include-archived")
                with Horizontal(classes="split"):
                    with Vertical(classes="list-box"):
                        yield Label("SELECT CHATS", classes="section-title")
                        yield SelectionList(id="chat-list")
                    with VerticalScroll(classes="preview-box"):
                        yield Label("CONVERSATION PREVIEW", classes="section-title")
                        yield Static("Highlight a chat to see its details.", id="chat-preview", markup=False)
                with Horizontal(classes="actions"):
                    yield Button("Select visible", id="select-visible")
                    yield Button("Clear", id="clear-chats")
                    yield Button("Export selected", variant="primary", id="export-chats", classes="operation")
                    yield Static("0 selected", id="chat-count", classes="counter")
            with TabPane("Import", id="imports"):
                with Horizontal(classes="toolbar"):
                    yield Select([], prompt="Bundle in exchange folder", id="bundle-select")
                    yield Button("Load bundle", id="load-bundle", classes="operation")
                with Horizontal(classes="toolbar", id="import-path-row"):
                    yield Input(placeholder="Or enter an absolute bundle path", id="import-path")
                with Horizontal(classes="split"):
                    with Vertical(classes="list-box"):
                        yield Label("CHATS IN BUNDLE", classes="section-title")
                        yield SelectionList(id="import-list")
                        with Horizontal(classes="actions"):
                            yield Button("Select all", id="select-imports")
                            yield Button("Clear", id="clear-imports")
                    with Vertical(classes="preview-box"):
                        yield Label("DESTINATION FOLDERS", classes="section-title")
                        with VerticalScroll(id="mapping-scroll"):
                            yield Static("Load a bundle to configure folder mappings.", markup=False)
                        yield Static("Review mappings before importing.", id="import-analysis", markup=False)
                with Horizontal(classes="actions"):
                    yield Button("Review import", id="review-import", classes="operation")
                    yield Button("Import selected", variant="primary", id="import-chats", classes="operation")
                    yield Static("0 selected", id="import-count", classes="counter")
            with TabPane("History", id="history"):
                yield Static("Rollback archives imported copies and keeps their messages recoverable. Original chats remain available.",
                             id="history-note", markup=False)
                yield DataTable(id="history-table", cursor_type="row")
                with Horizontal(classes="actions"):
                    yield Button("Refresh", id="refresh-history", classes="operation")
                    yield Button("Roll back selected", id="rollback-operation", classes="operation")
            with TabPane("Settings", id="settings"):
                yield Static(Text("Device-local paths and saved folder mappings"), id="settings-heading")
                yield Static(Text(str(self.backend.settings_path)), id="settings-path")
                with VerticalScroll(id="settings-scroll"):
                    defaults = self.backend.defaults()
                    for key, label in (("device_name", "Device label"), ("codex_home", "Codex data folder"),
                                       ("codex_executable", "Codex executable"), ("exchange_dir", "Bundle exchange folder"),
                                       ("state_dir", "Local state folder — outside synced folders")):
                        yield Label(label)
                        yield Input(value=str(defaults.get(key, "")), id="setting-" + key.replace("_", "-"))
                    yield Label("Saved folder mappings")
                    yield Select([], prompt="Choose a saved source folder", id="saved-mapping")
                    yield Input(placeholder="Destination folder", id="saved-destination")
                    yield Select([("Bundle project / unassigned", "auto")], value="auto", allow_blank=False,
                                 id="saved-project")
                    yield Button("Save mapping", id="save-mapping", classes="operation")
                with Horizontal(classes="actions"):
                    yield Button("Save device settings", variant="primary", id="save-settings", classes="operation")
        with Vertical(id="activity"):
            with Horizontal(id="status-row"):
                yield LoadingIndicator(id="activity-spinner")
                yield Static("Ready", id="status", markup=False)
            yield RichLog(id="activity-log", wrap=True, markup=False)
        yield Footer()

    def on_mount(self):
        self.screen_stack[0].query_one("#history-table", DataTable).add_columns("Created", "Status", "Conversations", "Operation")
        self._buttons()
        self._saved_mappings()
        if self.backend.config:
            self.action_refresh()
        else:
            self.screen_stack[0].query_one("#tabs", TabbedContent).active = "settings"
            self._log("Enter device paths and save settings to get started.")

    def on_resize(self, event):
        self.screen_stack[0].set_class(event.size.width < 100, "compact")
        self.screen_stack[0].set_class(event.size.height < 38, "short")

    def _log(self, message, style=None):
        self.screen_stack[0].query_one("#activity-log", RichLog).write(Text(str(message), style=style or ""))

    def _progress(self, message):
        self.screen_stack[0].query_one("#status", Static).update(Text(message))
        self._log(message)

    def _buttons(self):
        for kind in (Input, Select, Checkbox, SelectionList):
            for widget in self.screen_stack[0].query(kind):
                widget.disabled = self.busy
        for button in self.screen_stack[0].query(".operation"):
            button.disabled = self.busy
        self.screen_stack[0].query_one("#export-chats", Button).disabled = self.busy or not self.selected_chats
        self.screen_stack[0].query_one("#review-import", Button).disabled = self.busy or not self.mapping_forms_ready or not self.screen_stack[0].query_one("#import-list", SelectionList).selected
        self.screen_stack[0].query_one("#import-chats", Button).disabled = self.busy or self.import_plans is None
        self.screen_stack[0].query_one("#rollback-operation", Button).disabled = self.busy or not self.selected_operation

    def _operate(self, heading, function, finished):
        if self.busy:
            self.notify("Wait for the current operation to finish.", severity="warning")
            return
        self.busy = True
        self.screen_stack[0].query_one("#activity-spinner", LoadingIndicator).display = True
        self._buttons()
        self._progress(heading)

        def progress(message):
            self.call_from_thread(self._progress, message)

        async def worker():
            try:
                result = await asyncio.to_thread(function, progress)
                finished(result)
                self.screen_stack[0].query_one("#status", Static).update("Ready")
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                self.screen_stack[0].query_one("#status", Static).update(Text("Operation stopped: " + message))
                self._log(message, "red")
                self.notify(message, title="Operation stopped", severity="error", timeout=10)
            finally:
                self.busy = False
                self.screen_stack[0].query_one("#activity-spinner", LoadingIndicator).display = False
                self._buttons()

        self.run_worker(worker(), name=heading, group="operations", exit_on_error=False)

    def action_quit(self):
        if self.busy:
            self.notify("An operation is running. Wait for it to finish before closing.", severity="warning")
        else:
            self.exit()

    def action_show_preview(self):
        if self.screen_stack[0].query_one("#tabs", TabbedContent).active == "chats":
            content = self.screen_stack[0].query_one("#chat-preview", Static).render()
            self.push_screen(ConfirmScreen("Conversation preview", content, "Close"))

    def action_toggle_archived(self):
        if not self.busy:
            checkbox = self.screen_stack[0].query_one("#include-archived", Checkbox)
            checkbox.value = not checkbox.value

    def action_search(self):
        self.screen_stack[0].query_one("#tabs", TabbedContent).active = "chats"
        self.screen_stack[0].query_one("#chat-search", Input).focus()

    def action_refresh(self):
        if not self.backend.config:
            self.screen_stack[0].query_one("#tabs", TabbedContent).active = "settings"
            return
        archived = self.screen_stack[0].query_one("#include-archived", Checkbox).value
        self._operate("Loading local chats and projects…", lambda progress: self.backend.snapshot(archived), self._snapshot_ready)

    def _snapshot_ready(self, snapshot):
        self.threads, self.projects, self.bundles, history = snapshot
        self.selected_chats.intersection_update(t["id"] for t in self.threads)
        options = [("All chats", "all"), ("Unassigned chats", "unassigned")]
        options += [(Text("Project: " + p.get("name", p["id"])), "project:" + p["id"]) for p in self.projects]
        options += [(Text("Folder: " + folder), "folder:" + folder) for folder in sorted({t["cwd"] for t in self.threads})]
        widget = self.screen_stack[0].query_one("#chat-filter", Select)
        value = widget.value
        widget.set_options(options)
        widget.value = value if value in {v for _, v in options} else "all"
        self._render_chats()
        self._bundle_options()
        self._history_rows(history)
        self._saved_mappings()
        self._log(f"Loaded {len(self.threads)} chats and {len(self.projects)} projects.")

    @on(Input.Changed, "#chat-search")
    @on(Select.Changed, "#chat-filter")
    def filter_changed(self):
        self._render_chats()

    @on(Checkbox.Changed, "#include-archived")
    def archived_changed(self):
        self.action_refresh()

    def _render_chats(self):
        query = self.screen_stack[0].query_one("#chat-search", Input).value.casefold().strip()
        scope = self.screen_stack[0].query_one("#chat-filter", Select).value
        project_names = {p["id"]: p.get("name", p["id"]) for p in self.projects}
        rows = []
        for thread in self.threads:
            if query and query not in (title(thread) + " " + thread["cwd"]).casefold():
                continue
            if scope == "unassigned" and thread.get("projectId"):
                continue
            if isinstance(scope, str) and scope.startswith("project:") and thread.get("projectId") != scope[8:]:
                continue
            if isinstance(scope, str) and scope.startswith("folder:") and normalized_path(thread["cwd"]) != normalized_path(scope[7:]):
                continue
            name = title(thread)
            label = Text(name if len(name) <= 44 else name[:43] + "…")
            label.append("  ·  " + project_names.get(thread.get("projectId"), "Unassigned")[:22], style="dim")
            rows.append((label, thread["id"], thread["id"] in self.selected_chats))
        self.visible_chats = {value for _, value, _ in rows}
        widget = self.screen_stack[0].query_one("#chat-list", SelectionList)
        with widget.prevent(SelectionList.SelectedChanged):
            widget.clear_options()
            widget.add_options(rows)
        count = f"{len(self.selected_chats)} selected · {len(rows)} visible"
        self.screen_stack[0].query_one("#chat-count", Static).update(count)
        self._buttons()

    @on(SelectionList.SelectedChanged, "#chat-list")
    def chat_selection_changed(self, event):
        self.selected_chats.difference_update(self.visible_chats)
        self.selected_chats.update(event.selection_list.selected)
        self.screen_stack[0].query_one("#chat-count", Static).update(f"{len(self.selected_chats)} selected · {len(self.visible_chats)} visible")
        self._buttons()

    @on(SelectionList.SelectionHighlighted, "#chat-list")
    def highlight_chat(self, event):
        thread_id = event.selection.value
        thread = next((t for t in self.threads if t["id"] == thread_id), None)
        if not thread:
            return
        self.preview_serial += 1
        serial = self.preview_serial
        self.screen_stack[0].query_one("#chat-preview", Static).update(Text(f"{title(thread)}\n\nFolder\n{thread['cwd']}\n\nLoading completed history…"))
        async def preview():
            await asyncio.sleep(0.15)
            try:
                details = await asyncio.to_thread(self.backend.preview, thread_id)
                if serial == self.preview_serial:
                    text = f"{title(thread)}\n\nFolder\n{thread['cwd']}\n\nTurns\n{details['completed']} completed / {details['turn_count']} total\n\nLast assistant message\n{details['last_message']}"
                    self.screen_stack[0].query_one("#chat-preview", Static).update(Text(text))
            except Exception as exc:
                if serial == self.preview_serial:
                    self.screen_stack[0].query_one("#chat-preview", Static).update(Text(f"{title(thread)}\n\n{thread['cwd']}\n\nPreview unavailable: {exc}"))
        self.run_worker(preview(), group="previews", exclusive=True, exit_on_error=False)

    @on(Button.Pressed, "#select-visible")
    def select_visible(self):
        self.screen_stack[0].query_one("#chat-list", SelectionList).select_all()

    @on(Button.Pressed, "#clear-chats")
    def clear_chats(self):
        self.selected_chats.clear()
        self._render_chats()

    @on(Button.Pressed, "#export-chats")
    def action_export_selected(self):
        if self.busy or not self.selected_chats or not self.backend.config:
            return
        selected = sorted(self.selected_chats)
        summary = Text(f"Export {len(selected)} selected conversations into one bundle.\n\nExchange folder\n{self.backend.config['exchange_dir']}")
        def confirmed(accepted):
            if accepted:
                self._operate("Exporting selected conversations…", lambda progress: self.backend.export(selected, progress), self._export_ready)
        self.push_screen(ConfirmScreen("Export conversations", summary, "Export"), confirmed)

    def _export_ready(self, path):
        self._log("Export ready: " + str(path), "green")
        self.notify("Bundle saved to the exchange folder.", title="Export complete")
        self.bundles.insert(0, Path(path))
        self._bundle_options()

    def _bundle_options(self):
        widget = self.screen_stack[0].query_one("#bundle-select", Select)
        current = widget.value
        options = [(Text(path.name), str(path)) for path in dict.fromkeys(self.bundles)]
        widget.set_options(options)
        if current in {value for _, value in options}:
            widget.value = current

    @on(Select.Changed, "#bundle-select")
    def bundle_changed(self, event):
        if event.value is not Select.BLANK:
            self.screen_stack[0].query_one("#import-path", Input).value = str(event.value)

    @on(Button.Pressed, "#load-bundle")
    def load_bundle(self):
        path = self.screen_stack[0].query_one("#import-path", Input).value.strip().strip(chr(34))
        if not path:
            self.notify("Select a bundle or enter its path.", severity="warning")
            return
        if not self.backend.config:
            self.screen_stack[0].query_one("#tabs", TabbedContent).active = "settings"
            return
        self._operate("Validating bundle checksums and dependencies…", lambda progress: self.backend.inspect(path), self._bundle_ready)

    async def _mount_mappings(self):
        panel = self.screen_stack[0].query_one("#mapping-scroll", VerticalScroll)
        await panel.remove_children()
        defaults = self.backend.config.get("mappings", {})
        options = [("Bundle project / unassigned", "auto")] + [(Text(p.get("name", p["id"])), p["id"]) for p in self.projects]
        valid = {value for _, value in options}
        for i, source in enumerate(self.sources):
            saved = defaults.get(source, {})
            row = Vertical(id=f"mapping-{i}", classes="mapping-row")
            await panel.mount(row)
            project = saved.get("project_id") or "auto"
            await row.mount(Label(Text(source)), Input(value=saved.get("destination", ""),
                            placeholder="Existing destination folder", id=f"destination-{i}"),
                            Select(options, value=project if project in valid else "auto",
                                   allow_blank=False, id=f"project-{i}"))
        self.mapping_forms_ready = True
        self._invalidate_import()

    def _bundle_ready(self, result):
        self.bundle_path, self.manifest, self.bundle_hash = result
        self.sources = list(dict.fromkeys(c["cwd"] for c in self.manifest["chats"]))
        widget = self.screen_stack[0].query_one("#import-list", SelectionList)
        with widget.prevent(SelectionList.SelectedChanged):
            widget.clear_options()
            widget.add_options([(Text(f"{c['title']}\n{len(c['turns'])} completed turns"), c["source_thread_id"]) for c in self.manifest["chats"]])
        self.mapping_forms_ready = False
        self.run_worker(self._mount_mappings(), group="mapping-forms", exclusive=True, exit_on_error=False)
        self._invalidate_import()
        self._log(f"Bundle verified: {len(self.manifest['chats'])} conversations. Select chats and map their folders.", "green")

    def _invalidate_import(self):
        self.import_plans = None
        count = len(self.screen_stack[0].query_one("#import-list", SelectionList).selected)
        self.screen_stack[0].query_one("#import-count", Static).update(f"{count} selected")
        chosen = set(self.screen_stack[0].query_one("#import-list", SelectionList).selected)
        selected_sources = {c["cwd"] for c in (self.manifest or {}).get("chats", []) if c["source_thread_id"] in chosen}
        for row in self.screen_stack[0].query(".mapping-row"):
            source = self.sources[int(row.id.split("-")[-1])]
            row.display = not chosen or source in selected_sources
        self.screen_stack[0].query_one("#import-analysis", Static).update("Review mappings and selected chats before importing.")
        self._buttons()

    @on(SelectionList.SelectedChanged, "#import-list")
    def import_selection_changed(self):
        self._invalidate_import()

    @on(Input.Changed)
    def mapping_input_changed(self, event):
        if event.input.id and event.input.id.startswith("destination-"):
            self._invalidate_import()
        if event.input.id == "import-path" and self.bundle_path and event.value != str(self.bundle_path):
            self._invalidate_import()

    @on(Select.Changed)
    def mapping_project_changed(self, event):
        if event.select.id and event.select.id.startswith("project-"):
            self._invalidate_import()

    @on(Button.Pressed, "#select-imports")
    def select_imports(self):
        self.screen_stack[0].query_one("#import-list", SelectionList).select_all()

    @on(Button.Pressed, "#clear-imports")
    def clear_imports(self):
        self.screen_stack[0].query_one("#import-list", SelectionList).deselect_all()

    def _import_arguments(self):
        if not self.manifest or not self.bundle_path:
            raise SyncError("Load a bundle first.")
        if Path(self.screen_stack[0].query_one("#import-path", Input).value.strip().strip(chr(34))).expanduser().resolve() != self.bundle_path:
            raise SyncError("Load the newly entered bundle before reviewing.")
        selected = list(self.screen_stack[0].query_one("#import-list", SelectionList).selected)
        if not selected:
            raise SyncError("Select at least one bundled conversation.")
        sources = {c["cwd"] for c in self.manifest["chats"] if c["source_thread_id"] in selected}
        destinations, projects = {}, {}
        for i, source in enumerate(self.sources):
            if source in sources:
                destinations[source] = self.screen_stack[0].query_one(f"#destination-{i}", Input).value
                project = self.screen_stack[0].query_one(f"#project-{i}", Select).value
                projects[source] = None if project == "auto" else project
        return self.bundle_path, selected, destinations, projects, self.bundle_hash

    @on(Button.Pressed, "#review-import")
    def review_import(self):
        try:
            arguments = self._import_arguments()
        except (SyncError, ValueError) as exc:
            self.notify(str(exc), severity="warning")
            return
        def reviewed(plans):
            if arguments != self._import_arguments():
                self._invalidate_import()
                self.notify("Selection or folder mappings changed. Review the import again.", severity="warning")
                return
            self._analysis_ready(plans)
        self._operate("Comparing selected chats with local histories…", lambda progress: self.backend.analyze(*arguments, progress), reviewed)

    def _analysis_ready(self, plans):
        self.import_plans = plans
        text = Text()
        for plan in plans:
            text.append(ACTION_LABELS.get(plan["action"], plan["action"].upper()).ljust(10), style=COLORS.get(plan["action"], ""))
            text.append(plan["title"] + "\n")
        self.screen_stack[0].query_one("#import-analysis", Static).update(text)
        self._log("Import preview is ready. Branches and older copies are preserved.")

    @on(Button.Pressed, "#import-chats")
    def confirm_import(self):
        if self.busy or self.import_plans is None:
            return
        try:
            arguments = self._import_arguments()
        except (SyncError, ValueError) as exc:
            self.notify(str(exc), severity="warning")
            return
        summary = Text()
        for plan in self.import_plans:
            summary.append(ACTION_LABELS.get(plan["action"], plan["action"].upper()).ljust(10), style=COLORS.get(plan["action"], ""))
            summary.append(f"{plan['title']}\n{plan['destination']}\n\n")
        summary.append("Different histories remain separate branches. Existing conversations are retained.")
        def confirmed(accepted):
            if accepted:
                self._operate("Importing selected conversations…", lambda progress: self.backend.perform_import(*arguments, progress), self._import_ready)
        self.push_screen(ConfirmScreen("Confirm import", summary, "Import"), confirmed)

    def _import_ready(self, plans):
        for plan in plans:
            self._log(f"{ACTION_LABELS.get(plan['action'], plan['action'].upper())} · {plan['title']}", COLORS.get(plan["action"]))
            if plan.get("thread_id"):
                self._log("Continue: codex resume " + plan["thread_id"])
        self._invalidate_import()
        self.notify("Import finished. Existing conversations are retained.", title="Import complete")
        summary = Text()
        for plan in plans:
            summary.append(ACTION_LABELS.get(plan["action"], plan["action"].upper()).ljust(10), style=COLORS.get(plan["action"], ""))
            summary.append(plan["title"] + "\n")
            if plan.get("thread_id"):
                summary.append("codex resume " + plan["thread_id"] + "\n\n")
        self.call_later(self.action_refresh)
        self.call_later(self.push_screen, ConfirmScreen("Import complete", summary, "Close"))

    def _history_rows(self, rows):
        table = self.screen_stack[0].query_one("#history-table", DataTable)
        table.clear()
        self.selected_operation = None
        for row in rows:
            table.add_row(Text(row["created_at"][:19].replace("T", " ")), Text(row["status"]),
                          Text(row["title"]), Text(row["operation"][:12]), key=row["operation"])
        self._buttons()

    @on(DataTable.RowHighlighted, "#history-table")
    def operation_highlighted(self, event):
        self.selected_operation = event.row_key.value
        self._buttons()

    @on(Button.Pressed, "#refresh-history")
    def refresh_history(self):
        self._operate("Loading operation journals…", lambda progress: self.backend.history(), self._history_rows)

    @on(Button.Pressed, "#rollback-operation")
    def confirm_rollback(self):
        if not self.selected_operation or self.busy:
            return
        operation = self.selected_operation
        summary = Text("Archive the imported copies for this operation?\n\nTheir messages remain recoverable in Codex's archive. Original conversations and native forks remain available.\n\nOperation: " + operation)
        def confirmed(accepted):
            if accepted:
                self._operate("Rolling back imported copies…", lambda progress: self.backend.rollback(operation, progress), self._history_rows)
        self.push_screen(ConfirmScreen("Roll back import", summary, "Archive copies"), confirmed)

    def _saved_mappings(self):
        options = [(Text(source), source) for source in (self.backend.config or {}).get("mappings", {})]
        self.screen_stack[0].query_one("#saved-mapping", Select).set_options(options)
        projects = [("Bundle project / unassigned", "auto")] + [(Text(p.get("name", p["id"])), p["id"]) for p in self.projects]
        self.screen_stack[0].query_one("#saved-project", Select).set_options(projects)
        self.screen_stack[0].query_one("#saved-project", Select).value = "auto"

    @on(Select.Changed, "#saved-mapping")
    def saved_mapping_changed(self, event):
        if event.value is Select.BLANK:
            return
        saved = self.backend.config.get("mappings", {}).get(event.value, {})
        self.screen_stack[0].query_one("#saved-destination", Input).value = saved.get("destination", "")
        project = saved.get("project_id") or "auto"
        self.screen_stack[0].query_one("#saved-project", Select).value = project if project == "auto" or project in {p["id"] for p in self.projects} else "auto"

    @on(Button.Pressed, "#save-mapping")
    def save_mapping(self):
        source = self.screen_stack[0].query_one("#saved-mapping", Select).value
        if source is Select.BLANK:
            self.notify("Choose a saved source folder first.", severity="warning")
            return
        destination = self.screen_stack[0].query_one("#saved-destination", Input).value
        project = self.screen_stack[0].query_one("#saved-project", Select).value
        self._operate("Saving folder mapping…", lambda progress: self.backend.save_mapping(source, destination, None if project == "auto" else project),
                      lambda result: self._log("Folder mapping saved.", "green"))

    @on(Button.Pressed, "#save-settings")
    def save_settings(self):
        values = {key: self.screen_stack[0].query_one("#setting-" + key.replace("_", "-"), Input).value.strip().strip(chr(34))
                  for key in ("device_name", "codex_home", "codex_executable", "exchange_dir", "state_dir")}
        def saved(result):
            self._log("Device settings saved and Codex connection verified.", "green")
            self.notify("Device settings saved.")
            self.call_later(self.action_refresh)
        self._operate("Checking paths and Codex connection…", lambda progress: self.backend.save_settings(values), saved)


def run_tui(settings_path=None):
    ChatSyncApp(settings_path).run()
    return 0
