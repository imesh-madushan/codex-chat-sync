# Codex Chat Sync

A standalone terminal tool for moving selected Codex chats between devices. Python 3.11+ and an installed Codex CLI are the only runtime requirements. No web server, hosted service, Python packages, SSH, or Syncthing API access.

## Start

From this folder, run:

```powershell
python chat_sync.py setup
python chat_sync.py
```

Windows launcher:

```powershell
.\run.cmd setup
.\run.cmd
```

`run.cmd` uses `CHATSYNC_PYTHON` when set, then the standard per-user Python installation, then the `py -3` launcher. For another Python installation, set `CHATSYNC_PYTHON` to the interpreter’s absolute path. Other operating systems run `python3 chat_sync.py` directly.

If `python` opens the Microsoft Store, use the full path to your installed Python executable instead. On Windows, setup requires the actual `codex.exe`, rather than the npm `.cmd`/PowerShell wrapper. An installed npm executable is suggested when found; you can enter any other installation.

Setup asks for your Codex data folder, Codex executable, bundle exchange folder and a **local state folder outside your synced folders**. Paths are entered/confirmed by you and saved per device. Settings are independent of the account name, project location and device pair. Settings → Edit device paths changes them later. Each device uses its own settings and receipts, even when this program's source folder is synced.

Default settings: `%LOCALAPPDATA%\CodexChatSync\config.json` on Windows; `~/.local/share/CodexChatSync/config.json` elsewhere. Override with `--config PATH` before the command, or `CHATSYNC_CONFIG`.

## Configuration examples

The following locations illustrate a Windows configuration. Environment variables resolve to the current account; project and exchange folders can be placed elsewhere.

| Setting | Example location |
|---|---|
| Codex data | `%USERPROFILE%\.codex` |
| Local state | `%LOCALAPPDATA%\CodexChatSync\state` |
| Bundle exchange | `D:\Shared\ChatBundles` |
| Project folder | `D:\Projects\sample-app` |

In PowerShell, expand environment variables with `$env:` when passing arguments:

```powershell
.\run.cmd setup --codex-home "$env:USERPROFILE\.codex" --exchange-dir "D:\Shared\ChatBundles" --state-dir "$env:LOCALAPPDATA\CodexChatSync\state"
```

Setup prompts for the Codex executable if it is not supplied. When entering a path in an interactive prompt, use the resolved absolute path; the `%VARIABLE%` notation in the table is documentation notation.

## Export and import

The export menu supports chats across projects, all chats in multiple selected projects, or chats selected by folder. Enter `1,3-5` or `all` to select multiple entries. Unassigned ordinary chats are included in the chat picker. Project membership and folder grouping are separate options because older Codex versions sometimes leave project membership empty.

Each export produces one immutable `.chatbundle.zip`. Put the exchange folder wherever your existing file-transfer/sync service runs. The tool handles export and import; your transport copies the bundle between devices. It never automatically imports every file that arrives.

On import, choose the bundled chats and map their source folders to existing folders on this device. You can choose existing Codex projects; project chats can also recreate a native project. Folder/project mappings are saved and can be edited in Settings. Multiple selected chats may use different destination mappings.

The tool validates the bundle and reconstructs all selected history in a temporary, unauthenticated Codex data folder before adding copies to your actual Codex data folder. It checks completed turns again after restarting. Existing raw conversations and databases are never replaced or directly edited.

Import results:

- `same`: the completed history is already available; no duplicate is created.
- `stale`: a local conversation already includes the incoming history; nothing is replaced.
- `update`: the incoming history extends a local version; a new resumable snapshot is created and the earlier copy remains available.
- `branch`: the histories have different messages/content; both survive. The new title names its source device.
- `new`: this logical chat has not been imported here before.
- `relocate`: the same completed history exists in a different folder/project; a new copy uses the changed mapping.

Continue using the returned resume ID: `codex resume ID`. Close the same chat in other local clients if Codex reports an exclusive writer lock. The desktop may need to be reopened to refresh newly registered chats. Native project assignment is verified through the protocol; older desktop builds also maintain a separate sidebar project cache, so their sidebar may require opening the chat and assigning its project in the app. This tool does not edit that private cache.

## Commands

```text
python chat_sync.py list
python chat_sync.py list --archived
python chat_sync.py export --thread ID1 --thread ID2
python chat_sync.py export --project PROJECT1 --project PROJECT2
python chat_sync.py export --cwd "absolute/project/folder"
python chat_sync.py export --thread ID --asset "absolute/file/path"
python chat_sync.py inspect "bundle.chatbundle.zip"
python chat_sync.py import "bundle.chatbundle.zip" --dry-run --map "SOURCE=DESTINATION"
python chat_sync.py import "bundle.chatbundle.zip" --yes --map "SOURCE=DESTINATION"
python chat_sync.py import "bundle.chatbundle.zip" --chat LOGICAL_ID1 --chat LOGICAL_ID2
python chat_sync.py doctor
python chat_sync.py rollback OPERATION_ID
```

`--map` and `--project-map SOURCE=LOCAL_PROJECT_ID` can each be repeated. `--chat` uses the logical IDs printed by `inspect`, while `export --thread` uses physical Codex IDs printed by `list`. Interactive import previews its actions before confirmation. `--yes` requires saved or explicit mappings.

Rollback archives only the imported copies for that operation. Their messages remain recoverable through Codex's archive; originals remain available. Operation journals and pre-import receipt backups live in the configured local state folder. Interrupted imports retain their new files/evidence and a prepared/failed journal; they do not delete original chats. Keep local receipts backed up: they link logical chats to device-local IDs across repeated exports.

## Attachments and limits

Structured local image, audio and file-mention inputs are included automatically. Inline image data remains in the transcript. Other files mentioned in prose, files read by tools, generated files, code repositories and environments are **not inferred or copied**: include needed documents explicitly with `--asset`, and transfer project files separately. Attachments are stored under the configured local state folder by content hash; user project files are never overwritten. Historical text and historical tool folders retain their original values. Changing the local state folder copies managed receipts/assets and retains the old folder as a backup; keep that backup because previously imported image paths may still reference it.

Bundles contain private conversation text/tool outputs and may contain sensitive information that was already in the chat. They do not include account credentials, configuration files or whole Codex databases. Keep bundles and receipts private. Import rejects unsafe ZIP paths, duplicate members, symlinks, unsupported formats, invalid dependencies and failed checksums. Limits: 256 MiB per file, 1 GiB total uncompressed, 10,000 archive members. Authentication, plugins and tools must already be configured on the destination when you continue a conversation.

## Compatibility and verification

Codex path-resume and paginated-history APIs are experimental. The tool enables the required capability and fails when a build cannot reconstruct the exact exported history. It cannot promise compatibility with every future Codex storage version. Export currently requires all persisted turns to be completed; finish interrupted/active turns in Codex first.

Unit tests:

```text
python -m unittest discover -s tests -v
```

Real integration tests require `CHATSYNC_TEST_CODEX` (the actual executable) and `CHATSYNC_TEST_FIXTURE` (a local parent/fork regression fixture ZIP containing a nine-turn parent and its ten-turn descendant). They use isolated data folders, no accounts and no model calls. See `VALIDATION.md` for recorded results and remaining acceptance limits.

Protocol reference: [official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server).
