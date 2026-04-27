"""Tests for search auto-escalation behavior."""

from datetime import datetime
from pathlib import Path

import pytest

from afterpaths.search import search_combined
from afterpaths.sources.base import SessionEntry, SessionInfo


class _StubAdapter:
    """In-memory adapter that returns canned entries per session."""

    name = "claude_code"

    def __init__(self, entries_by_session_id: dict[str, list[SessionEntry]]):
        self._entries = entries_by_session_id

    def list_sessions(self, project_filter=None):
        return []

    def read_session(self, session: SessionInfo) -> list[SessionEntry]:
        return self._entries.get(session.session_id, [])

    @classmethod
    def is_available(cls):
        return True


@pytest.fixture
def afterpaths_tmp(tmp_path, monkeypatch):
    """Run search with a tmp cwd so get_afterpaths_dir writes to an isolated dir."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".afterpaths" / "summaries").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def patch_adapters(monkeypatch):
    """Install a stub adapter so search_transcripts can read our fake sessions."""
    def _install(entries_by_session_id):
        stub = _StubAdapter(entries_by_session_id)
        monkeypatch.setattr(
            "afterpaths.sources.base.get_all_adapters",
            lambda: [stub],
        )
    return _install


def _make_session(session_id: str, tmp_path: Path) -> SessionInfo:
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text("")
    return SessionInfo(
        session_id=session_id,
        source="claude_code",
        project=str(tmp_path),
        path=path,
        modified=datetime.now(),
        size=100,
    )


def _write_summary(afterpaths_tmp: Path, session_id: str, text: str) -> None:
    (afterpaths_tmp / ".afterpaths" / "summaries" / f"{session_id}.md").write_text(text)


def test_auto_escalates_when_summary_returns_zero(afterpaths_tmp, patch_adapters):
    session = _make_session("aaaa1111", afterpaths_tmp)
    entries = [SessionEntry(role="user", content="we discussed expanded_prompts.py here")]
    patch_adapters({session.session_id: entries})

    # No summary exists for this session, so auto-deep should search its transcript
    result = search_combined("expanded_prompts", [session], deep=False)

    assert result.auto_expanded is True
    assert result.search_mode == "auto-deep"
    assert result.total_matches == 1


def test_does_not_escalate_when_summary_matches(afterpaths_tmp, patch_adapters):
    session = _make_session("bbbb2222", afterpaths_tmp)
    _write_summary(afterpaths_tmp, session.session_id, "this summary mentions widgets")
    patch_adapters({session.session_id: []})

    result = search_combined("widgets", [session], deep=False)

    assert result.auto_expanded is False
    assert result.search_mode == "summaries"
    assert result.total_matches == 1


def test_explicit_deep_not_marked_auto_expanded(afterpaths_tmp, patch_adapters):
    session = _make_session("cccc3333", afterpaths_tmp)
    entries = [SessionEntry(role="user", content="foo bar baz")]
    patch_adapters({session.session_id: entries})

    result = search_combined("foo", [session], deep=True)

    assert result.auto_expanded is False
    assert result.search_mode == "deep"


def test_auto_deep_skips_summarized_sessions(afterpaths_tmp, patch_adapters):
    """Auto-escalation targets un-summarized sessions only — summaries that
    returned zero genuinely don't match."""
    with_summary = _make_session("dddd4444", afterpaths_tmp)
    without_summary = _make_session("eeee5555", afterpaths_tmp)

    _write_summary(afterpaths_tmp, with_summary.session_id, "nothing relevant here")

    # Both transcripts contain the query, but only the un-summarized one should be read
    entries = [SessionEntry(role="user", content="needle")]
    patch_adapters({
        with_summary.session_id: entries,
        without_summary.session_id: entries,
    })

    result = search_combined("needle", [with_summary, without_summary], deep=False)

    assert result.auto_expanded is True
    # Only one match — from the un-summarized session
    assert result.total_matches == 1
    assert result.matches[0].session.session_id == without_summary.session_id
