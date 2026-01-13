"""Manage .afterpaths/ directory and session metadata."""

import json
from datetime import datetime
from pathlib import Path


def get_afterpaths_dir(project_root: Path | None = None) -> Path:
    """Get or create the .afterpaths directory."""
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
    """Load metadata from meta.json."""
    meta_path = afterpaths_dir / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {"sessions": [], "version": 1}


def save_meta(afterpaths_dir: Path, meta: dict):
    """Save metadata to meta.json."""
    meta_path = afterpaths_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str))


def add_session_to_index(
    afterpaths_dir: Path,
    session_id: str,
    source: str,
    source_path: Path,
    summary_path: Path,
    git_refs: list[str] | None = None,
):
    """Add or update a session in the metadata index."""
    meta = get_meta(afterpaths_dir)

    existing = next(
        (s for s in meta["sessions"] if s["session_id"] == session_id), None
    )

    if existing:
        existing.update(
            {
                "summary_path": str(summary_path),
                "git_refs": git_refs or [],
                "updated_at": datetime.now().isoformat(),
            }
        )
    else:
        meta["sessions"].append(
            {
                "session_id": session_id,
                "source": source,
                "source_path": str(source_path),
                "summary_path": str(summary_path),
                "git_refs": git_refs or [],
                "created_at": datetime.now().isoformat(),
            }
        )

    save_meta(afterpaths_dir, meta)


def find_sessions_by_git_ref(afterpaths_dir: Path, ref: str) -> list[dict]:
    """Find sessions that reference a specific git ref."""
    meta = get_meta(afterpaths_dir)
    return [
        s for s in meta["sessions"] if any(ref in r for r in s.get("git_refs", []))
    ]
