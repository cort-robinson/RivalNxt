"""Integration safeguards added while porting EdwinSmayich's improvements."""
import json
import sqlite3
import zipfile

import pytest

from core.api import server
from core.backup import service


def snapshot(root, name, kind, date):
    path = service.backups_dir(root) / f"{name}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"name": name, "kind": kind, "created_at": date}))
        archive.writestr("mods.db", b"fixture")
    return path


def test_retention_never_prunes_manual_or_unknown_snapshots(tmp_path):
    manual = snapshot(tmp_path, "manual", "manual", "2025-01-01")
    unknown = snapshot(tmp_path, "unknown", "future-kind", "2025-01-02")
    old = snapshot(tmp_path, "old", "pre-restore", "2026-01-01")
    new = snapshot(tmp_path, "new", "pre-compact", "2026-02-01")
    assert service.get_retention(data_dir=tmp_path) is None
    service.set_retention(1, data_dir=tmp_path)
    assert service.get_retention(data_dir=tmp_path) == 1
    assert service.prune_backups(keep=1, data_dir=tmp_path) == [str(old)]
    assert manual.exists() and unknown.exists() and new.exists()
    service.set_retention(None, data_dir=tmp_path)
    assert service.get_retention(data_dir=tmp_path) is None


def test_restore_removes_downloads_absent_from_snapshot_but_preserves_unmanaged_files(tmp_path, monkeypatch):
    for name in ["old.pak", "old.utoc", "old.ucas", "unmanaged.pak"]:
        (tmp_path / name).write_bytes(b"fixture")
    monkeypatch.setattr(server, "_mods_folder_from_env", lambda: tmp_path)
    monkeypatch.setattr(server, "_read_active_paks", lambda: {})
    monkeypatch.setattr(server, "_read_download_paths", lambda: {})
    result = server._materialise_active_paks({7: ["old.pak"]}, {7: "old.zip"})
    assert result["failed"] == 0
    assert result["deactivated"] == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["unmanaged.pak"]


def test_restore_does_not_remove_files_still_requested_by_another_download(tmp_path, monkeypatch):
    (tmp_path / "shared.pak").write_bytes(b"fixture")
    monkeypatch.setattr(server, "_mods_folder_from_env", lambda: tmp_path)
    monkeypatch.setattr(server, "_read_active_paks", lambda: {9: ["shared.pak"]})
    monkeypatch.setattr(server, "_read_download_paths", lambda: {9: "same.zip"})
    result = server._materialise_active_paks({7: ["shared.pak"]}, {7: "same.zip"})
    assert result == {"activated": 0, "deactivated": 0, "failed": 0, "errors": []}
    assert (tmp_path / "shared.pak").exists()


@pytest.fixture
def batch_db(schema_db, monkeypatch):
    path = schema_db.execute("PRAGMA database_list").fetchone()[2]
    schema_db.execute("INSERT INTO local_downloads (id, path, name, contents, active_paks) VALUES (1, 'mod.zip', 'Example', ?, '[]')",
                      (json.dumps(["A.pak", "B.pak"]),))
    schema_db.commit()
    monkeypatch.setattr(server, "get_db", lambda: sqlite3.connect(path))
    monkeypatch.setattr(server, "_safe_rebuild_conflicts", lambda *a, **kw: None)
    monkeypatch.setattr(server, "_log_activity", lambda *a: None)
    calls = []
    monkeypatch.setattr(server, "set_active_paks", lambda i, p: calls.append((i, p)))
    return calls


def test_bulk_enable_requires_a_choice_for_inactive_variants(batch_db):
    result = server.bulk_activate_downloads(server.BulkActivatePayload(download_ids=[1], activate=True))
    assert result["needs_selection"] == [1]
    assert result["changed"] == 0
    assert batch_db == []


def test_bulk_explicit_selection_is_validated_and_ids_are_deduplicated(batch_db):
    result = server.bulk_activate_downloads(server.BulkActivatePayload(download_ids=[1, 1], activate=True, selections={1: ["B.pak"]}))
    assert result["changed"] == 1
    assert batch_db == [(1, {"active_paks": ["B.pak"], "rebuild_conflicts": False})]
    result = server.bulk_activate_downloads(server.BulkActivatePayload(download_ids=[1], activate=True, selections={1: ["unknown.pak"]}))
    assert result["failed"] == 1
    assert len(batch_db) == 1
