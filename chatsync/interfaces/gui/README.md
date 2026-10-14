# Desktop interface (pywebview + React)

An interface like `cli/`: it talks only to `chatsync.core.service.ChatSyncService`
(never to the engine or another interface), so core changes reach every UI the same way.

```
app.py   Python bridge: Api class exposed to JavaScript, plus main()
web/     Vite + React source (src/); `npm run build` writes web/dist
```

## Run

```text
python -m pip install -r requirements-gui.txt
cd chatsync/interfaces/gui/web && npm install && npm run build   # once per machine (dist/ is git-ignored)
python chat_sync_gui.py            # Windows: run-gui.cmd
```

On Windows, `run-gui.cmd` starts the application with `pythonw.exe` and
returns immediately, so it does not keep a console window open. It uses
`CHATSYNC_PYTHON`'s sibling `pythonw.exe` when configured, otherwise the local
virtual environment, the standard per-user installation, or `pyw -3`.
A double-clicked CMD launcher may briefly show a console while starting;
it closes after dispatch. For startup errors and console diagnostics, run
`python chat_sync_gui.py` directly in the same Python environment.

## Develop the UI

```text
cd chatsync/interfaces/gui/web
npm run dev                                    # plain browser, mock data, no Codex needed
python chat_sync_gui.py --dev                  # real window + real service against the dev server
```

## Contract with core

`tests/gui/test_bridge.py` binds the real `ChatSyncService` signatures to every call the bridge makes,
so a core change that would break the GUI fails the test suite. It also checks that this package imports
only `chatsync.core` and that `webview` is imported lazily (the CLI/core need no GUI packages).

## Packaging

`pyinstaller --noconsole --add-data "chatsync/interfaces/gui/web/dist;chatsync/interfaces/gui/web/dist" chat_sync_gui.py`
(use `:` instead of `;` on macOS/Linux).
