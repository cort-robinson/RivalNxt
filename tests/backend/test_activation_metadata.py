"""Legacy backup metadata and mod files commit or roll back together."""
import copy
import json
import sqlite3

import pytest

from core.activation import ActivationError, ActivationService
from core.db.db import init_schema, run_migrations
from test_set_active_paks import activation_env as activation_env


PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
       "/x8AAwMCAO+j2ioAAAAASUVORK5CYII=")
TABLES = ("mods", "mod_custom_tags", "mod_custom_images", "custom_authors", "local_mod_metadata")


@pytest.fixture
def metadata_env(tmp_path):
    database = tmp_path / "isolated.db"
    root = tmp_path / "game-mods"
    root.mkdir()
    (root / "old.pak").write_bytes(b"original package")
    (root / "notes.txt").write_bytes(b"unmanaged")

    def get_db():
        conn = sqlite3.connect(database)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    init_schema(conn)
    run_migrations(conn)
    for key, pak, active in ((1, "old.pak", ["old.pak"]), (2, "new.pak", [])):
        source = tmp_path / f"source-{key}.zip"
        source.write_bytes(b"synthetic archive")
        conn.execute(
            "INSERT INTO local_downloads(id,path,name,contents,active_paks,last_activated_at) "
            "VALUES (?,?,?,?,?,?)",
            (key, str(source), f"Local {key}", json.dumps([pak]), json.dumps(active), "before"))
    conn.execute("INSERT INTO mods(mod_id,game,name,description_bbcode) VALUES(-1,'marvelrivals','Local 1','original description')")
    conn.execute("INSERT INTO mod_custom_tags(mod_id,tag) VALUES(-1,'existing tag')")
    conn.commit()
    conn.close()

    def activate(key, payload):
        conn = get_db()
        previous = json.loads(conn.execute("SELECT active_paks FROM local_downloads WHERE id=?", (key,)).fetchone()[0])
        for pak in previous:
            (root / pak).unlink(missing_ok=True)
        for pak in payload["active_paks"]:
            (root / pak).write_bytes(b"replacement package")
        conn.execute("UPDATE local_downloads SET active_paks=?,last_activated_at='after' WHERE id=?",
                     (json.dumps(payload["active_paks"]), key))
        conn.commit()
        conn.close()
        return {"active_paks": payload["active_paks"]}

    return ActivationService(get_db, root, tmp_path / "journals", activate, lambda: None), root


def metadata():
    return [
        {"mod_id": -1, "description": "restored old description"},
        {"mod_id": -2, "description": "restored new description", "custom_tags": ["Costume", "Favorite"],
         "custom_images": [{"data": PNG, "filename": "cover.png", "mimeType": "image/png"}],
         "author": {"name": "Backup Author", "author_type": "custom", "avatar": f"data:image/png;base64,{PNG}"}},
    ]


def database_state(service):
    conn = service.get_db()
    try:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in TABLES}
    finally:
        conn.close()


def assert_original_files(root):
    assert (root / "old.pak").read_bytes() == b"original package"
    assert not (root / "new.pak").exists()
    assert (root / "notes.txt").read_bytes() == b"unmanaged"


def test_metadata_restore_commits_all_fields_with_file_selection(metadata_env):
    service, root = metadata_env
    payload = metadata()
    plan = service.preview({"2": ["new.pak"]}, metadata=payload)
    service.apply(plan["entries"], plan["token"], metadata=payload)
    assert not (root / "old.pak").exists()
    assert (root / "new.pak").read_bytes() == b"replacement package"
    conn = service.get_db()
    try:
        assert conn.execute("SELECT description_bbcode FROM mods WHERE mod_id=-1").fetchone()[0] == "restored old description"
        assert conn.execute("SELECT description_bbcode FROM mods WHERE mod_id=-2").fetchone()[0] == "restored new description"
        assert set(conn.execute("SELECT tag FROM mod_custom_tags WHERE mod_id=-2").fetchall()) == {("Costume",), ("Favorite",)}
        assert conn.execute("SELECT filename,mime_type FROM mod_custom_images WHERE mod_id=-2").fetchall() == [("cover.png", "image/png")]
        author = conn.execute("SELECT a.display_name,a.author_type,a.avatar_base64 FROM custom_authors a "
                              "JOIN local_mod_metadata m ON m.custom_author_id=a.id WHERE m.mod_key='local:2'").fetchone()
        assert author == ("Backup Author", "custom", f"data:image/png;base64,{PNG}")
    finally:
        conn.close()
    assert not service.pending_recovery()


def test_repeated_restore_deduplicates_images_tags_and_authors(metadata_env):
    service, _ = metadata_env
    payload = metadata()
    for _ in range(2):
        plan = service.preview({"2": ["new.pak"]}, metadata=payload)
        service.apply(plan["entries"], plan["token"], metadata=payload)
    conn = service.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM mod_custom_images WHERE mod_id=-2").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mod_custom_tags WHERE mod_id=-2").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM custom_authors").fetchone()[0] == 1
        assert conn.execute("SELECT tag FROM mod_custom_tags WHERE mod_id=-1").fetchall() == [("existing tag",)]
    finally:
        conn.close()


def test_metadata_restores_even_when_file_selection_already_matches(metadata_env):
    service, root = metadata_env
    payload = [{"mod_id": -1, "description": "metadata-only restore"}]
    plan = service.preview({"1": ["old.pak"]}, metadata=payload)
    assert plan["changes"] == []
    service.apply(plan["entries"], plan["token"], metadata=payload)
    assert_original_files(root)
    conn = service.get_db()
    try:
        assert conn.execute("SELECT description_bbcode FROM mods WHERE mod_id=-1").fetchone()[0] == "metadata-only restore"
    finally:
        conn.close()


@pytest.mark.parametrize("payload", [
    [{"mod_id": -2, "custom_images": [{"data": "not valid base64!"}]}],
    [{"mod_id": 99999, "description": "missing target"}],
])
def test_invalid_metadata_rejected_before_any_file_or_database_change(metadata_env, payload):
    service, root = metadata_env
    before = database_state(service)
    with pytest.raises(ActivationError):
        plan = service.preview({"2": ["new.pak"]}, metadata=payload)
        service.apply(plan["entries"], plan["token"], metadata=payload)
    assert_original_files(root)
    assert database_state(service) == before


def test_changed_metadata_invalidates_preview_before_file_changes(metadata_env):
    service, root = metadata_env
    payload = metadata()
    plan = service.preview({"2": ["new.pak"]}, metadata=payload)
    conn = service.get_db()
    conn.execute("UPDATE mods SET description_bbcode='edited after preview' WHERE mod_id=-1")
    conn.commit()
    conn.close()
    before = database_state(service)
    with pytest.raises(ActivationError, match="fresh preview"):
        service.apply(plan["entries"], plan["token"], metadata=payload)
    assert_original_files(root)
    assert database_state(service) == before


def test_tampered_metadata_payload_invalidates_preview(metadata_env):
    service, root = metadata_env
    payload = metadata()
    plan = service.preview({"2": ["new.pak"]}, metadata=payload)
    tampered = copy.deepcopy(payload)
    tampered[1]["description"] = "not reviewed"
    with pytest.raises(ActivationError, match="fresh preview"):
        service.apply(plan["entries"], plan["token"], metadata=tampered)
    assert_original_files(root)


def test_metadata_edit_during_activation_preserved_while_files_roll_back(metadata_env):
    service, root = metadata_env
    selection_before = service._rows()
    original_activate = service.activate

    def edit_during_activation(key, payload):
        result = original_activate(key, payload)
        if key == 2:
            conn = service.get_db()
            conn.execute("UPDATE mods SET description_bbcode='concurrent edit' WHERE mod_id=-1")
            conn.commit()
            conn.close()
        return result

    payload = metadata()
    plan = service.preview({"2": ["new.pak"]}, metadata=payload)
    service.activate = edit_during_activation
    with pytest.raises(ActivationError, match="fresh preview"):
        service.apply(plan["entries"], plan["token"], metadata=payload)
    assert_original_files(root)
    assert service._rows() == selection_before
    conn = service.get_db()
    try:
        assert conn.execute("SELECT description_bbcode FROM mods WHERE mod_id=-1").fetchone()[0] == "concurrent edit"
        assert conn.execute("SELECT 1 FROM mods WHERE mod_id=-2").fetchone() is None
    finally:
        conn.close()


def test_activation_routes_forward_metadata_through_preview_and_apply(metadata_env, monkeypatch):
    from core.api import activation as routes

    service, root = metadata_env
    monkeypatch.setattr(routes, "service", lambda: service)
    payload = {"entries": {"2": ["new.pak"]}, "metadata": metadata()}
    plan = routes.preview(payload)
    routes.apply({**payload, "token": plan["token"]})
    assert (root / "new.pak").read_bytes() == b"replacement package"
    conn = service.get_db()
    try:
        assert conn.execute("SELECT description_bbcode FROM mods WHERE mod_id=-2").fetchone()[0] == "restored new description"
    finally:
        conn.close()


def test_metadata_failure_rolls_back_files_selection_and_placeholder(metadata_env, monkeypatch):
    from core import activation_metadata

    service, root = metadata_env
    before = database_state(service)
    selection_before = service._rows()
    original = activation_metadata.apply

    def fail_after_writes(conn, payload):
        original(conn, payload)
        assert conn.execute("SELECT 1 FROM mods WHERE mod_id=-2").fetchone()
        raise OSError("metadata storage failure")

    monkeypatch.setattr(activation_metadata, "apply", fail_after_writes)
    payload = metadata()
    plan = service.preview({"2": ["new.pak"]}, metadata=payload)
    with pytest.raises(ActivationError, match="restored"):
        service.apply(plan["entries"], plan["token"], metadata=payload)
    assert_original_files(root)
    assert service._rows() == selection_before
    assert database_state(service) == before
    assert not service.pending_recovery()


def test_recovery_after_database_commit_preserves_completed_restore(metadata_env, monkeypatch):
    from core import activation

    class SimulatedProcessExit(BaseException):
        pass

    service, root = metadata_env
    original_write = activation._write

    def crash_before_committed_journal(path, manifest):
        if manifest["state"] == "committed":
            raise SimulatedProcessExit()
        original_write(path, manifest)

    payload = metadata()
    plan = service.preview({"2": ["new.pak"]}, metadata=payload)
    with monkeypatch.context() as patch:
        patch.setattr(activation, "_write", crash_before_committed_journal)
        with pytest.raises(SimulatedProcessExit):
            service.apply(plan["entries"], plan["token"], metadata=payload)
    after_commit = database_state(service)
    selection = service._rows()
    assert service.pending_recovery()
    restarted = ActivationService(service.get_db, root, service.journal_root, service.activate, lambda: None)
    restarted.recover()
    assert database_state(service) == after_commit
    assert restarted._rows() == selection
    assert not (root / "old.pak").exists()
    assert (root / "new.pak").read_bytes() == b"replacement package"
    assert not restarted.pending_recovery()


def test_recovery_before_database_commit_restores_previous_files_and_metadata(metadata_env, monkeypatch):
    from core import activation_metadata

    class SimulatedProcessExit(BaseException):
        pass

    service, root = metadata_env
    before = database_state(service)
    selection_before = service._rows()
    original_apply = activation_metadata.apply

    def crash_after_uncommitted_writes(conn, payload):
        original_apply(conn, payload)
        raise SimulatedProcessExit()

    payload = metadata()
    plan = service.preview({"2": ["new.pak"]}, metadata=payload)
    with monkeypatch.context() as patch:
        patch.setattr(activation_metadata, "apply", crash_after_uncommitted_writes)
        with pytest.raises(SimulatedProcessExit):
            service.apply(plan["entries"], plan["token"], metadata=payload)
    assert service.pending_recovery()
    restarted = ActivationService(service.get_db, root, service.journal_root, service.activate, lambda: None)
    restarted.recover()
    assert database_state(service) == before
    assert restarted._rows() == selection_before
    assert_original_files(root)
    assert not restarted.pending_recovery()


def test_real_archive_activation_restores_metadata_in_same_operation(activation_env, tmp_path):
    from core.api import server

    service = ActivationService(server.get_db, activation_env["mods_dir"], tmp_path / "journals",
                                server.set_active_paks, lambda: None)
    payload = [{**metadata()[1], "mod_id": 1, "mod_key": "mod:1"}]
    plan = service.preview({"1": ["fresh.pak"]}, metadata=payload)
    service.apply(plan["entries"], plan["token"], metadata=payload)
    assert list(activation_env["mods_dir"].rglob("fresh.pak"))
    assert not list(activation_env["mods_dir"].rglob("stale.pak"))
    conn = activation_env["db"]
    assert conn.execute("SELECT description_bbcode FROM mods WHERE mod_id=1").fetchone()[0] == "restored new description"
    assert {row[0] for row in conn.execute("SELECT tag FROM mod_custom_tags WHERE mod_id=1")} == {"Costume", "Favorite"}
    image = conn.execute("SELECT image_data,filename,mime_type FROM mod_custom_images WHERE mod_id=1").fetchone()
    assert tuple(image) == (PNG, "cover.png", "image/png")
    author = conn.execute("SELECT a.display_name,a.author_type,a.avatar_base64 FROM custom_authors a "
                          "JOIN local_mod_metadata m ON m.custom_author_id=a.id WHERE m.mod_key='mod:1'").fetchone()
    assert tuple(author) == ("Backup Author", "custom", f"data:image/png;base64,{PNG}")
    assert not service.pending_recovery()
