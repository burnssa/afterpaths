"""Core distillation logic - extract rules from session summaries."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .exporters.base import Rule
from .storage import get_afterpaths_dir, get_meta, save_meta


@dataclass
class RulesResult:
    """Result of a distillation run."""

    status: str  # success, no_summaries, no_new_summaries, error
    rules_extracted: int = 0
    rules_after_merge: int = 0
    sessions_processed: int = 0
    export_results: list = None
    error: str | None = None

    def __post_init__(self):
        if self.export_results is None:
            self.export_results = []


EXTRACTION_PROMPT = """Extract actionable rules from these session summaries for an AI coding assistant.

<summaries>
{summaries_content}
</summaries>

For each category, extract rules that would help future AI coding sessions on this project:

1. **DEAD_ENDS**: Approaches that failed and should be avoided
   - Format: Brief title + explanation of what doesn't work and why

2. **DECISIONS**: Architectural or technical choices made with rationale
   - Format: Brief title + what was chosen and why it's preferred

3. **GOTCHAS**: Non-obvious things to watch out for
   - Format: Brief title + what to be careful about and when

4. **PATTERNS**: Discovered techniques or conventions that work well
   - Format: Brief title + the pattern/technique to use

Output valid JSON:
{{
  "dead_ends": [
    {{"title": "Short descriptive title", "content": "Don't do X because Y", "source_session": "session_id", "confidence": "high"}}
  ],
  "decisions": [
    {{"title": "Short descriptive title", "content": "Use X over Y when Z because...", "source_session": "session_id", "confidence": "high"}}
  ],
  "gotchas": [
    {{"title": "Short descriptive title", "content": "Watch out for X when doing Y", "source_session": "session_id", "confidence": "high"}}
  ],
  "patterns": [
    {{"title": "Short descriptive title", "content": "For X, use pattern Y", "source_session": "session_id", "confidence": "high"}}
  ]
}}

Guidelines:
- Be specific and actionable, not vague
- Include enough context for the rule to be useful standalone
- Skip trivial or obvious learnings
- Set confidence to "high" if explicitly stated, "medium" if inferred
- Each rule should be 1-2 sentences max
- Use the actual session_id from the summary metadata
"""


MERGE_PROMPT = """Merge and deduplicate these rules for an AI coding assistant.

<existing_rules>
{existing_rules_json}
</existing_rules>

<new_rules>
{new_rules_json}
</new_rules>

Tasks:
1. Identify duplicate or overlapping rules - merge them, keeping the clearest formulation
2. Identify contradictory rules - keep the more specific/recent one
3. Combine source_sessions lists when merging
4. Remove rules that are too vague to be actionable

Output valid JSON with the merged rules:
{{
  "dead_ends": [
    {{"title": "...", "content": "...", "source_sessions": ["id1", "id2"]}}
  ],
  "decisions": [...],
  "gotchas": [...],
  "patterns": [...]
}}

Guidelines:
- Prefer specific rules over vague ones
- When merging, use the clearest formulation
- Preserve all source session IDs
- Keep rules concise (1-2 sentences)
- Remove truly redundant rules rather than keeping duplicates
"""


def load_recent_summaries(days: int = 14) -> list[tuple[str, str, datetime]]:
    """Load summaries from the last N days.

    Returns list of (session_id, content, modified_time) tuples.
    """
    afterpaths_dir = get_afterpaths_dir()
    summaries_dir = afterpaths_dir / "summaries"

    if not summaries_dir.exists():
        return []

    cutoff = datetime.now() - timedelta(days=days)
    summaries = []

    for summary_file in summaries_dir.glob("*.md"):
        mtime = datetime.fromtimestamp(summary_file.stat().st_mtime)
        if mtime >= cutoff:
            content = summary_file.read_text()
            session_id = summary_file.stem
            summaries.append((session_id, content, mtime))

    # Sort by modification time (newest first)
    summaries.sort(key=lambda x: x[2], reverse=True)
    return summaries


def parse_summary_sections(content: str) -> dict[str, str]:
    """Parse markdown summary into sections.

    Returns dict with keys: discoveries, dead_ends, decisions, gotchas, open_questions
    """
    sections = {}
    current_section = None
    current_content = []

    section_map = {
        "discoveries": "discoveries",
        "dead ends": "dead_ends",
        "decisions": "decisions",
        "gotchas": "gotchas",
        "gotchas & warnings": "gotchas",
        "open questions": "open_questions",
        "summary": "summary",
    }

    for line in content.split("\n"):
        if line.startswith("## "):
            # Save previous section
            if current_section:
                sections[current_section] = "\n".join(current_content).strip()

            # Start new section
            header = line[3:].strip().lower()
            current_section = section_map.get(header)
            current_content = []
        elif current_section:
            current_content.append(line)

    # Save final section
    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def format_summaries_for_extraction(
    summaries: list[tuple[str, str, datetime]]
) -> str:
    """Format summaries for the extraction prompt."""
    parts = []

    for session_id, content, mtime in summaries:
        sections = parse_summary_sections(content)

        # Only include relevant sections
        relevant = []
        for key in ["discoveries", "dead_ends", "decisions", "gotchas"]:
            if key in sections and sections[key]:
                relevant.append(f"### {key.replace('_', ' ').title()}\n{sections[key]}")

        if relevant:
            parts.append(
                f"<session id=\"{session_id}\" date=\"{mtime.strftime('%Y-%m-%d')}\">\n"
                + "\n\n".join(relevant)
                + "\n</session>"
            )

    return "\n\n".join(parts)


def extract_rules_from_summaries(
    summaries: list[tuple[str, str, datetime]]
) -> dict[str, list[Rule]]:
    """Extract rules from summaries using LLM."""
    from .llm import generate

    if not summaries:
        return {}

    # Format summaries for prompt
    summaries_content = format_summaries_for_extraction(summaries)

    if not summaries_content.strip():
        return {}

    prompt = EXTRACTION_PROMPT.format(summaries_content=summaries_content)
    response = generate(prompt)

    # Parse JSON from response
    try:
        # Try to find JSON in the response
        content = response.content
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            data = json.loads(json_match.group())
        else:
            return {}
    except json.JSONDecodeError:
        return {}

    # Convert to Rule objects
    rules = {}
    for category in ["dead_ends", "decisions", "gotchas", "patterns"]:
        if category in data and data[category]:
            rules[category] = [
                Rule(
                    category=category,
                    title=r.get("title", "Untitled"),
                    content=r.get("content", ""),
                    source_sessions=[r.get("source_session", "unknown")],
                    confidence=r.get("confidence", "medium"),
                )
                for r in data[category]
                if r.get("content")
            ]

    return rules


def merge_rules(
    existing: dict[str, list[Rule]],
    new_rules: dict[str, list[Rule]],
) -> dict[str, list[Rule]]:
    """Merge new rules with existing rules using LLM deduplication."""
    from .llm import generate

    if not existing:
        return new_rules
    if not new_rules:
        return existing

    # Convert to JSON-serializable format
    def rules_to_json(rules_dict):
        result = {}
        for cat, rules in rules_dict.items():
            result[cat] = [
                {
                    "title": r.title,
                    "content": r.content,
                    "source_sessions": r.source_sessions,
                }
                for r in rules
            ]
        return result

    existing_json = json.dumps(rules_to_json(existing), indent=2)
    new_json = json.dumps(rules_to_json(new_rules), indent=2)

    prompt = MERGE_PROMPT.format(
        existing_rules_json=existing_json,
        new_rules_json=new_json,
    )

    response = generate(prompt)

    # Parse JSON from response
    try:
        content = response.content
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            data = json.loads(json_match.group())
        else:
            # Fall back to simple concatenation
            return _simple_merge(existing, new_rules)
    except json.JSONDecodeError:
        return _simple_merge(existing, new_rules)

    # Convert back to Rule objects
    merged = {}
    for category in ["dead_ends", "decisions", "gotchas", "patterns"]:
        if category in data and data[category]:
            merged[category] = [
                Rule(
                    category=category,
                    title=r.get("title", "Untitled"),
                    content=r.get("content", ""),
                    source_sessions=r.get("source_sessions", []),
                )
                for r in data[category]
                if r.get("content")
            ]

    return merged


def _simple_merge(
    existing: dict[str, list[Rule]],
    new_rules: dict[str, list[Rule]],
) -> dict[str, list[Rule]]:
    """Simple merge without LLM deduplication (fallback)."""
    merged = {}

    all_categories = set(existing.keys()) | set(new_rules.keys())

    for category in all_categories:
        merged[category] = list(existing.get(category, []))
        merged[category].extend(new_rules.get(category, []))

    return merged


def get_distill_metadata() -> dict:
    """Get metadata about previous distill runs."""
    afterpaths_dir = get_afterpaths_dir()
    meta = get_meta(afterpaths_dir)
    return meta.get("distill", {})


def update_distill_metadata(session_ids: list[str]) -> None:
    """Update metadata after a distill run."""
    afterpaths_dir = get_afterpaths_dir()
    meta = get_meta(afterpaths_dir)

    if "distill" not in meta:
        meta["distill"] = {
            "sessions_included": [],
            "version": 1,
        }

    # Add new session IDs (avoid duplicates)
    existing = set(meta["distill"].get("sessions_included", []))
    existing.update(session_ids)
    meta["distill"]["sessions_included"] = list(existing)
    meta["distill"]["last_run"] = datetime.now().isoformat()

    save_meta(afterpaths_dir, meta)


def run_extract_rules(
    days: int = 14,
    rebuild: bool = False,
    dry_run: bool = False,
    target: str | None = None,
    project_root: Path | None = None,
) -> RulesResult:
    """Main distillation logic.

    Args:
        days: Include summaries from last N days
        rebuild: Rebuild rules from scratch (ignore existing)
        dry_run: Preview without writing files
        target: Specific export target (None = all detected)
        project_root: Project root directory (defaults to cwd)

    Returns:
        RulesResult with details of what was done
    """
    from .exporters import get_all_exporters, get_exporter

    if project_root is None:
        project_root = Path.cwd()

    # 1. Load summaries
    summaries = load_recent_summaries(days)

    if not summaries:
        return RulesResult(status="no_summaries")

    # 2. Get metadata about previous runs
    meta = get_distill_metadata()
    previous_sessions = set(meta.get("sessions_included", [])) if not rebuild else set()

    # 3. Filter to new summaries (unless rebuilding)
    if not rebuild and previous_sessions:
        new_summaries = [(sid, content, mtime) for sid, content, mtime in summaries
                         if sid not in previous_sessions]
    else:
        new_summaries = summaries

    # 4. Determine which exporters to use
    if target and target != "all":
        exporters = [get_exporter(target)]
    else:
        exporters = [e for e in get_all_exporters() if e.detect(project_root)]

    # 5. Load existing rules (for merge)
    existing_rules = {}
    if not rebuild:
        for exporter in exporters:
            loaded = exporter.load_existing(project_root)
            # Merge loaded rules (prefer first exporter's version)
            for cat, rules in loaded.items():
                if cat not in existing_rules:
                    existing_rules[cat] = rules

    # 6. Extract rules from new summaries
    if new_summaries:
        extracted = extract_rules_from_summaries(new_summaries)
    else:
        if not existing_rules:
            return RulesResult(status="no_new_summaries")
        extracted = {}

    # 7. Merge with existing rules
    if existing_rules and extracted:
        merged = merge_rules(existing_rules, extracted)
    elif existing_rules:
        merged = existing_rules
    else:
        merged = extracted

    if not merged:
        return RulesResult(status="no_rules_extracted")

    # Count rules
    rules_extracted = sum(len(r) for r in extracted.values()) if extracted else 0
    rules_after_merge = sum(len(r) for r in merged.values())

    # 8. Export to targets
    export_results = []
    if not dry_run:
        for exporter in exporters:
            result = exporter.export(merged, project_root)
            export_results.append(result)

        # Update metadata
        all_session_ids = [sid for sid, _, _ in summaries]
        update_distill_metadata(all_session_ids)

    return RulesResult(
        status="success",
        rules_extracted=rules_extracted,
        rules_after_merge=rules_after_merge,
        sessions_processed=len(summaries),
        export_results=export_results,
    )
