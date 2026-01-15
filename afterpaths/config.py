"""Global configuration for afterpaths.

Stores user preferences in ~/.afterpaths/config.json (not project-scoped).
"""

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path


def get_global_afterpaths_dir() -> Path:
    """Get the global afterpaths directory (~/.afterpaths/)."""
    global_dir = Path.home() / ".afterpaths"
    global_dir.mkdir(exist_ok=True)
    return global_dir


def get_global_config() -> dict:
    """Load global config from ~/.afterpaths/config.json."""
    config_path = get_global_afterpaths_dir() / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_global_config(config: dict) -> None:
    """Save global config to ~/.afterpaths/config.json."""
    config_path = get_global_afterpaths_dir() / "config.json"
    config_path.write_text(json.dumps(config, indent=2, default=str))


def get_anonymous_id() -> str:
    """Get or generate anonymous ID for analytics.

    The ID is a SHA256 hash of a random UUID, making it:
    - Unique per installation
    - Not reversible to any machine identifier
    - Persistent across sessions
    """
    config = get_global_config()

    if "anonymous_id" not in config:
        # Generate a new anonymous ID
        random_id = str(uuid.uuid4())
        config["anonymous_id"] = hashlib.sha256(random_id.encode()).hexdigest()[:16]
        config["anonymous_id_created_at"] = datetime.now().isoformat()
        save_global_config(config)

    return config["anonymous_id"]


def has_analytics_decision() -> bool:
    """Check if user has made an analytics opt-in/out decision."""
    config = get_global_config()
    return "analytics_opted_in" in config


def is_analytics_enabled() -> bool:
    """Check if analytics is enabled (user opted in)."""
    config = get_global_config()
    return config.get("analytics_opted_in", False)


def save_analytics_decision(opted_in: bool) -> None:
    """Save user's analytics opt-in/out decision."""
    config = get_global_config()
    config["analytics_opted_in"] = opted_in
    config["analytics_decided_at"] = datetime.now().isoformat()

    # Generate anonymous ID if opting in
    if opted_in and "anonymous_id" not in config:
        get_anonymous_id()

    save_global_config(config)


def disable_analytics() -> None:
    """Disable analytics (opt out)."""
    save_analytics_decision(False)


def enable_analytics() -> None:
    """Enable analytics (opt in)."""
    save_analytics_decision(True)
