"""Bound Nexus traffic and honor server cooldowns across concurrent callers."""
from __future__ import annotations

import hashlib
import math
import threading
import time
from concurrent.futures import Future
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

requests = threading.BoundedSemaphore(3)
_lock = threading.Lock()
_cooldowns = {}
_inflight = {}


def _key(api_key):
    return hashlib.sha256(api_key.encode()).digest()


def retry_after(api_key):
    with _lock:
        return max(0, math.ceil(_cooldowns.get(_key(api_key), 0) - time.time()))


def _reset(value, now):
    try:
        result = float(value)
        return result if math.isfinite(result) else now + 60
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
        except (AttributeError, ValueError):
            return now + 60


def observe(api_key, status, headers):
    headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    now = time.time()
    deadline = 0
    if status == 429:
        value = headers.get("retry-after")
        try:
            seconds = float(value)
            deadline = now + max(1, seconds) if math.isfinite(seconds) else now + 60
        except (TypeError, ValueError):
            try:
                deadline = max(now + 1, parsedate_to_datetime(value).timestamp())
            except (TypeError, ValueError, AttributeError):
                deadline = now + 60
    if headers.get("x-rl-daily-remaining") == "0" and headers.get("x-rl-hourly-remaining") == "0":
        resets = [_reset(headers.get(key), now) for key in ("x-rl-daily-reset", "x-rl-hourly-reset")]
        deadline = max(deadline, min(reset for reset in resets if reset > now) if any(reset > now for reset in resets) else now + 60)
    if deadline:
        with _lock:
            for key in list(_cooldowns):
                if _cooldowns[key] <= now:
                    del _cooldowns[key]
            key = _key(api_key)
            _cooldowns[key] = max(deadline, _cooldowns.get(key, 0))


def singleflight(key, operation):
    """Share an in-flight check; never cache a stale completed result."""
    with _lock:
        future = _inflight.get(key)
        leader = future is None
        if leader:
            future = _inflight[key] = Future()
    if not leader:
        return future.result()
    try:
        result = operation()
        future.set_result(result)
        return result
    except BaseException as error:
        future.set_exception(error)
        raise
    finally:
        with _lock:
            del _inflight[key]
