"""Adapter for OpenAI Codex CLI sessions stored in ~/.codex/sessions/"""

import json
import os
from datetime import datetime
from pathlib import Path

from .base import SessionEntry, SessionInfo, SourceAdapter


class CodexAdapter(SourceAdapter):
    """Adapter for OpenAI Codex CLI sessions.

    Codex stores session transcripts as JSONL files under:
    ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl

    The JSONL format contains events like:
    - thread.started, turn.started, turn.completed
    - item.* (messages, tool calls, etc.)
    - error events
    """

    name = "codex"

    @classmethod
    def get_sessions_dir(cls) -> Path:
        """Get the Codex sessions directory."""
        codex_home = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        return Path(codex_home) / "sessions"

    @classmethod
    def is_available(cls) -> bool:
        return cls.get_sessions_dir().exists()

    def list_sessions(self, project_filter: str | None = None) -> list[SessionInfo]:
        sessions = []
        sessions_dir = self.get_sessions_dir()

        if not sessions_dir.exists():
            return sessions

        # Walk through YYYY/MM/DD directory structure
        for jsonl_file in sessions_dir.glob("**/rollout-*.jsonl"):
            stat = jsonl_file.stat()

            # Extract session ID from filename (rollout-SESSION_ID.jsonl)
            session_id = jsonl_file.stem.replace("rollout-", "")

            # Try to determine project from session content
            project_name = self._get_project_from_session(jsonl_file)

            if project_filter and project_name != project_filter:
                continue

            summary = self._get_session_summary(jsonl_file)

            sessions.append(
                SessionInfo(
                    session_id=session_id,
                    source=self.name,
                    project=project_name or "unknown",
                    path=jsonl_file,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    size=stat.st_size,
                    summary=summary,
                )
            )

        return sessions

    def read_session(self, session: SessionInfo) -> list[SessionEntry]:
        entries = []
        current_model: str | None = None

        try:
            with open(session.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if event.get("type") == "turn_context":
                            payload = event.get("payload", {})
                            if isinstance(payload, dict):
                                current_model = payload.get("model") or payload.get(
                                    "model_name"
                                )
                            continue
                        parsed = self._normalize_event(event)
                        if current_model:
                            for entry in parsed:
                                if entry.role == "assistant" and not entry.model:
                                    entry.model = current_model
                        entries.extend(parsed)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        return entries

    def _normalize_event(self, event: dict) -> list[SessionEntry]:
        """Normalize a Codex event to SessionEntry objects."""
        entries = []
        event_type = event.get("type", "")
        timestamp = event.get("timestamp")
        model = event.get("model")

        if event_type == "response_item":
            payload = event.get("payload", {})
            if isinstance(payload, dict):
                event = payload
                event_type = event.get("type", "")
                model = event.get("model", model)

        # Handle different event types
        if event_type == "message":
            role = event.get("role", "")
            content = event.get("content", "")

            if isinstance(content, str) and content:
                entries.append(
                    SessionEntry(
                        role=self._normalize_role(role),
                        content=content,
                        timestamp=timestamp,
                        model=model,
                    )
                )
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type", "")

                        if block_type in ("text", "input_text", "output_text"):
                            text = block.get("text", "")
                            if text:
                                entries.append(
                                    SessionEntry(
                                        role=self._normalize_role(role),
                                        content=text,
                                        timestamp=timestamp,
                                        model=model,
                                    )
                                )
                        elif block_type in ("tool_use", "function_call"):
                            tool_name = block.get("name", block.get("function", "unknown"))
                            entries.append(
                                SessionEntry(
                                    role="assistant",
                                    content=f"[Tool: {tool_name}]",
                                    timestamp=timestamp,
                                    tool_name=tool_name,
                                    tool_input=block.get("input", block.get("arguments")),
                                    model=model,
                                )
                            )
                        elif block_type == "tool_result":
                            tool_content = block.get("content", block.get("output", ""))
                            is_error = block.get("is_error")
                            if is_error is None:
                                tool_text = str(tool_content).lower()
                                is_error = "error" in tool_text or "rejected" in tool_text
                            entries.append(
                                SessionEntry(
                                    role="tool_result",
                                    content=str(tool_content),
                                    timestamp=timestamp,
                                    is_error=is_error,
                                )
                            )

        elif event_type == "function_call":
            # Legacy function call format
            name = event.get("name", "unknown")
            entries.append(
                SessionEntry(
                    role="assistant",
                    content=f"[Tool: {name}]",
                    timestamp=timestamp,
                    tool_name=name,
                    tool_input=event.get("arguments"),
                    model=model,
                )
            )

        elif event_type == "function_call_output":
            # Legacy function result format
            output = event.get("output", "")
            output_text = str(output).lower() if output else ""
            is_error = (
                "error" in output_text
                or "rejected" in output_text
                or "refused" in output_text
            )
            entries.append(
                SessionEntry(
                    role="tool_result",
                    content=str(output),
                    timestamp=timestamp,
                    is_error=is_error,
                )
            )

        elif event_type in ("item.created", "item"):
            # Item-based events
            item = event.get("item", event)
            item_type = item.get("type", "")

            if item_type == "message":
                role = item.get("role", "")
                content = item.get("content", [])

                if isinstance(content, str):
                    entries.append(
                        SessionEntry(
                            role=self._normalize_role(role),
                            content=content,
                            timestamp=timestamp,
                            model=model,
                        )
                    )
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                entries.append(
                                    SessionEntry(
                                        role=self._normalize_role(role),
                                        content=part.get("text", ""),
                                        timestamp=timestamp,
                                        model=model,
                                    )
                                )
                            elif part.get("type") in ("input_text", "output_text"):
                                entries.append(
                                    SessionEntry(
                                        role=self._normalize_role(role),
                                        content=part.get("text", ""),
                                        timestamp=timestamp,
                                        model=model,
                                    )
                                )

            elif item_type == "function_call":
                name = item.get("name", "unknown")
                entries.append(
                    SessionEntry(
                        role="assistant",
                        content=f"[Tool: {name}]",
                        timestamp=timestamp,
                        tool_name=name,
                        tool_input=item.get("arguments"),
                        model=model,
                    )
                )

            elif item_type == "function_call_output":
                output = item.get("output", "")
                entries.append(
                    SessionEntry(
                        role="tool_result",
                        content=str(output),
                        timestamp=timestamp,
                    )
                )

        return entries

    def _normalize_role(self, role: str) -> str:
        """Normalize role names to standard format."""
        role_map = {
            "human": "user",
            "system": "user",
        }
        return role_map.get(role.lower(), role.lower())

    @staticmethod
    def _extract_first_text(content: object) -> str | None:
        """Extract the first text payload from content."""
        if isinstance(content, str):
            return content or None
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in (
                    "text",
                    "input_text",
                    "output_text",
                ):
                    text = part.get("text", "")
                    if text:
                        return text
        return None

    def _get_project_from_session(self, jsonl_path: Path) -> str | None:
        """Try to extract project path from session content."""
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        event_type = event.get("type", "")
                        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}

                        # Look for working directory or project info
                        cwd = event.get("cwd") or event.get("working_directory")
                        if cwd:
                            return cwd
                        if event_type in ("session_meta", "turn_context"):
                            cwd = payload.get("cwd") or payload.get("working_directory")
                            if cwd:
                                return cwd
                        # Check in metadata
                        metadata = event.get("metadata", {})
                        if metadata.get("cwd"):
                            return metadata["cwd"]
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return None

    def _get_session_summary(self, jsonl_path: Path) -> str | None:
        """Extract first user message as summary."""
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        # Look for first user message
                        event_type = event.get("type")
                        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
                        message_event = event

                        if event_type == "response_item":
                            message_event = payload

                        if (
                            message_event.get("type") == "message"
                            and message_event.get("role") == "user"
                        ):
                            content = message_event.get("content", "")
                            text = self._extract_first_text(content)
                            if text:
                                return text[:60] + "..." if len(text) > 60 else text
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return None
