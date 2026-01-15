"""Daily stats display for afterpaths.

Shows personalized daily usage stats on first use each day.
After day 2, includes opt-in teaser for community analytics.
"""

import platform
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .analytics import detect_llm_errors, _normalize_model_name
from .config import (
    get_global_config,
    save_global_config,
    has_analytics_decision,
)
from .sources.base import get_all_adapters
from .stack import detect_stack


@dataclass
class PeriodStats:
    """Stats for a time period."""

    messages: int = 0
    tool_calls: int = 0
    sessions: int = 0
    rejections: int = 0
    failures: int = 0
    # Model -> {tool_calls, rejections, failures}
    model_stats: dict[str, dict] = None

    def __post_init__(self):
        if self.model_stats is None:
            self.model_stats = {}

    @property
    def rejection_rate(self) -> float:
        return (self.rejections / self.tool_calls * 100) if self.tool_calls > 0 else 0

    @property
    def failure_rate(self) -> float:
        return (self.failures / self.tool_calls * 100) if self.tool_calls > 0 else 0


@dataclass
class DailyStatsData:
    """Data for daily stats display."""

    yesterday: PeriodStats
    last_7_days: PeriodStats
    stacks_used: list[str]
    platform_os: str
    peak_hours: list[int]


def get_daily_stats(project_path: Path | None = None) -> DailyStatsData | None:
    """Collect stats for yesterday and last 7 days.

    Yesterday: previous midnight to midnight (local timezone)
    Last 7 days: yesterday + 6 days before
    """
    if project_path is None:
        project_path = Path.cwd()

    # Calculate time boundaries in local timezone
    now = datetime.now()
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_midnight - timedelta(days=1)
    yesterday_end = today_midnight
    seven_days_start = today_midnight - timedelta(days=7)

    # Initialize period stats
    yesterday = PeriodStats()
    last_7_days = PeriodStats()

    stacks_used: set[str] = set()
    hours_active: dict[int, int] = {}

    # Detect stack for current project
    current_stack = detect_stack(project_path)
    stacks_used.update(current_stack)

    for adapter in get_all_adapters():
        # Get peak hours from cache (lifetime data)
        cached = adapter.get_cached_stats()
        if cached and cached.activity_by_hour:
            hours_active = cached.activity_by_hour

        # Parse sessions for both periods
        try:
            sessions = adapter.list_sessions()
            for session in sessions:
                # Skip sessions outside our 7-day window
                if session.modified < seven_days_start:
                    continue
                # Skip sessions from today (incomplete day)
                if session.modified >= today_midnight:
                    continue
                # Only main sessions
                if session.session_type != "main":
                    continue

                # Determine which periods this session belongs to
                is_yesterday = yesterday_start <= session.modified < yesterday_end
                is_in_7_days = True  # Already filtered above

                try:
                    entries = adapter.read_session(session)

                    # Count messages
                    message_count = sum(
                        1 for e in entries if e.role in ("user", "assistant")
                    )

                    # Get error stats by model
                    session_errors = detect_llm_errors(entries)

                    session_tool_calls = 0
                    session_rejections = 0
                    session_failures = 0

                    for model, stats in session_errors.items():
                        session_tool_calls += stats.total_tool_calls
                        session_rejections += stats.rejections
                        session_failures += stats.failures

                        # Aggregate model stats for 7-day view
                        if model not in last_7_days.model_stats:
                            last_7_days.model_stats[model] = {
                                "tool_calls": 0,
                                "rejections": 0,
                                "failures": 0,
                            }
                        last_7_days.model_stats[model]["tool_calls"] += stats.total_tool_calls
                        last_7_days.model_stats[model]["rejections"] += stats.rejections
                        last_7_days.model_stats[model]["failures"] += stats.failures

                        # Also track yesterday's model stats
                        if is_yesterday:
                            if model not in yesterday.model_stats:
                                yesterday.model_stats[model] = {
                                    "tool_calls": 0,
                                    "rejections": 0,
                                    "failures": 0,
                                }
                            yesterday.model_stats[model]["tool_calls"] += stats.total_tool_calls
                            yesterday.model_stats[model]["rejections"] += stats.rejections
                            yesterday.model_stats[model]["failures"] += stats.failures

                    # Update 7-day totals
                    last_7_days.messages += message_count
                    last_7_days.sessions += 1
                    last_7_days.tool_calls += session_tool_calls
                    last_7_days.rejections += session_rejections
                    last_7_days.failures += session_failures

                    # Update yesterday totals
                    if is_yesterday:
                        yesterday.messages += message_count
                        yesterday.sessions += 1
                        yesterday.tool_calls += session_tool_calls
                        yesterday.rejections += session_rejections
                        yesterday.failures += session_failures

                except Exception:
                    continue
        except Exception:
            continue

    # Get top 3 peak hours
    peak_hours = []
    if hours_active:
        peak_hours = [
            h for h, _ in sorted(hours_active.items(), key=lambda x: -x[1])[:3]
        ]

    return DailyStatsData(
        yesterday=yesterday,
        last_7_days=last_7_days,
        stacks_used=sorted(stacks_used),
        platform_os=_get_platform_name(),
        peak_hours=peak_hours,
    )


def _get_platform_name() -> str:
    """Get human-readable platform name."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    return system


def format_daily_stats(stats: DailyStatsData, box_width: int = 72) -> str:
    """Format daily stats for CLI display with box drawing."""
    lines = []
    inner_width = box_width - 4  # Account for "│  " and "  │"

    def pad_line(text: str) -> str:
        """Pad a line to fit within the box."""
        return f"│  {text:<{inner_width}}│"

    # Top border with title
    title = " Your Stats "
    left_border = "╭─"
    right_border_len = box_width - len(left_border) - len(title) - 1
    lines.append(f"{left_border}{title}{'─' * right_border_len}╮")

    # Empty line
    lines.append(pad_line(""))

    # Yesterday section
    lines.append(pad_line("Yesterday"))
    y = stats.yesterday
    if y.sessions > 0:
        activity_line = (
            f"  Sessions: {y.sessions:<3} "
            f"Messages: {y.messages:<5} "
            f"Tool calls: {y.tool_calls}"
        )
        lines.append(pad_line(activity_line))

        # Model performance for yesterday
        for model, mstats in sorted(y.model_stats.items()):
            tool_calls = mstats["tool_calls"]
            rejections = mstats["rejections"]
            failures = mstats["failures"]
            rej_pct = (rejections / tool_calls * 100) if tool_calls > 0 else 0
            fail_pct = (failures / tool_calls * 100) if tool_calls > 0 else 0

            perf_line = (
                f"  {model}: "
                f"Rejections {rejections} ({rej_pct:.1f}%)  "
                f"Failures {failures} ({fail_pct:.1f}%)"
            )
            lines.append(pad_line(perf_line))
    else:
        lines.append(pad_line("  No activity"))
    lines.append(pad_line(""))

    # Last 7 days section
    lines.append(pad_line("Last 7 Days"))
    w = stats.last_7_days
    if w.sessions > 0:
        activity_line = (
            f"  Sessions: {w.sessions:<3} "
            f"Messages: {w.messages:<5} "
            f"Tool calls: {w.tool_calls}"
        )
        lines.append(pad_line(activity_line))

        # Model performance for 7 days
        for model, mstats in sorted(w.model_stats.items()):
            tool_calls = mstats["tool_calls"]
            rejections = mstats["rejections"]
            failures = mstats["failures"]
            rej_pct = (rejections / tool_calls * 100) if tool_calls > 0 else 0
            fail_pct = (failures / tool_calls * 100) if tool_calls > 0 else 0

            perf_line = (
                f"  {model}: "
                f"Rejections {rejections} ({rej_pct:.1f}%)  "
                f"Failures {failures} ({fail_pct:.1f}%)"
            )
            lines.append(pad_line(perf_line))
    else:
        lines.append(pad_line("  No activity"))
    lines.append(pad_line(""))

    # Stack Used
    if stats.stacks_used:
        stack_str = ", ".join(stats.stacks_used[:5])
        lines.append(pad_line(f"Stack Used: {stack_str}"))

    # Platform
    lines.append(pad_line(f"Platform: {stats.platform_os}"))

    # Peak Hours
    if stats.peak_hours:
        hours_str = ", ".join(f"{h}:00" for h in stats.peak_hours)
        lines.append(pad_line(f"Peak Hours: {hours_str}"))

    lines.append(pad_line(""))

    # Bottom border
    lines.append(f"╰{'─' * (box_width - 2)}╯")

    return "\n".join(lines)


def format_optin_teaser(
    rejection_rate: float,
    stacks: list[str],
    platform_os: str,
    box_width: int = 72,
) -> str:
    """Format the opt-in teaser for Day 2+."""
    lines = []
    inner_width = box_width - 4

    def pad_line(text: str) -> str:
        return f"│  {text:<{inner_width}}│"

    # Top border with title
    title = " Unlock Community Insights "
    left_border = "┌─"
    right_border_len = box_width - len(left_border) - len(title) - 1
    lines.append(f"{left_border}{title}{'─' * right_border_len}┐")

    lines.append(pad_line(""))

    # Personalized comparison teaser
    lines.append(pad_line(f"See how your {rejection_rate:.1f}% rejection rate compares to:"))

    # Stack comparison
    if stacks:
        stack_str = " + ".join(stacks[:2])
        lines.append(pad_line(f"  • Other {stack_str} developers"))

    lines.append(pad_line("  • Opus vs Sonnet across 1,200+ developers"))

    # Platform comparison
    other_platform = "Linux" if platform_os == "macOS" else "macOS"
    lines.append(pad_line(f"  • {platform_os} vs {other_platform} error patterns"))

    lines.append(pad_line(""))
    lines.append(pad_line("Share anonymized counts only. No code or content."))
    lines.append(pad_line(""))

    # Bottom border
    lines.append(f"└{'─' * (box_width - 2)}┘")

    return "\n".join(lines)


def should_show_daily_stats() -> bool:
    """Check if we should show daily stats (once per day)."""
    config = get_global_config()
    today = datetime.now().strftime("%Y-%m-%d")

    last_shown = config.get("last_daily_stats_shown")
    return last_shown != today


def mark_daily_stats_shown() -> None:
    """Mark that we've shown daily stats today."""
    config = get_global_config()
    today = datetime.now().strftime("%Y-%m-%d")

    # Track first use date if not set
    if "first_use_date" not in config:
        config["first_use_date"] = today

    config["last_daily_stats_shown"] = today
    save_global_config(config)


def is_day_two_or_later() -> bool:
    """Check if this is day 2+ of usage (for opt-in prompt)."""
    config = get_global_config()
    first_use = config.get("first_use_date")

    if not first_use:
        return False

    try:
        first_date = datetime.strptime(first_use, "%Y-%m-%d")
        return datetime.now() >= first_date + timedelta(days=1)
    except ValueError:
        return False


def show_daily_stats_if_needed(project_path: Path | None = None) -> str | None:
    """Show daily stats if we haven't shown them today.

    Returns the formatted string to display, or None if already shown today.
    """
    if not should_show_daily_stats():
        return None

    stats = get_daily_stats(project_path)
    if not stats:
        return None

    # Mark as shown
    mark_daily_stats_shown()

    output_parts = [format_daily_stats(stats)]

    # On day 2+, show opt-in teaser if user hasn't decided
    if is_day_two_or_later() and not has_analytics_decision():
        # Use 7-day rejection rate for teaser
        rejection_rate = stats.last_7_days.rejection_rate

        output_parts.append("")  # Blank line between boxes
        output_parts.append(
            format_optin_teaser(
                rejection_rate=rejection_rate,
                stacks=stats.stacks_used,
                platform_os=stats.platform_os,
            )
        )

    return "\n".join(output_parts)
