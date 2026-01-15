"""Analytics event collection and insights.

Collects anonymized usage stats and retrieves community insights.
For Sprint 1, insights are mock data. Sprint 2 will add real API.
"""

import hashlib
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import get_anonymous_id, is_analytics_enabled
from .stack import detect_stack
from .storage import get_afterpaths_dir
from .sources.base import SessionEntry


@dataclass
class LLMErrorStats:
    """Error statistics for an LLM model."""

    rejections: int = 0  # User rejected tool call before execution
    failures: int = 0  # Tool execution failed (traceback, etc.)
    total_tool_calls: int = 0  # Total tool calls for rate calculation
    # Breakdown by tool name
    rejections_by_tool: dict[str, int] = field(default_factory=dict)
    failures_by_tool: dict[str, int] = field(default_factory=dict)
    # Hour-of-day distribution (0-23)
    rejections_by_hour: dict[int, int] = field(default_factory=dict)
    failures_by_hour: dict[int, int] = field(default_factory=dict)


@dataclass
class DailyEvent:
    """Anonymized daily usage event."""

    anonymous_id: str
    date: str  # YYYY-MM-DD
    project_hash: str
    stack: list[str]
    sessions: dict  # {"count": 3, "duration_buckets": {...}}
    rules: dict  # {"dead-ends": 2, "patterns": 1, ...}
    errors_by_model: dict[str, dict] = field(default_factory=dict)  # {"claude-opus-4": {"rejections": 2, "failures": 1}}
    # Environment metadata for segmentation
    os: str = ""  # "Darwin", "Linux", "Windows"
    utc_offset_hours: float = 0.0  # Local timezone offset from UTC


@dataclass
class UserInsights:
    """User's own stats."""

    session_count: int
    rule_count: int
    rules_by_category: dict[str, int]
    most_productive_day: str | None
    stack: list[str]
    errors_by_model: dict[str, LLMErrorStats] = field(default_factory=dict)
    # From platform cache (when available)
    total_messages: int | None = None
    total_tool_calls: int | None = None
    tokens_by_model: dict[str, dict] | None = None  # model -> {input, output, cache_read}
    activity_by_hour: dict[int, int] | None = None


@dataclass
class CommunityInsights:
    """Aggregated community stats."""

    avg_session_count: float
    avg_rule_count: float
    rule_category_distribution: dict[str, float]
    total_users: int
    # Error benchmarks by model
    rejection_rates_by_model: dict[str, float] = field(default_factory=dict)  # model -> rejection rate
    failure_rates_by_model: dict[str, float] = field(default_factory=dict)  # model -> failure rate


@dataclass
class Insights:
    """Combined insights response."""

    user: UserInsights
    community: CommunityInsights
    period: str = "7d"


def detect_llm_errors(entries: list[SessionEntry]) -> dict[str, LLMErrorStats]:
    """Detect LLM errors from session entries, grouped by model.

    Detects:
    - Rejections: User rejected tool call before execution
    - Failures: Tool execution failed (traceback, error codes, etc.)

    Also tracks breakdowns by tool name and hour of day.

    Returns dict mapping model name to error stats.
    """
    stats_by_model: dict[str, LLMErrorStats] = {}
    current_model = "unknown"
    current_tool = "unknown"

    for entry in entries:
        # Track current model from assistant entries
        if entry.role == "assistant" and entry.model:
            current_model = _normalize_model_name(entry.model)

        # Track current tool and count tool calls
        if entry.role == "assistant" and entry.tool_name:
            current_tool = entry.tool_name
            if current_model not in stats_by_model:
                stats_by_model[current_model] = LLMErrorStats()
            stats_by_model[current_model].total_tool_calls += 1

        # Detect errors in tool results
        if entry.role == "tool_result" and entry.is_error:
            if current_model not in stats_by_model:
                stats_by_model[current_model] = LLMErrorStats()

            stats = stats_by_model[current_model]
            content_lower = entry.content.lower()

            # Extract hour from timestamp if available
            hour = _extract_hour(entry.timestamp)

            # Check if it's a user rejection
            if "rejected" in content_lower or "doesn't want to proceed" in content_lower:
                stats.rejections += 1
                # Track by tool
                stats.rejections_by_tool[current_tool] = (
                    stats.rejections_by_tool.get(current_tool, 0) + 1
                )
                # Track by hour
                if hour is not None:
                    stats.rejections_by_hour[hour] = (
                        stats.rejections_by_hour.get(hour, 0) + 1
                    )
            # Otherwise it's an execution failure
            else:
                stats.failures += 1
                # Track by tool
                stats.failures_by_tool[current_tool] = (
                    stats.failures_by_tool.get(current_tool, 0) + 1
                )
                # Track by hour
                if hour is not None:
                    stats.failures_by_hour[hour] = (
                        stats.failures_by_hour.get(hour, 0) + 1
                    )

    return stats_by_model


def _extract_hour(timestamp: str | None) -> int | None:
    """Extract hour (0-23) from ISO timestamp string."""
    if not timestamp:
        return None
    try:
        # Handle various ISO formats
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return dt.hour
    except (ValueError, AttributeError):
        return None


def _hour_to_period(hour: int) -> str:
    """Convert hour (0-23) to human-readable time period."""
    if 5 <= hour < 9:
        return f"early morning ({hour}:00)"
    elif 9 <= hour < 12:
        return f"morning ({hour}:00)"
    elif 12 <= hour < 14:
        return f"midday ({hour}:00)"
    elif 14 <= hour < 17:
        return f"afternoon ({hour}:00)"
    elif 17 <= hour < 21:
        return f"evening ({hour}:00)"
    elif 21 <= hour < 24:
        return f"night ({hour}:00)"
    else:  # 0-4
        return f"late night ({hour}:00)"


def _normalize_model_name(model: str) -> str:
    """Normalize model name for grouping (e.g., 'claude-opus-4-5-20251101' -> 'claude-opus-4')."""
    if not model:
        return "unknown"

    # Extract base model name without date suffix
    parts = model.split("-")

    # Handle claude-* models
    if model.startswith("claude-"):
        # claude-opus-4-5-20251101 -> claude-opus-4
        # claude-sonnet-4-5-20250929 -> claude-sonnet-4
        if len(parts) >= 3:
            return "-".join(parts[:3])

    # Handle gpt-* models
    if model.startswith("gpt-"):
        # gpt-4-turbo-2024-04-09 -> gpt-4-turbo
        if "turbo" in model:
            return "gpt-4-turbo"
        return parts[0] + "-" + parts[1] if len(parts) >= 2 else model

    return model


def hash_project_path(project_path: str) -> str:
    """Create anonymous hash of project path."""
    return hashlib.sha256(project_path.encode()).hexdigest()[:16]


def collect_project_stats(project_path: Path) -> dict:
    """Collect stats for a project.

    Returns dict with session count, rule counts by category, and stack.
    """
    afterpaths_dir = get_afterpaths_dir(project_path)
    summaries_dir = afterpaths_dir / "summaries"

    # Count summaries
    summary_count = 0
    if summaries_dir.exists():
        summary_count = len(list(summaries_dir.glob("*.md")))

    # Count rules by category (from .claude/rules/)
    rules_dir = project_path / ".claude" / "rules"
    rule_counts = {
        "dead-ends": 0,
        "patterns": 0,
        "gotchas": 0,
        "decisions": 0,
    }

    if rules_dir.exists():
        for rule_file in rules_dir.glob("*.md"):
            # Count rules in each file (lines starting with "- **")
            try:
                content = rule_file.read_text()
                rule_count = content.count("\n- **")
                category = rule_file.stem.replace("-", "_")

                # Map filename to category
                if "dead" in category or "end" in category:
                    rule_counts["dead-ends"] += rule_count
                elif "pattern" in category:
                    rule_counts["patterns"] += rule_count
                elif "gotcha" in category:
                    rule_counts["gotchas"] += rule_count
                elif "decision" in category:
                    rule_counts["decisions"] += rule_count
            except Exception:
                pass

    # Detect stack
    stack = detect_stack(project_path)

    return {
        "summary_count": summary_count,
        "rule_counts": rule_counts,
        "stack": stack,
    }


def build_daily_event(project_path: Path) -> DailyEvent | None:
    """Build a daily event for the current project."""
    if not is_analytics_enabled():
        return None

    stats = collect_project_stats(project_path)

    # Get UTC offset in hours
    now = datetime.now().astimezone()
    utc_offset = now.utcoffset()
    utc_offset_hours = utc_offset.total_seconds() / 3600 if utc_offset else 0.0

    return DailyEvent(
        anonymous_id=get_anonymous_id(),
        date=datetime.now().strftime("%Y-%m-%d"),
        project_hash=hash_project_path(str(project_path)),
        stack=stats["stack"],
        sessions={"count": stats["summary_count"], "duration_buckets": {}},
        rules=stats["rule_counts"],
        os=platform.system(),
        utc_offset_hours=utc_offset_hours,
    )


def send_event(event: DailyEvent) -> bool:
    """Send event to analytics API.

    Sprint 1: No-op, just returns True.
    Sprint 2: Will send to real API.
    """
    # TODO: Implement real API call in Sprint 2
    api_url = os.environ.get("AFTERPATHS_API_URL")
    if not api_url:
        # No API configured, silently skip
        return True

    # For now, just log that we would send
    return True


def get_insights(project_path: Path | None = None) -> Insights:
    """Get insights for the user.

    Sprint 1: Returns mock community data + real local stats.
    Sprint 2: Will fetch from real API.
    """
    from .sources.base import get_all_adapters

    # Collect real local stats
    if project_path is None:
        project_path = Path.cwd()

    stats = collect_project_stats(project_path)

    # Collect error stats from sessions (always parse - not in platform caches)
    errors_by_model = _collect_error_stats(project_path)

    # Collect cached stats from adapters (avoid re-computing)
    cached = _get_merged_cached_stats()

    # Convert token usage to serializable dict
    tokens_by_model = None
    if cached and cached.tokens_by_model:
        tokens_by_model = {
            model: {
                "input": usage.input_tokens,
                "output": usage.output_tokens,
                "cache_read": usage.cache_read_tokens,
            }
            for model, usage in cached.tokens_by_model.items()
        }

    user_insights = UserInsights(
        session_count=stats["summary_count"],
        rule_count=sum(stats["rule_counts"].values()),
        rules_by_category=stats["rule_counts"],
        most_productive_day=_get_most_productive_day(project_path),
        stack=stats["stack"],
        errors_by_model=errors_by_model,
        # From platform cache
        total_messages=cached.total_messages if cached else None,
        total_tool_calls=cached.total_tool_calls if cached else None,
        tokens_by_model=tokens_by_model,
        activity_by_hour=cached.activity_by_hour if cached else None,
    )

    # Mock community data for Sprint 1
    # Sprint 2: Fetch from API based on user's stack
    community_insights = CommunityInsights(
        avg_session_count=8.2,
        avg_rule_count=4.7,
        rule_category_distribution={
            "dead-ends": 0.38,
            "gotchas": 0.28,
            "patterns": 0.22,
            "decisions": 0.12,
        },
        total_users=127,  # Mock
        # Mock error benchmarks - Sprint 2 will compute from real data
        rejection_rates_by_model={
            "claude-opus-4": 0.02,
            "claude-sonnet-4": 0.03,
        },
        failure_rates_by_model={
            "claude-opus-4": 0.05,
            "claude-sonnet-4": 0.07,
        },
    )

    return Insights(
        user=user_insights,
        community=community_insights,
        period="7d",
    )


def _get_merged_cached_stats():
    """Get merged cached stats from all adapters.

    Returns the first non-None cached stats found. In the future,
    this could merge stats from multiple adapters.
    """
    from .sources.base import CachedStats, get_all_adapters

    for adapter in get_all_adapters():
        cached = adapter.get_cached_stats()
        if cached:
            return cached
    return None


def _get_most_productive_day(project_path: Path) -> str | None:
    """Determine user's most productive day based on summary creation times."""
    afterpaths_dir = get_afterpaths_dir(project_path)
    summaries_dir = afterpaths_dir / "summaries"

    if not summaries_dir.exists():
        return None

    day_counts: dict[str, int] = {}

    for summary_file in summaries_dir.glob("*.md"):
        try:
            mtime = summary_file.stat().st_mtime
            day = datetime.fromtimestamp(mtime).strftime("%A")
            day_counts[day] = day_counts.get(day, 0) + 1
        except Exception:
            pass

    if not day_counts:
        return None

    return max(day_counts, key=day_counts.get)


def _collect_error_stats(project_path: Path) -> dict[str, LLMErrorStats]:
    """Collect error stats from all sessions for a project.

    Reads sessions from the last 7 days and aggregates rejections/failures by model.
    """
    from .sources.base import get_all_adapters

    aggregated: dict[str, LLMErrorStats] = {}
    cutoff = datetime.now() - timedelta(days=7)
    project_str = str(project_path)

    for adapter in get_all_adapters():
        try:
            sessions = adapter.list_sessions(project_filter=project_str)
            for session in sessions:
                # Only include recent sessions
                if session.modified < cutoff:
                    continue

                # Only include main sessions (skip agent sub-processes)
                if session.session_type != "main":
                    continue

                try:
                    entries = adapter.read_session(session)
                    session_errors = detect_llm_errors(entries)

                    # Merge into aggregated stats
                    for model, stats in session_errors.items():
                        if model not in aggregated:
                            aggregated[model] = LLMErrorStats()
                        agg = aggregated[model]
                        agg.rejections += stats.rejections
                        agg.failures += stats.failures
                        agg.total_tool_calls += stats.total_tool_calls

                        # Merge tool breakdowns
                        for tool, count in stats.rejections_by_tool.items():
                            agg.rejections_by_tool[tool] = (
                                agg.rejections_by_tool.get(tool, 0) + count
                            )
                        for tool, count in stats.failures_by_tool.items():
                            agg.failures_by_tool[tool] = (
                                agg.failures_by_tool.get(tool, 0) + count
                            )

                        # Merge hour breakdowns
                        for hour, count in stats.rejections_by_hour.items():
                            agg.rejections_by_hour[hour] = (
                                agg.rejections_by_hour.get(hour, 0) + count
                            )
                        for hour, count in stats.failures_by_hour.items():
                            agg.failures_by_hour[hour] = (
                                agg.failures_by_hour.get(hour, 0) + count
                            )
                except Exception:
                    # Skip sessions that fail to parse
                    continue
        except Exception:
            # Skip adapters that fail
            continue

    return aggregated


def format_insights(insights: Insights) -> str:
    """Format insights for CLI display."""
    lines = []

    lines.append("Community Insights")
    lines.append("-" * 40)
    lines.append("")

    # User stats
    lines.append(f"Your Stats (last {insights.period}):")
    lines.append(
        f"  Sessions: {insights.user.session_count} "
        f"(community avg: {insights.community.avg_session_count:.1f})"
    )
    lines.append(
        f"  Rules generated: {insights.user.rule_count} "
        f"(community avg: {insights.community.avg_rule_count:.1f})"
    )
    lines.append("")

    # LLM Error Stats - the "money" metrics
    if insights.user.errors_by_model:
        lines.append("LLM Performance (your sessions):")
        for model, stats in sorted(insights.user.errors_by_model.items()):
            if stats.total_tool_calls > 0:
                rejection_rate = stats.rejections / stats.total_tool_calls
                failure_rate = stats.failures / stats.total_tool_calls

                # Get community benchmarks for comparison
                community_rejection = insights.community.rejection_rates_by_model.get(
                    model, 0
                )
                community_failure = insights.community.failure_rates_by_model.get(
                    model, 0
                )

                lines.append(f"  {model}:")
                lines.append(
                    f"    Rejections: {stats.rejections}/{stats.total_tool_calls} "
                    f"({rejection_rate*100:.1f}%) "
                    f"[community: {community_rejection*100:.1f}%]"
                )
                lines.append(
                    f"    Failures: {stats.failures}/{stats.total_tool_calls} "
                    f"({failure_rate*100:.1f}%) "
                    f"[community: {community_failure*100:.1f}%]"
                )

                # Show top failing tools if any
                if stats.failures_by_tool:
                    top_tools = sorted(
                        stats.failures_by_tool.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:3]
                    tool_str = ", ".join(f"{t}({c})" for t, c in top_tools)
                    lines.append(f"    Top failing tools: {tool_str}")

                # Show time pattern if data exists
                if stats.failures_by_hour or stats.rejections_by_hour:
                    all_hours = {**stats.failures_by_hour, **stats.rejections_by_hour}
                    if all_hours:
                        peak_hour = max(all_hours, key=all_hours.get)
                        time_label = _hour_to_period(peak_hour)
                        lines.append(f"    Peak error time: {time_label}")
        lines.append("")

    # Stack info
    if insights.user.stack:
        stack_str = " + ".join(insights.user.stack[:3])
        lines.append(f"Your Stack: {stack_str}")
        lines.append("")

    # Rule category distribution
    lines.append("Top Rule Categories (community-wide):")
    sorted_cats = sorted(
        insights.community.rule_category_distribution.items(),
        key=lambda x: x[1],
        reverse=True,
    )
    for i, (cat, pct) in enumerate(sorted_cats[:4], 1):
        lines.append(f"  {i}. {cat.replace('-', ' ').title()} ({pct*100:.0f}%)")
    lines.append("")

    # Most productive day
    if insights.user.most_productive_day:
        lines.append(f"Your Most Productive Day: {insights.user.most_productive_day}")
        lines.append("")

    # Lifetime stats from platform cache (if available)
    if insights.user.total_messages:
        lines.append("Lifetime Stats (from Claude Code):")
        lines.append(f"  Total messages: {insights.user.total_messages:,}")
        if insights.user.tokens_by_model:
            total_output = sum(
                t.get("output", 0) for t in insights.user.tokens_by_model.values()
            )
            lines.append(f"  Total output tokens: {total_output:,}")
        if insights.user.activity_by_hour:
            peak_hours = sorted(
                insights.user.activity_by_hour.items(), key=lambda x: -x[1]
            )[:3]
            peak_str = ", ".join(f"{h}:00" for h, _ in peak_hours)
            lines.append(f"  Peak activity hours: {peak_str}")
        lines.append("")

    # Footer
    lines.append("-" * 40)
    lines.append(f"Based on {insights.community.total_users} afterpaths users")

    return "\n".join(lines)
