"""Afterpaths CLI."""

import click
from pathlib import Path

from .sources.base import list_all_sessions, get_all_adapters, get_sessions_for_cwd
from .sources.claude_code import ClaudeCodeAdapter
from .storage import get_afterpaths_dir, get_meta


def _load_env():
    """Load .env file from current directory or afterpaths package directory."""
    from dotenv import load_dotenv

    # Try current directory first
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        return

    # Try afterpaths directory (where the tool is installed/run from)
    afterpaths_env = Path(__file__).parent.parent / ".env"
    if afterpaths_env.exists():
        load_dotenv(afterpaths_env)


@click.group()
def cli():
    """Afterpaths: A research log for AI-assisted work."""
    _load_env()


@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Show all sessions across projects")
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main",
              help="Filter by session type (default: main)")
@click.option("--limit", default=10, help="Number of sessions to show")
def log(show_all, session_type, limit):
    """List recent AI coding sessions.

    By default, only shows main sessions (full conversations).
    Use --type=agent to see sub-agent sessions, or --type=all for everything.
    """
    sessions = list_all_sessions() if show_all else get_sessions_for_cwd()

    if not sessions:
        click.echo("No sessions found." + (" Try --all to see all projects." if not show_all else ""))
        return

    # Filter by session type
    if session_type != "all":
        sessions = [s for s in sessions if s.session_type == session_type]

    if not sessions:
        click.echo(f"No {session_type} sessions found. Try --type=all to see all session types.")
        return

    # Count totals for display
    total_main = len([s for s in (list_all_sessions() if show_all else get_sessions_for_cwd()) if s.session_type == "main"])
    total_agent = len([s for s in (list_all_sessions() if show_all else get_sessions_for_cwd()) if s.session_type == "agent"])

    # Check which sessions have afterpaths summaries
    afterpaths_dir = get_afterpaths_dir()
    summaries_dir = afterpaths_dir / "summaries"

    click.echo(f"Sessions: {total_main} main, {total_agent} agent")
    click.echo("-" * 40)

    for i, s in enumerate(sessions[:limit]):
        # Check if afterpaths summary exists
        summary_path = summaries_dir / f"{s.session_id}.md"
        has_summary = summary_path.exists()

        # Show index, type badge, summary indicator, and session ID
        type_badge = "[agent]" if s.session_type == "agent" else ""
        summary_badge = "[summarized]" if has_summary else ""
        click.echo(f"[{i+1}] {s.session_id[:12]}  {type_badge}{summary_badge}")

        # Show project (shortened) - skip if not showing all projects
        if show_all:
            project_display = s.project
            if len(project_display) > 50:
                project_display = "..." + project_display[-47:]
            click.echo(f"    Project: {project_display}")

        # Show modified time and size
        click.echo(f"    {s.modified.strftime('%Y-%m-%d %H:%M')} | {s.size/1024:.1f}KB")

        # Show afterpaths summary title if available, otherwise Claude's built-in summary
        if has_summary:
            # Extract title from afterpaths summary (first # heading)
            summary_content = summary_path.read_text()
            title_line = next((line for line in summary_content.split('\n') if line.startswith('# ')), None)
            if title_line:
                title = title_line[2:].strip()  # Remove "# " prefix
                title_display = title[:60] + "..." if len(title) > 60 else title
                click.echo(f"    {title_display}")
        elif s.summary:
            # Fall back to Claude Code's built-in summary
            summary_display = s.summary[:60] + "..." if len(s.summary) > 60 else s.summary
            click.echo(f"    {summary_display}")

        click.echo()


@cli.command()
@click.argument("session_ref")
@click.option("--raw", is_flag=True, help="Show raw transcript instead of summary")
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main",
              help="Filter by session type (must match 'log' filter for number refs)")
@click.option("--limit", default=50, help="Limit entries shown in raw mode")
def show(session_ref, raw, session_type, limit):
    """Show session summary or transcript.

    SESSION_REF can be a session number (from 'log' output) or a session ID prefix.
    """
    sessions = get_sessions_for_cwd() or list_all_sessions()

    if not sessions:
        click.echo("No sessions found.")
        return

    # Apply same type filter as log command for consistent numbering
    if session_type != "all":
        sessions = [s for s in sessions if s.session_type == session_type]

    # Try to interpret as number first
    session = None
    try:
        idx = int(session_ref)
        if 1 <= idx <= len(sessions):
            session = sessions[idx - 1]
    except ValueError:
        # Try to match by session ID prefix (search all sessions for ID match)
        all_sessions = get_sessions_for_cwd() or list_all_sessions()
        session = next((s for s in all_sessions if s.session_id.startswith(session_ref)), None)

    if not session:
        click.echo(f"Session not found: {session_ref}")
        click.echo("Use 'afterpaths log' to see available sessions.")
        return

    if raw:
        _show_raw_transcript(session, limit)
    else:
        _show_summary(session)


def _get_adapter_for_session(session):
    """Get the appropriate adapter for a session."""
    return next(
        (a for a in get_all_adapters() if a.name == session.source),
        ClaudeCodeAdapter()
    )


def _show_raw_transcript(session, limit):
    """Display raw transcript entries."""
    from .git_refs import extract_all_git_refs, format_refs_for_display

    adapter = _get_adapter_for_session(session)
    entries = adapter.read_session(session)
    refs = extract_all_git_refs(entries)

    click.echo(f"Session: {session.session_id}")
    click.echo(f"Project: {session.project}")
    click.echo(f"Entries: {len(entries)}")
    click.echo(f"Git refs: {format_refs_for_display(refs)}")
    click.echo("-" * 60)

    for i, entry in enumerate(entries[:limit]):
        role_display = entry.role.upper()
        if entry.tool_name:
            role_display = f"TOOL:{entry.tool_name}"

        # Truncate content for display
        content = entry.content
        if len(content) > 500:
            content = content[:500] + "..."

        click.echo(f"\n[{role_display}]")
        click.echo(content)

    if len(entries) > limit:
        click.echo(f"\n... ({len(entries) - limit} more entries, use --limit to show more)")


def _show_summary(session):
    """Display session summary if available."""
    afterpaths_dir = get_afterpaths_dir()
    summary_path = afterpaths_dir / "summaries" / f"{session.session_id}.md"

    if summary_path.exists():
        click.echo(summary_path.read_text())
    else:
        click.echo(f"No summary found for session {session.session_id[:8]}...")
        click.echo()
        if session.summary:
            click.echo(f"Claude Code summary: {session.summary}")
            click.echo()
        click.echo("To generate a summary, run: afterpaths summarize <session_number>")
        click.echo("(Requires anthropic package: pip install afterpaths[summarize])")


@cli.command()
@click.argument("session_ref")
@click.option("--notes", default="", help="Additional context for summarization")
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main",
              help="Filter by session type")
@click.option("--force", is_flag=True, help="Overwrite existing summary")
@click.option("--update", "update_mode", is_flag=True, help="Update existing summary instead of regenerating")
def summarize(session_ref, notes, session_type, force, update_mode):
    """Generate a research log summary for a session.

    SESSION_REF can be a session number (from 'log' output) or a session ID prefix.

    The summary focuses on discoveries, dead ends, and learnings that would help
    future work on this codebase.

    Use --update to refine an existing summary rather than regenerating from scratch.
    Use --force to overwrite an existing summary without updating.

    Configure LLM provider via .env file or environment variables:
        AFTERPATHS_LLM_PROVIDER=anthropic|openai|openai-compatible
        ANTHROPIC_API_KEY=sk-ant-...
        AFTERPATHS_MODEL=claude-sonnet-4-5-20250929

    Examples:
        afterpaths summarize 1
        afterpaths summarize 1 --notes="Focus on the auth changes"
        afterpaths summarize 1 --update --notes="Add more detail on the dead ends"
        afterpaths summarize a410a860 --force
    """
    from .summarize import summarize_session, update_summary
    from .git_refs import extract_all_git_refs
    from .llm import get_provider_info

    sessions = get_sessions_for_cwd() or list_all_sessions()

    if session_type != "all":
        sessions = [s for s in sessions if s.session_type == session_type]

    # Find session by number or ID prefix
    session = None
    try:
        idx = int(session_ref)
        if 1 <= idx <= len(sessions):
            session = sessions[idx - 1]
    except ValueError:
        all_sessions = list_all_sessions()
        session = next((s for s in all_sessions if s.session_id.startswith(session_ref)), None)

    if not session:
        click.echo(f"Session not found: {session_ref}")
        click.echo("Use 'afterpaths log' to see available sessions.")
        return

    # Check for existing summary
    afterpaths_dir = get_afterpaths_dir()
    summary_path = afterpaths_dir / "summaries" / f"{session.session_id}.md"
    existing_summary = None

    if summary_path.exists():
        existing_summary = summary_path.read_text()

        if update_mode:
            click.echo(f"Updating existing summary for {session.session_id[:12]}...")
        elif force:
            click.echo(f"Overwriting existing summary for {session.session_id[:12]}...")
        else:
            click.echo(f"Summary already exists: {summary_path}")
            click.echo()
            click.echo("Options:")
            click.echo("  --update  Refine the existing summary")
            click.echo("  --force   Overwrite with a fresh summary")
            return

    click.echo(f"Project: {session.project}")
    click.echo(f"Size: {session.size/1024:.1f}KB")
    click.echo(f"LLM: {get_provider_info()}")
    click.echo()

    adapter = _get_adapter_for_session(session)
    entries = adapter.read_session(session)

    action = "Updating" if update_mode and existing_summary else "Generating"
    click.echo(f"Parsed {len(entries)} entries. {action} summary...")
    click.echo()

    try:
        if update_mode and existing_summary:
            result = update_summary(entries, session, existing_summary, notes)
        else:
            result = summarize_session(entries, session, notes)
    except ImportError as e:
        click.echo(f"Missing dependency: {e}")
        click.echo("Install with: pip install afterpaths[summarize] or afterpaths[openai]")
        return
    except ValueError as e:
        click.echo(f"Configuration error: {e}")
        return
    except Exception as e:
        click.echo(f"Summarization failed: {e}")
        return

    # Save summary with metadata footer
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(result.with_metadata_footer())

    # Extract and store git refs
    git_refs = extract_all_git_refs(entries)
    git_refs_flat = list(git_refs.get("branches", set())) + list(git_refs.get("commits", set()))

    from .storage import add_session_to_index
    add_session_to_index(
        afterpaths_dir,
        session.session_id,
        session.source,
        session.path,
        summary_path,
        git_refs_flat,
    )

    click.echo(f"Saved to: {summary_path}")
    click.echo(f"Model: {result.provider}/{result.model}")
    if result.input_tokens:
        click.echo(f"Tokens: {result.input_tokens} in, {result.output_tokens} out")
    click.echo("-" * 60)
    click.echo(result.content)


@cli.command()
@click.argument("git_ref")
@click.option("--all", "show_all", is_flag=True, help="Search all projects")
def link(git_ref, show_all):
    """Find sessions that reference a git commit or branch.

    GIT_REF can be a commit hash (or prefix) or branch name.

    Examples:
        afterpaths link ab3f2d1
        afterpaths link feature/auth
    """
    from .git_refs import extract_all_git_refs

    sessions = list_all_sessions() if show_all else get_sessions_for_cwd()

    if not sessions:
        click.echo("No sessions found.")
        return

    # Only search main sessions by default
    sessions = [s for s in sessions if s.session_type == "main"]

    matches = []
    click.echo(f"Searching {len(sessions)} sessions for '{git_ref}'...")

    for session in sessions:
        adapter = _get_adapter_for_session(session)
        entries = adapter.read_session(session)
        refs = extract_all_git_refs(entries)

        # Check if git_ref matches any commit or branch
        all_refs = refs["commits"] | refs["branches"]
        matching = [r for r in all_refs if git_ref.lower() in r.lower()]

        if matching:
            matches.append((session, refs, matching))

    if not matches:
        click.echo(f"No sessions reference '{git_ref}'")
        return

    click.echo(f"\nFound {len(matches)} session(s):\n")

    for session, refs, matching in matches:
        click.echo(f"[{session.session_id[:12]}]")
        click.echo(f"    {session.modified.strftime('%Y-%m-%d %H:%M')} | {session.size/1024:.1f}KB")
        if session.summary:
            click.echo(f"    {session.summary[:60]}...")
        click.echo(f"    Matched: {', '.join(matching)}")
        if refs["branches"] - set(matching):
            click.echo(f"    Other branches: {', '.join(sorted(refs['branches'] - set(matching))[:3])}")
        if refs["commits"] - set(matching):
            click.echo(f"    Other commits: {', '.join(sorted(refs['commits'] - set(matching))[:3])}")
        click.echo()


@cli.command()
@click.argument("session_ref")
@click.option("--all", "show_all", is_flag=True, help="Search all projects for session ID")
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main",
              help="Filter by session type")
def refs(session_ref, show_all, session_type):
    """Show git refs detected in a session.

    SESSION_REF can be a session number or ID prefix.
    Use --all to search across all projects when using a session ID.
    """
    from .git_refs import extract_all_git_refs

    sessions = list_all_sessions() if show_all else (get_sessions_for_cwd() or list_all_sessions())

    if session_type != "all":
        sessions = [s for s in sessions if s.session_type == session_type]

    # Find session
    session = None
    try:
        idx = int(session_ref)
        if 1 <= idx <= len(sessions):
            session = sessions[idx - 1]
    except ValueError:
        # Search all sessions for ID prefix match
        all_sessions = list_all_sessions()
        session = next((s for s in all_sessions if s.session_id.startswith(session_ref)), None)

    if not session:
        click.echo(f"Session not found: {session_ref}")
        return

    adapter = _get_adapter_for_session(session)
    entries = adapter.read_session(session)
    refs = extract_all_git_refs(entries)

    click.echo(f"Session: {session.session_id[:12]}")
    if session.summary:
        click.echo(f"Summary: {session.summary}")
    click.echo()

    if refs["branches"]:
        click.echo("Branches:")
        for branch in sorted(refs["branches"]):
            click.echo(f"  - {branch}")
    else:
        click.echo("Branches: none detected")

    click.echo()

    if refs["commits"]:
        click.echo("Commits:")
        for commit in sorted(refs["commits"]):
            click.echo(f"  - {commit}")
    else:
        click.echo("Commits: none detected")


@cli.command()
@click.argument("commit_ref")
@click.option("--all", "show_all", is_flag=True, help="Search all projects")
@click.option("--days", default=7, help="Max days before commit to search (default: 7)")
@click.option("--limit", default=5, help="Maximum sessions to show")
def trace(commit_ref, show_all, days, limit):
    """Find sessions that likely produced a commit (by matching file modifications).

    Unlike 'link' which looks for explicit git refs in transcripts, 'trace' matches
    the files changed in a commit against files modified (Edit/Write) in sessions.

    COMMIT_REF is a git commit hash or reference (e.g., HEAD, HEAD~1, abc1234).

    Examples:
        afterpaths trace HEAD          # What session produced the last commit?
        afterpaths trace abc1234       # Trace a specific commit
        afterpaths trace HEAD~3 --all  # Search all projects
        afterpaths trace HEAD --days=3 # Only search last 3 days
    """
    from .file_tracking import get_commit_files, find_sessions_for_commit

    # Get commit info first
    commit_info = get_commit_files(commit_ref)

    if 'error' in commit_info:
        click.echo(f"Error: {commit_info['error']}")
        return

    click.echo(f"Commit: {commit_info['hash'][:12]}")
    click.echo(f"Message: {commit_info['message']}")
    click.echo(f"Time: {commit_info['time'].strftime('%Y-%m-%d %H:%M')}")
    click.echo(f"Files changed: {len(commit_info['files'])}")

    for f in sorted(commit_info['files'])[:5]:
        # Show relative path if possible
        try:
            rel = Path(f).relative_to(Path.cwd())
            click.echo(f"  - {rel}")
        except ValueError:
            click.echo(f"  - {f}")
    if len(commit_info['files']) > 5:
        click.echo(f"  ... and {len(commit_info['files']) - 5} more")

    click.echo()
    click.echo("Searching sessions for matching file modifications...")

    sessions = list_all_sessions() if show_all else get_sessions_for_cwd()

    # Only search main sessions
    sessions = [s for s in sessions if s.session_type == "main"]

    if not sessions:
        click.echo("No sessions found.")
        return

    adapter = _get_adapter_for_session(sessions[0])
    matches = find_sessions_for_commit(commit_ref, sessions, adapter, max_days_before=days)

    if not matches:
        click.echo("\nNo matching sessions found.")
        click.echo("This could mean:")
        click.echo("  - The changes were made manually (not via Claude Code)")
        click.echo("  - The session was in a different project (try --all)")
        click.echo("  - The session was deleted or is too old")
        return

    click.echo(f"\nFound {len(matches)} session(s) with matching file modifications:\n")

    for session, activity, matching_files in matches[:limit]:
        click.echo(f"[{session.session_id[:12]}]")
        click.echo(f"    {session.modified.strftime('%Y-%m-%d %H:%M')} | {session.size/1024:.1f}KB")

        if session.summary:
            click.echo(f"    {session.summary[:60]}...")

        click.echo(f"    Matching files ({len(matching_files)}):")
        for f in sorted(matching_files)[:3]:
            try:
                rel = Path(f).relative_to(Path.cwd())
                click.echo(f"      - {rel}")
            except ValueError:
                click.echo(f"      - {Path(f).name}")

        if len(matching_files) > 3:
            click.echo(f"      ... and {len(matching_files) - 3} more")

        # Show other files modified in session (context)
        other_modified = activity.files_modified - matching_files
        if other_modified:
            click.echo(f"    Also modified in session: {len(other_modified)} other file(s)")

        click.echo()

    if len(matches) > limit:
        click.echo(f"... and {len(matches) - limit} more (use --limit to show more)")


@cli.command()
@click.argument("session_ref")
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main")
def files(session_ref, session_type):
    """Show files modified in a session.

    Useful for understanding what changes a session made before tracing commits.
    """
    from .file_tracking import extract_file_activity

    sessions = get_sessions_for_cwd() or list_all_sessions()

    if session_type != "all":
        sessions = [s for s in sessions if s.session_type == session_type]

    # Find session
    session = None
    try:
        idx = int(session_ref)
        if 1 <= idx <= len(sessions):
            session = sessions[idx - 1]
    except ValueError:
        all_sessions = list_all_sessions()
        session = next((s for s in all_sessions if s.session_id.startswith(session_ref)), None)

    if not session:
        click.echo(f"Session not found: {session_ref}")
        return

    adapter = _get_adapter_for_session(session)
    entries = adapter.read_session(session)
    activity = extract_file_activity(entries, session)

    click.echo(f"Session: {session.session_id[:12]}")
    if session.summary:
        click.echo(f"Summary: {session.summary}")
    click.echo()

    if activity.files_modified:
        click.echo(f"Files modified ({len(activity.files_modified)}):")
        for f in sorted(activity.files_modified):
            try:
                rel = Path(f).relative_to(Path.cwd())
                click.echo(f"  [write] {rel}")
            except ValueError:
                click.echo(f"  [write] {Path(f).name}")
    else:
        click.echo("Files modified: none")

    click.echo()

    if activity.files_read:
        click.echo(f"Files read only ({len(activity.files_read)}):")
        for f in sorted(activity.files_read)[:10]:
            try:
                rel = Path(f).relative_to(Path.cwd())
                click.echo(f"  [read] {rel}")
            except ValueError:
                click.echo(f"  [read] {Path(f).name}")
        if len(activity.files_read) > 10:
            click.echo(f"  ... and {len(activity.files_read) - 10} more")
    else:
        click.echo("Files read only: none")


@cli.command()
@click.option("--days", default=14, help="Include summaries from last N days")
@click.option("--rebuild", is_flag=True, help="Rebuild rules from scratch (ignore existing)")
@click.option("--dry-run", is_flag=True, help="Preview without writing files")
@click.option("--target", type=click.Choice(["claude", "cursor", "all"]), default="all",
              help="Export target (default: all detected)")
def rules(days, rebuild, dry_run, target):
    """Extract rules from session summaries for AI coding assistants.

    Analyzes your session summaries and automatically generates rule files
    that Claude Code, Cursor, and other AI assistants load into context.

    Turn your hard-won discoveries into persistent guidance—no more manually
    writing CLAUDE.md rules after every painful debugging session.

    Examples:
        afterpaths rules                    # Extract and export to all targets
        afterpaths rules --days=30          # Include last 30 days
        afterpaths rules --target=claude    # Only export to Claude Code
        afterpaths rules --rebuild          # Rebuild from scratch
        afterpaths rules --dry-run          # Preview without writing
    """
    from .rules import run_extract_rules
    from .llm import get_provider_info

    click.echo(f"Extracting rules from last {days} days of summaries...")
    click.echo(f"LLM: {get_provider_info()}")

    if dry_run:
        click.echo("(Dry run - no files will be written)")
    click.echo()

    try:
        result = run_extract_rules(
            days=days,
            rebuild=rebuild,
            dry_run=dry_run,
            target=target if target != "all" else None,
        )
    except ImportError as e:
        click.echo(f"Missing dependency: {e}")
        click.echo("Install with: pip install afterpaths[summarize]")
        return
    except ValueError as e:
        click.echo(f"Configuration error: {e}")
        return
    except Exception as e:
        click.echo(f"Rule extraction failed: {e}")
        return

    # Display results
    if result.status == "no_summaries":
        click.echo("No summaries found.")
        click.echo("Generate summaries first with: afterpaths summarize <session>")
        return

    if result.status == "no_new_summaries":
        click.echo("No new summaries to process.")
        click.echo("Use --rebuild to regenerate rules from all summaries.")
        return

    if result.status == "no_rules_extracted":
        click.echo("No actionable rules could be extracted from summaries.")
        return

    click.echo(f"Processed {result.sessions_processed} session(s)")
    click.echo(f"Extracted {result.rules_extracted} new rule(s)")
    click.echo(f"Total rules after merge: {result.rules_after_merge}")
    click.echo()

    if result.export_results:
        for export in result.export_results:
            click.echo(f"Exported to {export.target}:")
            for path in export.files_written:
                try:
                    rel = path.relative_to(Path.cwd())
                    click.echo(f"  - {rel}")
                except ValueError:
                    click.echo(f"  - {path}")
        click.echo()
        click.echo("Rules will be automatically loaded by your AI coding assistant.")
    elif dry_run:
        click.echo("Dry run complete. Use without --dry-run to write files.")


@cli.command()
@click.argument("session_ref")
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main",
              help="Filter by session type")
def path(session_ref, session_type):
    """Print the path to a session's raw file.

    Useful for inspecting raw session content with your own tools (cat, jq, less, etc.).

    SESSION_REF can be a session number (from 'log' output) or a session ID prefix.

    Examples:
        afterpaths path 1
        afterpaths path 1 | xargs cat | jq .
        cat $(afterpaths path 1) | jq '.[] | select(.type == "user")'
    """
    sessions = get_sessions_for_cwd() or list_all_sessions()

    if not sessions:
        click.echo("No sessions found.", err=True)
        return

    # Apply same type filter as log command for consistent numbering
    if session_type != "all":
        sessions = [s for s in sessions if s.session_type == session_type]

    # Try to interpret as number first
    session = None
    try:
        idx = int(session_ref)
        if 1 <= idx <= len(sessions):
            session = sessions[idx - 1]
    except ValueError:
        # Try to match by session ID prefix (search all sessions for ID match)
        all_sessions = get_sessions_for_cwd() or list_all_sessions()
        session = next((s for s in all_sessions if s.session_id.startswith(session_ref)), None)

    if not session:
        click.echo(f"Session not found: {session_ref}", err=True)
        click.echo("Use 'afterpaths log' to see available sessions.", err=True)
        return

    # Print just the path (no newline issues, easy to use with xargs/subshell)
    click.echo(session.path)


@cli.command()
def status():
    """Show afterpaths status and configuration."""
    from .llm import get_provider_info
    from .storage import get_afterpaths_dir, get_meta

    click.echo("Afterpaths Status")
    click.echo("-" * 40)

    # LLM configuration
    click.echo(f"LLM Provider: {get_provider_info()}")

    # Storage info
    afterpaths_dir = get_afterpaths_dir()
    summaries_dir = afterpaths_dir / "summaries"
    summary_count = len(list(summaries_dir.glob("*.md"))) if summaries_dir.exists() else 0
    click.echo(f"Summaries: {summary_count} saved")

    # Rules metadata
    meta = get_meta(afterpaths_dir)
    rules_meta = meta.get("distill", {})  # Still stored as "distill" for backwards compat
    if rules_meta.get("last_run"):
        click.echo(f"Last rules extraction: {rules_meta['last_run'][:16]}")
        click.echo(f"Sessions processed: {len(rules_meta.get('sessions_included', []))}")


def main():
    cli()


if __name__ == "__main__":
    main()
