import json
import urllib.error
import urllib.request
import ssl
from typing import Any, Dict, Optional, Tuple

from core.config import settings
from core.nexus import request_limits

try:
    # Disable SSL certificate verification globally for Nexus API calls to bypass expired cert issues
    SSL_CONTEXT = ssl._create_unverified_context()
except AttributeError:
    SSL_CONTEXT = ssl.create_default_context()

BASE_URL = "https://api.nexusmods.com/v1"
DEFAULT_GAME = "marvelrivals"
APP_NAME = "Project_ModManager_Rivals"
from core.version import APP_VERSION  # noqa: F401

def _coerce_key(raw: str | None) -> str:
    return raw.strip() if raw else ""


def get_api_key(*_, **__) -> Optional[str]:
    active_settings = settings.SETTINGS
    value = _coerce_key(getattr(active_settings, "nexus_api_key", ""))
    if value:
        return value

    # If the in-memory settings are stale, reload once from disk.
    refreshed = settings.reload_settings()
    value = _coerce_key(getattr(refreshed, "nexus_api_key", ""))
    return value or None

def _get(api_key: str, path: str) -> Tuple[int, Any]:
    with request_limits.requests:
        cooldown = request_limits.retry_after(api_key)
        if cooldown:
            return 429, {"error": True, "message": f"Nexus request limit reached. Try again in {cooldown} seconds.", "retry_after": cooldown}
        return _get_unlocked(api_key, path)


def _get_unlocked(api_key: str, path: str) -> Tuple[int, Any]:
    url = f"{BASE_URL}{path}"
    headers = {
        "apikey": api_key,
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        "Application-Name": APP_NAME,
        "Application-Version": APP_VERSION,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=30) as resp:
            status = resp.getcode()
            request_limits.observe(api_key, status, getattr(resp, "headers", {}))
            data = resp.read()
            try:
                return status, json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                return status, data.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        request_limits.observe(api_key, e.code, e.headers)
        body = ""
        try:
            body = e.read().decode("utf-8")
            parsed = json.loads(body)
        except Exception:
            parsed = body if body else str(e)
        return e.code, {"error": True, "message": str(e), "body": parsed, "retry_after": request_limits.retry_after(api_key)}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"error": True, "message": str(e)}

def get_mod_info(api_key: str, game: str, mod_id: int) -> Tuple[int, Any]:
    return _get(api_key, f"/games/{game}/mods/{mod_id}.json")

def get_mod_files(api_key: str, game: str, mod_id: int) -> Tuple[int, Any]:
    return _get(api_key, f"/games/{game}/mods/{mod_id}/files.json")

def get_mod_changelogs(api_key: str, game: str, mod_id: int) -> Tuple[int, Any]:
    return _get(api_key, f"/games/{game}/mods/{mod_id}/changelogs.json")


def get_mod_file_download_link(api_key: str, game: str, mod_id: int, file_id: int) -> Tuple[int, Any]:
    """Retrieve the temporary download link metadata for a specific mod file."""
    return _get(api_key, f"/games/{game}/mods/{mod_id}/files/{file_id}/download_link.json")

def get_mod_by_md5(api_key: str, game: str, md5_hash: str) -> Tuple[int, Any]:
    """Look up a mod by a file's MD5 hash."""
    return _get(api_key, f"/games/{game}/mods/md5_search/{md5_hash}.json")


def collect_for_update(api_key: str, game: str, mod_id: int) -> Dict[str, Any]:
    """Update checks need mod/file metadata, not a third changelog request."""
    status, info = get_mod_info(api_key, game, mod_id)
    result = {"game": game, "mod_id": mod_id, "mod_info_status": status, "mod_info": info}
    if status == 200:
        status, files = get_mod_files(api_key, game, mod_id)
        result.update(files_status=status, files=files)
    return result


def collect_all_for_mod(api_key: str, game: str, mod_id: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"game": game, "mod_id": mod_id}
    s, d = get_mod_info(api_key, game, mod_id)
    out["mod_info_status"], out["mod_info"] = s, d
    s, d = get_mod_files(api_key, game, mod_id)
    out["files_status"], out["files"] = s, d
    s, d = get_mod_changelogs(api_key, game, mod_id)
    out["changelogs_status"], out["changelogs"] = s, d
    return out

__all__ = [
    'DEFAULT_GAME','get_api_key','collect_all_for_mod','get_mod_files','get_mod_info','get_mod_changelogs','get_mod_file_download_link', 'get_mod_by_md5'
]
