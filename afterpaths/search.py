"""Cross-session search engine for summaries and transcripts."""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .serializers import serialize_session_info
from .sources.base import SessionInfo


@dataclass
class SearchMatch:
    """A single search match within a session."""

    session: SessionInfo
    matched_text: str
    context: str  # surrounding ~100 chars before/after
    location: str  # "summary" or "transcript"
    score: float = 1.0


@dataclass
class SearchResult:
    """Result of a search operation."""

    query: str
    matches: list[SearchMatch] = field(default_factory=list)
    total_matches: int = 0
    sessions_searched: int = 0
    search_mode: str = "summaries"  # "summaries", "transcripts", "combined", "deep"
    time_ms: int = 0
    auto_expanded: bool = False  # True when deep=False found 0 and we escalated


def _build_pattern(query: str, case_sensitive: bool, regex: bool) -> re.Pattern:
    """Build a compiled regex pattern from the query."""
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        return re.compile(query, flags)
    return re.compile(re.escape(query), flags)


def _extract_context(text: str, match: re.Match, context_chars: int = 100) -> str:
    """Extract context around a regex match."""
    start = max(0, match.start() - context_chars)
    end = min(len(text), match.end() + context_chars)

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""

    snippet = text[start:end]
    # Clean up whitespace
    snippet = " ".join(snippet.split())
    return f"{prefix}{snippet}{suffix}"


def search_summaries(
    query: str,
    sessions: list[SessionInfo],
    case_sensitive: bool = False,
    regex: bool = False,
    max_results: int = 20,
) -> SearchResult:
    """Search across session summaries (.afterpaths/summaries/*.md)."""
    from .storage import get_afterpaths_dir

    start = time.monotonic()
    pattern = _build_pattern(query, case_sensitive, regex)
    afterpaths_dir = get_afterpaths_dir()
    summaries_dir = afterpaths_dir / "summaries"

    matches = []
    sessions_searched = 0

    for session in sessions:
        summary_path = summaries_dir / f"{session.session_id}.md"
        if not summary_path.exists():
            # Also check Claude's built-in summary
            if session.summary:
                sessions_searched += 1
                m = pattern.search(session.summary)
                if m:
                    matches.append(SearchMatch(
                        session=session,
                        matched_text=m.group(),
                        context=_extract_context(session.summary, m),
                        location="summary (built-in)",
                        score=0.5,  # lower score for built-in summaries
                    ))
            continue

        sessions_searched += 1
        content = summary_path.read_text()

        for m in pattern.finditer(content):
            matches.append(SearchMatch(
                session=session,
                matched_text=m.group(),
                context=_extract_context(content, m),
                location="summary",
                score=1.0,
            ))
            if len(matches) >= max_results:
                break

        if len(matches) >= max_results:
            break

    elapsed = int((time.monotonic() - start) * 1000)

    return SearchResult(
        query=query,
        matches=matches[:max_results],
        total_matches=len(matches),
        sessions_searched=sessions_searched,
        search_mode="summaries",
        time_ms=elapsed,
    )


def search_transcripts(
    query: str,
    sessions: list[SessionInfo],
    case_sensitive: bool = False,
    regex: bool = False,
    max_results: int = 20,
) -> SearchResult:
    """Search across session transcripts (full entry content)."""
    from .sources.base import get_all_adapters

    start = time.monotonic()
    pattern = _build_pattern(query, case_sensitive, regex)

    # Build adapter lookup
    adapters = {a.name: a for a in get_all_adapters()}

    matches = []
    sessions_searched = 0

    for session in sessions:
        adapter = adapters.get(session.source)
        if not adapter:
            continue

        sessions_searched += 1

        try:
            entries = adapter.read_session(session)
        except Exception:
            continue

        for entry in entries:
            if not entry.content:
                continue

            m = pattern.search(entry.content)
            if m:
                matches.append(SearchMatch(
                    session=session,
                    matched_text=m.group(),
                    context=_extract_context(entry.content, m),
                    location=f"transcript ({entry.role})",
                    score=0.3,  # lower score for raw transcript
                ))
                if len(matches) >= max_results:
                    break

        if len(matches) >= max_results:
            break

    elapsed = int((time.monotonic() - start) * 1000)

    return SearchResult(
        query=query,
        matches=matches[:max_results],
        total_matches=len(matches),
        sessions_searched=sessions_searched,
        search_mode="transcripts",
        time_ms=elapsed,
    )


def search_combined(
    query: str,
    sessions: list[SessionInfo],
    deep: bool = False,
    case_sensitive: bool = False,
    regex: bool = False,
    max_results: int = 20,
) -> SearchResult:
    """Search summaries first, optionally fall back to transcripts.

    With deep=True, also searches transcripts for sessions without summary matches.

    When deep=False and the summary search returns zero matches, the search
    auto-escalates to transcript search across un-summarized sessions — the set
    most likely to hide matches that summaries dropped. The returned
    SearchResult has auto_expanded=True in that case.
    """
    from .storage import get_afterpaths_dir

    start = time.monotonic()

    # Search summaries first
    summary_result = search_summaries(
        query, sessions, case_sensitive, regex, max_results
    )

    matches = list(summary_result.matches)
    sessions_with_matches = {m.session.session_id for m in matches}

    auto_expanded = False
    effective_deep = deep
    if not deep and len(matches) == 0:
        effective_deep = True
        auto_expanded = True

    if effective_deep and len(matches) < max_results:
        if auto_expanded:
            # Only search transcripts of un-summarized sessions — summaries that
            # returned nothing genuinely don't match and re-scanning their raw
            # transcripts is expensive and low-yield.
            summaries_dir = get_afterpaths_dir() / "summaries"
            candidate_sessions = [
                s for s in sessions
                if not (summaries_dir / f"{s.session_id}.md").exists()
            ]
        else:
            candidate_sessions = [
                s for s in sessions if s.session_id not in sessions_with_matches
            ]
        remaining_limit = max_results - len(matches)

        transcript_result = search_transcripts(
            query, candidate_sessions, case_sensitive, regex, remaining_limit
        )
        matches.extend(transcript_result.matches)

    matches.sort(key=lambda m: m.score, reverse=True)

    elapsed = int((time.monotonic() - start) * 1000)

    if deep:
        mode = "deep"
    elif auto_expanded:
        mode = "auto-deep"
    else:
        mode = "summaries"

    return SearchResult(
        query=query,
        matches=matches[:max_results],
        total_matches=len(matches),
        sessions_searched=len(sessions),
        search_mode=mode,
        time_ms=elapsed,
        auto_expanded=auto_expanded,
    )


def serialize_search_result(result: SearchResult) -> dict:
    """Serialize a SearchResult to a JSON-compatible dict."""
    return {
        "query": result.query,
        "total_matches": result.total_matches,
        "sessions_searched": result.sessions_searched,
        "search_mode": result.search_mode,
        "auto_expanded": result.auto_expanded,
        "time_ms": result.time_ms,
        "matches": [
            {
                "session": serialize_session_info(m.session),
                "matched_text": m.matched_text,
                "context": m.context,
                "location": m.location,
                "score": m.score,
            }
            for m in result.matches
        ],
    }
