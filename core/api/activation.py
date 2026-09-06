"""Small route boundary for previewed activation transactions."""
from fastapi import APIRouter, Body, HTTPException
from core.activation import ActivationError, ActivationService, read_pending_recovery
from core.compatibility import service as compatibility

router = APIRouter(prefix="/api/activation", tags=["activation"])


@router.get("/status")
def status():
    from core.api import server
    return {"recovery_required": read_pending_recovery(server._get_current_settings().data_dir),
            "journal_folder": str(server._get_current_settings().data_dir / "activation-journals")}


def service():
    from core.api import server

    def refresh():
        conn = server.get_db()
        try:
            server._safe_rebuild_conflicts(conn, active_only=True, purpose="loadout_transaction", raise_on_error=True)
        finally:
            conn.close()

    return ActivationService(server.get_db, server._mods_folder_from_env(),
                             server._get_current_settings().data_dir / "activation-journals",
                             server.set_active_paks, refresh)


def run(operation):
    try:
        return operation()
    except ActivationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/preview")
@compatibility.serialized
def preview(payload: dict = Body(...)):
    return run(lambda: service().preview(payload.get("entries"), payload.get("download_paths"), payload.get("metadata")))


@router.post("/apply")
@compatibility.serialized
def apply(payload: dict = Body(...)):
    return run(lambda: service().apply(payload.get("entries"), payload.get("token"), payload.get("download_paths"), payload.get("metadata")))


@router.post("/keep-preview")
@compatibility.serialized
def keep_preview(payload: dict = Body(...)):
    if not isinstance(payload.get("download_id"), int) or not isinstance(payload.get("pak"), str):
        raise HTTPException(status_code=400, detail="Choose an installed download and pak file.")
    return run(lambda: service().preview_keep(payload["download_id"], payload["pak"]))


@router.post("/recover")
@compatibility.serialized
def recover():
    return run(lambda: service().recover())
