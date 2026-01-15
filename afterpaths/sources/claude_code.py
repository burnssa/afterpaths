"""Adapter for Claude Code sessions stored in ~/.claude/projects/"""

import json
import os
from datetime import datetime
from pathlib import Path

from .base import SessionEntry, SessionInfo, SourceAdapter


class ClaudeCodeAdapter(SourceAdapter):
    """Adapter for Claude Code sessions stored in ~/.claude/projects/"""

    name = "claude_code"

    @classmethod
    def is_available(cls) -> bool:
        return (Path.home() / ".claude" / "projects").exists()

    def list_sessions(self, project_filter: str | None = None) -> list[SessionInfo]:
        sessions = []
        projects_dir = Path.home() / ".claude" / "projects"

        if not projects_dir.exists():
            return sessions

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            project_name = self._decode_project_name(project_dir.name)

            if project_filter and project_name != project_filter:
                continue

            for jsonl_file in project_dir.glob("*.jsonl"):
                stat = jsonl_file.stat()
                summary = self._get_session_summary(jsonl_file)
                sessions.append(
                    SessionInfo(
                        session_id=jsonl_file.stem,
                        source=self.name,
                        project=project_name,
                        path=jsonl_file,
                        modified=datetime.fromtimestamp(stat.st_mtime),
                        size=stat.st_size,
                        summary=summary,
                    )
                )

        return sessions

    def read_session(self, session: SessionInfo) -> list[SessionEntry]:
        entries = []

        with open(session.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    parsed = self._normalize_entry(raw)
                    entries.extend(parsed)
                except json.JSONDecodeError:
                    continue

        return entries

    def _normalize_entry(self, raw: dict) -> list[SessionEntry]:
        """Normalize a raw JSONL entry to SessionEntry objects.

        Returns a list because one raw entry may contain multiple logical entries
        (e.g., tool results embedded in user messages).
        """
        entries = []
        entry_type = raw.get("type")
        timestamp = raw.get("timestamp")
        message = raw.get("message", {})
        model = message.get("model")  # LLM model for assistant entries

        if entry_type == "user":
            content = message.get("content", "")

            if isinstance(content, str):
                entries.append(
                    SessionEntry(role="user", content=content, timestamp=timestamp)
                )
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_result":
                            tool_content = block.get("content", "")
                            if isinstance(tool_content, list):
                                tool_content = "\n".join(
                                    b.get("text", str(b))
                                    for b in tool_content
                                    if isinstance(b, dict)
                                )
                            is_error = block.get("is_error", False)
                            entries.append(
                                SessionEntry(
                                    role="tool_result",
                                    content=str(tool_content),
                                    timestamp=timestamp,
                                    is_error=is_error,
                                )
                            )
                        elif block.get("type") == "text":
                            entries.append(
                                SessionEntry(
                                    role="user",
                                    content=block.get("text", ""),
                                    timestamp=timestamp,
                                )
                            )

        elif entry_type == "assistant":
            content = message.get("content", [])

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type")

                        if block_type == "text":
                            text = block.get("text", "")
                            if text:
                                entries.append(
                                    SessionEntry(
                                        role="assistant",
                                        content=text,
                                        timestamp=timestamp,
                                        model=model,
                                    )
                                )

                        elif block_type == "tool_use":
                            entries.append(
                                SessionEntry(
                                    role="assistant",
                                    content=f"[Tool: {block.get('name', 'unknown')}]",
                                    timestamp=timestamp,
                                    tool_name=block.get("name"),
                                    tool_input=block.get("input"),
                                    model=model,
                                )
                            )

        return entries

    def _get_session_summary(self, jsonl_path: Path) -> str | None:
        """Extract session summary if present."""
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        if raw.get("type") == "summary":
                            return raw.get("summary")
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return None

    @staticmethod
    def _decode_project_name(encoded_name: str) -> str:
        """Decode project directory name to path.

        Claude Code uses hyphen-separated paths, e.g.:
        -Users-burnssa-Code-afterpaths -> /Users/burnssa/Code/afterpaths

        Since hyphens can appear in directory names, we try to find a path
        that actually exists on the filesystem.
        """
        if not encoded_name.startswith("-"):
            return encoded_name

        # Remove leading hyphen and split by hyphen
        parts = encoded_name[1:].split("-")

        # Try to find a valid path by greedily joining parts
        def find_valid_path(idx: int, current_path: str) -> str | None:
            if idx >= len(parts):
                return current_path if Path(current_path).exists() else None

            # Try joining with next part using hyphen (keeping it as folder name)
            for end_idx in range(len(parts), idx, -1):
                segment = "-".join(parts[idx:end_idx])
                candidate = f"{current_path}/{segment}"
                if Path(candidate).exists():
                    result = find_valid_path(end_idx, candidate)
                    if result:
                        return result

            return None

        result = find_valid_path(0, "")
        if result:
            return result

        # Fallback: just replace hyphens with slashes
        return "/" + encoded_name[1:].replace("-", "/")
