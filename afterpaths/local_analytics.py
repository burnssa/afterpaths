"""Local analytics storage for afterpaths.

Stores daily usage snapshots in ~/.afterpaths/analytics.json.
Users can review their own data before deciding to share with community.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

from .config import get_global_afterpaths_dir
from .analytics import detect_llm_errors


@dataclass
class DailySnapshot:
    """A single day's usage statistics."""

    date: str  # YYYY-MM-DD
    sessions: int = 0
    messages: int = 0
    tool_calls: int = 0
    rejections: int = 0
    failures: int = 0
    model_stats: dict[str, dict] = field(default_factory=dict)
    # Format: {"claude-opus-4": {"tool_calls": 100, "rejections": 2, "failures": 1}}
    ides_used: list[str] = field(default_factory=list)
    stacks_used: list[str] = field(default_factory=list)
    projects_active: int = 0

    @property
    def rejection_rate(self) -> float:
        return (self.rejections / self.tool_calls * 100) if self.tool_calls > 0 else 0

    @property
    def failure_rate(self) -> float:
        return (self.failures / self.tool_calls * 100) if self.tool_calls > 0 else 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DailySnapshot":
        return cls(**data)


@dataclass
class LifetimeStats:
    """Aggregated lifetime statistics."""

    first_recorded: str | None = None
    last_recorded: str | None = None
    total_days_active: int = 0
    total_sessions: int = 0
    total_messages: int = 0
    total_tool_calls: int = 0
    total_rejections: int = 0
    total_failures: int = 0
    model_stats: dict[str, dict] = field(default_factory=dict)
    ides_used: list[str] = field(default_factory=list)
    stacks_used: list[str] = field(default_factory=list)

    @property
    def rejection_rate(self) -> float:
        return (self.total_rejections / self.total_tool_calls * 100) if self.total_tool_calls > 0 else 0

    @property
    def failure_rate(self) -> float:
        return (self.total_failures / self.total_tool_calls * 100) if self.total_tool_calls > 0 else 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LifetimeStats":
        return cls(**data)


def get_analytics_path() -> Path:
    """Get path to local analytics file."""
    return get_global_afterpaths_dir() / "analytics.json"


def load_analytics() -> dict:
    """Load analytics data from disk."""
    path = get_analytics_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {"version": 1, "snapshots": [], "lifetime": {}}
    return {"version": 1, "snapshots": [], "lifetime": {}}


def save_analytics(data: dict) -> None:
    """Save analytics data to disk."""
    path = get_analytics_path()
    path.write_text(json.dumps(data, indent=2, default=str))


def record_daily_snapshot(snapshot: DailySnapshot) -> None:
    """Record or update a daily snapshot.

    If a snapshot for this date already exists, it will be replaced.
    Also updates lifetime aggregates.
    """
    data = load_analytics()
    snapshots = data.get("snapshots", [])

    # Find existing snapshot for this date
    existing_idx = None
    for i, s in enumerate(snapshots):
        if s.get("date") == snapshot.date:
            existing_idx = i
            break

    snapshot_dict = snapshot.to_dict()

    if existing_idx is not None:
        # Replace existing snapshot
        old_snapshot = snapshots[existing_idx]
        snapshots[existing_idx] = snapshot_dict
        # Adjust lifetime stats (subtract old, add new)
        _update_lifetime_stats(data, old_snapshot, subtract=True)
        _update_lifetime_stats(data, snapshot_dict, subtract=False)
    else:
        # Add new snapshot
        snapshots.append(snapshot_dict)
        _update_lifetime_stats(data, snapshot_dict, subtract=False)

    # Sort snapshots by date (most recent last)
    snapshots.sort(key=lambda x: x.get("date", ""))

    # Keep only last 90 days of detailed snapshots
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    data["snapshots"] = [s for s in snapshots if s.get("date", "") >= cutoff]

    save_analytics(data)


def _update_lifetime_stats(data: dict, snapshot: dict, subtract: bool = False) -> None:
    """Update lifetime stats based on a snapshot."""
    lifetime = data.setdefault("lifetime", {})
    multiplier = -1 if subtract else 1

    # Update totals
    lifetime["total_sessions"] = lifetime.get("total_sessions", 0) + snapshot.get("sessions", 0) * multiplier
    lifetime["total_messages"] = lifetime.get("total_messages", 0) + snapshot.get("messages", 0) * multiplier
    lifetime["total_tool_calls"] = lifetime.get("total_tool_calls", 0) + snapshot.get("tool_calls", 0) * multiplier
    lifetime["total_rejections"] = lifetime.get("total_rejections", 0) + snapshot.get("rejections", 0) * multiplier
    lifetime["total_failures"] = lifetime.get("total_failures", 0) + snapshot.get("failures", 0) * multiplier

    # Update date range
    snapshot_date = snapshot.get("date")
    if snapshot_date and not subtract:
        if not lifetime.get("first_recorded") or snapshot_date < lifetime["first_recorded"]:
            lifetime["first_recorded"] = snapshot_date
        if not lifetime.get("last_recorded") or snapshot_date > lifetime["last_recorded"]:
            lifetime["last_recorded"] = snapshot_date

    # Update model stats
    model_stats = lifetime.setdefault("model_stats", {})
    for model, stats in snapshot.get("model_stats", {}).items():
        if model not in model_stats:
            model_stats[model] = {"tool_calls": 0, "rejections": 0, "failures": 0}
        model_stats[model]["tool_calls"] += stats.get("tool_calls", 0) * multiplier
        model_stats[model]["rejections"] += stats.get("rejections", 0) * multiplier
        model_stats[model]["failures"] += stats.get("failures", 0) * multiplier

    # Update IDEs and stacks (set union, only on add)
    if not subtract:
        existing_ides = set(lifetime.get("ides_used", []))
        existing_ides.update(snapshot.get("ides_used", []))
        lifetime["ides_used"] = sorted(existing_ides)

        existing_stacks = set(lifetime.get("stacks_used", []))
        existing_stacks.update(snapshot.get("stacks_used", []))
        lifetime["stacks_used"] = sorted(existing_stacks)

    # Count active days
    if not subtract:
        lifetime["total_days_active"] = len(data.get("snapshots", [])) + 1


def get_recent_snapshots(days: int = 7) -> list[DailySnapshot]:
    """Get snapshots from the last N days."""
    data = load_analytics()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    snapshots = []
    for s in data.get("snapshots", []):
        if s.get("date", "") >= cutoff:
            snapshots.append(DailySnapshot.from_dict(s))

    return sorted(snapshots, key=lambda x: x.date)


def get_lifetime_stats() -> LifetimeStats:
    """Get lifetime aggregated statistics."""
    data = load_analytics()
    lifetime = data.get("lifetime", {})
    return LifetimeStats.from_dict(lifetime) if lifetime else LifetimeStats()


def get_period_stats(days: int) -> dict:
    """Get aggregated stats for a specific period.

    Returns dict with totals and rates for the period.
    """
    snapshots = get_recent_snapshots(days)

    if not snapshots:
        return {
            "days": days,
            "sessions": 0,
            "messages": 0,
            "tool_calls": 0,
            "rejections": 0,
            "failures": 0,
            "rejection_rate": 0,
            "failure_rate": 0,
            "model_stats": {},
            "days_active": 0,
        }

    totals = {
        "days": days,
        "sessions": sum(s.sessions for s in snapshots),
        "messages": sum(s.messages for s in snapshots),
        "tool_calls": sum(s.tool_calls for s in snapshots),
        "rejections": sum(s.rejections for s in snapshots),
        "failures": sum(s.failures for s in snapshots),
        "days_active": len(snapshots),
        "model_stats": {},
    }

    # Aggregate model stats
    model_stats: dict[str, dict] = {}
    for s in snapshots:
        for model, stats in s.model_stats.items():
            if model not in model_stats:
                model_stats[model] = {"tool_calls": 0, "rejections": 0, "failures": 0}
            model_stats[model]["tool_calls"] += stats.get("tool_calls", 0)
            model_stats[model]["rejections"] += stats.get("rejections", 0)
            model_stats[model]["failures"] += stats.get("failures", 0)

    totals["model_stats"] = model_stats

    # Compute rates
    tc = totals["tool_calls"]
    totals["rejection_rate"] = (totals["rejections"] / tc * 100) if tc > 0 else 0
    totals["failure_rate"] = (totals["failures"] / tc * 100) if tc > 0 else 0

    return totals


def collect_and_record_today(project_path: Path | None = None) -> DailySnapshot | None:
    """Collect today's stats from all adapters and record to local analytics.

    This scans sessions modified today and aggregates their stats.
    Should be called periodically (e.g., on ap log, ap stats commands).
    """
    from .sources.base import get_all_adapters
    from .stack import detect_stack

    if project_path is None:
        project_path = Path.cwd()

    today = datetime.now().strftime("%Y-%m-%d")
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Initialize snapshot
    snapshot = DailySnapshot(date=today)

    ides_used: set[str] = set()
    stacks_used: set[str] = set()
    projects_seen: set[str] = set()
    model_stats: dict[str, dict] = {}

    # Detect stack for current project
    stacks_used.update(detect_stack(project_path))

    for adapter in get_all_adapters():
        try:
            sessions = adapter.list_sessions()
            for session in sessions:
                # Only include sessions from today
                if session.modified < today_start:
                    continue
                # Only main sessions
                if session.session_type != "main":
                    continue

                ides_used.add(_get_ide_display_name(adapter.name))
                if session.project:
                    projects_seen.add(session.project)

                try:
                    entries = adapter.read_session(session)

                    # Count messages
                    message_count = sum(
                        1 for e in entries if e.role in ("user", "assistant")
                    )

                    # Get error stats by model
                    session_errors = detect_llm_errors(entries)

                    for model, stats in session_errors.items():
                        snapshot.tool_calls += stats.total_tool_calls
                        snapshot.rejections += stats.rejections
                        snapshot.failures += stats.failures

                        if model not in model_stats:
                            model_stats[model] = {"tool_calls": 0, "rejections": 0, "failures": 0}
                        model_stats[model]["tool_calls"] += stats.total_tool_calls
                        model_stats[model]["rejections"] += stats.rejections
                        model_stats[model]["failures"] += stats.failures

                    snapshot.messages += message_count
                    snapshot.sessions += 1

                except Exception:
                    continue
        except Exception:
            continue

    # Set collected metadata
    snapshot.ides_used = sorted(ides_used)
    snapshot.stacks_used = sorted(stacks_used)
    snapshot.projects_active = len(projects_seen)
    snapshot.model_stats = model_stats

    # Only record if there's activity
    if snapshot.sessions > 0:
        record_daily_snapshot(snapshot)
        return snapshot

    return None


def _get_ide_display_name(adapter_name: str) -> str:
    """Get human-readable IDE/tool name."""
    names = {
        "claude_code": "Claude Code",
        "codex": "Codex CLI",
        "cursor": "Cursor",
    }
    return names.get(adapter_name, adapter_name)


def backfill_analytics(days: int = 30, project_path: Path | None = None) -> int:
    """Backfill analytics for the last N days.

    Scans all sessions and creates daily snapshots for days that are missing.
    Returns the number of days backfilled.
    """
    from .sources.base import get_all_adapters
    from .stack import detect_stack

    if project_path is None:
        project_path = Path.cwd()

    # Get existing snapshot dates
    data = load_analytics()
    existing_dates = {s.get("date") for s in data.get("snapshots", [])}

    # Calculate date range
    today = datetime.now()
    start_date = today - timedelta(days=days)

    # Collect sessions by date
    sessions_by_date: dict[str, list] = {}
    stacks_used = set(detect_stack(project_path))

    for adapter in get_all_adapters():
        try:
            sessions = adapter.list_sessions()
            for session in sessions:
                if session.modified < start_date:
                    continue
                if session.session_type != "main":
                    continue

                # Get the date of the session
                session_date = session.modified.strftime("%Y-%m-%d")

                if session_date not in sessions_by_date:
                    sessions_by_date[session_date] = []

                sessions_by_date[session_date].append((adapter, session))
        except Exception:
            continue

    # Create snapshots for each date
    backfilled = 0
    for date_str, session_list in sorted(sessions_by_date.items()):
        if date_str in existing_dates:
            continue  # Already have this date
        if date_str == today.strftime("%Y-%m-%d"):
            continue  # Skip today, handled by collect_and_record_today

        snapshot = DailySnapshot(date=date_str)
        ides_used: set[str] = set()
        projects_seen: set[str] = set()
        model_stats: dict[str, dict] = {}

        for adapter, session in session_list:
            ides_used.add(_get_ide_display_name(adapter.name))
            if session.project:
                projects_seen.add(session.project)

            try:
                entries = adapter.read_session(session)
                message_count = sum(1 for e in entries if e.role in ("user", "assistant"))
                session_errors = detect_llm_errors(entries)

                for model, stats in session_errors.items():
                    snapshot.tool_calls += stats.total_tool_calls
                    snapshot.rejections += stats.rejections
                    snapshot.failures += stats.failures

                    if model not in model_stats:
                        model_stats[model] = {"tool_calls": 0, "rejections": 0, "failures": 0}
                    model_stats[model]["tool_calls"] += stats.total_tool_calls
                    model_stats[model]["rejections"] += stats.rejections
                    model_stats[model]["failures"] += stats.failures

                snapshot.messages += message_count
                snapshot.sessions += 1
            except Exception:
                continue

        if snapshot.sessions > 0:
            snapshot.ides_used = sorted(ides_used)
            snapshot.stacks_used = sorted(stacks_used)
            snapshot.projects_active = len(projects_seen)
            snapshot.model_stats = model_stats
            record_daily_snapshot(snapshot)
            backfilled += 1

    return backfilled
