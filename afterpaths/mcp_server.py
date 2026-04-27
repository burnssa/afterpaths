"""MCP server exposing afterpaths tools to AI coding assistants.

Run with: python -m afterpaths.mcp_server
Or via entry point: afterpaths-mcp

IMPORTANT: No print() calls — stdio is the MCP protocol channel.
"""

import os
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP(
    "afterpaths",
    instructions=(
        "Afterpaths gives you access to your session history — previous conversations, "
        "discoveries, dead ends, and extracted rules from past coding sessions. "
        "Use these tools when you need to recall what was done before, avoid repeating "
        "past mistakes, or recover context lost to compaction."
    ),
)


def _load_env():
    """Load .env file for API key access."""
    from dotenv import load_dotenv

    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        return

    afterpaths_env = Path(__file__).parent.parent / ".env"
    if afterpaths_env.exists():
        load_dotenv(afterpaths_env)


def _find_session_by_id(session_id: str, sessions=None):
    """Find a session by ID prefix."""
    from .sources.base import list_all_sessions

    if sessions is None:
        sessions = list_all_sessions()
    return next((s for s in sessions if s.session_id.startswith(session_id)), None)


@mcp.tool()
def afterpaths_list_sessions(
    project: str | None = None,
    session_type: str = "main",
    limit: int = 10,
) -> dict:
    """List recent AI coding sessions for this project or all projects.

    Use when you need to see previous sessions, check what was done before,
    or find a specific session to recover context from. Shows session IDs,
    dates, sizes, and summaries.

    Args:
        project: Filter to specific project path. None = current directory.
        session_type: "main" (default), "agent", or "all".
        limit: Maximum sessions to return (default 10).
    """
    try:
        from .sources.base import list_all_sessions, get_sessions_for_cwd
        from .serializers import serialize_session_list

        if project:
            sessions = list_all_sessions(project_filter=project)
        else:
            sessions = get_sessions_for_cwd()

        if session_type != "all":
            sessions = [s for s in sessions if s.session_type == session_type]

        return serialize_session_list(sessions[:limit])
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def afterpaths_show_session(
    session_id: str,
    include_transcript: bool = False,
    entry_limit: int = 50,
) -> dict:
    """Show details of a specific session — its summary and optionally the transcript.

    Use when you need to recover context from a previous session, understand
    what happened in session X, or find specific decisions/discoveries.

    Args:
        session_id: Session ID or prefix (e.g., "a410a860").
        include_transcript: If True, include transcript entries.
        entry_limit: Max transcript entries to include (default 50).
    """
    try:
        from .serializers import serialize_summary, serialize_session_info, serialize_session_entry
        from .storage import get_afterpaths_dir
        from .sources.base import get_all_adapters

        session = _find_session_by_id(session_id)
        if not session:
            return {"error": f"Session not found: {session_id}"}

        # Read summary
        afterpaths_dir = get_afterpaths_dir()
        summary_path = afterpaths_dir / "summaries" / f"{session.session_id}.md"
        summary_content = summary_path.read_text() if summary_path.exists() else None

        result = serialize_summary(session, summary_content)

        if include_transcript:
            adapters = {a.name: a for a in get_all_adapters()}
            adapter = adapters.get(session.source)
            if adapter:
                entries = adapter.read_session(session)
                result["entries"] = [serialize_session_entry(e) for e in entries[:entry_limit]]
                result["total_entries"] = len(entries)
                if not entries and session.source == "cursor":
                    result["warning"] = (
                        "Cursor session returned 0 entries. The adapter does not yet parse "
                        "this session's chat/composer storage format. See the afterpaths "
                        "README (Known Limitations) for context."
                    )

        return result
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def afterpaths_show_artifacts(session_id: str) -> dict:
    """Show the artifacts ledger for a session — every file written/edited with provenance.

    Use this to answer "where did this file come from?" or "what did this
    session build?" without re-reading the full transcript. Each artifact
    carries the user message that triggered the write and the reference
    files read beforehand.

    Args:
        session_id: Session ID or prefix (e.g., "a410a860").
    """
    try:
        from .serializers import serialize_session_info, serialize_artifact
        from .sources.base import get_all_adapters
        from .file_tracking import extract_artifacts

        session = _find_session_by_id(session_id)
        if not session:
            return {"error": f"Session not found: {session_id}"}

        adapters = {a.name: a for a in get_all_adapters()}
        adapter = adapters.get(session.source)
        if not adapter:
            return {"error": f"No adapter for source: {session.source}"}

        entries = adapter.read_session(session)
        artifacts = extract_artifacts(entries)

        result = {
            **serialize_session_info(session),
            "artifacts": [serialize_artifact(a) for a in artifacts],
            "total_artifacts": len(artifacts),
        }
        if not entries and session.source == "cursor":
            result["warning"] = (
                "Cursor session returned 0 entries. The adapter does not yet parse "
                "this session's chat/composer storage format."
            )
        return result
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def afterpaths_summarize(
    session_id: str,
    notes: str = "",
    force: bool = False,
) -> dict:
    """Generate or retrieve a structured summary for a session.

    Use when context was lost to compaction, or to create a searchable record
    of what happened. Checks for existing summaries first.

    Requires an LLM API key (ANTHROPIC_API_KEY or OPENAI_API_KEY).

    Args:
        session_id: Session ID or prefix.
        notes: Additional context to guide summarization.
        force: Overwrite existing summary if True.
    """
    try:
        from .serializers import serialize_summary
        from .storage import get_afterpaths_dir, add_session_to_index
        from .sources.base import get_all_adapters
        from .git_refs import extract_all_git_refs

        session = _find_session_by_id(session_id)
        if not session:
            return {"error": f"Session not found: {session_id}"}

        afterpaths_dir = get_afterpaths_dir()
        summary_path = afterpaths_dir / "summaries" / f"{session.session_id}.md"

        # Return existing summary if available and not forcing
        if summary_path.exists() and not force:
            return {
                **serialize_summary(session, summary_path.read_text()),
                "status": "existing",
            }

        # Generate new summary
        from .summarize import summarize_session

        adapters = {a.name: a for a in get_all_adapters()}
        adapter = adapters.get(session.source)
        if not adapter:
            return {"error": f"No adapter for source: {session.source}"}

        entries = adapter.read_session(session)
        result = summarize_session(entries, session, notes)

        # Save
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(result.with_metadata_footer())

        # Update index
        git_refs = extract_all_git_refs(entries)
        git_refs_flat = list(git_refs.get("branches", set())) + list(git_refs.get("commits", set()))

        add_session_to_index(
            afterpaths_dir,
            session.session_id,
            session.source,
            session.path,
            summary_path,
            git_refs_flat,
        )

        return {
            **serialize_summary(session, result.with_metadata_footer()),
            "status": "generated",
            "model": f"{result.provider}/{result.model}",
        }
    except ImportError as e:
        return {"error": f"Missing dependency: {e}. Install with: pip install afterpaths[summarize]"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def afterpaths_search(
    query: str,
    deep: bool = False,
    project: str | None = None,
    regex: bool = False,
    case_sensitive: bool = False,
    limit: int = 20,
) -> dict:
    """Search across session summaries and transcripts for past discussions.

    Use when you need to check "have we seen this before?", find previous
    discussions about a topic, or locate sessions relevant to the current task.

    Searches summaries by default. When deep=False returns zero summary matches,
    automatically falls through to transcript search on un-summarized sessions —
    the result includes auto_expanded=True when this happens. Pass deep=True to
    search transcripts of every session regardless of summary hits.

    Args:
        query: Search query (text or regex pattern).
        deep: Also search raw transcripts (slower). Auto-escalated on 0 summary hits.
        project: Filter to specific project path. None = current directory.
        regex: Treat query as regex pattern.
        case_sensitive: Use case-sensitive matching (default False).
        limit: Maximum results (default 20).
    """
    try:
        from .sources.base import list_all_sessions, get_sessions_for_cwd
        from .search import search_combined, serialize_search_result

        if project:
            sessions = list_all_sessions(project_filter=project)
        else:
            sessions = get_sessions_for_cwd()

        sessions = [s for s in sessions if s.session_type == "main"]

        result = search_combined(
            query, sessions, deep=deep,
            case_sensitive=case_sensitive,
            regex=regex, max_results=limit,
        )
        return serialize_search_result(result)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def afterpaths_get_rules(
    category: str | None = None,
) -> dict:
    """Get extracted rules (dead ends, decisions, gotchas, patterns) for this project.

    Use when you need to know what past sessions discovered — what to avoid,
    what architectural decisions were made, and what patterns work well.

    Args:
        category: Filter to specific category: "dead_ends", "decisions", "gotchas", "patterns". None = all.
    """
    try:
        from .exporters.claude import ClaudeExporter

        exporter = ClaudeExporter()
        rules = exporter.load_existing(Path.cwd())

        if not rules:
            return {"rules": {}, "total_count": 0, "message": "No rules found. Run 'ap rules' to extract rules from session summaries."}

        if category:
            rules = {k: v for k, v in rules.items() if k == category}

        serialized = {}
        total = 0
        for cat, rule_list in rules.items():
            serialized[cat] = [
                {
                    "title": r.title,
                    "content": r.content,
                    "source_sessions": r.source_sessions,
                    "confidence": r.confidence,
                }
                for r in rule_list
            ]
            total += len(rule_list)

        return {"rules": serialized, "total_count": total}
    except Exception as e:
        return {"error": str(e)}


def main():
    """Entry point for the MCP server."""
    _load_env()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
