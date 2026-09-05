"""Bounded, independent index verification for Rivals PAK v10/v11.

The official repak reader does not verify index hashes. Check them here before
calling its writer, and compare retained entry records and the entire data prefix
afterwards. Asset data is never decompressed or rebuilt.
"""
from __future__ import annotations

import hashlib
import io
import struct
from dataclasses import dataclass
from pathlib import Path

from Crypto.Cipher import AES

KEY = bytes.fromhex("0C263D8C22DCB085894899C3A3796383E9BF9DE0CBFB08C9BF2DEF2E84F29D74")
MAX_INDEX = 64 * 1024 * 1024
MAX_ENTRIES = 250_000


class PakError(ValueError):
    pass


def read(stream, size):
    if size < 0 or size > MAX_INDEX:
        raise PakError("Index size exceeds the supported limit")
    data = stream.read(size)
    if len(data) != size:
        raise PakError("Archive is incomplete")
    return data


def number(stream, fmt):
    return struct.unpack("<" + fmt, read(stream, struct.calcsize("<" + fmt)))[0]


def string(stream):
    size = number(stream, "i")
    if size == 0 or abs(size) > 32768:
        raise PakError("Invalid archive path length")
    data = read(stream, size if size > 0 else -size * 2)
    terminator = b"\0" if size > 0 else b"\0\0"
    if not data.endswith(terminator):
        raise PakError("Archive path is not terminated")
    value = data[:-len(terminator)].decode("utf-8" if size > 0 else "utf-16-le")
    if "\0" in value:
        raise PakError("Archive path contains a null character")
    return value


def count(stream):
    value = number(stream, "I")
    if value > MAX_ENTRIES:
        raise PakError("Too many index entries")
    return value


def unsupported(path):
    value = path.replace("\\", "/").lower()
    return value in ("../../../chunknames", "../../../patched_files") or value.rsplit("/", 1)[-1] == "desktop.ini"


def full_path(mount, entry):
    entry = entry.replace("\\", "/")
    return entry if entry.startswith("../../../") else mount.replace("\\", "/").rstrip("/") + "/" + entry.lstrip("/")


@dataclass
class PakIndex:
    offset: int
    mount: str
    entries: dict[str, bytes]

    @property
    def removed(self):
        return [name for name in self.entries if unsupported(name)]


def inspect(path: Path) -> PakIndex:
    with path.open("rb") as file:
        size = path.stat().st_size
        # Rivals v10/v11 footer: UUID + encrypted flag + magic/version +
        # offset/size/hash + five 32-byte compression names.
        footer_size = 221
        if size < footer_size:
            raise PakError("PAK footer is missing")
        file.seek(size - footer_size)
        footer = read(file, footer_size)
        if footer[17:21] != b"\xe1\x12\x6f\x5a":
            raise PakError("Unsupported PAK footer")
        version, offset, length = struct.unpack_from("<IQQ", footer, 21)
        if version not in (10, 11) or footer[16] not in (0, 1):
            raise PakError("Only PAK versions 10 and 11 are supported")
        encrypted = bool(footer[16])
        regions = []

        def block(start, length, digest):
            if start < offset or start + length > size - footer_size or length > MAX_INDEX:
                raise PakError("Index range is outside the archive")
            if any(start < end and start + length > begin for begin, end in regions):
                raise PakError("Index ranges overlap")
            regions.append((start, start + length))
            file.seek(start)
            data = read(file, length)
            if encrypted:
                if len(data) % 16:
                    raise PakError("Encrypted index is not aligned")
                def swap(value):
                    return b"".join(value[i:i + 4][::-1] for i in range(0, len(value), 4))
                data = swap(AES.new(swap(KEY), AES.MODE_ECB).decrypt(swap(data)))
            # Older writers omit zero padding from the hash.
            if not any(hashlib.sha1(data[:len(data) - pad]).digest() == digest
                       and (pad == 0 or data[-pad:] == bytes(pad))
                       for pad in range(16 if encrypted else 1)):
                raise PakError("Index hash check failed")
            return data

        index = io.BytesIO(block(offset, length, footer[41:61]))
        mount = string(index)
        expected = count(index)
        number(index, "Q")
        phi = None
        for kind in ("path", "directory"):
            present = number(index, "I")
            if present not in (0, 1):
                raise PakError("Invalid index flag")
            if not present:
                if kind == "directory":
                    raise PakError("Full directory index is required")
                continue
            start, length = number(index, "Q"), number(index, "Q")
            data = block(start, length, read(index, 20))
            if kind == "path":
                phi = io.BytesIO(data)
            else:
                directory = io.BytesIO(data)
        encoded = read(index, number(index, "I"))
        if number(index, "I") != 0:
            raise PakError("Unencoded entries are not supported")
        if any(index.read()):
            raise PakError("Unexpected index data")
        entries = {}
        offsets = set()
        for _ in range(count(directory)):
            folder = string(directory)
            for _ in range(count(directory)):
                name = full_path(mount, folder.lstrip("/") + string(directory))
                entry_offset = number(directory, "I")
                if name in entries or entry_offset in offsets or entry_offset >= len(encoded):
                    raise PakError("Duplicate or invalid entry reference")
                offsets.add(entry_offset)
                record = io.BytesIO(encoded)
                record.seek(entry_offset)
                bits = number(record, "I")
                if bits & 63 == 63:
                    number(record, "I")
                data_offset = number(record, "I" if bits & (1 << 31) else "Q")
                unpacked = number(record, "I" if bits & (1 << 30) else "Q")
                compression = (bits >> 23) & 63
                packed = number(record, "I" if bits & (1 << 29) else "Q") if compression else unpacked
                blocks = (bits >> 6) & 65535
                encrypted_entry = bool(bits & (1 << 22))
                if blocks and (blocks != 1 or encrypted_entry):
                    read(record, blocks * 4)
                header = 53 + (4 + blocks * 16 if compression else 0)
                if data_offset + header + packed > offset:
                    raise PakError("Entry data is outside the data area")
                entries[name] = encoded[entry_offset:record.tell()]
                if len(entries) > MAX_ENTRIES:
                    raise PakError("Too many directory entries")
        if any(directory.read()) or len(entries) != expected:
            raise PakError("Directory entry count does not match")
        if phi is not None:
            phi_offsets = []
            for _ in range(count(phi)):
                number(phi, "Q")
                phi_offsets.append(number(phi, "I"))
            # repak appends a zero directory count to its path index.
            if set(phi_offsets) != offsets or len(phi_offsets) != expected or any(phi.read()):
                raise PakError("Path index does not match the directory")
        return PakIndex(offset, mount, entries)
