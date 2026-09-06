"""Legacy backup metadata writes, owned by the activation transaction.

No helper in this module commits. The caller commits these writes together with
a durable receipt, only after the package selection has been verified.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re


class MetadataError(ValueError):
    pass


def _text(value, limit, label, *, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise MetadataError(f"The backup contains an invalid {label}.")
    return value


def validate(conn, value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 10000:
        raise MetadataError("The backup metadata must be a list of installed mods.")
    if len(json.dumps(value).encode()) > 64 * 1024 * 1024:
        raise MetadataError("The backup metadata exceeds 64 MB. Use a full snapshot for larger backups.")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {"mod_id", "mod_key", "description", "custom_tags", "custom_images", "author"}:
            raise MetadataError("The backup contains unsupported metadata fields.")
        mod_id = item.get("mod_id")
        if type(mod_id) is not int or not mod_id or abs(mod_id) > 2**53 - 1 or mod_id in seen:
            raise MetadataError("The backup contains invalid or duplicate metadata mod IDs.")
        seen.add(mod_id)
        if mod_id < 0:
            installed = conn.execute("SELECT name, mod_id FROM local_downloads WHERE id=?", (-mod_id,)).fetchone()
            if not installed or installed[1] not in (None, mod_id):
                raise MetadataError("A saved local mod was removed or reassigned. Review a fresh preview.")
            keys = {f"local:{-mod_id}"} if installed[1] is None else {f"mod:{mod_id}"}
        else:
            installed = conn.execute("SELECT 1 FROM local_downloads WHERE mod_id=?", (mod_id,)).fetchone()
            if not installed or not conn.execute("SELECT 1 FROM mods WHERE mod_id=?", (mod_id,)).fetchone():
                raise MetadataError("A metadata target is no longer installed. Review a fresh preview.")
            keys = {f"mod:{mod_id}"}
        key = item.get("mod_key", next(iter(keys)))
        if not isinstance(key, str) or key not in keys:
            raise MetadataError("The saved author belongs to a different mod. Review a fresh preview.")
        normalized = {"mod_id": mod_id, "mod_key": key}
        if "description" in item:
            normalized["description"] = _text(item["description"], 2 * 1024 * 1024, "description")
        if "custom_tags" in item:
            tags = item["custom_tags"]
            if not isinstance(tags, list) or len(tags) > 1000:
                raise MetadataError("The backup contains invalid custom tags.")
            normalized["custom_tags"] = [_text(tag, 256, "tag", empty=False).strip() for tag in tags]
        if "custom_images" in item:
            images = item["custom_images"]
            if not isinstance(images, list) or len(images) > 1000:
                raise MetadataError("The backup contains invalid custom images.")
            normalized["custom_images"] = []
            for image in images:
                if not isinstance(image, dict) or set(image) - {"data", "filename", "mimeType"}:
                    raise MetadataError("The backup contains invalid image metadata.")
                data = _text(image.get("data"), 64 * 1024 * 1024, "image", empty=False)
                try:
                    base64.b64decode(data, validate=True)
                except ValueError as error:
                    raise MetadataError("The backup contains invalid base64 image data.") from error
                normalized["custom_images"].append({"data": data,
                    "filename": _text(image.get("filename", ""), 4096, "image filename"),
                    "mimeType": _text(image.get("mimeType", ""), 128, "image type")})
        if "author" in item:
            author = item["author"]
            if not isinstance(author, dict) or set(author) - {"name", "author_type", "avatar"}:
                raise MetadataError("The backup contains invalid author metadata.")
            author_type = author.get("author_type", "custom")
            if author_type not in ("custom", "nexus"):
                raise MetadataError("The backup contains an invalid author type.")
            avatar = author.get("avatar")
            if avatar is not None:
                _text(avatar, 8 * 1024 * 1024, "author avatar")
            normalized["author"] = {"name": _text(author.get("name"), 1024, "author name", empty=False).strip(),
                                    "author_type": author_type, "avatar": avatar}
        result.append(normalized)
    return result


def fingerprint(conn, metadata):
    """Bind a preview to the touched records without copying artwork to disk."""
    digest = hashlib.sha256()

    def include(sql, args):
        for row in conn.execute(sql, args):
            digest.update(json.dumps(tuple(row), separators=(",", ":")).encode())
        digest.update(b"\n")

    for item in metadata:
        mod_id = item["mod_id"]
        include("SELECT mod_id, game, name, description_bbcode, description_html FROM mods WHERE mod_id=?", (mod_id,))
        include("SELECT id,path,mod_id FROM local_downloads WHERE mod_id=? OR id=? ORDER BY id,path", (mod_id, -mod_id))
        include("SELECT * FROM mod_custom_tags WHERE mod_id=? ORDER BY id", (mod_id,))
        include("SELECT * FROM mod_custom_images WHERE mod_id=? ORDER BY id", (mod_id,))
        include("SELECT * FROM local_mod_metadata WHERE mod_key=?", (item["mod_key"],))
        if "author" in item:
            include("SELECT * FROM custom_authors WHERE name_normalized=?", (item["author"]["name"].lower(),))
    return digest.hexdigest()


def apply(conn, metadata):
    for item in metadata:
        mod_id = item["mod_id"]
        if not conn.execute("SELECT 1 FROM mods WHERE mod_id=?", (mod_id,)).fetchone():
            name = conn.execute("SELECT name FROM local_downloads WHERE id=?", (-mod_id,)).fetchone()[0]
            conn.execute("INSERT INTO mods(mod_id,game,name,author) VALUES (?,'marvelrivals',?,'Local')", (mod_id, name))
        if "description" in item:
            description = item["description"].strip()
            if re.search(r"\[(?:b|i|u|s|url|img|quote|code|list|color|size|font|center|left|right|justify|sub|sup|hr|spoiler|youtube|email)", description, re.I):
                from core.utils.bbcode_wrapper import bbcode_to_html
                rendered = bbcode_to_html(description)
            else:
                rendered = html.escape(description).replace("\n", "<br>")
            conn.execute("UPDATE mods SET description_bbcode=?,description_html=? WHERE mod_id=?", (description, rendered, mod_id))
        for tag in item.get("custom_tags", []):
            conn.execute("INSERT INTO mod_custom_tags(mod_id,tag) VALUES (?,?) ON CONFLICT(mod_id,tag) DO NOTHING", (mod_id, tag))
        for image in item.get("custom_images", []):
            # These bytes came from stored artwork. Do not re-encode an already
            # compressed backup; repeated restores must not degrade its quality.
            data = image["data"]
            digest = hashlib.sha256(data.encode()).hexdigest()
            if not conn.execute("SELECT 1 FROM mod_custom_images WHERE mod_id=? AND (content_hash=? OR image_data=?)",
                                (mod_id, digest, data)).fetchone():
                conn.execute("INSERT INTO mod_custom_images(mod_id,image_data,filename,mime_type,content_hash) VALUES (?,?,?,?,?)",
                             (mod_id, data, image["filename"], image["mimeType"], digest))
        if "author" in item:
            author = item["author"]
            conn.execute("""INSERT INTO custom_authors(name_normalized,display_name,author_type,avatar_base64)
                         VALUES (?,?,?,?) ON CONFLICT(name_normalized) DO UPDATE SET
                         display_name=excluded.display_name,author_type=excluded.author_type,
                         avatar_base64=COALESCE(excluded.avatar_base64,custom_authors.avatar_base64),updated_at=datetime('now')""",
                         (author["name"].lower(), author["name"], author["author_type"], author["avatar"]))
            author_id = conn.execute("SELECT id FROM custom_authors WHERE name_normalized=?", (author["name"].lower(),)).fetchone()[0]
            conn.execute("""INSERT INTO local_mod_metadata(mod_key,custom_author_id) VALUES (?,?)
                         ON CONFLICT(mod_key) DO UPDATE SET custom_author_id=excluded.custom_author_id,updated_at=datetime('now')""",
                         (item["mod_key"], author_id))


def ensure_receipts(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS activation_metadata_commits (journal_id TEXT PRIMARY KEY)")
    conn.commit()


def committed(conn, journal_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='activation_metadata_commits'").fetchone():
        return False
    return conn.execute("SELECT 1 FROM activation_metadata_commits WHERE journal_id=?", (journal_id,)).fetchone() is not None
