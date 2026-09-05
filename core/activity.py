"""Durable operation status without storing request bodies, URLs or credentials."""
from datetime import datetime, timezone
import json
import logging
import re
from uuid import uuid4

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

_LOG = logging.getLogger(__name__)
_SESSION = uuid4().hex


def _table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS activity_operations (
        id TEXT PRIMARY KEY, session TEXT NOT NULL, at TEXT NOT NULL,
        updated_at TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
        status TEXT NOT NULL, detail TEXT)""")


def get_recent_operations(get_db, limit=200):
    conn = get_db()
    try:
        _table(conn)
        conn.execute("UPDATE activity_operations SET status='interrupted' WHERE status='running' AND session != ?", (_SESSION,))
        conn.execute("DELETE FROM activity_operations WHERE status != 'running' AND id NOT IN "
                     "(SELECT id FROM activity_operations ORDER BY at DESC LIMIT 500)")
        conn.commit()
        rows = conn.execute(
            "SELECT id, at, updated_at, kind, summary, status, detail, session "
            "FROM activity_operations ORDER BY at DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
        return [dict(zip(("id", "at", "updated_at", "kind", "summary", "status", "detail"),
                         (*r[:5], "interrupted" if r[5] == "running" and r[7] != _SESSION else r[5], r[6])))
                for r in rows]
    finally:
        conn.close()


def _write(get_db, operation_id, kind, summary, status, detail=None):
    conn = None
    try:
        conn = get_db()
        _table(conn)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE activity_operations SET status='interrupted' WHERE status='running' AND session != ?", (_SESSION,))
        conn.execute("""INSERT INTO activity_operations VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,
            status=excluded.status, detail=excluded.detail""",
                     (operation_id, _SESSION, now, now, kind, summary, status, detail))
        conn.execute("DELETE FROM activity_operations WHERE status != 'running' AND id NOT IN "
                     "(SELECT id FROM activity_operations ORDER BY at DESC LIMIT 500)")
        conn.commit()
    except Exception:
        # Recording an operation must not change its result.
        _LOG.warning("Could not save operation status", exc_info=True)
    finally:
        if conn is not None:
            conn.close()


def describe_operation(method, path):
    if method not in ("POST", "DELETE", "PUT"):
        return None
    if re.fullmatch(r"/api/nxm/handoff/[^/]+/ingest", path):
        return "download", "Download and extract mod"
    if path in ("/api/mods/upload", "/api/mods/copy-to-downloads", "/api/mods/add"):
        return "extraction", "Import and extract mod"
    if re.fullmatch(r"/api/mods/\d+/update", path):
        return "download", "Update and extract mod"
    if path in ("/api/activation/apply", "/api/activation/recover"):
        return "activation", "Apply preset or resolve conflicts" if path.endswith("apply") else "Recover active mods"
    if path.startswith("/api/backup/") and path.rsplit("/", 1)[-1] in ("create", "restore", "delete", "prune"):
        return "backup", f"{path.rsplit('/', 1)[-1].capitalize()} backup"
    if path.startswith("/api/compatibility/"):
        return "repair", "Repair or restore packages"
    if (path.startswith(("/api/local_downloads/", "/api/collections/", "/api/presets/"))
            and path.rsplit("/", 1)[-1] in ("set-active", "bulk-activate", "activate-by-name", "deactivate-by-name", "activate", "deactivate", "apply")) or path == "/api/mods/disable-all":
        return "activation", "Change active mods"
    return None


class ActivityMiddleware:
    def __init__(self, app, get_db):
        self.app, self.get_db = app, get_db

    async def __call__(self, scope, receive, send):
        operation = describe_operation(scope.get("method"), scope.get("path", "")) if scope["type"] == "http" else None
        if operation is None:
            return await self.app(scope, receive, send)
        operation_id = uuid4().hex
        await run_in_threadpool(_write, self.get_db, operation_id, *operation, "running")
        status_code, body = 500, bytearray()

        async def capture(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body" and len(body) < 65536:
                body.extend(message.get("body", b"")[:65536 - len(body)])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        except BaseException:
            await run_in_threadpool(_write, self.get_db, operation_id, *operation, "failed", "Operation stopped before completion. Review the affected mods before retrying.")
            raise
        failed = status_code >= 400
        cancelled = status_code == 499
        try:
            result = json.loads(body)
            cancelled = cancelled or (isinstance(result, dict) and result.get("cancelled") is True)
            failed = failed or (isinstance(result, dict) and (result.get("ok") is False or bool(result.get("errors"))
                or bool(result.get("activation_warning")) or bool(result.get("deactivation_warnings"))
                or any(row.get("archive") == "failed" or row.get("ok") is False for row in (result.get("results") or []) if isinstance(row, dict))))
        except (ValueError, TypeError):
            pass
        await run_in_threadpool(_write, self.get_db, operation_id, *operation, "cancelled" if cancelled else "failed" if failed else "succeeded",
                                "Could not finish all requested changes. Review the operation before retrying." if failed and not cancelled else None)


def install_activity(app, get_db):
    router = APIRouter()

    @router.get("/api/activity/operations")
    def operations(limit: int = 200):
        return {"operations": get_recent_operations(get_db, limit)}

    @router.post("/api/activity/operations/clear")
    def clear_operations():
        conn = get_db()
        try:
            _table(conn)
            conn.execute("DELETE FROM activity_operations WHERE status != 'running' OR session != ?", (_SESSION,))
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()

    app.include_router(router)
    app.add_middleware(ActivityMiddleware, get_db=get_db)
