"""Synthetic PAKs plus fault injection; never reads the installed game."""
import hashlib
import json
import struct

import pytest
from Crypto.Cipher import AES

from core.compatibility import pak, service


def make_pak(path, names=None, encrypted=False):
    names = names if names is not None else ["chunknames", "Marvel/Content/Marvel/Characters/test.uasset"]
    def string(value):
        value = value.encode() + b"\0"
        return struct.pack("<i", len(value)) + value
    def block(value):
        if encrypted:
            value += bytes((-len(value)) % 16)
        sha = hashlib.sha1(value).digest()
        if encrypted:
            def swap(value):
                return b"".join(value[i:i + 4][::-1] for i in range(0, len(value), 4))
            value = swap(AES.new(swap(pak.KEY), AES.MODE_ECB).encrypt(swap(value)))
        return value, sha
    # Real uncompressed entry headers followed by data, with encoded records.
    payload, encoded, directories = b"", b"", {}
    for name in names:
        content = b"valid asset data: " + name.encode()
        offset = len(payload)
        payload += struct.pack("<QQQI", 0, len(content), len(content), 0) + hashlib.sha1(content).digest() + struct.pack("<BI", 0, 0) + content
        folder, _, leaf = name.rpartition("/")
        directories.setdefault(folder + "/" if folder else "", []).append((leaf, len(encoded)))
        encoded += struct.pack("<III", (1 << 31) | (1 << 30) | (1 << 29), offset, len(content))
    # Use no path-hash index; supported by repak, which creates one on write.
    directory = struct.pack("<I", len(directories))
    for folder, entries in directories.items():
        directory += string(folder) if folder else struct.pack("<i", 1) + b"\0"
        directory += struct.pack("<I", len(entries))
        for name, offset in entries:
            directory += string(name) + struct.pack("<I", offset)
    directory, dhash = block(directory)
    prefix = string("../../../") + struct.pack("<IQII", len(names), 0, 0, 1)
    index_size = len(prefix) + 36 + 4 + len(encoded) + 4
    if encrypted:
        index_size += -index_size % 16
    index = prefix + struct.pack("<QQ", len(payload) + index_size, len(directory)) + dhash + struct.pack("<I", len(encoded)) + encoded + struct.pack("<I", 0)
    index, ihash = block(index)
    footer = bytes(16) + bytes([encrypted]) + struct.pack("<IIQQ", 0x5A6F12E1, 11, len(payload), len(index)) + ihash + bytes(160)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + index + directory + footer)
    return path


@pytest.mark.parametrize("encrypted", [False, True])
def test_mixed_content_preserved_and_repeat_no_change(tmp_path, encrypted):
    root, backups = tmp_path / "mods", tmp_path / "backups"
    path = make_pak(root / "mixed.pak", ["chunknames", "patched_files", "desktop.ini", "Marvel/Content/WwiseAudio/voice.wem", "Marvel/Content/Marvel/Characters/desktop.ini.uasset"], encrypted)
    original = path.read_bytes()
    results = service.repair_installed(root, backups)
    assert results[0]["archive"] == "repaired", results
    assert results[0]["game_compatibility"] == "unknown"
    assert "audio" in results[0]["content_notes"]
    assert len(pak.inspect(path).entries) == 2
    repaired = path.read_bytes()
    assert repaired != original
    assert service.repair_installed(root, backups)[0]["archive"] == "checked"
    assert path.read_bytes() == repaired
    assert len(service.backups(root, backups)) == 1
    service.restore(root, backups, results[0]["backup_id"])
    assert path.read_bytes() == original


@pytest.mark.parametrize("damage", ["short", "hash", "version", "range"])
def test_bad_archives_never_change(tmp_path, damage):
    path = make_pak(tmp_path / "mods/bad.pak")
    data = bytearray(path.read_bytes())
    if damage == "short":
        data = data[:50]
    elif damage == "hash":
        data[-221 + 41] ^= 1
    elif damage == "version":
        struct.pack_into("<I", data, len(data) - 221 + 21, 99)
    else:
        struct.pack_into("<Q", data, len(data) - 221 + 25, 2**62)
    path.write_bytes(data)
    assert service.repair_installed(path.parent, tmp_path / "backups")[0]["archive"] == "blocked"
    assert path.read_bytes() == data
    assert not (tmp_path / "backups").exists()


def test_companions_unchanged_and_orphan_blocked(tmp_path):
    root = tmp_path / "mods"
    path = make_pak(root / "test.pak")
    for ext in (".utoc", ".ucas"):
        path.with_suffix(ext).write_bytes(b"companion bytes")
    (root / "orphan.ucas").write_bytes(b"orphan")
    result = service.repair_installed(root, tmp_path / "backups")
    assert {row["archive"] for row in result} == {"repaired", "blocked"}
    for ext in (".utoc", ".ucas"):
        assert path.with_suffix(ext).read_bytes() == b"companion bytes"


def test_restore_refuses_later_change_and_corrupt_backup(tmp_path):
    root, backups = tmp_path / "mods", tmp_path / "backups"
    path = make_pak(root / "test.pak")
    result = service.repair_installed(root, backups)[0]
    repaired = path.read_bytes()
    path.write_bytes(b"later change")
    with pytest.raises(pak.PakError, match="later file change"):
        service.restore(root, backups, result["backup_id"])
    assert path.read_bytes() == b"later change"
    path.write_bytes(repaired)
    (backups / result["backup_id"] / "0.bak").write_bytes(b"corrupt")
    with pytest.raises(pak.PakError, match="Backup hash"):
        service.restore(root, backups, result["backup_id"])
    assert path.read_bytes() == repaired


def test_partial_install_rolls_back(tmp_path, monkeypatch):
    staging, root, backups = tmp_path / "staging", tmp_path / "mods", tmp_path / "backups"
    make_pak(staging / "a.pak")
    make_pak(staging / "b.pak")
    old = make_pak(root / "a.pak", ["old.uasset"]).read_bytes()
    replace = service.replace_copy
    def fail_second(source, target):
        if target == root / "b.pak":
            raise OSError("disk full")
        replace(source, target)
    monkeypatch.setattr(service, "replace_copy", fail_second)
    with pytest.raises(OSError, match="disk full"):
        service.install_staged(staging, root, backups)
    assert (root / "a.pak").read_bytes() == old
    assert not (root / "b.pak").exists()
    assert service.backups(root, backups)[0]["state"] == "restored"


def test_invalid_install_does_not_replace_existing(tmp_path):
    root, staging = tmp_path / "mods", tmp_path / "stage"
    old = make_pak(root / "a.pak").read_bytes()
    make_pak(staging / "a.pak")
    (staging / "b.pak").write_bytes(b"bad")
    with pytest.raises(pak.PakError):
        service.install_staged(staging, root, tmp_path / "backups")
    assert (root / "a.pak").read_bytes() == old


def test_path_escape_rejected(tmp_path):
    with pytest.raises(pak.PakError):
        service.safe_path(tmp_path, "../outside.pak")
    with pytest.raises(pak.PakError):
        service.restore(tmp_path, tmp_path, "../bad")


def test_worker_failure_keeps_original(tmp_path, monkeypatch):
    path = make_pak(tmp_path / "mods/a.pak")
    before = path.read_bytes()
    def fail(*args):
        raise OSError("worker failed")
    monkeypatch.setattr(service, "repair_copy", fail)
    assert service.repair_installed(path.parent, tmp_path / "backups")[0]["archive"] == "failed"
    assert path.read_bytes() == before


def test_backup_failure_prevents_replacement(tmp_path, monkeypatch):
    path = make_pak(tmp_path / "mods/a.pak")
    original = path.read_bytes()
    copy = service.verified_copy
    def fail_backup(source, target):
        if target.suffix == ".bak":
            raise OSError("backup disk full")
        return copy(source, target)
    monkeypatch.setattr(service, "verified_copy", fail_backup)
    result = service.repair_installed(path.parent, tmp_path / "backups")[0]
    assert result["archive"] == "failed"
    assert path.read_bytes() == original


def test_interrupted_journal_can_restore_twice(tmp_path):
    root, backups = tmp_path / "mods", tmp_path / "backups"
    path = make_pak(root / "a.pak")
    original = path.read_bytes()
    result = service.repair_installed(root, backups)[0]
    manifest_path = backups / result["backup_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["state"] = "prepared"
    manifest_path.write_text(json.dumps(manifest))
    service.restore(root, backups, result["backup_id"])
    service.restore(root, backups, result["backup_id"])
    assert path.read_bytes() == original


def test_install_subfolder_backup_is_visible_and_sources_are_verified(tmp_path):
    staging, root, backups = tmp_path / "stage", tmp_path / "mods", tmp_path / "backups"
    path = make_pak(staging / "a.pak")
    original = path.read_bytes()
    result = service.install_staged(staging, root / "character", backups, root=root)
    saved = service.backups(root, backups)
    assert saved[0]["id"] == result["backup_id"]
    folder = backups / result["backup_id"]
    source = json.loads((folder / "manifest.json").read_text())["sources"][0]
    assert service.digest(folder / source["backup"]) == source["sha256"]
    assert (folder / source["backup"]).read_bytes() == original
    service.restore(root, backups, result["backup_id"])
    assert not (root / "character/a.pak").exists()


def test_missing_companion_blocks_repair(tmp_path):
    path = make_pak(tmp_path / "mods/a.pak")
    original = path.read_bytes()
    path.with_suffix(".utoc").write_bytes(b"manifest")
    assert service.repair_installed(path.parent, tmp_path / "backups")[0]["archive"] == "blocked"
    assert path.read_bytes() == original


def test_directory_hash_damage_is_rejected(tmp_path):
    path = make_pak(tmp_path / "a.pak")
    data = bytearray(path.read_bytes())
    data[-222] ^= 1
    path.write_bytes(data)
    with pytest.raises(pak.PakError, match="hash check"):
        pak.inspect(path)


def test_version_10_repair(tmp_path):
    path = make_pak(tmp_path / "mods/a.pak")
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, len(data) - 221 + 21, 10)
    path.write_bytes(data)
    assert service.repair_installed(path.parent, tmp_path / "backups")[0]["archive"] == "repaired"


def test_restore_rejects_changed_companion(tmp_path):
    root, backups = tmp_path / "mods", tmp_path / "backups"
    path = make_pak(root / "a.pak")
    for ext in (".utoc", ".ucas"):
        path.with_suffix(ext).write_bytes(b"original companion")
    result = service.repair_installed(root, backups)[0]
    path.with_suffix(".ucas").write_bytes(b"new companion")
    with pytest.raises(pak.PakError, match="companion change"):
        service.restore(root, backups, result["backup_id"])


def test_install_rejects_stale_companion(tmp_path):
    root, staging = tmp_path / "mods", tmp_path / "stage"
    path = make_pak(root / "a.pak")
    original = path.read_bytes()
    path.with_suffix(".utoc").write_bytes(b"old")
    path.with_suffix(".ucas").write_bytes(b"old")
    make_pak(staging / "a.pak")
    with pytest.raises(pak.PakError, match="omits an installed companion"):
        service.install_staged(staging, root, tmp_path / "backups")
    assert path.read_bytes() == original
