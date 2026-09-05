"""Previewed loadout switches with a durable filesystem rollback journal.

The existing activation callback remains responsible for archive validation and
compatibility repair. This layer supplies atomic batch semantics around it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from core.compatibility import service as compatibility


class ActivationError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _list(value):
    result = json.loads(value or "[]")
    if not isinstance(result, list) or any(not isinstance(p, str) for p in result):
        raise ActivationError("A download has invalid file metadata. Refresh the library first.")
    return result


def _base(path):
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _stems(paks):
    return {os.path.splitext(_base(p))[0] for p in paks}


def _available(requested, contents):
    normalized = requested.replace("\\", "/").lower()
    paths = {path.replace("\\", "/").lower() for path in contents}
    if normalized in paths:
        return True
    relative_stem = os.path.splitext(normalized)[0]
    if relative_stem in {os.path.splitext(path)[0] for path in paths}:
        return True
    # Legacy selections contain basenames, which are usable only when unique.
    matches = {os.path.splitext(path)[0] for path in paths
               if os.path.splitext(_base(path))[0] == os.path.splitext(_base(requested))[0]}
    return "/" not in normalized and len(matches) == 1


def _files(root):
    """Never follow links, including Windows junctions, while snapshotting."""
    result = {}
    if not root.exists():
        return result
    compatibility.safe_path(root, ".")
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            relative = path.relative_to(root)
            compatibility.safe_path(root, relative)
            if path.is_file():
                stat = path.stat()
                result[relative.as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return result


def _write(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_pending_recovery(data_dir):
    """Used by the server mutation gate before any other mod-changing route."""
    return _pending(Path(data_dir) / "activation-journals")


def _pending(journal_root):
    for path in journal_root.glob("*/journal.json"):
        try:
            if json.loads(path.read_text(encoding="utf-8"))["state"] in ("applying", "step_in_progress", "rollback_failed"):
                return True
        except (OSError, ValueError, KeyError):
            return True
    return False


class ActivationService:
    def __init__(self, get_db, mods_root, journal_root, activate, refresh):
        self.get_db = get_db
        self.mods_root = Path(mods_root).absolute()
        self.journal_root = Path(journal_root).absolute()
        self.activate = activate
        self.refresh = refresh

    def _rows(self):
        conn = self.get_db()
        try:
            cursor = conn.execute("SELECT id, path, name, contents, active_paks, "
                                  "last_activated_at, last_deactivated_at FROM local_downloads ORDER BY id")
            keys = [column[0] for column in cursor.description]
            return [dict(zip(keys, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _state(self):
        rows = self._rows()
        sources = {}
        for row in rows:
            path = Path(row["path"])
            if path.is_file():
                stat = path.stat()
                sources[str(row["id"])] = [stat.st_size, stat.st_mtime_ns]
            elif path.is_dir():
                sources[str(row["id"])] = _files(path)
            else:
                sources[str(row["id"])] = None
        return rows, sources, _files(self.mods_root)

    @compatibility.serialized
    def preview(self, entries, download_paths=None):
        if not isinstance(entries, dict) or len(entries) > 10000:
            raise ActivationError("The preset must contain a download-to-files mapping.")
        target = {}
        if download_paths is None:
            download_paths = {}
        if not isinstance(download_paths, dict) or any(not isinstance(path, str) for path in download_paths.values()):
            raise ActivationError("The preset contains invalid download identities.")
        for key, paks in entries.items():
            if not str(key).isdigit() or not isinstance(paks, list) or len(paks) > 10000 or any(
                not isinstance(p, str) or not p.strip() or len(p) > 4096
                or p.startswith(("/", "\\")) or ":" in p
                or os.path.splitext(p)[1].lower() not in (".pak", ".utoc", ".ucas")
                or ".." in p.replace("\\", "/").split("/") for p in paks
            ):
                raise ActivationError("The preset contains invalid download IDs or file paths.")
            target[str(int(key))] = sorted(set(paks))
        rows, sources, files = self._state()
        known = {str(row["id"]): row for row in rows}
        missing = [{"download_id": int(key), "name": f"Download {key}", "reason": "Download is no longer installed"}
                   for key in target if key not in known]
        changes = []
        for key, row in known.items():
            desired = target.get(key, [])
            current = _list(row["active_paks"])
            contents = _list(row["contents"])
            if key in download_paths and os.path.normcase(os.path.normpath(download_paths[key])) != os.path.normcase(os.path.normpath(row["path"])):
                missing.append({"download_id": row["id"], "name": row["name"], "reason": "Saved download was replaced by a different source"})
            unavailable = [p for p in desired if not _available(p, contents)]
            if desired and (sources[key] is None or unavailable):
                missing.append({"download_id": row["id"], "name": row["name"],
                                "reason": "Source download is missing" if sources[key] is None else "Saved variant is missing or ambiguous",
                                "files": unavailable})
            if sorted(current) != desired:
                changes.append({"download_id": row["id"], "name": row["name"], "before": current, "after": desired})
        fingerprint = hashlib.sha256(_json([rows, sources, files, target, download_paths]).encode()).hexdigest()
        pending = self.pending_recovery()
        return {"token": fingerprint, "entries": target, "changes": changes,
                "missing": missing, "can_apply": not missing and not pending, "recovery_required": pending,
                "download_paths": download_paths}

    def pending_recovery(self):
        return _pending(self.journal_root)

    def _discard(self, folder):
        # Only discard the exact journal directory created underneath this root.
        resolved = folder.resolve()
        if resolved.parent != self.journal_root.resolve() or folder.is_symlink():
            raise ActivationError("Invalid rollback journal directory.")
        try:
            shutil.rmtree(resolved)
        except OSError:
            logging.getLogger(__name__).warning("Completed activation journal could not be removed: %s", folder)

    def _hashes(self):
        return {relative: compatibility.digest(compatibility.safe_path(self.mods_root, relative))
                for relative in _files(self.mods_root)}

    def _snapshot(self, owned_stems=None):
        self.journal_root.mkdir(parents=True, exist_ok=True)
        folder = self.journal_root / uuid.uuid4().hex
        folder.mkdir()
        files = _files(self.mods_root)
        manifest = {"state": "preparing", "root": str(self.mods_root), "rows": self._rows(), "files": {},
                    "owned_stems": sorted(owned_stems if owned_stems is not None else _stems(files))}
        _write(folder / "journal.json", manifest)
        for relative in files:
            source = compatibility.safe_path(self.mods_root, relative)
            destination = folder / "files" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            with destination.open("rb+") as durable_copy:
                os.fsync(durable_copy.fileno())
            manifest["files"][relative] = compatibility.digest(destination)
            if manifest["files"][relative] != compatibility.digest(source):
                raise ActivationError("A game file changed while preparing rollback. No selection was changed.")
        manifest["expected"] = manifest["files"].copy()
        manifest["expected_rows"] = manifest["rows"]
        manifest["state"] = "applying"
        _write(folder / "journal.json", manifest)
        return folder, manifest

    def _rollback(self, folder, manifest):
        if manifest["root"] != str(self.mods_root):
            raise ActivationError("The game folder changed. Restore its original setting before recovery.")
        if manifest["state"] == "step_in_progress":
            raise ActivationError("RivalNxt stopped while copying a file. Automatic recovery cannot verify the interrupted step. "
                                  "The original files remain in the activation-journals folder for manual recovery.")
        current = self._hashes()
        owned = set(manifest["owned_stems"])

        def managed(relative):
            return os.path.splitext(_base(relative))[0] in owned and os.path.splitext(relative)[1].lower() in (".pak", ".utoc", ".ucas")

        expected = manifest["expected"]
        expected_rows = {row["id"]: row for row in manifest["expected_rows"]}
        actual_rows = {row["id"]: row for row in self._rows()}
        for key, row in expected_rows.items():
            if actual_rows.get(key) != row:
                raise ActivationError("The library changed after this switch. Automatic recovery was stopped to preserve those edits.")
        # Later external edits must never be overwritten by an old journal.
        for relative in set(current) | set(expected):
            if managed(relative) and current.get(relative) != expected.get(relative):
                raise ActivationError("Game files changed after this switch. Automatic recovery was stopped to preserve those edits. "
                                      "The original files remain in the activation-journals folder for manual recovery.")
        # Validate the entire rollback copy before touching the game folder.
        for relative, digest in manifest["files"].items():
            source = compatibility.safe_path(folder / "files", relative)
            if compatibility.digest(source) != digest:
                raise ActivationError("The rollback copy is damaged. Its journal has been retained.")
        for relative in current:
            if managed(relative) and relative not in manifest["files"]:
                compatibility.safe_path(self.mods_root, relative).unlink()
        for relative in manifest["files"]:
            if not managed(relative):
                continue
            destination = compatibility.safe_path(self.mods_root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / "files" / relative, destination)
        conn = self.get_db()
        try:
            for row in manifest["rows"]:
                conn.execute("UPDATE local_downloads SET active_paks=?, last_activated_at=?, last_deactivated_at=? "
                             "WHERE id=? AND path=?", (row["active_paks"], row["last_activated_at"],
                                                      row["last_deactivated_at"], row["id"], row["path"]))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        self.refresh()
        manifest["state"] = "rolled_back"
        _write(folder / "journal.json", manifest)

    @compatibility.serialized
    @compatibility.recovery_operation
    def recover(self):
        recovered = 0
        for path in sorted(self.journal_root.glob("*/journal.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                state = manifest["state"]
            except (OSError, ValueError, KeyError) as error:
                raise ActivationError("An activation journal cannot be read. Keep the activation-journals folder for manual recovery.") from error
            if state in ("applying", "step_in_progress", "rollback_failed"):
                self._rollback(path.parent, manifest)
                recovered += 1
                self._discard(path.parent)
        return {"recovered": recovered}

    @compatibility.serialized
    @compatibility.recovery_operation
    def apply(self, entries, token, download_paths=None):
        if self.pending_recovery():
            raise ActivationError("An interrupted switch needs recovery. Recover the previous selection before applying another preset.")
        plan = self.preview(entries, download_paths)
        if plan["token"] != token:
            raise ActivationError("The library or game files changed. Review a fresh preview before applying.")
        if not plan["can_apply"]:
            raise ActivationError("Restore the missing downloads or save a new preset before applying.")
        if not plan["changes"]:
            return {"updated": 0, "missing": 0}
        owned_stems = _stems([pak for change in plan["changes"] for pak in change["before"] + change["after"]])
        folder, manifest = self._snapshot(owned_stems)

        def step(download_id, paks):
            manifest["state"] = "step_in_progress"
            _write(folder / "journal.json", manifest)
            try:
                return self.activate(download_id, {"active_paks": paks, "rebuild_conflicts": False})
            finally:
                # A process interruption before this checkpoint is explicitly ambiguous.
                manifest["expected"] = self._hashes()
                manifest["expected_rows"] = self._rows()
                manifest["state"] = "applying"
                _write(folder / "journal.json", manifest)
        try:
            # Remove old selections first so later disables cannot remove newly copied files.
            for change in plan["changes"]:
                if change["before"]:
                    step(change["download_id"], [])
            for change in plan["changes"]:
                if change["after"]:
                    result = step(change["download_id"], change["after"])
                    if _stems(result.get("active_paks", [])) != _stems(change["after"]):
                        raise ActivationError(f"Could not enable every file in {change['name']}.")
            self.refresh()
            rows = self._rows()
            disk_stems = _stems(_files(self.mods_root))
            wanted_stems = _stems([pak for paks in plan["entries"].values() for pak in paks])
            removed_stems = _stems([pak for change in plan["changes"] for pak in change["before"]]) - wanted_stems
            if removed_stems & disk_stems:
                raise ActivationError("Some disabled files could not be removed from the game folder.")
            for row in rows:
                desired = plan["entries"].get(str(row["id"]), [])
                if _stems(_list(row["active_paks"])) != _stems(desired) or not _stems(desired) <= disk_stems:
                    raise ActivationError(f"The resulting selection for {row['name']} could not be verified.")
            manifest["state"] = "committed"
            _write(folder / "journal.json", manifest)
        except Exception as error:
            try:
                self._rollback(folder, manifest)
            except Exception as rollback_error:
                manifest["state"] = "rollback_failed"
                _write(folder / "journal.json", manifest)
                raise ActivationError("Switch failed and recovery needs attention. Retry recovery before changing mods.") from rollback_error
            self._discard(folder)
            raise ActivationError(f"Switch failed; the previous files and selection were restored. {getattr(error, 'detail', str(error))}") from error
        self._discard(folder)
        return {"updated": len(plan["changes"]), "missing": 0}

    @compatibility.serialized
    def preview_keep(self, download_id, pak):
        rows = self._rows()
        entries = {str(row["id"]): _list(row["active_paks"]) for row in rows}
        selected = next((row for row in rows if row["id"] == download_id), None)
        if selected is None:
            raise ActivationError("This download is no longer installed. Refresh conflicts.")
        matches = [p for p in _list(selected["contents"]) if _base(p) == _base(pak)]
        if len(matches) != 1:
            raise ActivationError("This variant cannot be identified uniquely. Open the mod to choose its files.")
        conn = self.get_db()
        try:
            overlaps = conn.execute("SELECT DISTINCT other.pak_name FROM pak_assets chosen JOIN pak_assets other "
                                    "ON chosen.asset_path=other.asset_path WHERE chosen.pak_name=? AND other.pak_name<>?",
                                    (pak, pak)).fetchall()
        finally:
            conn.close()
        opposed = _stems([row[0] for row in overlaps])
        for key, active in entries.items():
            entries[key] = [p for p in active if os.path.splitext(_base(p))[0] not in opposed]
        entries[str(download_id)] = sorted(set(entries[str(download_id)] + matches))
        return self.preview(entries)
