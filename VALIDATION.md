# Validation summary

Status: working first release, tested in two Windows environments. Compatibility with every Codex build or history format is not established.

Detailed acceptance logs are retained locally and excluded from version control. This document summarizes the results without account names, machine identifiers, local paths, conversation IDs or private conversation content.

## Automated checks

| Environment | Python | Codex CLI | Result |
|---|---|---|---|
| Environment A | 3.14 | 0.162.1 | All 9 tests passed |
| Environment B | 3.12.14 | 0.162.0-alpha.17.2 | All 9 tests passed |

The engine, bundle validator, RPC adapter and integration test source hashes matched across both environments. The tests ran in writable temporary folders with isolated Codex data directories.

The integration test uses locally supplied conversation rollouts and checks:

- Two chats in one file, native project creation/assignment and ordinary unassigned chats.
- Complete ancestor closure, new physical IDs for every dependency and preservation of projected messages/tool items.
- Restart and resume by ID, exact completed-turn signatures and destination folder mappings.
- Reimport without duplication, export back to the source, older checkpoints and linear updates.
- Divergent persisted histories, exporting both branches together and retaining both.
- Multiple destination folders, changed mappings, spaces/non-ASCII paths, explicit documents, local-image assets and inline image data.
- Nested metadata-only forks, rollback and retention of native forks/user histories.
- Terminal setup, bundle inspection and import preview.

Unit checks cover checksums, unsafe archive names, missing dependencies, immutable publication, history comparison, multi-selection, local operation locks and relocating managed state while retaining a backup.

## Terminal interface checks

The Textual 8.2.8 interface was checked in headless terminal sessions on Windows with Python 3.14. Tests cover keyboard selection, retention of hidden selections across filters, first-launch settings, compact layouts, F3 previews, import-review invalidation, explicit confirmation/cancellation, exact branch selection, bundle-change detection, saved mappings, rollback and prevention of overlapping operations or quitting during a transaction.

The combined local run passed all 19 tests: nine existing core/native checks and ten interface/service checks. The native Codex regression test also verifies exact selection of one divergent branch and progress reporting. A read-only smoke test loaded the saved configuration, the configured chat and project inventories without performing a live migration or model turn. Published screenshots use synthetic conversations and neutral paths; private regression fixtures and detailed logs remain excluded from Git.

## Continuation and CLI checks

A completed conversation was exported and imported as a temporary test copy with fresh IDs. It restored ten completed turns and successfully completed an additional verification turn, recalling earlier context without calling tools or modifying files. The original conversation was retained.

The Codex CLI resume command opened the imported copy and displayed its title, destination folder, restored conversation and verification answer. It exited without another user/model turn. The test copy was archived afterward.

## Compatibility boundaries

- Native project assignment works through Codex's protocol. Some desktop builds maintain a separate sidebar cache that may require reopening Codex, opening the imported chat and assigning its project in the app.
- Tested histories include tool/reasoning records and synthetic branch/image inputs. Compacted histories, remote file-ID-only attachments, very large conversations, interrupted histories and future Codex versions have not received equivalent live acceptance coverage. Verification rejects incompatible imports before production registration.
- Python 3.11+ is required. Windows has device-level acceptance coverage; macOS/Linux do not yet have equivalent coverage.
- Updates retain earlier copies. Rollback archives imported copies rather than deleting messages. Whole-project selection uses native project membership; folder selection covers chats whose membership is empty.
- An existing file-transfer service carries immutable bundles. Automatic import/watch scheduling is not part of this release.

## CLI-only core restructure (0.2.0)

The reorganized `main` branch passed all 16 tests on Windows with Python 3.14
and Codex CLI 0.162.1, with no skipped tests. The native integration run used
the existing private regression fixture and isolated data folders; it did not
import into production chat storage or invoke a model.

Additional checks cover exact branch-snapshot selection, optional progress
callbacks, bundle-change rejection between review and import, destination
validation, combined active/archived inventory and CLI routing. A dependency
check enforces that core modules do not import interfaces or UI packages.
The existing CLI launcher and help output were also verified.

This run verifies the new package layout locally. The earlier two-device
results above describe the original release; the restructure has not yet
been rerun on the second device or on macOS/Linux.

## Terminal interface on shared core (0.2.0)

The terminal-ui branch was adapted to the reorganized main branch and passed
all 23 tests on Windows with Python 3.14, Textual 8.2.8 and Codex CLI 0.162.1,
with no skipped tests. This includes the 16 shared core/CLI tests and seven
terminal interaction/routing tests. Native checks used isolated data folders;
production chats were not modified. Launcher routing was rerun after the final
help/error handling adjustment and passed.

Core modules, the plain CLI implementation and their tests match main exactly.
Textual screens and optional launch dispatch live in interfaces/terminal, using
the shared ChatSyncService. The duplicate UI service was removed. This updated
branch has not yet been tested on another device or operating system.
