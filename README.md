# Codex Chat Sync

Move selected Codex conversations between computers using a desktop application
or the command line. Select multiple chats or projects, export them into one
bundle, transfer the file, and import the conversations where you want to continue.

The application does not transfer files between devices automatically. Use any
method you prefer: copy/paste, a USB drive, a shared or network folder, or your
existing file-transfer service. No particular service is required.

## Get started

You need Python 3.11 or newer and an installed Codex CLI on each computer.
The desktop interface also needs its Python dependencies, which setup installs.
On Windows, the GUI uses the system webview; if it reports a missing WebView2
runtime, install that runtime and launch again.

Download or clone the complete project. In its folder, run:

```text
python setup.py
python launch.py
```

On macOS/Linux, use `python3` if that is your Python command. Windows users can
use `py -3` if `python` opens the Microsoft Store.

Setup creates `.venv` inside this project, installs the available interfaces'
Python dependencies, and checks that the included GUI files are present. It
does not change your global Python packages or saved chat settings. Dependency
installation requires internet access unless the packages are already available.

**Node.js/npm is optional.** The project includes the built GUI files, so normal
users do not need to build the frontend. If those files are missing, setup can
rebuild them when npm is installed, otherwise it explains how to get a complete copy.

On Windows, setup creates **Codex Chat Sync.lnk** in this folder. Double-click
that shortcut to open the application without a terminal. Keep the project at
the same location, or rerun setup after moving it. CMD launchers are optional;
you do not need them for the standard setup and launch flow.

For a CLI-only installation:

```text
python setup.py --interface cli
python launch.py --interface cli
```

The CLI can also run directly with `python chat_sync.py`; it needs no third-party
Python packages. Setup prepares the Python application; it does not create an
executable or installer.

## Configure each computer

Open **Settings**, enter the following, and click **Save device settings**:

| Setting | What to choose |
|---|---|
| Device label | A name that helps you identify where an imported branch came from. |
| Codex data folder | Your existing Codex data folder, usually `~/.codex`. |
| Codex executable | The installed executable. On Windows, select the actual `codex.exe`, not a `.cmd` or `.ps1` wrapper. |
| Bundle exchange folder | Any folder where exported bundles should be saved. It can be local, removable, shared, or on a network drive. |
| Local state folder | A dedicated folder on this computer for receipts and imported attachments, separate from the bundle folder. Keep it local. |

Use **Browse** to select paths. Saving verifies the Codex connection. Each
computer has its own settings; usernames, folder names, and project paths do not
have to match. You can change these settings later.

For example, bundles could be saved to `D:\ChatBundles`, with a destination
project at `D:\Projects\sample-app`. On Windows, settings are saved under
`%LOCALAPPDATA%\CodexChatSync\config.json`; elsewhere the default is
`~/.local/share/CodexChatSync/config.json`. Override with `CHATSYNC_CONFIG` or
`--config PATH`. The default local state folder is beside the settings file.

## Export chats

1. Finish active or interrupted turns in the conversations you want to export.
2. Open **Chats**. Search or filter by project/folder to find conversations.
3. Select the chats you want. **Select visible** selects the currently displayed
   chats; selections can include multiple projects or unassigned conversations.
4. Click **Export selected**, review the selection, and confirm **Export**.
5. Note the saved `.chatbundle.zip` path shown when export completes.

Each bundle is a snapshot of completed history. Export again after adding new
messages; an old bundle does not update itself. Existing bundles are never overwritten.

## Transfer the bundle

Copy the completed `.chatbundle.zip` to the other computer by any method.
For example, save it in a shared/network folder both computers can access, then
open that same file on the destination. Alternatively, copy it onto a USB drive,
then copy it into any folder on the destination computer.

You can keep incoming files in the configured bundle folder for convenience,
but **Import → Browse** can open a bundle from another location. Copy the complete
file before importing. Do not copy this application's local state folder or
Codex authentication files as part of the transfer.

## Import and continue

1. On the destination computer, open **Import** and **Browse** for the bundle.
2. Click **Load bundle** and select the conversations to import.
3. Map each selected source folder to an existing project folder on this computer.
   Choose the destination project assignment where offered. Different chats can
   use different folders, and the original source path does not have to exist here.
4. Click **Review import** and inspect the planned actions.
5. Click **Import selected**, then confirm **Import**.
6. Use the resume command shown in the result, or open the imported conversation
   in Codex. Reopen Codex if its chat list has not refreshed.

The tool verifies reconstructed histories in an isolated temporary Codex folder
before registering imported copies. Existing conversations are retained.
Folder/project mappings are saved for later imports; the Settings page edits
device paths, while importing lets you change the destination mappings.

| Result | Meaning |
|---|---|
| New | A conversation is being imported here for the first time. |
| Update | The incoming history extends a local version; a new snapshot is created. |
| Branch | Both computers added different messages; both versions are preserved. |
| Duplicate / same | This completed history is already available; no duplicate is created. |
| Older / stale | The local conversation already includes the incoming history. |
| Relocate | A new copy uses a changed destination folder/project mapping. |

Branches remain separate conversations. The tool does not combine conflicting
messages automatically. CLI `--chat` selects a logical chat family; the GUI can
select individual bundled branch snapshots.

Some Codex desktop versions maintain a separate project sidebar cache. If needed,
open the imported chat and assign its project within Codex. For an exclusive-writer
error, close that same chat in another local client and retry.

## History and rollback

Open **History**, select an import operation, and click **Roll back selected**.
Review the confirmation before choosing **Archive copies**. Rollback archives
that operation's imported copies; original conversations remain available and
archived messages remain recoverable through Codex.

Keep your device-local state backed up: receipts identify histories previously
imported here. Changing the state folder copies managed receipts/assets and keeps
the old folder as a backup. Retain that backup because older imported attachments
may still reference it. Interrupted imports retain journals for diagnosis.

## Command-line usage

Use the plain menu with `python launch.py --interface cli`. The following direct
commands are also available and need no GUI dependencies:

```text
python chat_sync.py setup
python chat_sync.py list
python chat_sync.py list --archived
python chat_sync.py export --thread ID1 --thread ID2
python chat_sync.py export --project PROJECT1 --project PROJECT2
python chat_sync.py export --cwd "absolute/project/folder"
python chat_sync.py export --thread ID --output "bundle.chatbundle.zip"
python chat_sync.py export --thread ID --asset "absolute/file/path"
python chat_sync.py inspect "bundle.chatbundle.zip"
python chat_sync.py import "bundle.chatbundle.zip" --dry-run --map "SOURCE=DESTINATION"
python chat_sync.py import "bundle.chatbundle.zip" --yes --map "SOURCE=DESTINATION"
python chat_sync.py import "bundle.chatbundle.zip" --chat LOGICAL_ID1 --chat LOGICAL_ID2
python chat_sync.py doctor
python chat_sync.py rollback OPERATION_ID
codex resume IMPORTED_ID
```

Replace the example IDs and paths with values from `list` or `inspect`.
`--thread`, `--project`, `--cwd`, `--asset`, `--map`, and
`--project-map SOURCE=LOCAL_PROJECT_ID` can be repeated. Interactive selectors
accept numbers/ranges such as `1,3-5`, `all`, or `cancel`. Interactive import
reviews its actions before confirmation; `--yes` requires saved or explicit mappings.
Use `python chat_sync.py --config "settings.json" COMMAND` for a custom configuration.

## What travels with a chat?

Bundles contain completed conversation history and required ancestor snapshots.
Structured local image, audio, and file-mention inputs are included automatically;
inline images remain in the transcript. Other documents can be included explicitly
with CLI `--asset`.

Project source code, development environments, files only mentioned in prose,
and authentication are not automatically copied. Transfer project files separately
and configure accounts, tools, and plugins on the destination. Historical text and
tool paths remain as recorded; imported attachments are stored in local state and
do not overwrite project files. Treat exported bundles as private conversation data.

## Troubleshooting

- **GUI does not start:** run `.venv\Scripts\python.exe chat_sync_gui.py` on Windows,
  or `.venv/bin/python chat_sync_gui.py` elsewhere, to see startup diagnostics.
- **Missing Python dependencies:** rerun `python setup.py` in this project folder.
- **Missing interface files:** get a complete project copy, or install Node.js/npm
  and run `python setup.py --rebuild`.
- **Cannot find Codex:** select its real executable in Settings; CLI `doctor` checks
  the configured executable and protocol.
- **Export says history is incomplete:** finish the conversation's active/interrupted
  turns in Codex, then export again.
- **Destination folder is missing:** create or select the project folder before import.

The interface is designed for Windows, macOS, and Linux, but current acceptance
coverage is on Windows. Codex history APIs are experimental: incompatible history
is rejected rather than imported without verification. See [VALIDATION.md](VALIDATION.md)
for tested behavior and remaining limits.

## Development

To rebuild the shipped frontend after changing GUI source:

```text
python setup.py --rebuild
```

This uses `npm ci` and `npm run build`. Commit the updated GUI `web/dist` files
alongside source changes so users without npm receive the current interface.
Other `dist`, `build`, `node_modules`, `.venv`, private fixtures, and local shortcuts
remain ignored. Use `--skip-install` only when Python dependencies are already prepared.

Interfaces register setup requirements in `chatsync/interfaces/NAME/setup.json`.
The CLI and GUI are included on `main`; another interface can add its entry point,
optional requirements, and optional frontend build paths without changing the engine.
The optional terminal UI is maintained separately for now.

```text
chatsync/core/             Shared configuration, bundles, RPC, engine and service
chatsync/interfaces/cli/   Plain command-line interface
chatsync/interfaces/gui/   Desktop bridge and React interface
setup.py                  Prepare the local environment and interface resources
launch.py                 Launch an interface using that environment
tests/                    Core, CLI, setup and GUI bridge checks
```

Run `python -m unittest discover -s tests -v`. Native integration checks additionally
require `CHATSYNC_TEST_CODEX` and `CHATSYNC_TEST_FIXTURE`, and use isolated folders
without accounts or model calls. Interfaces depend on the shared core; core never
imports presentation frameworks. Standalone executable/installer releases are future work.
