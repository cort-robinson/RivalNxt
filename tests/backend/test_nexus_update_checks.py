"""Concurrent update checks respect quotas and never erase usable metadata."""
import io
import json
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.nexus import nexus_api, request_limits


@pytest.fixture(autouse=True)
def isolated_limits():
    request_limits._cooldowns.clear()
    yield
    request_limits._cooldowns.clear()


def test_nexus_requests_are_bounded_to_three(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    active = peak = 0

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            nonlocal active
            with lock:
                active -= 1

        def getcode(self):
            return 200

        def read(self):
            assert release.wait(5)
            return b'{}'

    def open_request(request, *, context, timeout):
        nonlocal active, peak
        assert timeout == 30
        with lock:
            active += 1
            peak = max(active, peak)
            if active == 3:
                entered.set()
        return Response()

    monkeypatch.setattr(nexus_api.urllib.request, "urlopen", open_request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = [pool.submit(nexus_api.get_mod_info, "synthetic", "marvelrivals", index) for index in range(8)]
        try:
            assert entered.wait(5)
            assert peak == 3
        finally:
            release.set()
        assert all(future.result()[0] == 200 for future in pending)
    assert peak == 3


def test_429_stops_later_requests_until_retry_after(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(request_limits.time, "time", lambda: now[0])
    calls = []

    def limited(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError("https://api.nexusmods.com/test", 429, "limit", {"Retry-After": "120"}, io.BytesIO(b'{}'))

    monkeypatch.setattr(nexus_api.urllib.request, "urlopen", limited)
    assert nexus_api.get_mod_info("synthetic", "marvelrivals", 1)[0] == 429
    status, body = nexus_api.get_mod_files("synthetic", "marvelrivals", 2)
    assert status == 429 and body["retry_after"] == 120
    assert len(calls) == 1
    now[0] += 121
    nexus_api.get_mod_files("synthetic", "marvelrivals", 2)
    assert len(calls) == 2


def test_quotas_block_only_when_daily_and_hourly_are_exhausted(monkeypatch):
    monkeypatch.setattr(request_limits.time, "time", lambda: 1000)
    request_limits.observe("synthetic", 200, {"X-RL-Daily-Remaining": "0", "X-RL-Hourly-Remaining": "4"})
    assert request_limits.retry_after("synthetic") == 0
    request_limits.observe("synthetic", 200, {"X-RL-Daily-Remaining": "0", "X-RL-Hourly-Remaining": "0",
        "X-RL-Daily-Reset": "5000", "X-RL-Hourly-Reset": "1200"})
    assert request_limits.retry_after("synthetic") == 200
    assert request_limits.retry_after("different synthetic account") == 0


def test_update_check_fetches_two_endpoints_without_changelogs(monkeypatch):
    calls = []
    monkeypatch.setattr(nexus_api, "get_mod_info", lambda *args: (calls.append("info") or (200, {"name": "Example"})))
    monkeypatch.setattr(nexus_api, "get_mod_files", lambda *args: (calls.append("files") or (200, {"files": [{"file_id": 2}]})))
    monkeypatch.setattr(nexus_api, "get_mod_changelogs", lambda *args: pytest.fail("Unnecessary changelog request"))
    assert nexus_api.collect_for_update("synthetic", "marvelrivals", 1)["files_status"] == 200
    assert calls == ["info", "files"]


def test_authentication_failure_does_not_issue_more_requests(monkeypatch):
    monkeypatch.setattr(nexus_api, "get_mod_info", lambda *args: (401, {"error": True}))
    monkeypatch.setattr(nexus_api, "get_mod_files", lambda *args: pytest.fail("Request after authentication failure"))
    assert nexus_api.collect_for_update("synthetic", "marvelrivals", 1)["mod_info_status"] == 401


@pytest.mark.parametrize("status,data", [(429, {"error": True, "retry_after": 120}), (0, {"error": True}), (200, {"files": []})])
def test_failed_check_keeps_cached_mod_files(schema_db, monkeypatch, status, data):
    from core.api import server

    schema_db.execute("INSERT INTO mods(mod_id,game,name) VALUES(1,'marvelrivals','Existing')")
    schema_db.execute("INSERT INTO mod_files(mod_id,file_id,name,version) VALUES(1,2,'Variant','2')")
    schema_db.commit()
    before = schema_db.execute("SELECT * FROM mod_files").fetchall()
    monkeypatch.setattr(server, "get_api_key", lambda: "synthetic")
    monkeypatch.setattr(nexus_api, "collect_for_update", lambda *args: {
        "mod_info_status": 200, "mod_info": {"name": "New name"}, "files_status": status, "files": data})
    result = server._sync_mod_metadata(schema_db, 1, None, update_check=True)
    assert result.get("metadata_warning")
    assert schema_db.execute("SELECT * FROM mod_files").fetchall() == before
    assert schema_db.execute("SELECT name FROM mods WHERE mod_id=1").fetchone()[0] == "Existing"


def test_parallel_same_mod_checks_share_one_inflight_result(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def operation():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {"needs_update": False}

    joined = threading.Event()
    original_future = request_limits.Future

    class ObservedFuture(original_future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout)

    monkeypatch.setattr(request_limits, "Future", ObservedFuture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request_limits.singleflight, "same mod", operation)
        assert entered.wait(5)
        second = pool.submit(request_limits.singleflight, "same mod", operation)
        try:
            assert joined.wait(5)
        finally:
            release.set()
        assert first.result() == second.result() == {"needs_update": False}
    assert calls == [1]
    assert "same mod" not in request_limits._inflight


def test_timeout_returns_an_error_instead_of_hanging_check(monkeypatch):
    monkeypatch.setattr(nexus_api.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("offline")))
    status, data = nexus_api.get_mod_info("synthetic", "marvelrivals", 1)
    assert status == 0 and data["error"]
    assert "synthetic" not in json.dumps(data)
