"""Base classes for source adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class TokenUsage:
    """Token usage for a model."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class CachedStats:
    """Stats that platforms may pre-compute.

    Adapters can return these from get_cached_stats() if the platform
    maintains its own stats cache. This avoids re-calculating what's
    already been computed elsewhere.
    """

    total_sessions: int | None = None
    total_messages: int | None = None
    total_tool_calls: int | None = None
    tokens_by_model: dict[str, TokenUsage] | None = None
    activity_by_hour: dict[int, int] | None = None
    activity_by_date: dict[str, dict] | None = None  # date -> {messages, sessions, tool_calls}
    first_session_date: str | None = None


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

    def get_cached_stats(self) -> CachedStats | None:
        """Return pre-computed stats if the platform maintains a cache.

        Override in subclasses that have access to platform-maintained
        stats caches (e.g., Claude Code's stats-cache.json).

        Returns None if no cached stats are available.
        """
        return None


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
