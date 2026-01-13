"""Cache for extracted session data to speed up repeated operations."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .storage import get_afterpaths_dir


def get_cache_dir() -> Path:
    """Get or create the cache directory."""
    cache_dir = get_afterpaths_dir() / "cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def get_cached_file_activity(session_id: str, session_mtime: float) -> dict | None:
    """Get cached file activity for a session if still valid.

    Returns None if cache miss or stale.
    """
    cache_file = get_cache_dir() / f"{session_id}.json"

    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())

        # Check if cache is still valid (session file hasn't changed)
        if data.get("session_mtime") != session_mtime:
            return None

        return data.get("activity")
    except (json.JSONDecodeError, KeyError):
        return None


def cache_file_activity(
    session_id: str,
    session_mtime: float,
    files_modified: set[str],
    files_read: set[str],
):
    """Cache file activity for a session."""
    cache_file = get_cache_dir() / f"{session_id}.json"

    data = {
        "session_mtime": session_mtime,
        "cached_at": datetime.now().isoformat(),
        "activity": {
            "files_modified": sorted(files_modified),
            "files_read": sorted(files_read),
        }
    }

    try:
        cache_file.write_text(json.dumps(data, indent=2))
    except Exception:
        pass  # Cache write failures are non-fatal


def clear_cache():
    """Clear all cached data."""
    cache_dir = get_cache_dir()
    for cache_file in cache_dir.glob("*.json"):
        try:
            cache_file.unlink()
        except Exception:
            pass
