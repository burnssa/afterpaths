"""Adapter for Cursor sessions stored in workspaceStorage."""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .base import CachedStats, SessionEntry, SessionInfo, SourceAdapter


class CursorAdapter(SourceAdapter):
    """Adapter for Cursor AI sessions stored in workspaceStorage.

    Cursor stores chat history in SQLite databases (state.vscdb) within
    workspace-specific folders in ~/Library/Application Support/Cursor/User/workspaceStorage/

    Cursor also stores code tracking stats (suggested/accepted lines) in
    the global state.vscdb at ~/Library/Application Support/Cursor/User/globalStorage/
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
    def get_global_storage_dir(cls) -> Path:
        """Get platform-specific globalStorage directory."""
        import platform

        system = platform.system()
        if system == "Darwin":  # macOS
            return Path.home() / "Library/Application Support/Cursor/User/globalStorage"
        elif system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "Cursor/User/globalStorage"
        else:  # Linux
            return Path.home() / ".config/Cursor/User/globalStorage"

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

                # Get timestamp from session data (ms) or fall back to file mtime
                last_updated = session_data.get("lastUpdatedAt")
                if last_updated and isinstance(last_updated, (int, float)):
                    modified = datetime.fromtimestamp(last_updated / 1000)
                else:
                    modified = datetime.fromtimestamp(stat.st_mtime)

                sessions.append(
                    SessionInfo(
                        session_id=session_id,
                        source=self.name,
                        project=project_name,
                        path=vscdb_path,
                        modified=modified,
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

        Handles multiple Cursor data formats:
        - Old: workbench.panel.aichat.view.aichat.chatdata (dict or list)
        - Newer: composer.composerData (dict with composers key)
        - Current: allComposers (list of composer objects)
        """
        sessions = {}

        try:
            conn = sqlite3.connect(str(vscdb_path))
            cursor = conn.cursor()

            # Query for chat data (all known keys)
            cursor.execute(
                "SELECT [key], value FROM ItemTable WHERE [key] IN "
                "('aiService.prompts', 'workbench.panel.aichat.view.aichat.chatdata', "
                "'composer.composerData', 'allComposers')"
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
                    # Composer chats - can have nested allComposers or composers dict
                    if isinstance(data, dict):
                        # Check for allComposers list inside composer.composerData
                        all_composers = data.get("allComposers", [])
                        if isinstance(all_composers, list):
                            for composer in all_composers:
                                if isinstance(composer, dict):
                                    comp_id = composer.get("composerId", "")
                                    if comp_id:
                                        sessions[f"composer-{comp_id}"] = composer

                        # Also check for older composers dict format
                        composers = data.get("composers", {})
                        if isinstance(composers, dict):
                            for comp_id, composer in composers.items():
                                if isinstance(composer, dict):
                                    sessions[f"composer-{comp_id}"] = composer

                elif key == "allComposers":
                    # Standalone allComposers key (alternative location)
                    if isinstance(data, list):
                        for composer in data:
                            if isinstance(composer, dict):
                                comp_id = composer.get("composerId", composer.get("id", ""))
                                if comp_id:
                                    sessions[f"composer-{comp_id}"] = composer

            conn.close()

        except sqlite3.Error:
            pass

        return sessions

    def _extract_summary(self, session_data: dict) -> str | None:
        """Extract a summary from session data."""
        # Try to get name (newer composer format)
        if session_data.get("name"):
            return session_data["name"]

        # Try to get title (older format)
        if session_data.get("title"):
            return session_data["title"]

        # Try first message as summary
        messages = session_data.get("messages", [])
        if messages:
            first_msg = messages[0]
            content = first_msg.get("content", "")
            if isinstance(content, str):
                return content[:60] + "..." if len(content) > 60 else content

        return None


    def get_cached_stats(self) -> CachedStats | None:
        """Get code tracking stats from Cursor's global storage.

        Cursor stores daily code tracking stats in aiCodeTracking.dailyStats keys.
        Format: {"date": "YYYY-MM-DD", "tabSuggestedLines": N, "tabAcceptedLines": N,
                 "composerSuggestedLines": N, "composerAcceptedLines": N}
        """
        global_db = self.get_global_storage_dir() / "state.vscdb"
        if not global_db.exists():
            return None

        try:
            conn = sqlite3.connect(str(global_db))
            cursor = conn.cursor()

            # Query for daily stats entries (last 30 days)
            cursor.execute(
                "SELECT [key], value FROM ItemTable WHERE [key] LIKE 'aiCodeTracking.dailyStats%'"
            )

            activity_by_date: dict[str, dict] = {}
            for key, value in cursor.fetchall():
                if not value:
                    continue
                try:
                    data = json.loads(value)
                    date = data.get("date")
                    if date:
                        activity_by_date[date] = {
                            "tab_suggested": data.get("tabSuggestedLines", 0),
                            "tab_accepted": data.get("tabAcceptedLines", 0),
                            "composer_suggested": data.get("composerSuggestedLines", 0),
                            "composer_accepted": data.get("composerAcceptedLines", 0),
                        }
                except json.JSONDecodeError:
                    continue

            conn.close()

            if not activity_by_date:
                return None

            return CachedStats(activity_by_date=activity_by_date)

        except sqlite3.Error:
            return None

    def get_code_tracking_stats(self, days: int = 7) -> dict:
        """Get aggregated code tracking stats for the last N days.

        Returns dict with totals for suggested/accepted lines.
        """
        cached = self.get_cached_stats()
        if not cached or not cached.activity_by_date:
            return {
                "tab_suggested": 0,
                "tab_accepted": 0,
                "composer_suggested": 0,
                "composer_accepted": 0,
                "tab_acceptance_rate": 0,
                "composer_acceptance_rate": 0,
            }

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        totals = {
            "tab_suggested": 0,
            "tab_accepted": 0,
            "composer_suggested": 0,
            "composer_accepted": 0,
        }

        for date, stats in cached.activity_by_date.items():
            if date >= cutoff:
                totals["tab_suggested"] += stats.get("tab_suggested", 0)
                totals["tab_accepted"] += stats.get("tab_accepted", 0)
                totals["composer_suggested"] += stats.get("composer_suggested", 0)
                totals["composer_accepted"] += stats.get("composer_accepted", 0)

        # Calculate acceptance rates
        if totals["tab_suggested"] > 0:
            totals["tab_acceptance_rate"] = totals["tab_accepted"] / totals["tab_suggested"] * 100
        else:
            totals["tab_acceptance_rate"] = 0

        if totals["composer_suggested"] > 0:
            totals["composer_acceptance_rate"] = totals["composer_accepted"] / totals["composer_suggested"] * 100
        else:
            totals["composer_acceptance_rate"] = 0

        return totals


def get_cursor_sessions_for_cwd() -> list[SessionInfo]:
    """Get Cursor sessions for current working directory."""
    return CursorAdapter().list_sessions(project_filter=os.getcwd())
