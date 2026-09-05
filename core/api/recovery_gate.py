"""Keep unrelated mutation routes from bypassing an interrupted batch switch."""
import json
import os
from pathlib import Path

from starlette.responses import JSONResponse

from core.activation import read_pending_recovery


class RecoveryGate:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        method = scope.get("method", "")
        if scope["type"] != "http" or method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        # These requests do not mutate mod files. Cancellation must reach a
        # running download immediately rather than wait behind its request.
        if path in {"/api/debug/log", "/api/settings/validate-path", "/api/activation/preview", "/api/activation/keep-preview"} or (
                path.startswith("/api/nxm/handoff/") and path.endswith("/cancel")):
            return await self.app(scope, receive, send)
        current = self.settings()
        pending = read_pending_recovery(current.data_dir)
        if pending and path == "/api/settings":
            # Game path correction is useful for recovery; moving the data
            # folder would hide the journal and silently lift this gate.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > 65536:
                    return await JSONResponse(status_code=413, content={"detail": "Settings request is too large."})(scope, receive, send)
                if not message.get("more_body", False):
                    break
            try:
                payload = json.loads(body)
                requested = payload.get("data_dir") if isinstance(payload, dict) else None
                if isinstance(requested, str) and requested.strip() and os.path.normcase(str(Path(requested.strip()).resolve())) != os.path.normcase(str(Path(current.data_dir).resolve())):
                    return await JSONResponse(status_code=409, content={"detail": "Recover the interrupted switch before moving the data folder. Game path settings can still be corrected."})(scope, receive, send)
            except (ValueError, OSError):
                return await JSONResponse(status_code=400, content={"detail": "Invalid settings request."})(scope, receive, send)
            original_receive = receive
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = replay
        elif pending and path not in {"/api/activation/recover", "/api/backup/create"}:
            return await JSONResponse(status_code=409, content={
                "detail": "An interrupted preset switch needs recovery. Use Review recovery before changing mods.",
                "error": "activation_recovery_required",
            })(scope, receive, send)
        return await self.app(scope, receive, send)
