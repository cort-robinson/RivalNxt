import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.activity import install_activity, get_recent_operations, describe_operation


def setup_app(tmp_path):
    def get_db():
        return sqlite3.connect(tmp_path / "activity.db")
    app = FastAPI()
    install_activity(app, get_db)
    return app, get_db


def test_records_success_and_partial_failure_without_request_secrets(tmp_path):
    app, get_db = setup_app(tmp_path)

    @app.post("/api/local_downloads/1/set-active")
    def activate():
        return {"ok": True}

    @app.post("/api/compatibility/repair")
    def repair():
        return {"results": [{"archive": "failed", "error": "api_key=secret"}]}

    with TestClient(app) as client:
        client.post("/api/local_downloads/1/set-active", json={"private": "secret"})
        client.post("/api/compatibility/repair")
    rows = get_recent_operations(get_db)
    assert [r["status"] for r in rows] == ["failed", "succeeded"]
    assert "secret" not in str(rows)
    assert rows[1]["kind"] == "activation"


def test_http_errors_remain_visible_after_a_new_client(tmp_path):
    from fastapi import HTTPException
    app, get_db = setup_app(tmp_path)

    @app.post("/api/backup/create")
    def backup():
        raise HTTPException(409, "private path")

    with TestClient(app) as client:
        assert client.post("/api/backup/create").status_code == 409
    with TestClient(app) as client:
        rows = client.get("/api/activity/operations").json()["operations"]
    assert rows[0]["status"] == "failed"
    assert "private path" not in str(rows)


def test_old_session_running_operation_is_interrupted(tmp_path):
    from core.activity import _write
    _, get_db = setup_app(tmp_path)
    _write(get_db, "job", "backup", "Create backup", "running")
    conn = get_db()
    conn.execute("UPDATE activity_operations SET session='old-process'")
    conn.commit()
    conn.close()
    assert get_recent_operations(get_db)[0]["status"] == "interrupted"


def test_ignores_reads_and_credentials_endpoints():
    assert describe_operation("POST", "/api/nxm/handoff") is None
    assert describe_operation("GET", "/api/backup/create") is None
    assert describe_operation("POST", "/api/nxm/handoff/key/ingest")[0] == "download"


def test_cancellation_is_not_reported_as_a_failure(tmp_path):
    app, get_db = setup_app(tmp_path)

    @app.post("/api/nxm/handoff/job/ingest")
    def download():
        return {"ok": False, "cancelled": True}

    with TestClient(app) as client:
        client.post("/api/nxm/handoff/job/ingest")
    assert get_recent_operations(get_db)[0]["status"] == "cancelled"


def test_clearing_history_preserves_live_operations(tmp_path):
    from core.activity import _write
    app, get_db = setup_app(tmp_path)
    _write(get_db, "live", "download", "Download", "running")
    _write(get_db, "done", "backup", "Backup", "succeeded")
    with TestClient(app) as client:
        assert client.post("/api/activity/operations/clear").status_code == 200
    assert [r["id"] for r in get_recent_operations(get_db)] == ["live"]


def test_actual_nxm_http_cancellation_is_recorded_as_cancelled(tmp_path):
    from fastapi import HTTPException
    app, get_db = setup_app(tmp_path)

    @app.post("/api/nxm/handoff/job/ingest")
    def download():
        raise HTTPException(499, "Download cancelled by user")

    with TestClient(app) as client:
        client.post("/api/nxm/handoff/job/ingest")
    assert get_recent_operations(get_db)[0]["status"] == "cancelled"
