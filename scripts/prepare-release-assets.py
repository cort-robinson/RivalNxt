"""Create the signed Tauri update feed and checksum beside the verified installer."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def prepare(installer: Path, version: str, notes: Path) -> None:
    if installer.name != f"RivalNxt_{version}_x64-setup.exe":
        raise ValueError("Installer filename does not match the release version")
    signature = Path(str(installer) + ".sig").read_text().strip()
    if not signature:
        raise ValueError("Updater signature is missing")
    with installer.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    Path(str(installer) + ".sha256").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    feed = {
        "version": version,
        "notes": notes.read_text(encoding="utf-8"),
        "pub_date": datetime.now(timezone.utc).isoformat(),
        "platforms": {"windows-x86_64": {
            "url": f"https://github.com/cort-robinson/RivalNxt/releases/download/v{version}/{installer.name}",
            "signature": signature,
        }},
    }
    (installer.parent / "latest.json").write_text(json.dumps(feed, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("version")
    parser.add_argument("notes", type=Path)
    args = parser.parse_args()
    prepare(args.installer, args.version, args.notes)
