# Desktop interface

The desktop window uses pywebview with a React frontend. All migration operations
go through `chatsync.core.service.ChatSyncService`; this package contains the bridge
and presentation, not a separate migration engine.

## Run

From the project root, run `python setup.py`, then `python launch.py`.
Setup installs Python dependencies and uses the included `web/dist` resources;
Node.js/npm is not required for normal use. On Windows, double-click the generated
`Codex Chat Sync.lnk` shortcut for a window without a terminal.

Read the root README for settings and the complete export, transfer, and import flow.
For startup diagnostics, run the project environment's Python with `chat_sync_gui.py`.
The existing `run-gui.cmd` launcher remains optional.

## Develop

With Node.js/npm installed, `python setup.py --rebuild` installs frontend dependencies
using the lockfile and rebuilds `web/dist`. Commit the resulting resources with source
changes. For live frontend development:

```text
cd chatsync/interfaces/gui/web
npm ci
npm run dev
```

From another terminal in the project root, run the environment's Python with
`chat_sync_gui.py --dev`. The browser-only development page uses mock data; the
desktop window talks to the real shared service. No hosted server is needed for
normal application use.

`tests/gui/test_bridge.py` checks service signatures, bridge operations and interface
dependency boundaries. Executable/installer packaging will be addressed separately.
