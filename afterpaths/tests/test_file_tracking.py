"""Tests for the artifacts ledger in file_tracking.py."""

from afterpaths.file_tracking import extract_artifacts
from afterpaths.sources.base import SessionEntry


def _user(content: str) -> SessionEntry:
    return SessionEntry(role="user", content=content)


def _read(path: str) -> SessionEntry:
    return SessionEntry(
        role="assistant",
        content="[Tool: Read]",
        tool_name="Read",
        tool_input={"file_path": path},
    )


def _write(path: str, content: str = "x") -> SessionEntry:
    return SessionEntry(
        role="assistant",
        content="[Tool: Write]",
        tool_name="Write",
        tool_input={"file_path": path, "content": content},
    )


def _edit(path: str) -> SessionEntry:
    return SessionEntry(
        role="assistant",
        content="[Tool: Edit]",
        tool_name="Edit",
        tool_input={"file_path": path, "old_string": "a", "new_string": "b"},
    )


def test_extract_artifacts_captures_triggering_user_message():
    entries = [
        _user("please update the config"),
        _edit("/project/config.py"),
    ]

    artifacts = extract_artifacts(entries)

    assert len(artifacts) == 1
    assert artifacts[0].triggering_user_message == "please update the config"
    assert artifacts[0].operation == "edit"


def test_extract_artifacts_captures_reference_reads():
    entries = [
        _user("refactor the handler"),
        _read("/project/handler.py"),
        _read("/project/types.py"),
        _write("/project/handler_v2.py"),
    ]

    artifacts = extract_artifacts(entries)

    assert len(artifacts) == 1
    refs = artifacts[0].reference_files
    assert any("handler.py" in r for r in refs)
    assert any("types.py" in r for r in refs)


def test_extract_artifacts_resets_reference_context_on_new_user_message():
    entries = [
        _user("read the handler"),
        _read("/project/handler.py"),
        _user("now write a new module"),
        _write("/project/new_module.py"),
    ]

    artifacts = extract_artifacts(entries)

    assert len(artifacts) == 1
    # The handler.py read belonged to the previous user turn, not this write's
    assert artifacts[0].reference_files == []
    assert artifacts[0].triggering_user_message == "now write a new module"


def test_extract_artifacts_truncates_long_user_messages():
    long_msg = "x" * 5000
    entries = [_user(long_msg), _write("/a.py")]

    artifacts = extract_artifacts(entries, message_char_limit=500)

    assert artifacts[0].triggering_user_message is not None
    assert len(artifacts[0].triggering_user_message) <= 503  # 500 + "..."
    assert artifacts[0].triggering_user_message.endswith("...")


def test_extract_artifacts_preserves_chronological_order():
    entries = [
        _user("do the work"),
        _write("/a.py"),
        _edit("/b.py"),
        _write("/c.py"),
    ]

    artifacts = extract_artifacts(entries)

    assert [a.file_path.split("/")[-1] for a in artifacts] == ["a.py", "b.py", "c.py"]


def test_extract_artifacts_ignores_read_only_sessions():
    entries = [_user("explore the codebase"), _read("/a.py"), _read("/b.py")]

    artifacts = extract_artifacts(entries)

    assert artifacts == []
