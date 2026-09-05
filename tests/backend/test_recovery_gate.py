import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api.recovery_gate import RecoveryGate


def test_pending_journal_blocks_mutations_but_allows_inspection_and_recovery(tmp_path):
    journal = tmp_path / "activation-journals" / "example"
    journal.mkdir(parents=True)
    (journal / "journal.json").write_text(json.dumps({"state": "step_in_progress"}))
    app = FastAPI()
    app.add_middleware(RecoveryGate, settings=lambda: SimpleNamespace(data_dir=tmp_path))
    @app.post("/api/mods/disable-all")
    def disable():
        return {"ok": True}
    @app.get("/api/diagnostics")
    def diagnostics():
        return {"ok": True}
    @app.post("/api/activation/recover")
    def recover():
        return {"ok": True}
    client = TestClient(app)
    assert client.post("/api/mods/disable-all").status_code == 409
    assert client.get("/api/diagnostics").status_code == 200
    assert client.post("/api/activation/recover").status_code == 200
    (journal / "journal.json").write_text(json.dumps({"state": "committed"}))
    assert client.post("/api/mods/disable-all").status_code == 200


def test_settings_path_validation_and_correction_remain_available_without_hiding_journal(tmp_path):
    from fastapi import Body
    journal = tmp_path / "activation-journals" / "example"
    journal.mkdir(parents=True)
    (journal / "journal.json").write_text(json.dumps({"state": "rollback_failed"}))
    app = FastAPI()
    app.add_middleware(RecoveryGate, settings=lambda: SimpleNamespace(data_dir=tmp_path))

    @app.post("/api/settings/validate-path")
    def validate():
        return {"ok": True}

    @app.put("/api/settings")
    def settings(payload: dict = Body(...)):
        return payload

    with TestClient(app) as client:
        assert client.post("/api/settings/validate-path").status_code == 200
        corrected = {"marvel_rivals_root": "correct/game/path", "data_dir": str(tmp_path)}
        assert client.put("/api/settings", json=corrected).json() == corrected
        assert client.put("/api/settings", json={"data_dir": str(tmp_path / "new")}).status_code == 409


def test_gate_uses_current_settings_each_request(tmp_path):
    current = SimpleNamespace(data_dir=tmp_path / "first")
    app = FastAPI()
    app.add_middleware(RecoveryGate, settings=lambda: current)

    @app.post("/api/mods/disable-all")
    def disable():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.post("/api/mods/disable-all").status_code == 200
        current.data_dir = tmp_path / "second"
        journal = current.data_dir / "activation-journals" / "example"
        journal.mkdir(parents=True)
        (journal / "journal.json").write_text(json.dumps({"state": "applying"}))
        assert client.post("/api/mods/disable-all").status_code == 409


def test_waiting_mutation_rechecks_guard_after_lock_and_recovery_bypass_is_scoped(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from core.compatibility import service
    pending = False

    def guard():
        if pending:
            raise ValueError("recovery required")

    monkeypatch.setattr(service, "_mutation_guard", guard)

    @service.guarded_mutation
    def mutate():
        return "changed"

    @service.recovery_operation
    def recover():
        return mutate()

    with ThreadPoolExecutor() as pool:
        with service.mutation_lock:
            work = pool.submit(mutate)
            pending = True
        import pytest
        with pytest.raises(ValueError, match="recovery required"):
            work.result()
    assert recover() == "changed"
    with pytest.raises(ValueError, match="recovery required"):
        mutate()
