"""Completed updates should not require deleting retained older archives."""
import json

import pytest

from core.db.db import fetch_pak_version_status, make_version_key, replace_local_downloads
from core.update_status import apply_downloaded_update_status, record_download_file
from core.db.db import normalize_download_path


@pytest.fixture(autouse=True)
def download_root(tmp_path, monkeypatch):
    monkeypatch.setattr("core.utils.download_paths.known_download_roots", lambda: [tmp_path])


def seed(conn, tmp_path, *, name="Variant", version="2.0", file_id=None, exists=True):
    conn.execute("INSERT OR IGNORE INTO mods(mod_id, game, name) VALUES(1, 'marvelrivals', 'Mod')")
    download_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM local_downloads").fetchone()[0]
    path = tmp_path / f"archive-{download_id}.zip"
    if exists:
        path.write_bytes(b"completed archive")
    conn.execute("INSERT INTO local_downloads(id,path,name,mod_id,version,contents,nexus_file_id) VALUES(?,?,?,1,?,'[\"a.pak\"]',?)",
                 (download_id, normalize_download_path(path), name, version, file_id))
    return download_id


def remote(conn, file_id=99, name="Variant", version="2.0"):
    conn.execute("INSERT INTO mod_files(mod_id,file_id,name,version,version_key,uploaded_at) VALUES(1,?,?,?,?,?)",
                 (file_id, name, version, make_version_key(version)[0], f"2026-01-{file_id:03}"))


def old_pak(conn, tmp_path):
    old = seed(conn, tmp_path, version="1.0")
    conn.execute("INSERT INTO mod_paks(pak_name,mod_id,source_zip,local_download_id) VALUES('old.pak',1,'Variant',?)", (old,))
    remote(conn)
    return old


@pytest.mark.parametrize("file_id", [None, 99])
def test_retained_old_archive_is_satisfied_by_completed_target(schema_db, tmp_path, file_id):
    old = old_pak(schema_db, tmp_path)
    current = seed(schema_db, tmp_path, file_id=file_id)
    rows = fetch_pak_version_status(schema_db, download_ids=[old])
    assert rows[0]["needs_update"] is False
    assert rows[0]["downloaded_update_id"] == current
    assert rows[0]["version_status"] == "update_downloaded"
    assert schema_db.execute("SELECT COUNT(*) FROM local_downloads").fetchone()[0] == 2


@pytest.mark.parametrize("overrides", [
    {"name": "Other variant"}, {"version": "3.0"}, {"exists": False, "file_id": 99}, {"file_id": 98},
])
def test_unrelated_or_missing_download_does_not_satisfy_target(schema_db, tmp_path, overrides):
    old = old_pak(schema_db, tmp_path)
    seed(schema_db, tmp_path, **overrides)
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is True


def test_legacy_same_version_reupload_is_ambiguous(schema_db, tmp_path):
    old = old_pak(schema_db, tmp_path)
    remote(schema_db, file_id=98)
    seed(schema_db, tmp_path)
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is True


def test_exact_identity_survives_renaming_and_version_label_changes(schema_db, tmp_path):
    old = old_pak(schema_db, tmp_path)
    seed(schema_db, tmp_path, name="Renamed archive", version="unknown", file_id=99)
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is False


def test_zero_byte_target_does_not_clear_pending_update(schema_db, tmp_path):
    old = old_pak(schema_db, tmp_path)
    target = seed(schema_db, tmp_path, file_id=99)
    (tmp_path / f"archive-{target}.zip").write_bytes(b"")
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is True


def test_failed_ingestion_does_not_clear_pending_update(schema_db, tmp_path):
    old = old_pak(schema_db, tmp_path)
    target = seed(schema_db, tmp_path)
    schema_db.execute("UPDATE local_downloads SET contents='[]' WHERE id=?", (target,))
    assert record_download_file(schema_db, target, 1, 99) is False
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is True


def test_directory_companion_change_invalidates_exact_identity(schema_db, tmp_path):
    old = old_pak(schema_db, tmp_path)
    target = seed(schema_db, tmp_path, name="Renamed folder")
    folder = tmp_path / "extracted"
    folder.mkdir()
    (folder / "a.pak").write_bytes(b"pak")
    (folder / "a.ucas").write_bytes(b"companion")
    schema_db.execute("UPDATE local_downloads SET path=? WHERE id=?", (str(folder), target))
    assert record_download_file(schema_db, target, 1, 99)
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is False
    (folder / "a.ucas").write_bytes(b"changed companion bytes")
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is True


def test_file_identity_is_scoped_to_mod(schema_db, tmp_path):
    old = old_pak(schema_db, tmp_path)
    target = seed(schema_db, tmp_path, file_id=99)
    schema_db.execute("INSERT INTO mods(mod_id,game) VALUES(2,'marvelrivals')")
    schema_db.execute("UPDATE local_downloads SET mod_id=2 WHERE id=?", (target,))
    assert fetch_pak_version_status(schema_db, download_ids=[old])[0]["needs_update"] is True


@pytest.mark.parametrize("updates", [
    [{"old_file_id": 80, "new_file_id": 90}, {"old_file_id": 80, "new_file_id": 99}],
    [{"old_file_id": 80, "new_file_id": 90}, {"old_file_id": 90, "new_file_id": 80}],
])
def test_ambiguous_replacement_lineage_does_not_guess(schema_db, tmp_path, updates):
    old = seed(schema_db, tmp_path, file_id=80)
    remote(schema_db, 80)
    remote(schema_db, 90, "Variant B")
    remote(schema_db, 99, "Variant C")
    schema_db.execute("INSERT INTO mod_api_cache VALUES(1,'now',?)", (json.dumps({"files": {"file_updates": updates}}),))
    row = {"id": old, "mod_id": 1, "latest_file_id": 80, "needs_update": False}
    apply_downloaded_update_status(schema_db, [row])
    assert row["latest_file_id"] == 80
    assert row["needs_update"] is False


def test_explicit_replacement_chain_handles_renamed_same_version_updates(schema_db, tmp_path):
    old = seed(schema_db, tmp_path, file_id=80)
    remote(schema_db, 80)
    remote(schema_db, 90, "Renamed")
    remote(schema_db, 99, "Final name")
    payload = {"files": {"file_updates": [{"old_file_id": 80, "new_file_id": 90}, {"old_file_id": 90, "new_file_id": 99}]}}
    schema_db.execute("INSERT INTO mod_api_cache VALUES(1,'now',?)", (json.dumps(payload),))
    row = {"id": old, "mod_id": 1, "latest_file_id": 80, "needs_update": False}
    apply_downloaded_update_status(schema_db, [row])
    assert row["needs_update"] is True
    assert row["latest_file_id"] == 99
    seed(schema_db, tmp_path, name="Final name", file_id=99)
    apply_downloaded_update_status(schema_db, [row])
    assert row["needs_update"] is False


def test_record_identity_checks_association_and_manual_rescan_clears_it(schema_db, tmp_path):
    download_id = seed(schema_db, tmp_path)
    assert record_download_file(schema_db, download_id, 2, 99) is False
    assert record_download_file(schema_db, download_id, 1, 99) is True
    path = schema_db.execute("SELECT path FROM local_downloads WHERE id=?", (download_id,)).fetchone()[0]
    replace_local_downloads(schema_db, [{"path": path, "id": download_id, "name": "Variant", "mod_id": 1, "version": "3.0"}])
    assert schema_db.execute("SELECT nexus_file_id FROM local_downloads WHERE id=?", (download_id,)).fetchone()[0] is None


def test_unchanged_rescan_preserves_identity_but_replaced_archive_invalidates_it(schema_db, tmp_path):
    download_id = seed(schema_db, tmp_path)
    assert record_download_file(schema_db, download_id, 1, 99)
    path = schema_db.execute("SELECT path FROM local_downloads WHERE id=?", (download_id,)).fetchone()[0]
    row = {"path": path, "id": download_id, "name": "Variant", "mod_id": 1, "version": "2.0", "contents": ["a.pak"]}
    replace_local_downloads(schema_db, [row])
    assert schema_db.execute("SELECT nexus_file_id FROM local_downloads WHERE id=?", (download_id,)).fetchone()[0] == 99
    (tmp_path / path).write_bytes(b"replacement content changed")
    replace_local_downloads(schema_db, [row])
    assert schema_db.execute("SELECT nexus_file_id FROM local_downloads WHERE id=?", (download_id,)).fetchone()[0] is None


def test_list_and_detail_use_same_completed_target_status(schema_db, tmp_path, monkeypatch):
    import core.api.server as server

    old = old_pak(schema_db, tmp_path)
    seed(schema_db, tmp_path, file_id=99)
    class NoClose:
        def __getattr__(self, name):
            return getattr(schema_db, name)
        def close(self):
            pass
    monkeypatch.setattr(server, "get_db", NoClose)
    monkeypatch.setattr(server, "_get_actually_active_filenames", lambda logger: None)
    listed = next(row for row in server.list_downloads() if row["id"] == old)
    detailed = server.get_local_download(old)
    assert listed["needs_update"] is False
    assert detailed["needs_update"] is False
    assert listed["downloaded_update_id"] == detailed["downloaded_update_id"]


def test_check_update_includes_unindexed_archives_and_clears_completed_target(schema_db, tmp_path, monkeypatch):
    from types import SimpleNamespace
    import core.api.server as server

    old = seed(schema_db, tmp_path, version="1.0")
    remote(schema_db)
    class NoClose:
        def __getattr__(self, name):
            return getattr(schema_db, name)
        def close(self):
            pass
    monkeypatch.setattr(server, "get_db", NoClose)
    monkeypatch.setattr(server, "_sync_mod_metadata", lambda *args, **kwargs: {})
    monkeypatch.setattr(server, "_get_current_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    result = server._check_mod_update(1)
    assert result["checked_download_ids"] == [old]
    assert result["needs_update"] is True
    assert result["pending"][0]["reference_file_id"] == 99
    current = seed(schema_db, tmp_path, file_id=99)
    result = server._check_mod_update(1)
    assert result["checked_download_ids"] == [old, current]
    assert result["pending"] == []
    assert result["needs_update"] is False


def test_check_update_deduplicates_paks_for_same_archive_target(schema_db, tmp_path, monkeypatch):
    from types import SimpleNamespace
    import core.api.server as server

    old = old_pak(schema_db, tmp_path)
    schema_db.execute("INSERT INTO mod_paks(pak_name,mod_id,source_zip,local_download_id) VALUES('second.pak',1,'Variant',?)", (old,))
    class NoClose:
        def __getattr__(self, name):
            return getattr(schema_db, name)
        def close(self):
            pass
    monkeypatch.setattr(server, "get_db", NoClose)
    monkeypatch.setattr(server, "_sync_mod_metadata", lambda *args, **kwargs: {})
    monkeypatch.setattr(server, "_get_current_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    assert len(server._check_mod_update(1)["pending"]) == 1
