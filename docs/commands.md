# Command Reference

Complete reference for all afterpaths commands, with tips and recipes.

## Short Alias

**Use `ap` instead of `afterpaths`** for faster typing:

```bash
ap log           # instead of afterpaths log
ap show 1        # instead of afterpaths show 1
ap summarize 1   # instead of afterpaths summarize 1
```

Both `ap` and `afterpaths` work identically. Examples below use both interchangeably.

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `log` | List recent sessions |
| `show` | View session summary or transcript |
| `summarize` | Generate AI summary from session |
| `path` | Print raw session file path |
| `files` | Show files modified in a session |
| `refs` | Show git refs detected in a session |
| `link` | Find sessions that reference a git commit/branch |
| `trace` | Find sessions that produced a commit (by file matching) |
| `rules` | Extract rules from summaries for AI assistants |
| `insights` | View community insights and your stats |
| `analytics` | Manage community analytics settings |
| `status` | Show configuration and stats |

---

## `log`

List recent AI coding sessions.

```bash
afterpaths log [OPTIONS]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--all` | off | Show sessions from all projects (current project sessions are numbered, others show ID only) |
| `--type` | `main` | Filter by session type: `main`, `agent`, or `all` |
| `--limit` | 10 | Number of sessions to display |

**Examples:**
```bash
# List sessions for current project
ap log

# Show more sessions
ap log --limit=20

# Include agent sub-sessions (spawned by Task tool)
ap log --type=all

# See sessions across all projects (current project numbered, others show ID)
ap log --all
```

**Output explained:**
```
Sessions: 5 main, 12 agent
----------------------------------------
[1] 06f238b3-254e  [summarized]
    2024-01-14 10:30 | 245.3KB
    Implementing session path command

    b78227d9-0134                        ← no number (other project)
    Project: ~/Code/other-project
    2024-01-14 09:00 | 12.1KB

[2] 7faf6980-c5cf
    2024-01-13 15:22 | 1024.1KB
    Building afterpaths core functionality
```

- `[1]`, `[2]` — Session numbers for current project (use with other commands)
- No number — Session from another project (use ID prefix to access)
- `[summarized]` — Has an afterpaths summary
- `[agent]` — Sub-session spawned by Task tool (only shown with `--type=all`)

---

## `show`

View a session's summary or raw transcript.

```bash
afterpaths show SESSION_REF [OPTIONS]
```

**Arguments:**
- `SESSION_REF` — Session number (from `log`) or session ID prefix

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--raw` | off | Show transcript instead of summary |
| `--type` | `main` | Session type filter (must match `log` for number refs) |
| `--limit` | 50 | Max entries to show in raw mode |

**Examples:**
```bash
# View summary for session 1
ap show 1

# View raw transcript (truncated)
ap show 1 --raw

# Show more transcript entries
ap show 1 --raw --limit=200

# Reference by session ID prefix
ap show 7faf6980
```

---

## `summarize`

Generate an AI-powered summary from a session.

```bash
afterpaths summarize SESSION_REF [OPTIONS]
```

**Arguments:**
- `SESSION_REF` — Session number or ID prefix

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--notes` | "" | Additional context for the LLM |
| `--type` | `main` | Session type filter |
| `--force` | off | Overwrite existing summary |
| `--update` | off | Refine existing summary instead of regenerating |

**Examples:**
```bash
# Summarize session 1
ap summarize 1

# Add context to guide the summary
ap summarize 1 --notes="Focus on the authentication changes"

# Regenerate an existing summary
ap summarize 1 --force

# Refine existing summary with additional notes
ap summarize 1 --update --notes="Add more detail on the dead ends"
```

**Configuration:**

Set via environment variables or `.env` file:
```bash
AFTERPATHS_LLM_PROVIDER=anthropic  # or openai, openai-compatible
ANTHROPIC_API_KEY=sk-ant-...
AFTERPATHS_MODEL=claude-sonnet-4-5-20250929
```

---

## `path`

Print the path to a session's raw file.

```bash
afterpaths path SESSION_REF [OPTIONS]
```

**Arguments:**
- `SESSION_REF` — Session number or ID prefix

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--type` | `main` | Session type filter |

**Examples:**
```bash
# Get path to session 1
ap path 1
# Output: /Users/you/.claude/projects/-Users-you-Code-myproject/abc123.jsonl

# Use with other tools (see Recipes below)
cat $(ap path 1) | jq .
```

---

## `files`

Show files modified (written/edited) in a session.

```bash
afterpaths files SESSION_REF [OPTIONS]
```

**Arguments:**
- `SESSION_REF` — Session number or ID prefix

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--type` | `main` | Session type filter |

**Examples:**
```bash
# See what files session 1 modified
afterpaths files 1
```

**Output:**
```
Session: 7faf6980-c5cf
Summary: Building afterpaths core functionality

Files modified (8):
  [write] afterpaths/cli.py
  [write] afterpaths/summarize.py
  ...

Files read only (23):
  [read] README.md
  [read] pyproject.toml
  ...
```

---

## `refs`

Show git refs (commits, branches) detected in a session.

```bash
afterpaths refs SESSION_REF [OPTIONS]
```

**Arguments:**
- `SESSION_REF` — Session number (current project) or ID prefix (any project)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--type` | `main` | Session type filter |

**Examples:**
```bash
# See git refs in session 1 (current project)
afterpaths refs 1

# See git refs by session ID (any project)
afterpaths refs b78227d9
```

**Output:**
```
Session: 7faf6980-c5cf
Summary: Building afterpaths core functionality

Branches:
  - feature/session-parsing
  - main

Commits:
  - abc1234def5
  - 789xyz123ab
```

---

## `link`

Find sessions that explicitly reference a git commit or branch.

```bash
afterpaths link GIT_REF [OPTIONS]
```

**Arguments:**
- `GIT_REF` — Commit hash (or prefix) or branch name

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--all` | off | Search all projects |

**Examples:**
```bash
# Find sessions mentioning a commit
afterpaths link abc1234

# Find sessions mentioning a branch
afterpaths link feature/auth

# Search across all projects
afterpaths link abc1234 --all
```

---

## `trace`

Find sessions that likely produced a commit by matching file modifications.

Unlike `link` which looks for explicit git refs in transcripts, `trace` compares the files changed in a commit against files modified via Edit/Write tools in sessions.

```bash
afterpaths trace COMMIT_REF [OPTIONS]
```

**Arguments:**
- `COMMIT_REF` — Git commit hash or reference (e.g., `HEAD`, `HEAD~1`, `abc1234`)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--all` | off | Search all projects |
| `--days` | 7 | Max days before commit to search |
| `--limit` | 5 | Maximum sessions to show |

**Examples:**
```bash
# What session produced the last commit?
afterpaths trace HEAD

# Trace a specific commit
afterpaths trace abc1234

# Search further back in time
afterpaths trace HEAD --days=14

# Search all projects
afterpaths trace HEAD~3 --all
```

---

## `rules`

Extract rules from session summaries and export to AI assistant config files.

```bash
afterpaths rules [OPTIONS]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--days` | 14 | Include summaries from last N days |
| `--rebuild` | off | Rebuild rules from scratch (ignore existing) |
| `--dry-run` | off | Preview without writing files |
| `--target` | `all` | Export target: `claude`, `cursor`, or `all` |

**Examples:**
```bash
# Extract rules and export to all detected targets
afterpaths rules

# Include more history
afterpaths rules --days=30

# Only export to Claude Code
afterpaths rules --target=claude

# Preview what would be generated
afterpaths rules --dry-run

# Rebuild from scratch (ignore previous rules)
afterpaths rules --rebuild
```

**Output locations:**
- Claude Code: `.claude/rules/*.md`
- Cursor: `.cursor/rules/*.mdc`

---

## `insights`

View community insights and your usage statistics.

```bash
afterpaths insights
```

Displays how your afterpaths usage compares to the community, including:
- Session counts (yours vs average)
- Rule generation stats
- Top rule categories community-wide
- Your most productive day

**Requires analytics to be enabled** (see `analytics` command).

**Example output:**
```
Community Insights
----------------------------------------

Your Stats (last 7d):
  Sessions: 12 (community avg: 8.2)
  Rules generated: 7 (community avg: 4.7)

Your Stack: python + fastapi

Top Rule Categories (community-wide):
  1. Dead Ends (38%)
  2. Gotchas (28%)
  3. Patterns (22%)
  4. Decisions (12%)

Your Most Productive Day: Tuesday

----------------------------------------
Based on 127 afterpaths users
```

---

## `analytics`

Manage community analytics settings.

```bash
afterpaths analytics [OPTIONS]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--enable` | - | Enable community analytics |
| `--disable` | - | Disable community analytics |

**Examples:**
```bash
# Check current status
afterpaths analytics

# Enable analytics (share stats, get insights)
afterpaths analytics --enable

# Disable analytics
afterpaths analytics --disable
```

**What gets shared when enabled:**
- Session counts and duration buckets
- Rule counts by category (dead-ends, patterns, gotchas, decisions)
- Tech stack (detected from project files)

**What is NOT shared:**
- Code or file contents
- Rule text or details
- Project names or paths
- Any identifying information

---

## `status`

Show afterpaths configuration and statistics.

```bash
afterpaths status
```

**Output:**
```
Afterpaths Status
----------------------------------------
LLM Provider: anthropic/claude-sonnet-4-5-20250929
Summaries: 12 saved
Last rules extraction: 2024-01-14 10:30
Sessions processed: 8
Analytics: enabled
Detected Stack: python, fastapi
```

---

# Tips & Recipes

## Inspecting Raw Session Data

The `path` command outputs just the file path, making it easy to compose with other tools:

```bash
# Pretty-print entire session as JSON
cat $(ap path 1) | jq .

# View in a pager
less $(ap path 1)

# Count entries by type
cat $(ap path 1) | jq -s 'group_by(.type) | map({type: .[0].type, count: length})'

# Extract just user messages
cat $(ap path 1) | jq 'select(.type == "user") | .content'

# Find all tool uses
cat $(ap path 1) | jq 'select(.type == "assistant" and .tool_use) | .tool_use.name'

# Get session size in lines
wc -l $(ap path 1)
```

## Finding What Session Made a Change

```bash
# What session created the last commit?
ap trace HEAD

# What session worked on this file recently?
ap log --limit=20  # then check each with:
ap files 1 | grep "myfile.py"
```

## Bulk Operations

```bash
# Summarize the 3 most recent sessions
for i in 1 2 3; do ap summarize $i; done

# Export all session paths
for i in $(seq 1 10); do ap path $i 2>/dev/null; done
```

## Session Numbering

Session numbers always refer to **current project sessions only**. When using `--all`, other projects' sessions are displayed for context but aren't numbered:

```
ap log --all

[1] 06f238b3-254e              ← current project, use "1" or ID
    2024-01-14 10:30 | 245.3KB

    b78227d9-0134              ← other project, use ID only
    Project: ~/Code/other-project
    2024-01-14 09:00 | 12.1KB

[2] 7faf6980-c5cf              ← current project, use "2" or ID
    2024-01-13 15:22 | 1024.1KB
```

```bash
# Access current project by number or ID:
ap show 1
ap show 06f238b3

# Access other projects by ID only:
ap show b78227d9
```

**Note:** The `--type` filter affects which sessions are numbered. Use the same `--type` flag in `log` and other commands for consistent numbering.

## Working with Agent Sessions

Agent sessions are sub-processes spawned by the Task tool. They're usually small (1-2KB) and contain focused sub-tasks:

```bash
# See all sessions including agents
ap log --type=all

# Show a specific agent session
ap show 5 --type=all
```

## Git Integration

```bash
# Before committing: which session has context?
ap trace HEAD~0  # (no commit yet, but shows recent file matches)

# After a PR merge: find the session that built it
git log --oneline -5
ap trace abc1234

# Find all sessions that touched a branch
ap link feature/my-branch --all
```

## Debugging Summarization

```bash
# Check your LLM configuration
ap status

# Test with a small session first
ap log  # find a small one (low KB)
ap summarize 3

# Add notes if summary misses context
ap summarize 1 --update --notes="The main goal was X, focus on that"
```
