# Afterpaths Implementation Guide

**Scope:** Multi-source session capture, LLM summarization, git ref linking  
**Philosophy:** Minimal, working, extensible via source adapters

## Architecture

```
afterpaths/
├── __init__.py
├── cli.py              # Entry point, commands
├── sources/            # Source adapters (one per tool)
│   ├── __init__.py
│   ├── base.py         # Abstract base class
│   ├── claude_code.py  # Claude Code adapter (v0.1)
│   ├── cursor.py       # Cursor adapter (v0.2)
│   └── copilot.py      # GitHub Copilot adapter (v0.2)
├── summarize.py        # LLM summarization
├── git_refs.py         # Extract git refs from transcripts
└── storage.py          # Manage .afterpaths/ directory
```

Local storage:
```
.afterpaths/                      # In project root, gitignored
├── summaries/
│   └── {session_id}.md           # Generated research logs
└── meta.json                     # Session index
```

## Source Adapter Pattern

Each AI coding tool stores sessions differently. Source adapters normalize them to a common structure.

### Base Adapter

**sources/base.py**
```python
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SessionEntry:
    """Normalized conversation entry."""
    role: str           # 'user', 'assistant', 'tool_result'
    content: str
    timestamp: str
    tool_name: str = None
    tool_input: dict = None


@dataclass  
class SessionInfo:
    """Session metadata."""
    session_id: str
    source: str         # 'claude_code', 'cursor', etc.
    project: str
    path: Path
    modified: datetime
    size: int


class SourceAdapter(ABC):
    """Base class for AI coding tool adapters."""
    
    name: str
    
    @abstractmethod
    def list_sessions(self, project_filter: str = None) -> list[SessionInfo]:
        pass
    
    @abstractmethod
    def read_session(self, session: SessionInfo) -> list[SessionEntry]:
        pass
    
    @classmethod
    def is_available(cls) -> bool:
        return True


def get_all_adapters() -> list[SourceAdapter]:
    """Get all available source adapters."""
    from .claude_code import ClaudeCodeAdapter
    
    adapters = []
    for adapter_class in [ClaudeCodeAdapter]:
        if adapter_class.is_available():
            adapters.append(adapter_class())
    return adapters


def list_all_sessions(project_filter: str = None) -> list[SessionInfo]:
    """List sessions from all available sources."""
    sessions = []
    for adapter in get_all_adapters():
        sessions.extend(adapter.list_sessions(project_filter))
    return sorted(sessions, key=lambda x: x.modified, reverse=True)
```

### Claude Code Adapter

**sources/claude_code.py**
```python
from pathlib import Path
from datetime import datetime
import json
import base64
import os

from .base import SourceAdapter, SessionInfo, SessionEntry


class ClaudeCodeAdapter(SourceAdapter):
    """Adapter for Claude Code sessions stored in ~/.claude/projects/"""
    
    name = "claude_code"
    
    @classmethod
    def is_available(cls) -> bool:
        return (Path.home() / ".claude" / "projects").exists()
    
    def list_sessions(self, project_filter: str = None) -> list[SessionInfo]:
        sessions = []
        projects_dir = Path.home() / ".claude" / "projects"
        
        if not projects_dir.exists():
            return sessions
        
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            
            project_name = self._decode_project_name(project_dir.name)
            
            if project_filter and project_filter not in project_name:
                continue
            
            for jsonl_file in project_dir.glob("*.jsonl"):
                stat = jsonl_file.stat()
                sessions.append(SessionInfo(
                    session_id=jsonl_file.stem,
                    source=self.name,
                    project=project_name,
                    path=jsonl_file,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                    size=stat.st_size
                ))
        
        return sessions
    
    def read_session(self, session: SessionInfo) -> list[SessionEntry]:
        entries = []
        
        with open(session.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    entry = self._normalize_entry(raw)
                    if entry:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        
        return entries
    
    def _normalize_entry(self, raw: dict) -> SessionEntry | None:
        entry_type = raw.get("type")
        
        if entry_type == "user":
            return SessionEntry(
                role="user",
                content=self._extract_content(raw),
                timestamp=raw.get("timestamp"),
            )
        
        elif entry_type == "assistant":
            tool_use = raw.get("tool_use")
            return SessionEntry(
                role="assistant",
                content=self._extract_content(raw),
                timestamp=raw.get("timestamp"),
                tool_input=tool_use.get("input") if tool_use else None,
                tool_name=tool_use.get("name") if tool_use else None,
            )
        
        elif entry_type == "tool_result":
            return SessionEntry(
                role="tool_result",
                content=self._extract_content(raw),
                timestamp=raw.get("timestamp"),
                tool_name=raw.get("name"),
            )
        
        return None
    
    def _extract_content(self, entry: dict) -> str:
        content = entry.get("content", "")
        
        if isinstance(content, str):
            return content
        
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, str):
                    texts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            return "\n".join(texts)
        
        return str(content)
    
    @staticmethod
    def _decode_project_name(hash_name: str) -> str:
        try:
            return base64.urlsafe_b64decode(hash_name + "==").decode("utf-8")
        except:
            return hash_name


def get_sessions_for_cwd() -> list[SessionInfo]:
    """Get Claude Code sessions for current working directory."""
    return ClaudeCodeAdapter().list_sessions(project_filter=os.getcwd())
```

## LLM Summarization

**summarize.py**
```python
from pathlib import Path
import json
from datetime import datetime

import anthropic

from .sources.base import SessionInfo, SessionEntry
from .git_refs import extract_all_git_refs


def summarize_session(
    entries: list[SessionEntry], 
    session: SessionInfo,
    notes: str = ""
) -> str:
    """Generate a markdown summary from a session."""
    
    if not entries:
        return "# Empty Session\n\nNo conversation entries found."
    
    transcript = format_transcript_for_summary(entries)
    timestamps = [e.timestamp for e in entries if e.timestamp]
    duration = calculate_duration(timestamps)
    git_refs = extract_all_git_refs(entries)
    
    client = anthropic.Anthropic()
    
    prompt = f"""Analyze this AI coding session and produce a structured research log.

<transcript>
{transcript}
</transcript>

<git_refs_detected>
{json.dumps(git_refs) if git_refs else "None"}
</git_refs_detected>

<additional_notes>
{notes}
</additional_notes>

Produce markdown with these sections (skip any that don't apply):

# [Title from main task/objective]

**Date:** [from timestamps] | **Duration:** {duration or "Unknown"}
**Git refs:** [commits/branches detected, or "None"]

## Summary
2-3 sentences on what was accomplished or explored.

## Key Decisions
Choices made and why. Include alternatives considered.

## Discoveries  
What was learned? Unexpected findings?

## Dead Ends
Approaches tried and abandoned. Why didn't they work?

## Open Questions
Unresolved items for follow-up.

Be concise. Focus on decisions, discoveries, and dead ends."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.content[0].text


def format_transcript_for_summary(entries: list[SessionEntry]) -> str:
    lines = []
    
    for entry in entries:
        content = entry.content[:1000]
        ts = entry.timestamp[:16] if entry.timestamp else ""
        
        if entry.role == "user":
            lines.append(f"[{ts}] USER: {content}")
        elif entry.role == "assistant":
            lines.append(f"[{ts}] ASSISTANT: {content}")
            if entry.tool_name:
                lines.append(f"  → Tool: {entry.tool_name}")
        elif entry.role == "tool_result":
            preview = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"  ← Result: {preview}")
    
    full_text = "\n".join(lines)
    
    if len(full_text) > 30000:
        half = 15000
        full_text = full_text[:half] + "\n\n[...truncated...]\n\n" + full_text[-half:]
    
    return full_text


def calculate_duration(timestamps: list[str]) -> str | None:
    if len(timestamps) < 2:
        return None
    try:
        start = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
        delta = end - start
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"
    except:
        return None
```

## Git Ref Linking

**git_refs.py**
```python
import re
from .sources.base import SessionEntry


def extract_all_git_refs(entries: list[SessionEntry]) -> list[str]:
    refs = set()
    
    for entry in entries:
        refs.update(extract_git_refs_from_text(entry.content))
        if entry.tool_input:
            refs.update(extract_git_refs_from_text(str(entry.tool_input)))
    
    return sorted(refs)


def extract_git_refs_from_text(text: str) -> set[str]:
    refs = set()
    if not text:
        return refs
    
    # Commit hashes
    for match in re.finditer(r'commit\s+([0-9a-f]{7,40})', text, re.I):
        refs.add(f"commit:{match.group(1)[:12]}")
    
    for match in re.finditer(r'(?:^|[\s\[])([0-9a-f]{7,12})(?:[\s\].]|$)', text, re.M):
        candidate = match.group(1)
        if len(set(candidate)) > 3:
            refs.add(f"commit:{candidate}")
    
    # Branch names
    branch_patterns = [
        r'git\s+checkout\s+(?:-b\s+)?([^\s]+)',
        r'git\s+switch\s+(?:-c\s+)?([^\s]+)',
        r'On\s+branch\s+([^\s]+)',
        r"Switched\s+to.*?'([^']+)'",
    ]
    
    skip = {'main', 'master', '-', '--', '-b', '-c'}
    for pattern in branch_patterns:
        for match in re.finditer(pattern, text):
            branch = match.group(1).strip()
            if branch and branch not in skip:
                refs.add(f"branch:{branch}")
    
    return refs
```

## Storage

**storage.py**
```python
from pathlib import Path
from datetime import datetime
import json


def get_afterpaths_dir(project_root: Path = None) -> Path:
    if project_root is None:
        project_root = Path.cwd()
    
    afterpaths_dir = project_root / ".afterpaths"
    afterpaths_dir.mkdir(exist_ok=True)
    (afterpaths_dir / "summaries").mkdir(exist_ok=True)
    
    gitignore = afterpaths_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    
    return afterpaths_dir


def get_meta(afterpaths_dir: Path) -> dict:
    meta_path = afterpaths_dir / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {"sessions": [], "version": 1}


def save_meta(afterpaths_dir: Path, meta: dict):
    meta_path = afterpaths_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str))


def add_session_to_index(
    afterpaths_dir: Path,
    session_id: str,
    source: str,
    source_path: Path,
    summary_path: Path,
    git_refs: list[str] = None
):
    meta = get_meta(afterpaths_dir)
    
    existing = next(
        (s for s in meta["sessions"] if s["session_id"] == session_id), 
        None
    )
    
    if existing:
        existing.update({
            "summary_path": str(summary_path),
            "git_refs": git_refs or [],
            "updated_at": datetime.now().isoformat()
        })
    else:
        meta["sessions"].append({
            "session_id": session_id,
            "source": source,
            "source_path": str(source_path),
            "summary_path": str(summary_path),
            "git_refs": git_refs or [],
            "created_at": datetime.now().isoformat()
        })
    
    save_meta(afterpaths_dir, meta)


def find_sessions_by_git_ref(afterpaths_dir: Path, ref: str) -> list[dict]:
    meta = get_meta(afterpaths_dir)
    return [
        s for s in meta["sessions"] 
        if any(ref in r for r in s.get("git_refs", []))
    ]
```

## CLI

**cli.py**
```python
import click
from pathlib import Path

from .sources.base import list_all_sessions, get_all_adapters
from .sources.claude_code import get_sessions_for_cwd, ClaudeCodeAdapter
from .summarize import summarize_session
from .storage import (
    get_afterpaths_dir, 
    add_session_to_index, 
    find_sessions_by_git_ref, 
    get_meta
)
from .git_refs import extract_all_git_refs


@click.group()
def cli():
    """Afterpaths: A research log for AI-assisted work."""
    pass


@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Show all sessions")
@click.option("--limit", default=10, help="Number to show")
def log(show_all, limit):
    """List recent AI coding sessions."""
    sessions = list_all_sessions() if show_all else get_sessions_for_cwd()
    
    if not sessions:
        click.echo("No sessions found." + (" Try --all" if not show_all else ""))
        return
    
    for i, s in enumerate(sessions[:limit]):
        click.echo(f"[{i+1}] {s.session_id}")
        click.echo(f"    {s.modified.strftime('%Y-%m-%d %H:%M')} | {s.size/1024:.1f}KB")


@cli.command()
@click.argument("session_num", type=int)
@click.option("--notes", default="", help="Context for summarization")
def summarize(session_num, notes):
    """Generate summary for a session."""
    sessions = get_sessions_for_cwd() or list_all_sessions()
    
    if not 1 <= session_num <= len(sessions):
        click.echo(f"Invalid. Use 1-{len(sessions)}")
        return
    
    session = sessions[session_num - 1]
    click.echo(f"Summarizing {session.session_id}...")
    
    adapter = next(
        (a for a in get_all_adapters() if a.name == session.source),
        ClaudeCodeAdapter()
    )
    entries = adapter.read_session(session)
    summary = summarize_session(entries, session, notes)
    
    afterpaths_dir = get_afterpaths_dir()
    summary_path = afterpaths_dir / "summaries" / f"{session.session_id}.md"
    summary_path.write_text(summary)
    
    git_refs = extract_all_git_refs(entries)
    add_session_to_index(
        afterpaths_dir, 
        session.session_id,
        session.source,
        session.path, 
        summary_path, 
        git_refs
    )
    
    click.echo(f"Saved: {summary_path}")
    click.echo(f"Git refs: {git_refs or 'None'}\n")
    click.echo(summary)


@cli.command()
@click.argument("session_id")
@click.option("--raw", is_flag=True, help="Show raw transcript")
def show(session_id, raw):
    """Show session summary or transcript."""
    if raw:
        sessions = list_all_sessions()
        session = next((s for s in sessions if session_id in s.session_id), None)
        if session:
            adapter = next(
                (a for a in get_all_adapters() if a.name == session.source),
                ClaudeCodeAdapter()
            )
            for entry in adapter.read_session(session):
                click.echo(f"[{entry.role}] {entry.content[:500]}\n")
        else:
            click.echo("Session not found")
    else:
        summary_path = get_afterpaths_dir() / "summaries" / f"{session_id}.md"
        if summary_path.exists():
            click.echo(summary_path.read_text())
        else:
            click.echo("No summary. Run: afterpaths summarize <num>")


@cli.command()
@click.argument("git_ref")
def link(git_ref):
    """Find sessions referencing a git commit/branch."""
    sessions = find_sessions_by_git_ref(get_afterpaths_dir(), git_ref)
    
    if not sessions:
        click.echo(f"No sessions reference: {git_ref}")
        return
    
    for s in sessions:
        click.echo(f"{s['session_id']}")
        click.echo(f"  Refs: {', '.join(s.get('git_refs', []))}")


@cli.command()
@click.option("-o", "--output", help="Output file path")
def export(output):
    """Export all summaries."""
    meta = get_meta(get_afterpaths_dir())
    
    if not meta["sessions"]:
        click.echo("No summarized sessions to export.")
        return
    
    content_parts = ["# Afterpaths Export\n"]
    
    for session in meta["sessions"]:
        summary_path = Path(session.get("summary_path", ""))
        if summary_path.exists():
            content_parts.append(summary_path.read_text())
            content_parts.append("\n---\n")
    
    content = "\n".join(content_parts)
    
    if output:
        Path(output).write_text(content)
        click.echo(f"Exported to: {output}")
    else:
        click.echo(content)


def main():
    cli()
```

## pyproject.toml

```toml
[project]
name = "afterpaths"
version = "0.1.0"
description = "A research log for AI-assisted work"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = [
    "anthropic>=0.39.0",
    "click>=8.0.0",
]

[project.scripts]
afterpaths = "afterpaths.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

## Adding a New Source

1. Create `sources/{tool_name}.py`
2. Implement `SourceAdapter`:
   - `is_available()` — Check if storage exists
   - `list_sessions()` — Find session files
   - `read_session()` — Parse to `SessionEntry` list
3. Add to `get_all_adapters()` in `sources/base.py`

## Testing Checklist

- [ ] `afterpaths log` finds sessions
- [ ] `afterpaths summarize 1` generates summary
- [ ] `afterpaths show <id>` displays summary
- [ ] `afterpaths link <commit>` finds sessions
- [ ] .afterpaths/ created with .gitignore

## What NOT to Build Yet

- Rule distillation (Pro feature)
- Embeddings/semantic search
- Watch mode
- Web UI
