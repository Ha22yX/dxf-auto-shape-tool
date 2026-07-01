"""Application version and GitHub release checks."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from backend.config import BASE_DIR


GITHUB_RELEASES_URL = "https://github.com/Ha22yX/dxf-auto-shape-tool/releases"
GITHUB_LATEST_RELEASE_API = (
    "https://api.github.com/repos/Ha22yX/dxf-auto-shape-tool/releases/latest"
)
VERSION_INFO_PATH = BASE_DIR / "packaging" / "version-info.txt"
VERSION_CHECK_CACHE_SECONDS = 15 * 60
CURRENT_VERSION_FALLBACK = "v1.0.2"

_version_cache: dict[str, Any] | None = None
_version_cache_time = 0.0


def get_current_version() -> str:
    """Read the version shown in the packaged executable metadata."""

    try:
        text = VERSION_INFO_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return CURRENT_VERSION_FALLBACK

    match = re.search(r"ProductVersion'\s*,\s*u'([^']+)'", text)
    if match:
        return match.group(1).strip()

    match = re.search(r"ProductVersion['\"]?\s*,\s*['\"]([^'\"]+)['\"]", text)
    if match:
        return match.group(1).strip()

    return CURRENT_VERSION_FALLBACK


def _version_parts(version: str | None) -> tuple[int, ...]:
    if not version:
        return (0,)
    numbers = re.findall(r"\d+", version)
    if not numbers:
        return (0,)
    return tuple(int(item) for item in numbers[:4])


def is_newer_version(latest: str | None, current: str | None) -> bool:
    latest_parts = _version_parts(latest)
    current_parts = _version_parts(current)
    size = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (size - len(latest_parts))
    current_parts += (0,) * (size - len(current_parts))
    return latest_parts > current_parts


def _fetch_latest_release(timeout: float = 3.0) -> dict[str, Any]:
    req = urllib.request.Request(
        GITHUB_LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "DXF-Auto-Shape-Tool",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    latest_version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    latest_url = str(payload.get("html_url") or GITHUB_RELEASES_URL).strip()
    return {
        "latest_version": latest_version or None,
        "latest_release_url": latest_url or GITHUB_RELEASES_URL,
    }


def get_version_status(force: bool = False) -> dict[str, Any]:
    """Return current version and best-effort GitHub latest release status."""

    global _version_cache, _version_cache_time

    current_version = get_current_version()
    now = time.time()
    if (
        not force
        and _version_cache is not None
        and now - _version_cache_time < VERSION_CHECK_CACHE_SECONDS
    ):
        cached = dict(_version_cache)
        cached["current_version"] = current_version
        cached["update_available"] = is_newer_version(
            cached.get("latest_version"), current_version
        )
        return cached

    status: dict[str, Any] = {
        "current_version": current_version,
        "release_url": GITHUB_RELEASES_URL,
        "latest_version": None,
        "latest_release_url": GITHUB_RELEASES_URL,
        "update_available": False,
        "check_error": False,
    }

    try:
        latest = _fetch_latest_release()
    except Exception:
        status["check_error"] = True
        return status

    status.update(latest)
    status["update_available"] = is_newer_version(
        status.get("latest_version"), current_version
    )
    _version_cache = dict(status)
    _version_cache_time = now
    return status
