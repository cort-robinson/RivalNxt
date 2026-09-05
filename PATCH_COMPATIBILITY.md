# Patch compatibility repair

## Source used

Implementation started from upstream `main` at
`fecebc5926af8254f1496316d8555442a5b310e5` in a clean worktree.

On 5 September 2026, the official GitHub release API reported
[repak-rivals v3.7.4](https://github.com/natimerry/repak-rivals/releases/tag/v3.7.4)
as the latest release. The worker uses the `repak` library at commit
`56cce699c29c37a658b4c453ed2283aa59245bb3`. Cargo.lock records its dependencies.

The worker follows the official
[companion PAK index rewrite](https://github.com/natimerry/repak-rivals/blob/v3.7.4/repak-gui/src/install_mod/install_mod_logic/pak_files.rs).
It removes `../../../chunknames`, `../../../patched_files`, and files named
`desktop.ini`. The last check uses the full filename, without case sensitivity.
Thus, a valid asset named `desktop.ini.uasset` stays in the package. This is a
more limited match than the substring check in the official GUI.

Only the library's encryption feature is needed. The worker does not decode or
rebuild asset data. It does not include the GUI, asset converters, or bypass tools.
The existing `rust-ue-tools` submodule stays at its upstream revision.

## Use

1. Close the game and other mod tools.
2. In the active mods view, open **Patch compatibility**.
3. Select **Scan installed mods**.
4. Select **Repair old indexes** if the scan finds old entries.
5. Read each result. A repaired index does not confirm that the mod works in the game.

The scan is limited to the configured `~mods` folder. It does not search the
normal game PAK folder, reset settings, delete movie files, or change loaders.
Unpaired UTOC or UCAS files are reported and left in place.

The main activation path stages files outside the game before it checks them.
This path serves new installs, updates, per-file enable actions, collections,
and activation by name. The command-line activation script also stages and checks
packages. The original download is unchanged. If the archive check fails, the
new files are not enabled. An update keeps the previous mod active after an
activation failure.

## File checks and limits

- Supported indexes: Rivals PAK versions 10 and 11, with a full directory index,
  encoded records, and the known Rivals encryption key.
- The service checks the main, directory, and available path index hashes.
  It rejects invalid ranges, missing records, duplicate references, unsupported
  index forms, linked paths, and incomplete companion pairs.
- Each index is limited to 64 MiB and 250,000 entries. Other formats are blocked.
- After repair, the service compares all retained encoded records and all bytes
  before the original index. These bytes must be identical. The mount point and
  data offset must also match.
- The service does not decode assets or establish that the original asset payload
  was valid. It checks index structure and confirms that repair preserves data.
- UTOC and UCAS files are not rewritten. Their hashes guard installed repairs and
  later restore operations. Their asset manifests are not parsed by this feature.
- Audio, VFX, movie, config, camera-shake, other content, and unchecked IoStore
  assets have explicit notes. In-game compatibility remains **unknown** for every
  package. The v3.7.4 audio release note does not establish general audio support.
- Operations in the backend use one lock. Close other mod tools; a separate
  process must not change package files during a file operation.

## Backups and restore

Backups are stored under `<data_dir>/compatibility-backups/<id>`, outside `~mods`.
Each manifest records the root, relative paths, SHA-256 hashes, time, and state.
Every original file is copied and verified before a replacement starts. Source
PAKs repaired during an install are also saved and listed in the manifest.

Replacements use a temporary file on the destination volume and `os.replace`.
A multi-file publish failure starts rollback. The manifest is saved before the
first replacement, so an interrupted operation remains visible after restart.

Open **Restore saved files** to restore a backup. Restore checks all saved and
current hashes before it starts. It stops if a file or companion has changed
since the operation. It does not overwrite later edits. A restored first install
removes only the new files recorded in that install. Original backup files remain.

If a disk or permission error also prevents rollback, keep the complete backup
folder. Correct the file access problem, then use its restore action. Do not edit
the manifest or replace a backup with an unverified file.

A second repair of a clean index makes no file change and creates no new backup.
The archive repair does not change the database schema. The existing state backup
feature remains separate. Restore refreshes the active-file scan.

## Build and tests

```powershell
cargo build --release --locked --manifest-path tools/pak-repair/Cargo.toml
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/backend -q
npm ci
npm run typecheck
npm run build
npm test
```

The PyInstaller specification builds and embeds the worker and its repak license.
Backend CI also builds the worker before tests. No repair tool is downloaded at
application runtime.

Checks completed in this worktree:

- 372 backend tests passed. These include encrypted and plain indexes, mixed
  content, repeated repair, bad archives, missing companions, copy and backup
  failures, partial install rollback, interrupted journals, and guarded restore.
- 188 frontend tests passed, including repair status, restore, and error recovery.
- All 210 original PAK samples from the prior backup were copied to temporary
  storage. Their repairs passed retained-record and data-prefix checks.
- TypeScript, the frontend build, the native Python module, the repair worker,
  the PyInstaller backend, and the Tauri Windows installer built successfully.
- The changed Python files passed Ruff. The full repository check found 25
  existing lint errors in older test scripts.
- Browser controls and result text were checked with synthetic data. Screenshot
  capture timed out, so a full visual screenshot check is not claimed.
- `graphify update .` could not run: the command and graph output were absent.

The game and the built application were not started. No installed game file,
original audit, repair archive, or prior backup was changed. No in-game result is
claimed. The Windows installer is a local build, not a published release.
