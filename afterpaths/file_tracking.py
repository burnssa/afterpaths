"""Extract file modifications from session transcripts for commit matching."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess

from .sources.base import SessionEntry, SessionInfo


@dataclass
class FileModification:
    """A file modification detected in a session."""

    file_path: str
    operation: str  # 'edit', 'write', 'notebook_edit'
    timestamp: str | None = None


@dataclass
class SessionFileActivity:
    """Summary of file activity in a session."""

    session_id: str
    session_modified: datetime
    files_modified: set[str]  # files that were written/edited
    files_read: set[str]  # files that were only read
    modifications: list[FileModification]


@dataclass
class Artifact:
    """A file write/edit captured with its provenance.

    Unlike FileModification (which is just path+op+time), an Artifact carries
    the user message that triggered the change and the reference files read
    between that message and the write — enough to answer "where did this
    file come from?" without re-reading the raw transcript.
    """

    file_path: str
    operation: str  # 'write', 'edit', 'notebook_edit'
    timestamp: str | None
    triggering_user_message: str | None
    reference_files: list[str]


def extract_artifacts(entries: list[SessionEntry], message_char_limit: int = 500) -> list[Artifact]:
    """Build a chronological artifacts ledger from session entries.

    For each file write/edit, captures the most recent user message before it
    and any files read since that message (the "reference context" the write
    was built from).
    """
    artifacts: list[Artifact] = []
    last_user_msg: str | None = None
    reads_since_user_msg: list[str] = []

    for entry in entries:
        if entry.role == "user" and not entry.tool_name:
            content = entry.content or ""
            if message_char_limit and len(content) > message_char_limit:
                content = content[:message_char_limit] + "..."
            last_user_msg = content
            reads_since_user_msg = []
            continue

        if not entry.tool_name or not entry.tool_input:
            continue

        tool = entry.tool_name.lower()
        inputs = entry.tool_input

        if tool == "read":
            file_path = inputs.get("file_path")
            if file_path:
                normalized = _normalize_path(file_path)
                if normalized not in reads_since_user_msg:
                    reads_since_user_msg.append(normalized)
            continue

        if tool in ("write", "edit", "notebookedit"):
            file_path = inputs.get("file_path") or inputs.get("notebook_path")
            if not file_path:
                continue
            operation = "notebook_edit" if tool == "notebookedit" else tool
            artifacts.append(Artifact(
                file_path=_normalize_path(file_path),
                operation=operation,
                timestamp=entry.timestamp,
                triggering_user_message=last_user_msg,
                reference_files=list(reads_since_user_msg),
            ))

    return artifacts


def extract_file_activity(entries: list[SessionEntry], session: SessionInfo) -> SessionFileActivity:
    """Extract file modification activity from session entries."""
    modifications = []
    files_modified = set()
    files_read = set()

    for entry in entries:
        if not entry.tool_name or not entry.tool_input:
            continue

        tool = entry.tool_name.lower()
        inputs = entry.tool_input

        # File write operations
        if tool == 'write':
            file_path = inputs.get('file_path')
            if file_path:
                files_modified.add(_normalize_path(file_path))
                modifications.append(FileModification(
                    file_path=_normalize_path(file_path),
                    operation='write',
                    timestamp=entry.timestamp,
                ))

        elif tool == 'edit':
            file_path = inputs.get('file_path')
            if file_path:
                files_modified.add(_normalize_path(file_path))
                modifications.append(FileModification(
                    file_path=_normalize_path(file_path),
                    operation='edit',
                    timestamp=entry.timestamp,
                ))

        elif tool == 'notebookedit':
            notebook_path = inputs.get('notebook_path')
            if notebook_path:
                files_modified.add(_normalize_path(notebook_path))
                modifications.append(FileModification(
                    file_path=_normalize_path(notebook_path),
                    operation='notebook_edit',
                    timestamp=entry.timestamp,
                ))

        # File read operations (track but distinguish from writes)
        elif tool == 'read':
            file_path = inputs.get('file_path')
            if file_path:
                normalized = _normalize_path(file_path)
                # Only add to reads if not already modified
                if normalized not in files_modified:
                    files_read.add(normalized)

    return SessionFileActivity(
        session_id=session.session_id,
        session_modified=session.modified,
        files_modified=files_modified,
        files_read=files_read,
        modifications=modifications,
    )


def _normalize_path(path: str) -> str:
    """Normalize a file path for comparison."""
    # Convert to absolute path and resolve symlinks
    try:
        return str(Path(path).resolve())
    except Exception:
        return path


def get_commit_files(commit_ref: str, repo_path: str | None = None) -> dict:
    """Get files changed in a commit.

    Returns dict with:
        - files: set of file paths that were changed
        - commit_time: datetime of the commit
        - message: commit message
        - error: error message if failed
    """
    cmd = ['git', 'show', '--name-only', '--format=%H%n%aI%n%s', commit_ref]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=10,
        )

        if result.returncode != 0:
            return {'error': result.stderr.strip() or 'Commit not found'}

        lines = result.stdout.strip().split('\n')
        if len(lines) < 3:
            return {'error': 'Unexpected git output format'}

        commit_hash = lines[0]
        commit_time = datetime.fromisoformat(lines[1].replace('Z', '+00:00'))
        message = lines[2]

        # Files are listed after a blank line
        files = set()
        in_files = False
        for line in lines[3:]:
            if not line.strip():
                in_files = True
                continue
            if in_files and line.strip():
                # Normalize to absolute path
                if repo_path:
                    file_path = str(Path(repo_path) / line.strip())
                else:
                    file_path = str(Path.cwd() / line.strip())
                files.add(_normalize_path(file_path))

        return {
            'hash': commit_hash,
            'time': commit_time,
            'message': message,
            'files': files,
        }

    except subprocess.TimeoutExpired:
        return {'error': 'Git command timed out'}
    except Exception as e:
        return {'error': str(e)}


def get_file_activity_cached(session: SessionInfo, adapter) -> SessionFileActivity:
    """Get file activity for a session, using cache if available."""
    from .cache import get_cached_file_activity, cache_file_activity

    session_mtime = session.path.stat().st_mtime

    # Try cache first
    cached = get_cached_file_activity(session.session_id, session_mtime)
    if cached:
        return SessionFileActivity(
            session_id=session.session_id,
            session_modified=session.modified,
            files_modified=set(cached["files_modified"]),
            files_read=set(cached["files_read"]),
            modifications=[],  # Not cached, but not needed for matching
        )

    # Cache miss - extract and cache
    entries = adapter.read_session(session)
    activity = extract_file_activity(entries, session)

    cache_file_activity(
        session.session_id,
        session_mtime,
        activity.files_modified,
        activity.files_read,
    )

    return activity


def find_sessions_for_commit(
    commit_ref: str,
    sessions: list[SessionInfo],
    adapter,
    repo_path: str | None = None,
    max_days_before: int = 7,
) -> list[tuple[SessionInfo, SessionFileActivity, set[str]]]:
    """Find sessions that likely produced a commit based on file modifications.

    Args:
        commit_ref: Git commit reference
        sessions: List of sessions to search
        adapter: Source adapter for reading sessions
        repo_path: Optional repo path for git commands
        max_days_before: Max days before commit to search (default 7)

    Returns list of (session, activity, matching_files) tuples, sorted by relevance.
    """
    from datetime import timedelta

    commit_info = get_commit_files(commit_ref, repo_path)

    if 'error' in commit_info:
        return []

    commit_files = commit_info['files']
    commit_time = commit_info['time'].replace(tzinfo=None)

    matches = []

    for session in sessions:
        session_time = session.modified.replace(tzinfo=None)

        # Skip sessions that are too new (more than 1 day after commit)
        # This allows for sessions that were active during the commit
        if session_time > commit_time + timedelta(days=1):
            continue

        # Skip sessions outside the search window
        if session_time < commit_time - timedelta(days=max_days_before):
            continue

        # Use cached file activity when possible
        activity = get_file_activity_cached(session, adapter)

        # Find files that were modified in both session and commit
        matching_modified = activity.files_modified & commit_files

        if matching_modified:
            # Calculate time proximity score (closer to commit = better)
            time_diff = abs((session_time - commit_time).total_seconds())
            time_score = 1.0 / (1.0 + time_diff / 3600)  # Decay over hours

            matches.append((session, activity, matching_modified, time_score))

    # Sort by: number of matching files (primary), time proximity (secondary)
    matches.sort(key=lambda x: (-len(x[2]), -x[3]))

    # Return without the time_score
    return [(m[0], m[1], m[2]) for m in matches]
