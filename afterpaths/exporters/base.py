"""Base class for rule exporters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Rule:
    """A single extracted rule."""

    category: str  # dead_ends, decisions, gotchas, patterns
    title: str
    content: str
    source_sessions: list[str] = field(default_factory=list)
    confidence: str = "high"  # high, medium
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ExportResult:
    """Result of an export operation."""

    target: str
    files_written: list[Path]
    rules_count: int
    success: bool = True
    error: str | None = None


class RuleExporter(ABC):
    """Abstract base class for rule exporters.

    Each exporter handles a specific AI coding assistant's rule format.
    """

    name: str  # e.g., "claude", "cursor"
    description: str  # Human-readable description

    @abstractmethod
    def detect(self, project_root: Path) -> bool:
        """Return True if this target should be used for this project.

        Detection can be based on:
        - Presence of config files (e.g., .cursor/ directory)
        - Explicit user configuration
        - Default behavior
        """
        pass

    @abstractmethod
    def export(self, rules: dict[str, list[Rule]], project_root: Path) -> ExportResult:
        """Write rules to the target format.

        Args:
            rules: Dict mapping category names to lists of Rule objects
            project_root: Root directory of the project

        Returns:
            ExportResult with details of what was written
        """
        pass

    @abstractmethod
    def load_existing(self, project_root: Path) -> dict[str, list[Rule]]:
        """Load existing rules from the target for merging.

        Returns empty dict if no existing rules found.
        """
        pass

    def get_output_paths(self, project_root: Path) -> list[Path]:
        """Return the paths where this exporter writes files.

        Useful for dry-run and status display.
        """
        return []
