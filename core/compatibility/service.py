"""Verified staging, durable backups and guarded restore for PAK metadata repair."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
from functools import wraps
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from .pak import PakError, inspect

# Shared by activation, deactivation, repair and restore routes in this process.
mutation_lock = threading.RLock()
_mutation_guard = None
_recovery_operation = ContextVar("recovery_operation", default=False)


def configure_mutation_guard(callback):
    global _mutation_guard
    _mutation_guard = callback


def guarded_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with mutation_lock:
            if _mutation_guard is not None and not _recovery_operation.get():
                _mutation_guard()
            return function(*args, **kwargs)
    return wrapped


def recovery_operation(function):
    """Only an explicitly invoked transaction may mutate its pending journal."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _recovery_operation.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _recovery_operation.reset(token)
    return wrapped


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with mutation_lock:
            return function(*args, **kwargs)
    return wrapped


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def safe_path(root, relative):
    root = Path(root).absolute()
    target = root / relative
    if target.is_absolute() and not target.is_relative_to(root):
        raise PakError("Path is outside the mod folder")
    if ".." in Path(relative).parts:
        raise PakError("Parent paths are not allowed")
    for part in (target, *target.parents):
        reparse = bool(getattr(part.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) if part.exists() else False
        if part.is_symlink() or reparse:
            raise PakError("Linked folders and files are not supported")
    if not target.resolve().is_relative_to(root.resolve()):
        raise PakError("Path is outside the mod folder")
    return target


def worker():
    name = "rivalnxt-pak-repair" + (".exe" if os.name == "nt" else "")
    if getattr(sys, "frozen", False):
        path = Path(sys._MEIPASS) / "pak-repair" / name
    else:
        path = Path(__file__).resolve().parents[2] / "tools/pak-repair/target/release" / name
    if not path.is_file():
        raise PakError("Repair worker is missing. Build tools/pak-repair or reinstall RivalNxt.")
    return path


def repair_copy(source, output):
    before = inspect(source)
    subprocess.run([str(worker()), str(source), str(output)], check=True,
                   capture_output=True, timeout=180,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    after = inspect(output)
    expected = {name: value for name, value in before.entries.items() if name not in before.removed}
    if after.entries != expected or after.mount != before.mount or after.offset != before.offset:
        raise PakError("Repair changed a retained entry")
    with source.open("rb") as original, output.open("rb") as repaired:
        remaining = before.offset
        while remaining:
            size = min(remaining, 1024 * 1024)
            if original.read(size) != repaired.read(size):
                raise PakError("Repair changed package data")
            remaining -= size
    return before.removed


def describe(path):
    index = inspect(path)
    actual = [name for name in index.entries if name not in index.removed]
    flags = set()
    for name in actual:
        value = name.lower()
        if "wwise" in value or value.endswith((".bnk", ".wem")):
            flags.add("audio")
        if "/vfx/" in value:
            flags.add("VFX")
        if value.endswith(".bk2"):
            flags.add("movie")
        if "/config/" in value or value.endswith(".ini"):
            flags.add("config")
        if "camerashake" in value:
            flags.add("camera shake")
        if not value.startswith("../../../marvel/content/marvel/characters/"):
            flags.add("other content")
    utoc, ucas = path.with_suffix(".utoc"), path.with_suffix(".ucas")
    for companion in (utoc, ucas):
        safe_path(path.parent, companion.name)
    if utoc.exists() != ucas.exists():
        raise PakError("An IoStore companion is missing")
    if utoc.exists():
        flags.add("IoStore assets not checked")
    return {"archive": "repair_needed" if index.removed else "checked",
            "removed_entries": index.removed, "content_notes": sorted(flags),
            "game_compatibility": "unknown"}


def scan(root):
    root = Path(root)
    results = []
    if not root.exists():
        return results
    safe_path(root, ".")
    # Only the explicit ~mods root is supplied by the route. Never scan game PAKs.
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in (".pak", ".utoc", ".ucas"):
            continue
        relative = str(path.relative_to(root))
        try:
            path = safe_path(root, relative)
            if not path.is_file():
                continue
            if path.suffix.lower() != ".pak":
                if path.with_suffix(".pak").exists():
                    continue
                raise PakError("Companion has no matching PAK")
            row = describe(path)
        except (OSError, ValueError) as error:
            row = {"archive": "blocked", "error": str(error), "game_compatibility": "unknown"}
        results.append({"path": relative, **row})
    return results


def write_manifest(folder, manifest):
    temp = folder / "manifest.tmp"
    with temp.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, folder / "manifest.json")


def verified_copy(source, target):
    expected = digest(source)
    shutil.copyfile(source, target)
    if digest(target) != expected or digest(source) != expected:
        raise PakError("File changed during copy")
    with target.open("r+b") as file:
        os.fsync(file.fileno())
    shutil.copystat(source, target)
    return expected


def replace_copy(source, target):
    """Stage on the destination volume, then replace in one filesystem operation."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".rivalnxt-", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temp = Path(name)
    try:
        expected = verified_copy(source, temp)
        os.replace(temp, target)
        if digest(target) != expected:
            raise PakError("Replacement hash check failed")
    finally:
        temp.unlink(missing_ok=True)


def publish(root, replacements, backup_root, originals=None, expected_before=None, guards=None):
    """A journal survives partial failure or process exit. Restore checks hashes.

    Each entry is recorded before mutation. An interrupted entry can have either
    the before or after hash; anything else blocks restore instead of overwriting.
    """
    root, backup_root = Path(root), Path(backup_root)
    if backup_root.resolve().is_relative_to(root.resolve()):
        raise PakError("Backups must be outside the mod folder")
    backup_root.mkdir(parents=True, exist_ok=True)
    safe_path(backup_root, ".")
    folder = backup_root / uuid.uuid4().hex
    folder.mkdir()
    manifest = {"version": 1, "root": str(root.resolve()), "state": "prepared", "files": [],
                "created_at": datetime.now(timezone.utc).isoformat(), "guards": guards or {}}
    try:
        for i, (relative, staged) in enumerate(replacements.items()):
            target = safe_path(root, relative)
            before = verified_copy(target, folder / f"{i}.bak") if target.exists() else None
            if expected_before is not None and before != expected_before.get(relative):
                raise PakError("Source changed before backup")
            manifest["files"].append({"path": relative, "before": before, "after": digest(staged), "backup": f"{i}.bak"})
        # Imported source PAKs remain recoverable even on a first installation.
        manifest["sources"] = []
        if originals:
            for i, (relative, source) in enumerate(originals):
                filename = f"source-{i}.pak"
                value = verified_copy(source, folder / filename)
                manifest["sources"].append({"path": relative, "backup": filename, "sha256": value})
        write_manifest(folder, manifest)
        for relative, expected in manifest["guards"].items():
            if digest(safe_path(root, relative)) != expected:
                raise PakError("Companion changed before replacement")
        for item in manifest["files"]:
            target = safe_path(root, item["path"])
            if (digest(target) if target.exists() else None) != item["before"]:
                raise PakError("Destination changed before replacement")
            replace_copy(replacements[item["path"]], target)
        manifest["state"] = "complete"
        write_manifest(folder, manifest)
    except Exception:
        if (folder / "manifest.json").exists():
            restore(root, backup_root, folder.name)
        raise
    return folder.name


def restore(root, backup_root, backup_id):
    if len(backup_id) != 32 or any(c not in "0123456789abcdef" for c in backup_id):
        raise PakError("Invalid backup ID")
    folder = safe_path(backup_root, backup_id)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1 or manifest["root"] != str(Path(root).resolve()):
        raise PakError("Backup belongs to another mod folder")
    for relative, expected in manifest.get("guards", {}).items():
        if digest(safe_path(root, relative)) != expected:
            raise PakError("A later companion change prevents restore")
    # Check every file before the first mutation.
    for item in manifest["files"]:
        target = safe_path(root, item["path"])
        current = digest(target) if target.exists() else None
        if current not in (item["before"], item["after"]):
            raise PakError("A later file change prevents restore")
        if item["before"] and digest(safe_path(folder, item["backup"])) != item["before"]:
            raise PakError("Backup hash check failed")
    for item in reversed(manifest["files"]):
        target = safe_path(root, item["path"])
        if item["before"]:
            replace_copy(safe_path(folder, item["backup"]), target)
        else:
            target.unlink(missing_ok=True)
    manifest["state"] = "restored"
    write_manifest(folder, manifest)
    return {"backup_id": backup_id, "state": "restored"}


def backups(root, backup_root):
    results = []
    for path in sorted(Path(backup_root).glob("*/manifest.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["root"] == str(Path(root).resolve()):
                results.append({"id": path.parent.name, "state": data["state"], "files": len(data["files"]),
                                "created_at": data.get("created_at", "")})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(results, key=lambda row: row["created_at"], reverse=True)


def repair_installed(root, backup_root):
    results = scan(root)
    for row in results:
        if row["archive"] != "repair_needed":
            continue
        try:
            source = safe_path(root, row["path"])
            before = digest(source)
            companions = {ext: digest(source.with_suffix(ext)) for ext in (".utoc", ".ucas") if source.with_suffix(ext).exists()}
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "repaired.pak"
                repair_copy(source, output)
                if digest(source) != before or any(digest(source.with_suffix(ext)) != value for ext, value in companions.items()):
                    raise PakError("Package changed during repair")
                row["backup_id"] = publish(root, {row["path"]: output}, backup_root,
                                           expected_before={row["path"]: before},
                                           guards={str(source.with_suffix(ext).relative_to(root)): value for ext, value in companions.items()})
            row["archive"] = "repaired"
        except Exception as error:
            row["archive"] = "failed"
            row["error"] = str(error)
    return results


def install_staged(staging, destination, backup_root, root=None):
    """Validate all files and repair PAK copies before any destination is changed."""
    rows = scan(staging)
    if any(row["archive"] == "blocked" for row in rows):
        raise PakError("Package check failed: " + "; ".join(row.get("error", "") for row in rows if row["archive"] == "blocked"))
    for row in rows:
        for ext in (".utoc", ".ucas"):
            relative = Path(row["path"]).with_suffix(ext)
            if safe_path(destination, relative).exists() and not safe_path(staging, relative).exists():
                raise PakError("The new package omits an installed companion. Keep the previous package or disable it first.")
    originals = []
    with tempfile.TemporaryDirectory() as temp:
        for row in rows:
            if row["archive"] == "repair_needed":
                path = safe_path(staging, row["path"])
                original = Path(temp) / f"{len(originals)}.pak"
                verified_copy(path, original)
                originals.append((row["path"], original))
                output = Path(temp) / f"{len(originals)}-repaired.pak"
                repair_copy(path, output)
                replace_copy(output, path)
                row["archive"] = "repaired"
        root = Path(root) if root is not None else Path(destination)
        prefix = Path(destination).relative_to(root)
        replacements = {str(prefix / path.relative_to(staging)): path for path in Path(staging).rglob("*") if path.is_file()}
        backup_id = publish(root, replacements, backup_root, originals) if replacements else None
    return {"results": rows, "backup_id": backup_id, "game_compatibility": "unknown"}
