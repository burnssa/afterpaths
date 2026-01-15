"""Adapter for Cursor sessions stored in workspaceStorage."""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .base import SessionEntry, SessionInfo, SourceAdapter


class CursorAdapter(SourceAdapter):
    """Adapter for Cursor AI sessions stored in workspaceStorage.

    Cursor stores chat history in SQLite databases (state.vscdb) within
    workspace-specific folders in ~/Library/Application Support/Cursor/User/workspaceStorage/
    """

    name = "cursor"

    @classmethod
    def get_storage_dir(cls) -> Path:
        """Get platform-specific workspaceStorage directory."""
        import platform

        system = platform.system()
        if system == "Darwin":  # macOS
            return Path.home() / "Library/Application Support/Cursor/User/workspaceStorage"
        elif system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "Cursor/User/workspaceStorage"
        else:  # Linux
            return Path.home() / ".config/Cursor/User/workspaceStorage"

    @classmethod
    def is_available(cls) -> bool:
        return cls.get_storage_dir().exists()

    def list_sessions(self, project_filter: str | None = None) -> list[SessionInfo]:
        sessions = []
        storage_dir = self.get_storage_dir()

        if not storage_dir.exists():
            return sessions

        for workspace_dir in storage_dir.iterdir():
            if not workspace_dir.is_dir():
                continue

            vscdb_path = workspace_dir / "state.vscdb"
            if not vscdb_path.exists():
                continue

            # Try to get workspace folder from workspace.json
            project_name = self._get_workspace_folder(workspace_dir)
            if not project_name:
                project_name = workspace_dir.name  # Fall back to hash

            if project_filter and project_name != project_filter:
                continue

            # Check if there are any chat sessions
            chat_data = self._get_chat_data(vscdb_path)
            if not chat_data:
                continue

            for session_id, session_data in chat_data.items():
                stat = vscdb_path.stat()
                summary = self._extract_summary(session_data)
                sessions.append(
                    SessionInfo(
                        session_id=session_id,
                        source=self.name,
                        project=project_name,
                        path=vscdb_path,
                        modified=datetime.fromtimestamp(stat.st_mtime),
                        size=stat.st_size,
                        summary=summary,
                    )
                )

        return sessions

    def read_session(self, session: SessionInfo) -> list[SessionEntry]:
        entries = []
        chat_data = self._get_chat_data(session.path)

        if not chat_data or session.session_id not in chat_data:
            return entries

        session_data = chat_data[session.session_id]
        messages = session_data.get("messages", [])

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Handle different content formats
            if isinstance(content, list):
                # Multi-part content
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            entries.append(
                                SessionEntry(
                                    role=self._normalize_role(role),
                                    content=part.get("text", ""),
                                    timestamp=msg.get("timestamp"),
                                )
                            )
                        elif part.get("type") == "tool_use":
                            entries.append(
                                SessionEntry(
                                    role="assistant",
                                    content=f"[Tool: {part.get('name', 'unknown')}]",
                                    timestamp=msg.get("timestamp"),
                                    tool_name=part.get("name"),
                                    tool_input=part.get("input"),
                                )
                            )
                        elif part.get("type") == "tool_result":
                            entries.append(
                                SessionEntry(
                                    role="tool_result",
                                    content=str(part.get("content", "")),
                                    timestamp=msg.get("timestamp"),
                                )
                            )
                    elif isinstance(part, str):
                        entries.append(
                            SessionEntry(
                                role=self._normalize_role(role),
                                content=part,
                                timestamp=msg.get("timestamp"),
                            )
                        )
            elif isinstance(content, str):
                entries.append(
                    SessionEntry(
                        role=self._normalize_role(role),
                        content=content,
                        timestamp=msg.get("timestamp"),
                    )
                )

        return entries

    def _normalize_role(self, role: str) -> str:
        """Normalize role names to standard format."""
        role_map = {
            "human": "user",
            "ai": "assistant",
            "system": "user",
        }
        return role_map.get(role.lower(), role.lower())

    def _get_workspace_folder(self, workspace_dir: Path) -> str | None:
        """Extract the actual workspace folder path from workspace.json."""
        workspace_json = workspace_dir / "workspace.json"
        if workspace_json.exists():
            try:
                data = json.loads(workspace_json.read_text())
                folder = data.get("folder")
                if folder:
                    # folder is a URI like "file:///Users/..."
                    if folder.startswith("file://"):
                        return folder[7:]  # Remove file:// prefix
                    return folder
            except (json.JSONDecodeError, KeyError):
                pass
        return None

    def _get_chat_data(self, vscdb_path: Path) -> dict:
        """Extract chat data from state.vscdb SQLite database.

        Returns a dict of session_id -> session_data
        """
        sessions = {}

        try:
            conn = sqlite3.connect(str(vscdb_path))
            cursor = conn.cursor()

            # Query for chat data (AI chat panel)
            cursor.execute(
                "SELECT [key], value FROM ItemTable WHERE [key] IN "
                "('aiService.prompts', 'workbench.panel.aichat.view.aichat.chatdata', "
                "'composer.composerData')"
            )

            for key, value in cursor.fetchall():
                if not value:
                    continue

                try:
                    data = json.loads(value)
                except json.JSONDecodeError:
                    continue

                if key == "workbench.panel.aichat.view.aichat.chatdata":
                    # This is typically a list of chat sessions
                    if isinstance(data, list):
                        for i, chat in enumerate(data):
                            if isinstance(chat, dict) and chat.get("messages"):
                                chat_id = chat.get("id", f"chat-{i}")
                                sessions[chat_id] = chat
                    elif isinstance(data, dict):
                        # Could be a dict with tabs or other structure
                        tabs = data.get("tabs", [])
                        for i, tab in enumerate(tabs):
                            if isinstance(tab, dict) and tab.get("messages"):
                                chat_id = tab.get("id", f"tab-{i}")
                                sessions[chat_id] = tab

                elif key == "composer.composerData":
                    # Composer chats (newer format)
                    if isinstance(data, dict):
                        composers = data.get("composers", {})
                        for comp_id, composer in composers.items():
                            if isinstance(composer, dict):
                                sessions[f"composer-{comp_id}"] = composer

            conn.close()

        except sqlite3.Error:
            pass

        return sessions

    def _extract_summary(self, session_data: dict) -> str | None:
        """Extract a summary from session data."""
        # Try to get title or first message as summary
        if session_data.get("title"):
            return session_data["title"]

        messages = session_data.get("messages", [])
        if messages:
            first_msg = messages[0]
            content = first_msg.get("content", "")
            if isinstance(content, str):
                return content[:60] + "..." if len(content) > 60 else content

        return None


def get_cursor_sessions_for_cwd() -> list[SessionInfo]:
    """Get Cursor sessions for current working directory."""
    return CursorAdapter().list_sessions(project_filter=os.getcwd())
