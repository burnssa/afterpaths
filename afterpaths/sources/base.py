"""Base classes for source adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SessionEntry:
    """Normalized conversation entry."""

    role: str  # 'user', 'assistant', 'tool_result'
    content: str
    timestamp: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    is_error: bool = False  # True if tool result was an error/rejection
    model: str | None = None  # LLM model used (for assistant entries)


@dataclass
class SessionInfo:
    """Session metadata."""

    session_id: str
    source: str  # 'claude_code', 'cursor', etc.
    project: str
    path: Path
    modified: datetime
    size: int
    summary: str | None = None

    @property
    def session_type(self) -> str:
        """Classify session as 'agent' (sub-process) or 'main' (regular conversation)."""
        if self.session_id.startswith("agent-"):
            return "agent"
        return "main"


class SourceAdapter(ABC):
    """Base class for AI coding tool adapters."""

    name: str

    @abstractmethod
    def list_sessions(self, project_filter: str | None = None) -> list[SessionInfo]:
        """List available sessions, optionally filtered by project path."""
        pass

    @abstractmethod
    def read_session(self, session: SessionInfo) -> list[SessionEntry]:
        """Read and normalize session entries."""
        pass

    @classmethod
    def is_available(cls) -> bool:
        """Check if this adapter's data source exists."""
        return True


def get_all_adapters() -> list[SourceAdapter]:
    """Get all available source adapters."""
    from .claude_code import ClaudeCodeAdapter
    from .cursor import CursorAdapter

    adapters = []
    for adapter_class in [ClaudeCodeAdapter, CursorAdapter]:
        if adapter_class.is_available():
            adapters.append(adapter_class())
    return adapters


def list_all_sessions(project_filter: str | None = None) -> list[SessionInfo]:
    """List sessions from all available sources."""
    sessions = []
    for adapter in get_all_adapters():
        sessions.extend(adapter.list_sessions(project_filter))
    return sorted(sessions, key=lambda x: x.modified, reverse=True)


def get_sessions_for_cwd() -> list[SessionInfo]:
    """Get sessions from all adapters for current working directory."""
    import os

    return list_all_sessions(project_filter=os.getcwd())
