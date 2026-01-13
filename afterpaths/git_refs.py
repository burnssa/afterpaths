"""Extract git references (commits, branches) from session transcripts."""

import re
import subprocess
from pathlib import Path
from .sources.base import SessionEntry


def extract_all_git_refs(
    entries: list[SessionEntry],
    repo_path: str | None = None,
    filter_to_repo: bool = True,
) -> dict[str, set[str]]:
    """Extract git refs from session entries.

    Extracts refs from all content, then optionally filters to only include
    refs that actually exist in the current repo (to avoid false positives
    from discussion of other projects).

    Args:
        entries: Session entries to extract from
        repo_path: Path to git repo for filtering (defaults to cwd)
        filter_to_repo: If True, only return refs that exist in the repo

    Returns dict with 'commits' and 'branches' sets.
    """
    refs = {"commits": set(), "branches": set()}

    for entry in entries:
        # Extract from all text content
        entry_refs = extract_git_refs_from_text(entry.content)
        refs["commits"].update(entry_refs["commits"])
        refs["branches"].update(entry_refs["branches"])

        # Also check tool inputs
        if entry.tool_input:
            input_refs = extract_git_refs_from_text(str(entry.tool_input))
            refs["commits"].update(input_refs["commits"])
            refs["branches"].update(input_refs["branches"])

    # Filter to only refs that exist in the current repo
    if filter_to_repo and (refs["commits"] or refs["branches"]):
        refs = filter_refs_to_repo(refs, repo_path)

    return refs


def filter_refs_to_repo(
    refs: dict[str, set[str]],
    repo_path: str | None = None,
) -> dict[str, set[str]]:
    """Filter refs to only those that exist in the given git repo."""
    if repo_path is None:
        repo_path = str(Path.cwd())

    filtered = {"commits": set(), "branches": set()}

    # Get all branches in the repo
    try:
        result = subprocess.run(
            ["git", "branch", "-a", "--format=%(refname:short)"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        if result.returncode == 0:
            repo_branches = set(result.stdout.strip().split("\n"))
            # Also add without origin/ prefix for remote branches
            repo_branches.update(
                b.replace("origin/", "") for b in repo_branches if b.startswith("origin/")
            )
            # Filter to branches that exist
            filtered["branches"] = refs["branches"] & repo_branches
    except Exception:
        # If git fails, don't filter branches
        filtered["branches"] = refs["branches"]

    # Verify commits exist in the repo
    for commit in refs["commits"]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=2,
            )
            if result.returncode == 0:
                filtered["commits"].add(commit)
        except Exception:
            pass

    return filtered


def extract_git_refs_from_text(text: str) -> dict[str, set[str]]:
    """Extract git refs from a text string."""
    refs = {"commits": set(), "branches": set()}

    if not text:
        return refs

    # === Commit hashes ===

    # Explicit "commit <hash>" mentions
    for match in re.finditer(r'commit\s+([0-9a-f]{7,40})\b', text, re.I):
        refs["commits"].add(match.group(1)[:12])

    # Git log/show output: lines starting with commit hash
    for match in re.finditer(r'^([0-9a-f]{40})\b', text, re.M):
        refs["commits"].add(match.group(1)[:12])

    # Short hashes in common contexts (avoiding false positives)
    # Look for patterns like "ab3f2d1" in git-related context
    git_context_patterns = [
        r'(?:cherry-pick|revert|reset|checkout)\s+([0-9a-f]{7,12})\b',
        r'\b([0-9a-f]{7,12})\.\.+([0-9a-f]{7,12})\b',  # ranges like abc123..def456
        r'HEAD~?\d*\s*([0-9a-f]{7,12})\b',
    ]
    for pattern in git_context_patterns:
        for match in re.finditer(pattern, text, re.I):
            for group in match.groups():
                if group and len(set(group)) > 3:  # avoid low-entropy matches
                    refs["commits"].add(group[:12])

    # === Branch names ===

    branch_patterns = [
        # git checkout/switch commands
        (r'git\s+checkout\s+(?:-b\s+)?([^\s]+)', 1),
        (r'git\s+switch\s+(?:-c\s+)?([^\s]+)', 1),
        # git branch commands
        (r'git\s+branch\s+(?:-[dDmM]\s+)?([^\s]+)', 1),
        # Status output
        (r'On\s+branch\s+([^\s]+)', 1),
        (r"Switched\s+to.*?['\"]([^'\"]+)['\"]", 1),
        (r'Switched\s+to\s+branch\s+([^\s]+)', 1),
        # Merge/rebase
        (r'git\s+merge\s+([^\s]+)', 1),
        (r'git\s+rebase\s+([^\s]+)', 1),
        # Push/pull with branch
        (r'git\s+push\s+\w+\s+([^\s:]+)', 1),
        (r'git\s+pull\s+\w+\s+([^\s]+)', 1),
        # origin/branch references
        (r'\b(?:origin|upstream)/([^\s,\)]+)', 1),
    ]

    skip_branches = {
        'main', 'master', '-', '--', '-b', '-c', '-d', '-D', '-m', '-M',
        '.', '..', 'head', 'fetch_head', 'orig_head',  # lowercase for comparison
        # Common false positives from documentation/discussion
        'branch', 'branches', 'commit', 'commits', 'ref', 'refs',
        'the', 'a', 'an', 'to', 'from', 'with', 'for', 'and', 'or',
        'commands', 'command', 'session', 'sessions', 'git', 'code',
    }

    for pattern, group_idx in branch_patterns:
        for match in re.finditer(pattern, text):
            branch = match.group(group_idx).strip().rstrip('.,:;')
            if not branch:
                continue

            # Clean up branch name
            branch = branch.strip("'\"")

            # Skip if in blocklist
            if branch.lower() in skip_branches:
                continue

            # Skip if starts with dash (flag) or contains newlines
            if branch.startswith('-') or '\n' in branch:
                continue

            # Valid branch names: alphanumeric with /, -, _, .
            # Must have at least one letter to avoid pure numbers
            if not re.match(r'^[a-zA-Z0-9/_.-]+$', branch):
                continue
            if not re.search(r'[a-zA-Z]', branch):
                continue

            # Skip commit range notation (branch1..branch2)
            if '..' in branch:
                continue

            refs["branches"].add(branch)

    return refs


def format_refs_for_display(refs: dict[str, set[str]]) -> str:
    """Format refs dict for CLI display."""
    parts = []

    if refs.get("branches"):
        branches = sorted(refs["branches"])[:5]  # limit display
        parts.append(f"branches: {', '.join(branches)}")
        if len(refs["branches"]) > 5:
            parts[-1] += f" (+{len(refs['branches']) - 5} more)"

    if refs.get("commits"):
        commits = sorted(refs["commits"])[:5]
        parts.append(f"commits: {', '.join(commits)}")
        if len(refs["commits"]) > 5:
            parts[-1] += f" (+{len(refs['commits']) - 5} more)"

    return " | ".join(parts) if parts else "none detected"
