"""JSON serialization for sessions and entries. Shared by CLI --json and MCP server."""

from .sources.base import SessionEntry, SessionInfo


def serialize_session_info(session: SessionInfo) -> dict:
    """Serialize a SessionInfo to a JSON-compatible dict."""
    return {
        "session_id": session.session_id,
        "source": session.source,
        "project": session.project,
        "modified": session.modified.isoformat(),
        "size": session.size,
        "summary": session.summary,
        "session_type": session.session_type,
    }


def serialize_session_list(sessions: list[SessionInfo]) -> dict:
    """Serialize a list of sessions with metadata."""
    return {
        "total_count": len(sessions),
        "sessions": [serialize_session_info(s) for s in sessions],
    }


def serialize_summary(session: SessionInfo, summary_content: str | None) -> dict:
    """Serialize session metadata + summary content."""
    from .storage import get_afterpaths_dir

    afterpaths_dir = get_afterpaths_dir()
    summary_path = afterpaths_dir / "summaries" / f"{session.session_id}.md"
    has_afterpaths_summary = summary_path.exists()

    return {
        **serialize_session_info(session),
        "summary_content": summary_content,
        "has_afterpaths_summary": has_afterpaths_summary,
    }


def serialize_session_entry(entry: SessionEntry) -> dict:
    """Serialize a SessionEntry to a JSON-compatible dict."""
    return {
        "role": entry.role,
        "content": entry.content,
        "timestamp": entry.timestamp,
        "tool_name": entry.tool_name,
        "tool_input": entry.tool_input,
        "is_error": entry.is_error,
        "model": entry.model,
    }
