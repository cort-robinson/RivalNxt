"""Inspect the actual frozen backend without launching it or trusting stale TOCs."""
from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = ("PIL", "fastapi", "uvicorn", "requests", "rust_ue_tools", "Crypto",
            "core.activation", "core.activity", "core.diagnostics", "core.api.activation", "core.api.recovery_gate")


def bundle_entries(exe: Path) -> set[str]:
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    names = set(archive.toc)
    for name, entry in archive.toc.items():
        if entry[-1] == "z":
            names.update(archive.open_embedded_archive(name).toc)
    return {name.replace("\\", "/") for name in names}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_bundle.py <path to built executable>")
        return 2
    exe = Path(sys.argv[1])
    try:
        names = bundle_entries(exe)
    except Exception as exc:
        print(f"FAIL: cannot inspect {exe}: {exc}")
        return 1
    missing = [module for module in REQUIRED if not any(
        name == module or name.startswith(module + ".") or name.startswith(module + "/")
        for name in names)]
    if not any(name in names for name in ("pak-repair/rivalnxt-pak-repair.exe", "pak-repair/rivalnxt-pak-repair")):
        missing.append("PAK repair worker")
    if missing:
        print("FAIL: executable is missing " + ", ".join(missing))
        return 1
    print(f"Verified {exe.name}: required Python modules and PAK repair worker are packaged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
