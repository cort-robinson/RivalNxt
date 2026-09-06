"""Resolve downloaded update targets without deleting retained older archives."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from core.utils.download_paths import resolve_absolute_download_path


def record_download_file(conn, download_id: int, mod_id: int, file_id: int) -> bool:
    """Record a successfully ingested file identity; the caller commits."""
    if not all(isinstance(value, int) and value > 0 for value in (download_id, mod_id, file_id)):
        return False
    row = conn.execute("SELECT path, contents FROM local_downloads WHERE id = ? AND mod_id = ?", (download_id, mod_id)).fetchone()
    if not row or not _source_exists(*row):
        return False
    return conn.execute(
        "UPDATE local_downloads SET nexus_file_id = ?, nexus_file_fingerprint = ? WHERE id = ? AND mod_id = ?",
        (file_id, download_source_fingerprint(*row), download_id, mod_id),
    ).rowcount == 1


def download_source_fingerprint(path: str, contents: str | None = None) -> str | None:
    """Cheap archive identity for preserving provenance on unchanged rescans."""
    try:
        source = resolve_absolute_download_path(path)
        if source.is_file():
            stat = source.stat()
            return f"{stat.st_size}:{stat.st_mtime_ns}"
        if source.is_dir():
            entries = json.loads(contents or "[]")
            if not isinstance(entries, list) or not entries:
                return None
            root = source.resolve()
            files = set()
            for entry in entries:
                if not isinstance(entry, str):
                    return None
                file = (root / entry).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    return None
                files.add(file)
                for suffix in (".pak", ".utoc", ".ucas", ".sig"):
                    companion = file.with_suffix(suffix)
                    if companion.is_file():
                        files.add(companion)
            records = []
            for file in sorted(files):
                stat = file.stat()
                records.append((str(file.relative_to(root)), stat.st_size, stat.st_mtime_ns))
            return "directory:" + hashlib.sha256(json.dumps(records).encode()).hexdigest()
    except (OSError, ValueError, TypeError):
        pass
    return None


def _name_key(value: Any) -> str:
    return str(value or "").lower().replace(" ", "").replace("-", "").replace("_", "")


def _source_exists(path: str, contents: str | None) -> bool:
    if not path:
        return False
    try:
        source = resolve_absolute_download_path(path)
        entries = json.loads(contents or "[]")
        if not isinstance(entries, list) or not any(
            isinstance(entry, str) and entry.lower().endswith((".pak", ".utoc")) for entry in entries
        ):
            return False
        if source.is_file():
            return source.stat().st_size > 0
        return source.is_dir() and isinstance(entries, list) and bool(entries) and all(
            isinstance(entry, str) and (source / entry).resolve().is_relative_to(source.resolve())
            and (source / entry).is_file() for entry in entries
        )
    except (OSError, ValueError, TypeError):
        return False


def fetch_download_version_status(conn, mod_id: int) -> list[dict[str, Any]]:
    """Check one mod's archives even before its PAK index has been populated."""
    from core.db.db import make_version_key, versions_equivalent

    cursor = conn.execute(
        """WITH ranked_files AS (
            SELECT file_id, name, version,
                ROW_NUMBER() OVER (
                    PARTITION BY REPLACE(REPLACE(REPLACE(LOWER(name), ' ', ''), '-', ''), '_', '')
                    ORDER BY uploaded_at DESC, file_id DESC
                ) AS rank
            FROM mod_files WHERE mod_id = ?
        )
        SELECT l.id AS local_download_id, l.mod_id, l.name AS local_file_name,
            l.version AS local_version, l.path AS local_path,
            f.file_id AS reference_file_id, f.version AS reference_version
        FROM local_downloads l
        LEFT JOIN ranked_files f ON f.rank = 1
            AND REPLACE(REPLACE(REPLACE(LOWER(f.name), ' ', ''), '-', ''), '_', '')
                = REPLACE(REPLACE(REPLACE(LOWER(l.name), ' ', ''), '-', ''), '_', '')
        WHERE l.mod_id = ? ORDER BY l.id""",
        (mod_id, mod_id),
    )
    columns = [column[0] for column in cursor.description]
    rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
    for row in rows:
        local, remote = row["local_version"], row["reference_version"]
        row["display_version"] = local
        row["version_status"] = "missing_remote_version" if not remote else "match"
        row["needs_update"] = False
        if local and remote and not versions_equivalent(local, remote):
            local_key, remote_key = make_version_key(local)[0], make_version_key(remote)[0]
            row["needs_update"] = not (local_key and remote_key and local_key >= remote_key)
            row["version_status"] = "mismatch" if row["needs_update"] else "local_newer_or_equal"
    apply_downloaded_update_status(conn, rows)
    return rows


def apply_downloaded_update_status(conn, rows: list[dict[str, Any]]) -> None:
    """Use exact file identity, then unambiguous legacy name/version evidence.

    Supports both per-PAK status rows and download list/detail rows. An old
    archive stays in the library, but stops requesting a target already present.
    Merely having a higher version of another variant never satisfies a target.
    """
    from core.db.db import versions_equivalent

    mod_ids = sorted({row.get("mod_id") for row in rows if isinstance(row.get("mod_id"), int)})
    if not mod_ids:
        return
    placeholders = ",".join("?" for _ in mod_ids)
    downloads = conn.execute(
        f"SELECT id, mod_id, nexus_file_id, name, version, path, contents, nexus_file_fingerprint FROM local_downloads WHERE mod_id IN ({placeholders})",
        mod_ids,
    ).fetchall()
    files = conn.execute(
        f"SELECT mod_id, file_id, name, version, uploaded_at, version_key FROM mod_files WHERE mod_id IN ({placeholders})",
        mod_ids,
    ).fetchall()
    files_by_id = {(file[0], file[1]): file for file in files}
    files_by_name: dict[tuple[int, str], list] = {}
    for file in files:
        files_by_name.setdefault((file[0], _name_key(file[2])), []).append(file)
    downloads_by_id = {download[0]: download for download in downloads}
    available: dict[tuple[int, int], int] = {}
    for download_id, mod_id, file_id, name, version, path, contents, fingerprint in downloads:
        if not _source_exists(path, contents):
            continue
        if file_id is not None:
            if fingerprint and fingerprint != download_source_fingerprint(path, contents):
                continue
            available[(mod_id, file_id)] = download_id
            continue
        # Legacy records have no file ID. Only infer one when metadata names
        # and versions identify exactly one file, including archived entries.
        candidates = [file for file in files_by_name.get((mod_id, _name_key(name)), [])
                      if versions_equivalent(version, file[3])]
        if len(candidates) == 1:
            available[(mod_id, candidates[0][1])] = download_id

    replacements: dict[tuple[int, int], set[int]] = {}
    for mod_id, payload in conn.execute(
        f"SELECT mod_id, payload FROM mod_api_cache WHERE mod_id IN ({placeholders})", mod_ids
    ):
        try:
            metadata = json.loads(payload)
            listing = metadata.get("files", {})
            updates = listing.get("file_updates", []) if isinstance(listing, dict) else []
            for update in updates:
                old, new = update.get("old_file_id"), update.get("new_file_id")
                if isinstance(old, int) and isinstance(new, int) and old != new:
                    replacements.setdefault((mod_id, old), set()).add(new)
        except (ValueError, TypeError, AttributeError):
            continue

    for row in rows:
        pak_row = "local_download_id" in row
        download_id = row.get("local_download_id") if pak_row else row.get("id")
        local = downloads_by_id.get(download_id)
        if local is None:
            continue
        mod_id, local_file_id = local[1], local[2]
        file_key = "reference_file_id" if pak_row else "latest_file_id"
        version_key = "reference_version" if pak_row else "latest_version"
        target_id = row.get(file_key)
        # Nexus's explicit replacement chain also covers renamed files and
        # same-version reuploads. A branch/cycle is ambiguous, so do not guess.
        successor = local_file_id
        visited: set[int] = set()
        while successor is not None and successor not in visited:
            visited.add(successor)
            next_ids = replacements.get((mod_id, successor), set())
            if len(next_ids) != 1:
                break
            successor = next(iter(next_ids))
        terminal = files_by_id.get((mod_id, successor))
        if terminal and successor != local_file_id and not replacements.get((mod_id, successor)):
            target_id = successor
            row[file_key] = target_id
            row[version_key] = terminal[3]
            row["needs_update"] = True
            if pak_row:
                row["version_status"] = "replacement_available"
            else:
                row["latest_file_name"], row["latest_uploaded_at"], row["latest_version_key"] = terminal[2], terminal[4], terminal[5]
        satisfied_by = available.get((mod_id, target_id))
        if satisfied_by is not None:
            row["needs_update"] = False
            if satisfied_by != download_id:
                row["downloaded_update_id"] = satisfied_by
                if pak_row:
                    row["version_status"] = "update_downloaded"
