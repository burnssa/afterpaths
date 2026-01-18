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


def _maybe_show_daily_stats():
    """Show daily stats if we haven't shown them today."""
    from .daily_stats import show_daily_stats_if_needed
    from .config import save_analytics_decision
    from .local_analytics import collect_and_record_today

    # Record today's stats to local analytics (silently)
    try:
        collect_and_record_today()
    except Exception:
        pass  # Don't let analytics failures break CLI

    output = show_daily_stats_if_needed()
    if output:
        click.echo(output)
        click.echo()  # Blank line before command output

        # Check if opt-in teaser was shown (Day 2+)
        if "Unlock Community Insights" in output:
            response = click.prompt(
                "Enable community analytics? [y/n]",
                type=str,
                default="n",
            )
            if response.lower() in ("y", "yes"):
                save_analytics_decision(True)
                click.echo("Analytics enabled! Run 'ap insights' to see community comparisons.\n")
            else:
                save_analytics_decision(False)
                click.echo("No problem. You can enable later with 'ap analytics --enable'\n")


def _find_session(session_ref: str, session_type: str = "main"):
    """Find a session by number (current project) or ID prefix (any project).

    Numbers reference current project sessions only.
    ID prefixes search all sessions across all projects.
    """
    # Get current project sessions for number lookup
    cwd_sessions = get_sessions_for_cwd()
    if session_type != "all":
        cwd_sessions = [s for s in cwd_sessions if s.session_type == session_type]

    # Try to interpret as number first (current project only)
    try:
        idx = int(session_ref)
        if 1 <= idx <= len(cwd_sessions):
            return cwd_sessions[idx - 1]
        # Number out of range for current project
        return None
    except ValueError:
        pass

    # Try to match by session ID prefix (search ALL sessions)
    all_sessions = list_all_sessions()
    if session_type != "all":
        all_sessions = [s for s in all_sessions if s.session_type == session_type]

    return next((s for s in all_sessions if s.session_id.startswith(session_ref)), None)


@click.group()
@click.pass_context
def cli(ctx):
    """Afterpaths: A research log for AI-assisted work."""
    _load_env()

    # Show daily stats on first use each day (skip for help/completion)
    if ctx.invoked_subcommand is not None:
        _maybe_show_daily_stats()


@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Show all sessions across projects")
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main",
              help="Filter by session type (default: main)")
@click.option("--limit", default=10, help="Number of sessions to show")
@click.option("-v", "--verbose", is_flag=True, help="Show additional info (model used)")
def log(show_all, session_type, limit, verbose):
    """List recent AI coding sessions.

    By default, only shows main sessions (full conversations).
    Use --type=agent to see sub-agent sessions, or --type=all for everything.

    With --all, sessions from other projects are shown for context but only
    current project sessions are numbered. Use session IDs to access others.
    """
    cwd_sessions = get_sessions_for_cwd()
    all_sessions = list_all_sessions() if show_all else cwd_sessions

    if not all_sessions:
        click.echo("No sessions found." + (" Try --all to see all projects." if not show_all else ""))
        return

    # Filter by session type
    if session_type != "all":
        all_sessions = [s for s in all_sessions if s.session_type == session_type]
        cwd_sessions = [s for s in cwd_sessions if s.session_type == session_type]

    if not all_sessions:
        click.echo(f"No {session_type} sessions found. Try --type=all to see all session types.")
        return

    # Build set of current project session IDs for quick lookup
    cwd_session_ids = {s.session_id for s in cwd_sessions}

    # Count totals for display
    total_main = len([s for s in (list_all_sessions() if show_all else cwd_sessions) if s.session_type == "main"])
    total_agent = len([s for s in (list_all_sessions() if show_all else cwd_sessions) if s.session_type == "agent"])

    # Check which sessions have afterpaths summaries
    afterpaths_dir = get_afterpaths_dir()
    summaries_dir = afterpaths_dir / "summaries"

    click.echo(f"Sessions: {total_main} main, {total_agent} agent")
    click.echo("-" * 40)

    # Track numbering for current project sessions only
    cwd_index = 0

    for s in all_sessions[:limit]:
        # Check if afterpaths summary exists
        summary_path = summaries_dir / f"{s.session_id}.md"
        has_summary = summary_path.exists()

        # Show index, type badge, summary indicator, and session ID
        type_badge = "[agent]" if s.session_type == "agent" else ""
        summary_badge = "[summarized]" if has_summary else ""

        # Only number sessions from current project
        is_cwd_session = s.session_id in cwd_session_ids
        if is_cwd_session:
            cwd_index += 1
            click.echo(f"[{cwd_index}] {s.session_id[:12]}  {type_badge}{summary_badge}")
        else:
            # No number for other projects - show ID only with indent to align
            click.echo(f"    {s.session_id[:12]}  {type_badge}{summary_badge}")

        # Show model info if verbose
        if verbose:
            from .analytics import _normalize_model_name
            adapter = _get_adapter_for_session(s)
            entries = adapter.read_session(s)
            models = sorted({_normalize_model_name(e.model) for e in entries if e.model})
            if models:
                click.echo(f"    Model: {', '.join(models)}")

        # Show project (shortened) - always show for non-cwd sessions, optional for cwd
        if show_all and not is_cwd_session:
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
    Numbers reference current project sessions; use ID prefix for other projects.
    """
    session = _find_session(session_ref, session_type)

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
    from .analytics import _normalize_model_name

    adapter = _get_adapter_for_session(session)
    entries = adapter.read_session(session)
    refs = extract_all_git_refs(entries)
    models = sorted(
        {_normalize_model_name(entry.model) for entry in entries if entry.model}
    )

    click.echo(f"Session: {session.session_id}")
    click.echo(f"Project: {session.project}")
    click.echo(f"Entries: {len(entries)}")
    if models:
        click.echo(f"Models: {', '.join(models)}")
    click.echo(f"Git refs: {format_refs_for_display(refs)}")
    click.echo("-" * 60)

    for i, entry in enumerate(entries[:limit]):
        role_display = entry.role.upper()
        if entry.tool_name:
            role_display = f"TOOL:{entry.tool_name}"
        if entry.model:
            role_display = f"{role_display}:{_normalize_model_name(entry.model)}"

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
    Numbers reference current project sessions; use ID prefix for other projects.

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

    session = _find_session(session_ref, session_type)

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

    # Check for analytics opt-in (only prompt once)
    _maybe_prompt_analytics_optin()


def _maybe_prompt_analytics_optin():
    """Prompt for analytics opt-in if user hasn't decided yet."""
    from .config import has_analytics_decision, save_analytics_decision

    if has_analytics_decision():
        return

    click.echo()
    click.echo("Help improve afterpaths for everyone!")
    click.echo("Share anonymized usage stats and get community insights.")
    click.echo("We collect: session counts, rule counts by category, tech stack.")
    click.echo("We DON'T collect: code, file contents, or rule text.")
    click.echo()

    opted_in = click.confirm("Enable community analytics?", default=True)
    save_analytics_decision(opted_in)

    if opted_in:
        click.echo()
        click.echo("Thanks! Run 'afterpaths insights' to see community stats.")
    else:
        click.echo()
        click.echo("No problem. You can enable later with 'afterpaths analytics --enable'.")


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
@click.option("--type", "session_type", type=click.Choice(["main", "agent", "all"]), default="main",
              help="Filter by session type")
def refs(session_ref, session_type):
    """Show git refs detected in a session.

    SESSION_REF can be a session number or ID prefix.
    Numbers reference current project sessions; use ID prefix for other projects.
    """
    from .git_refs import extract_all_git_refs

    session = _find_session(session_ref, session_type)

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

    SESSION_REF can be a session number or ID prefix.
    Numbers reference current project sessions; use ID prefix for other projects.

    Useful for understanding what changes a session made before tracing commits.
    """
    from .file_tracking import extract_file_activity

    session = _find_session(session_ref, session_type)

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
    Numbers reference current project sessions; use ID prefix for other projects.

    Examples:
        afterpaths path 1
        afterpaths path 1 | xargs cat | jq .
        cat $(afterpaths path 1) | jq '.[] | select(.type == "user")'
    """
    session = _find_session(session_ref, session_type)

    if not session:
        click.echo(f"Session not found: {session_ref}", err=True)
        click.echo("Use 'afterpaths log' to see available sessions.", err=True)
        return

    # Print just the path (no newline issues, easy to use with xargs/subshell)
    click.echo(session.path)


@cli.command()
def insights():
    """Show community insights and your usage stats.

    Displays how your afterpaths usage compares to the community,
    including session counts, rule generation, and patterns.

    Requires analytics to be enabled. Enable with:
        afterpaths analytics --enable
    """
    from .config import is_analytics_enabled
    from .analytics import get_insights, format_insights

    if not is_analytics_enabled():
        click.echo("Analytics is not enabled.")
        click.echo()
        click.echo("Enable analytics to see community insights:")
        click.echo("  afterpaths analytics --enable")
        return

    insights_data = get_insights(Path.cwd())
    click.echo(format_insights(insights_data))


@cli.command()
@click.option("--enable", is_flag=True, help="Enable community analytics")
@click.option("--disable", is_flag=True, help="Disable community analytics")
def analytics(enable, disable):
    """Manage community analytics settings.

    When enabled, afterpaths shares anonymized usage stats:
    - Session counts and duration
    - Rule counts by category
    - Tech stack (detected from project files)

    In return, you get community insights via 'afterpaths insights'.

    We DON'T collect: code, file contents, rule text, or project names.
    """
    from .config import (
        is_analytics_enabled,
        enable_analytics,
        disable_analytics,
        has_analytics_decision,
    )

    if enable and disable:
        click.echo("Cannot use both --enable and --disable")
        return

    if enable:
        enable_analytics()
        click.echo("Analytics enabled.")
        click.echo("Run 'afterpaths insights' to see community stats.")
        return

    if disable:
        disable_analytics()
        click.echo("Analytics disabled.")
        click.echo("Your data is no longer shared.")
        return

    # No flags - show current status
    if not has_analytics_decision():
        click.echo("Analytics: not configured")
        click.echo()
        click.echo("Enable with: afterpaths analytics --enable")
        click.echo("This shares anonymized stats and gives you community insights.")
    elif is_analytics_enabled():
        click.echo("Analytics: enabled")
        click.echo()
        click.echo("Run 'afterpaths insights' to see community stats.")
        click.echo("Disable with: afterpaths analytics --disable")
    else:
        click.echo("Analytics: disabled")
        click.echo()
        click.echo("Enable with: afterpaths analytics --enable")


@cli.command()
@click.option("--daily", is_flag=True, help="Show day-by-day breakdown")
@click.option("--days", default=7, help="Number of days to show (default: 7)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def stats(daily, days, as_json):
    """Show your local usage analytics.

    Displays sessions, messages, tool calls, and model performance
    from your locally stored analytics data.

    Examples:
        ap stats              # Last 7 days summary
        ap stats --daily      # Day-by-day breakdown
        ap stats --days 30    # Last 30 days
        ap stats --json       # Export as JSON
    """
    from .local_analytics import (
        get_period_stats,
        get_recent_snapshots,
        get_lifetime_stats,
        collect_and_record_today,
        backfill_analytics,
        load_analytics,
    )
    import json as json_module

    # Check if we need to backfill (if we have very little historical data)
    data = load_analytics()
    snapshots = data.get("snapshots", [])
    if len(snapshots) < 3:  # Less than 3 days of data
        click.echo("Importing analytics from session history...")
        backfilled = backfill_analytics(days=30)
        if backfilled > 0:
            click.echo(f"Imported {backfilled} days of historical data.\n")

    # Ensure we have latest data
    collect_and_record_today()

    if as_json:
        # JSON export for later sharing
        snapshots = get_recent_snapshots(days)
        lifetime = get_lifetime_stats()
        data = {
            "period_days": days,
            "snapshots": [s.to_dict() for s in snapshots],
            "lifetime": lifetime.to_dict(),
        }
        click.echo(json_module.dumps(data, indent=2))
        return

    if daily:
        # Day-by-day breakdown
        snapshots = get_recent_snapshots(days)
        if not snapshots:
            click.echo("No analytics data yet. Use afterpaths for a day to see stats.")
            return

        click.echo(f"Daily Stats (last {days} days)")
        click.echo("=" * 60)
        click.echo()

        for s in reversed(snapshots):  # Most recent first
            rej_rate = f"{s.rejection_rate:.1f}%" if s.tool_calls > 0 else "-"
            fail_rate = f"{s.failure_rate:.1f}%" if s.tool_calls > 0 else "-"

            click.echo(f"{s.date}")
            click.echo(f"  Sessions: {s.sessions:<4} Messages: {s.messages:<5} Tool calls: {s.tool_calls}")
            click.echo(f"  Rejections: {s.rejections} ({rej_rate})  Failures: {s.failures} ({fail_rate})")

            if s.model_stats:
                models = ", ".join(s.model_stats.keys())
                click.echo(f"  Models: {models}")

            click.echo()
    else:
        # Summary view
        period = get_period_stats(days)
        lifetime = get_lifetime_stats()

        click.echo(_format_stats_display(period, lifetime, days))


def _format_stats_display(period: dict, lifetime, days: int) -> str:
    """Format stats for terminal display."""
    lines = []
    box_width = 64
    inner = box_width - 4

    def pad(text: str) -> str:
        return f"│ {text:<{inner}} │"

    # Header
    lines.append(f"╭─ Your Analytics {'─' * (box_width - 19)}╮")
    lines.append(pad(""))

    # Period stats
    lines.append(pad(f"Last {days} Days ({period['days_active']} active)"))
    lines.append(pad(f"  Sessions: {period['sessions']:<6} Messages: {period['messages']:<6} Tool calls: {period['tool_calls']}"))

    if period['tool_calls'] > 0:
        rej = period['rejections']
        fail = period['failures']
        rej_rate = period['rejection_rate']
        fail_rate = period['failure_rate']
        lines.append(pad(f"  Rejections: {rej} ({rej_rate:.1f}%)    Failures: {fail} ({fail_rate:.1f}%)"))

    # Model breakdown
    if period['model_stats']:
        lines.append(pad(""))
        lines.append(pad("  By Model:"))
        for model, stats in sorted(period['model_stats'].items()):
            tc = stats['tool_calls']
            rej = stats['rejections']
            fail = stats['failures']
            if tc > 0:
                rej_pct = rej / tc * 100
                fail_pct = fail / tc * 100
                lines.append(pad(f"    {model}: {tc} calls, {rej_pct:.1f}% rej, {fail_pct:.1f}% fail"))

    lines.append(pad(""))

    # Lifetime stats
    if lifetime.total_sessions > 0:
        lines.append(pad("Lifetime"))
        lines.append(pad(f"  Days active: {lifetime.total_days_active:<4} Total sessions: {lifetime.total_sessions}"))
        lines.append(pad(f"  Total messages: {lifetime.total_messages:<6} Total tool calls: {lifetime.total_tool_calls}"))

        if lifetime.total_tool_calls > 0:
            lines.append(pad(f"  Overall rejection rate: {lifetime.rejection_rate:.1f}%    Failure rate: {lifetime.failure_rate:.1f}%"))

        if lifetime.ides_used:
            ides = ", ".join(lifetime.ides_used)
            lines.append(pad(f"  IDEs: {ides}"))

        lines.append(pad(""))

    # Footer
    lines.append(pad("Run 'ap stats --daily' for day-by-day breakdown"))
    lines.append(pad("Run 'ap stats --json' to export for sharing"))
    lines.append(f"╰{'─' * (box_width - 2)}╯")

    return "\n".join(lines)


@cli.command()
def status():
    """Show afterpaths status and configuration."""
    from .llm import get_provider_info
    from .storage import get_afterpaths_dir, get_meta
    from .config import is_analytics_enabled, has_analytics_decision
    from .stack import detect_stack

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

    # Analytics status
    if has_analytics_decision():
        analytics_status = "enabled" if is_analytics_enabled() else "disabled"
    else:
        analytics_status = "not configured"
    click.echo(f"Analytics: {analytics_status}")

    # Tech stack
    stack = detect_stack(Path.cwd())
    if stack:
        click.echo(f"Detected Stack: {', '.join(stack)}")


def main():
    cli()


if __name__ == "__main__":
    main()
