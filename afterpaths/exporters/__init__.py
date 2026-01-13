"""Rule exporters for different AI coding assistants."""

from .base import RuleExporter, ExportResult, Rule
from .claude import ClaudeExporter
from .cursor import CursorExporter

# Registry of available exporters
EXPORTERS = {
    "claude": ClaudeExporter,
    "cursor": CursorExporter,
}


def get_exporter(name: str) -> RuleExporter:
    """Get an exporter by name."""
    if name not in EXPORTERS:
        raise ValueError(f"Unknown exporter: {name}. Available: {list(EXPORTERS.keys())}")
    return EXPORTERS[name]()


def get_all_exporters() -> list[RuleExporter]:
    """Get instances of all available exporters."""
    return [cls() for cls in EXPORTERS.values()]
