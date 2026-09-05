"""Bounded, local-only support reports. Settings and database contents are not exported."""
from __future__ import annotations

import json
import logging
import platform
import re
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter

from core.version import APP_VERSION

MAX_LOG_LINES = 150
MAX_TEXT = 4000
_SECRET = re.compile(
    r'''(?i)((?:["']?)(?:api[_-]?key|nexus[_-]?api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|signature|cookie)(?:["']?)\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)'''
)
# Headers can contain spaces (Basic auth) or multiple semicolon-separated cookies.
# Remove the whole header value, including unrecognized credential names.
_AUTH_HEADER = re.compile(r'''(?im)\b(?:authorization|proxy-authorization|cookie|set-cookie)["']?\s*[:=][^\r\n]*''')
_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*:(?://|\\/\\/)[^\s<>\"']+")
_TOKEN = re.compile(r'''(?i)(\b(?:token|credential|session[_-]?(?:id|key)|client[_-]?secret|x[_-]?auth[_-]?token)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')
_WINDOWS_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n\"'<>|]*")
_UNIX_HOME = re.compile(r"/(?:home|Users|root|tmp|var|mnt|media)/[^\r\n\"'<>]*")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def redact(text: object, secrets: tuple[str, ...] = (), roots: tuple[str, ...] = ()) -> str:
    """Redact before truncating, so a boundary cannot expose half of a secret."""
    value = str(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        value = value.replace(secret, "[redacted]")
    value = _AUTH_HEADER.sub("[authentication header removed]", value)
    value = _URL.sub("[URL removed]", value)
    value = _WINDOWS_PATH.sub("[local path]", value)
    value = _UNIX_HOME.sub("[local path]", value)
    for root in sorted((r for r in roots if r and r not in ("/", "\\")), key=len, reverse=True):
        for variant in {root, root.replace("\\", "/"), root.replace("/", "\\")}:
            value = re.sub(re.escape(variant), "[local folder]", value, flags=re.I)
    value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [redacted]", value)
    value = _SECRET.sub(r"\1[redacted]", value)
    value = _TOKEN.sub(r"\1[redacted]", value)
    return _EMAIL.sub("[email removed]", value)[:MAX_TEXT]


class DiagnosticLogHandler(logging.Handler):
    """Keep recent warning/error messages without retaining raw exception objects."""

    def __init__(self, settings: Callable):
        super().__init__(logging.WARNING)
        self.settings = settings
        self.lines: deque[dict] = deque(maxlen=MAX_LOG_LINES)
        self.guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            settings = self.settings()
            secrets, roots = redaction_context(settings)
            entry = {
                "at": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname,
                "message": redact(record.getMessage(), secrets, roots),
            }
            with self.guard:
                self.lines.append(entry)
        except Exception:
            # Diagnostics must never break the operation being logged.
            pass

    def snapshot(self) -> list[dict]:
        with self.guard:
            return list(self.lines)


def redaction_context(settings) -> tuple[tuple[str, ...], tuple[str, ...]]:
    secrets = tuple(str(getattr(settings, key, "") or "") for key in ("nexus_api_key", "aes_key_hex"))
    roots = tuple(str(getattr(settings, key, "") or "") for key in (
        "data_dir", "marvel_rivals_root", "marvel_rivals_local_downloads_root",
    )) + (str(Path.home()),)
    return secrets, roots


def build_report(settings, activity: Callable, handler: DiagnosticLogHandler, operations: Callable | None = None) -> dict:
    secrets, roots = redaction_context(settings)
    recent = []
    unavailable = []
    try:
        for entry in activity(50).get("entries", [])[:50]:
            recent.append({key: redact(entry.get(key, ""), secrets, roots)
                           for key in ("at", "kind", "summary", "detail")})
    except Exception:
        unavailable.append("Recent activity could not be read.")
    recent_operations = []
    if operations:
        try:
            recent_operations = [{key: redact(entry.get(key, ""), secrets, roots)
                                  for key in ("at", "kind", "summary", "status", "detail")}
                                 for entry in operations()[:50]]
        except Exception:
            unavailable.append("Recent operation status could not be read.")
    logs = handler.snapshot()
    # Only the app's fixed log name, with bounded reads and no linked files.
    log_path = Path(settings.data_dir) / "backend.log"
    if log_path.is_file() and not log_path.is_symlink():
        try:
            with log_path.open("rb") as stream:
                stream.seek(0, 2)
                size = stream.tell()
                offset = max(0, size - 65536)
                stream.seek(offset)
                if offset:
                    stream.readline()  # Never export a partial first line.
                tail = stream.read(65536).decode("utf-8", errors="replace")
            logs = [{"message": redact(line, secrets, roots)}
                    for line in tail.splitlines()[-MAX_LOG_LINES:]] + logs
        except OSError:
            unavailable.append("The saved backend log could not be read.")
    return {
        "report_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "application": {"name": "RivalNxt", "version": APP_VERSION},
        "runtime": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
        "configuration": {
            "game_folder_configured": bool(settings.marvel_rivals_root),
            "downloads_folder_configured": bool(settings.marvel_rivals_local_downloads_root),
            "nexus_key_configured": bool(settings.nexus_api_key),
        },
        "recent_activity": recent,
        "recent_operations": recent_operations,
        "recent_logs": logs[-MAX_LOG_LINES:],
        "unavailable": unavailable,
        "privacy": "Local preview only. Credentials, URLs, email addresses and local paths are redacted. Review before sharing.",
    }


def install_diagnostics(app, settings: Callable, activity: Callable, operations: Callable | None = None) -> DiagnosticLogHandler:
    handler = DiagnosticLogHandler(settings)
    logging.getLogger().addHandler(handler)
    router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

    @router.get("")
    def preview_diagnostics():
        report = build_report(settings(), activity, handler, operations)
        # JSON serialization also establishes a fixed, reviewable export format.
        return {"filename": f"RivalNxt-diagnostics-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json",
                "report": report, "text": json.dumps(report, ensure_ascii=False, indent=2)}

    app.include_router(router)
    return handler
