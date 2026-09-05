"""Batch switches preserve the exact prior files and selection on failure."""
import json
import sqlite3

import pytest

from core.activation import ActivationError, ActivationService, _write
from test_set_active_paks import activation_env as activation_env


@pytest.fixture
def setup(tmp_path):
    db = tmp_path / "test.db"
    root = tmp_path / "mods"
    root.mkdir()
    (root / "old.pak").write_bytes(b"original bytes")
    (root / "notes.txt").write_bytes(b"leave me alone")
    source = tmp_path / "source.zip"
    source.write_bytes(b"source data")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE local_downloads (id INTEGER PRIMARY KEY, path TEXT, name TEXT, "
                 "contents TEXT, active_paks TEXT, last_activated_at TEXT, last_deactivated_at TEXT)")
    for key, paks in ((1, ["old.pak"]), (2, [])):
        conn.execute("INSERT INTO local_downloads VALUES (?,?,?,?,?,?,?)", (
            key, str(source), f"Mod {key}", json.dumps(["old.pak"] if key == 1 else ["new.pak"]),
            json.dumps(paks), "before", None))
    conn.execute("CREATE TABLE pak_assets (pak_name TEXT, asset_path TEXT)")
    conn.executemany("INSERT INTO pak_assets VALUES (?,?)", [("old.pak", "shared"), ("new.pak", "shared")])
    conn.commit()
    conn.close()

    def get_db():
        return sqlite3.connect(db)

    def activate(key, payload):
        conn = get_db()
        before = json.loads(conn.execute("SELECT active_paks FROM local_downloads WHERE id=?", (key,)).fetchone()[0])
        for pak in before:
            (root / pak).unlink(missing_ok=True)
        for pak in payload["active_paks"]:
            (root / pak).write_bytes(b"new bytes")
        conn.execute("UPDATE local_downloads SET active_paks=?,last_activated_at='after' WHERE id=?",
                     (json.dumps(payload["active_paks"]), key))
        conn.commit()
        conn.close()
        return {"active_paks": payload["active_paks"]}

    service = ActivationService(get_db, root, tmp_path / "journals", activate, lambda: None)
    return service, root, source


def test_switch_commits_exact_selection_and_preserves_unmanaged_files(setup):
    service, root, _ = setup
    plan = service.preview({"2": ["new.pak"]})
    assert [change["download_id"] for change in plan["changes"]] == [1, 2]
    assert service.apply(plan["entries"], plan["token"])["updated"] == 2
    assert not (root / "old.pak").exists()
    assert (root / "new.pak").read_bytes() == b"new bytes"
    assert (root / "notes.txt").read_bytes() == b"leave me alone"
    assert not list(service.journal_root.iterdir())


def test_failure_after_partial_apply_rolls_back_bytes_and_database(setup):
    service, root, _ = setup
    before = service._rows()
    original = service.activate

    def fail(key, payload):
        original(key, payload)
        if key == 2:
            raise OSError("disk full")

    service.activate = fail
    plan = service.preview({"2": ["new.pak"]})
    with pytest.raises(ActivationError, match="previous files and selection were restored"):
        service.apply(plan["entries"], plan["token"])
    assert service._rows() == before
    assert (root / "old.pak").read_bytes() == b"original bytes"
    assert not (root / "new.pak").exists()


@pytest.mark.parametrize("changed", ["source", "game", "database"])
def test_rejects_stale_preview_without_touching_files(setup, changed):
    service, root, source = setup
    plan = service.preview({"2": ["new.pak"]})
    if changed == "source":
        source.write_bytes(b"updated source archive")
    elif changed == "game":
        (root / "external.pak").write_bytes(b"external edit")
    else:
        conn = service.get_db()
        conn.execute("UPDATE local_downloads SET name='renamed' WHERE id=2")
        conn.commit()
        conn.close()
    with pytest.raises(ActivationError, match="fresh preview"):
        service.apply(plan["entries"], plan["token"])
    assert (root / "old.pak").read_bytes() == b"original bytes"


@pytest.mark.parametrize("entries,reason", [({"99": ["missing.pak"]}, "no longer installed"),
                                         ({"2": ["missing.pak"]}, "variant is missing")])
def test_missing_download_or_variant_blocks_entire_switch(setup, entries, reason):
    service, root, _ = setup
    plan = service.preview(entries)
    assert not plan["can_apply"]
    assert reason in plan["missing"][0]["reason"]
    with pytest.raises(ActivationError, match="missing downloads"):
        service.apply(entries, plan["token"])
    assert (root / "old.pak").exists()


def test_missing_source_blocks_even_with_cached_contents(setup):
    service, _, source = setup
    source.unlink()
    assert not service.preview({"2": ["new.pak"]})["can_apply"]


def test_reused_download_id_is_not_treated_as_the_saved_source(setup):
    service, _, _ = setup
    plan = service.preview({"2": ["new.pak"]}, {"2": "/previous/download.zip"})
    assert not plan["can_apply"]
    assert "different source" in plan["missing"][0]["reason"]
    with pytest.raises(ActivationError, match="missing downloads"):
        service.apply(plan["entries"], plan["token"], plan["download_paths"])


def test_ambiguous_basename_does_not_select_an_arbitrary_variant(setup):
    service, _, _ = setup
    conn = service.get_db()
    conn.execute("UPDATE local_downloads SET contents=? WHERE id=2", ('["a/new.pak","b/new.pak"]',))
    conn.commit()
    conn.close()
    assert not service.preview({"2": ["new.pak"]})["can_apply"]
    assert service.preview({"2": ["b/new.pak"]})["can_apply"]


def test_interrupted_switch_can_be_recovered_by_new_service(setup):
    service, root, _ = setup
    before = service._rows()
    folder, manifest = service._snapshot({"old", "new"})
    service.activate(1, {"active_paks": []})
    service.activate(2, {"active_paks": ["new.pak"]})
    manifest["expected"] = service._hashes()
    manifest["expected_rows"] = service._rows()
    _write(folder / "journal.json", manifest)
    restarted = ActivationService(service.get_db, root, service.journal_root, service.activate, lambda: None)
    assert restarted.preview({})["recovery_required"]
    assert restarted.recover() == {"recovered": 1}
    assert restarted._rows() == before
    assert (root / "old.pak").read_bytes() == b"original bytes"
    assert not (root / "new.pak").exists()


def test_damaged_journal_aborts_recovery_before_deleting_anything(setup):
    service, root, _ = setup
    folder, _ = service._snapshot()
    (folder / "files" / "old.pak").write_bytes(b"damaged")
    (root / "new.pak").write_bytes(b"current")
    with pytest.raises(ActivationError, match="damaged"):
        service.recover()
    assert (root / "new.pak").read_bytes() == b"current"
    assert folder.exists()


def test_recovery_preserves_new_unrelated_files(setup):
    service, root, _ = setup
    service._snapshot()
    (root / "unrelated.pak").write_bytes(b"installed later")
    service.recover()
    assert (root / "unrelated.pak").read_bytes() == b"installed later"


def test_recovery_refuses_to_overwrite_later_edits(setup):
    service, root, _ = setup
    service._snapshot()
    (root / "old.pak").write_bytes(b"user replacement")
    with pytest.raises(ActivationError, match="preserve those edits"):
        service.recover()
    assert (root / "old.pak").read_bytes() == b"user replacement"


def test_incomplete_copy_requires_manual_recovery(setup):
    service, root, _ = setup
    folder, manifest = service._snapshot()
    manifest["state"] = "step_in_progress"
    _write(folder / "journal.json", manifest)
    with pytest.raises(ActivationError, match="manual recovery"):
        service.recover()
    assert (root / "old.pak").read_bytes() == b"original bytes"
    with pytest.raises(ActivationError, match="interrupted switch"):
        service.apply({}, "old-token")


def test_keep_variant_previews_overlapping_disables(setup):
    service, _, _ = setup
    plan = service.preview_keep(2, "new.pak")
    assert plan["entries"] == {"1": [], "2": ["new.pak"]}
    assert plan["changes"][0]["before"] == ["old.pak"]
    assert service._rows()[0]["active_paks"] == '["old.pak"]'


def test_success_response_with_missing_file_rolls_back(setup):
    service, root, _ = setup
    original = service.activate

    def fake_success(key, payload):
        result = original(key, payload)
        if key == 2:
            (root / "new.pak").unlink()
        return result

    service.activate = fake_success
    plan = service.preview({"2": ["new.pak"]})
    with pytest.raises(ActivationError, match="could not be verified"):
        service.apply(plan["entries"], plan["token"])
    assert (root / "old.pak").read_bytes() == b"original bytes"


def test_transaction_uses_real_archive_activation(activation_env, tmp_path):
    import core.api.server as server
    service = ActivationService(server.get_db, activation_env["mods_dir"], tmp_path / "journals",
                                server.set_active_paks, lambda: None)
    plan = service.preview({"1": ["fresh.pak"]})
    result = service.apply(plan["entries"], plan["token"])
    assert result["updated"] == 1
    assert list(activation_env["mods_dir"].rglob("fresh.pak"))
    assert not list(activation_env["mods_dir"].rglob("stale.pak"))


def test_real_archive_rejection_restores_previously_disabled_files(activation_env, tmp_path):
    import core.api.server as server
    service = ActivationService(server.get_db, activation_env["mods_dir"], tmp_path / "journals",
                                server.set_active_paks, lambda: None)
    (activation_env["src"] / "fresh.pak").write_bytes(b"bad archive")
    before = service._rows()
    plan = service.preview({"1": ["fresh.pak"]})
    with pytest.raises(ActivationError, match="previous files and selection were restored"):
        service.apply(plan["entries"], plan["token"])
    assert service._rows() == before
    assert (activation_env["mods_dir"] / "stale.pak").read_bytes() == b"\x00"
    assert (activation_env["mods_dir"] / "stale.utoc").read_bytes() == b"\x00"
