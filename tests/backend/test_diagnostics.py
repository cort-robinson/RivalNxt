from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from core.diagnostics import DiagnosticLogHandler, build_report, redact


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(data_dir=tmp_path, nexus_api_key="private-nexus-value",
                           aes_key_hex="private-aes-value", marvel_rivals_root="C:\\Games\\Rivals",
                           marvel_rivals_local_downloads_root="C:\\Users\\Alice\\Downloads")


@pytest.mark.parametrize("value", [
    'apikey="secret value"', "api_key=secret", "Authorization: Bearer secret",
    '"password": "secret"', "nxm://marvelrivals/mods/1?key=secret",
    "https://example.com/download?token=secret", "C:\\Users\\Alice\\private.txt",
    "/home/Alice/private.txt", "alice@example.com", "\\\\host\\share\\private.txt",
])
def test_redacts_sensitive_log_forms(value):
    result = redact(value)
    for secret in ("secret", "Alice", "alice@", "host\\share"):
        assert secret not in result


def test_report_redacts_activity_logs_and_configured_secrets(settings):
    (settings.data_dir / "backend.log").write_text(
        "failure private-nexus-value private-aes-value C:\\Users\\Alice\\mods\\foo.pak\n"
    )
    handler = DiagnosticLogHandler(lambda: settings)
    handler.emit(logging.makeLogRecord({"msg": "Nexus private-nexus-value failed", "levelno": 40, "levelname": "ERROR"}))
    report = build_report(settings, lambda limit: {"entries": [{"kind": "failed", "summary": "private-nexus-value"}]}, handler)
    text = json.dumps(report)
    assert "private-nexus-value" not in text
    assert "private-aes-value" not in text
    assert "Alice" not in text
    assert report["configuration"]["nexus_key_configured"] is True
    assert "settings" not in report


def test_report_bounds_logs_and_handles_activity_failure(settings):
    (settings.data_dir / "backend.log").write_text("warning\n" * 20000)
    def unavailable(limit):
        raise OSError("private error")
    report = build_report(settings, unavailable, DiagnosticLogHandler(lambda: settings))
    assert len(report["recent_logs"]) == 150
    assert report["unavailable"] == ["Recent activity could not be read."]
    assert "private error" not in json.dumps(report)


def test_ring_redacts_before_storage_and_is_bounded(settings):
    handler = DiagnosticLogHandler(lambda: settings)
    for _ in range(300):
        handler.emit(logging.makeLogRecord({"msg": "private-nexus-value", "levelno": 40, "levelname": "ERROR"}))
    assert len(handler.snapshot()) == 150
    assert "private-nexus-value" not in json.dumps(handler.snapshot())


def test_secret_is_redacted_before_truncation():
    secret = "x" * 100
    assert "x" not in redact("a" * 3990 + secret, (secret,))


@pytest.mark.parametrize("value, sensitive", [
    ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
    ("Proxy-Authorization: Digest username=private, response=secret", "private"),
    ("Cookie: session=first; custom_auth=second; other=third", "second"),
    ("Set-Cookie: session=private; Secure; HttpOnly", "private"),
    ('{"Authorization": "Basic dXNlcjpwYXNz"}', "dXNlcjpwYXNz"),
    ("ftp://username:password@example.com/private", "username"),
    ("wss://example.com/private?session=unknown", "unknown"),
    (r"https:\/\/example.com\/private?token=unknown", "example.com"),
    ("token=unknown session_id=private", "unknown"),
])
def test_redacts_complete_auth_headers_and_arbitrary_urls(value, sensitive):
    assert sensitive not in redact(value)


def test_known_root_does_not_leave_private_path_suffix():
    assert "personal" not in redact(r"C:\Users\Alice\personal\medical.txt", roots=(r"C:\Users\Alice",))
