"""Shared utility functions for afterpaths."""


def get_ide_display_name(adapter_name: str) -> str:
    """Get human-readable IDE/tool name from adapter name.

    Args:
        adapter_name: Internal adapter name (e.g., "claude_code", "cursor", "codex")

    Returns:
        Human-readable display name (e.g., "Claude Code", "Cursor", "Codex CLI")
    """
    names = {
        "claude_code": "Claude Code",
        "codex": "Codex CLI",
        "cursor": "Cursor",
    }
    return names.get(adapter_name, adapter_name)
