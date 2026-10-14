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

## Continuation and CLI checks

A completed conversation was exported and imported as a temporary test copy with fresh IDs. It restored ten completed turns and successfully completed an additional verification turn, recalling earlier context without calling tools or modifying files. The original conversation was retained.

The Codex CLI resume command opened the imported copy and displayed its title, destination folder, restored conversation and verification answer. It exited without another user/model turn. The test copy was archived afterward.

## Compatibility boundaries

- Native project assignment works through Codex's protocol. Some desktop builds maintain a separate sidebar cache that may require reopening Codex, opening the imported chat and assigning its project in the app.
- Tested histories include tool/reasoning records and synthetic branch/image inputs. Compacted histories, remote file-ID-only attachments, very large conversations, interrupted histories and future Codex versions have not received equivalent live acceptance coverage. Verification rejects incompatible imports before production registration.
- Python 3.11+ is required. Windows has device-level acceptance coverage; macOS/Linux do not yet have equivalent coverage.
- Updates retain earlier copies. Rollback archives imported copies rather than deleting messages. Whole-project selection uses native project membership; folder selection covers chats whose membership is empty.
- An existing file-transfer service carries immutable bundles. Automatic import/watch scheduling is not part of this release.
